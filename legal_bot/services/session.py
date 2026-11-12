"""موتور تعامل: هر «کار» (Job) یک coroutine است که مرورگر را می‌راند و هر جا لازم شد از
کاربر چیزی می‌پرسد و منتظر پاسخ می‌ماند.

- هر کاربر حداکثر یک Job فعال.
- callback_data فقط «j:<job>:<seq>:<index>» است (بدون هیچ مقدار)؛ دکمه‌ی مرحله‌ی قبلی بی‌اثر است.
- مقادیر حساس فقط در SecretVault (RAM) و با کلید (bale_id, job_id) نگه‌داری و در پایان Job
  (موفق/خطا/لغو/مهلت/ری‌استارت) پاک می‌شوند.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets as _secrets
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message

from .. import config, keyboards as K, texts as T

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    """کاربر «بازگشت/لغو» زد."""


class UserTimeout(Exception):
    """کاربر در مهلت مقرر پاسخ نداد."""


class FlowError(Exception):
    """خطای قابل‌گزارش در یک مرحله (category مطابق بخش ۱۳ سند)."""

    def __init__(self, category: str, message: str = "", user_message: str | None = None):
        super().__init__(message or category)
        self.category = category
        self.user_message = user_message


# ── نگه‌دارنده‌ی موقت اطلاعات ورود (فقط RAM) ─────────────────────────────
class SecretVault:
    def __init__(self):
        self._data: dict[tuple[int, str], dict[str, str]] = {}

    def put(self, owner: tuple[int, str], name: str, value: str):
        self._data.setdefault(owner, {})[name] = value

    def get(self, owner, name):
        return self._data.get(owner, {}).get(name)

    def pop(self, owner, name):
        return self._data.get(owner, {}).pop(name, None)

    def wipe(self, owner):
        d = self._data.pop(owner, None)
        if d:
            for k in list(d):
                d[k] = ""
            d.clear()

    def wipe_all(self):
        for k in list(self._data):
            self.wipe(k)

    def scrub(self, text: str) -> str:
        """هر مقدار حساسِ در حال استفاده را از متن (پیام خطا، لاگ) حذف می‌کند."""
        if not isinstance(text, str) or not text:
            return text
        for d in list(self._data.values()):
            for v in list(d.values()):
                if v and len(v) >= 3:
                    text = text.replace(v, "<hidden>")
        return text

    def is_empty(self, owner=None) -> bool:
        if owner is None:
            return not any(self._data.values())
        return not self._data.get(owner)


vault = SecretVault()


@dataclass
class _Expect:
    seq: int
    accept_text: bool
    secret: bool
    options: list
    future: asyncio.Future


@dataclass
class Job:
    bot: Bot
    user_id: int
    chat_id: int
    kind: str
    id: str = field(default_factory=lambda: _secrets.token_hex(3))
    run_id: int | None = None
    task: asyncio.Task | None = None
    _seq: int = 0
    _expect: _Expect | None = None
    _prompt_msgs: list = field(default_factory=list)

    @property
    def owner(self):
        return (self.user_id, self.id)

    # ── ارسال ──
    async def say(self, text, kb=None, **kw) -> Message | None:
        try:
            return await self.bot.send_message(self.chat_id, text, reply_markup=kb, **kw)
        except Exception as e:  # pragma: no cover - شبکه
            log.warning("send failed: %s", type(e).__name__)
            return None

    async def send_pdf(self, data: bytes, filename: str, caption: str = ""):
        """ارسال PDF با تا ۳ تلاش (خطای گذرای شبکه/بله).

        هر تلاش یک BufferedInputFile تازه می‌سازد چون فایل aiogram فقط یک‌بار
        خوانده می‌شود (read یک async generator یک‌بارمصرف است).
        """
        last: Exception | None = None
        for attempt in range(3):
            try:
                return await self.bot.send_document(
                    self.chat_id, BufferedInputFile(data, filename=filename),
                    caption=caption[:1000] or None)
            except Exception as e:  # pragma: no cover - شبکه
                last = e
                log.warning("send_pdf try %d failed: %s: %s", attempt + 1,
                            type(e).__name__, str(e)[:120])
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        raise last

    async def send_photo(self, data: bytes, caption: str = ""):
        """ارسال عکس (مثل اسکرین‌شات صفحه) با تا ۳ تلاش — مشابه send_pdf."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                return await self.bot.send_photo(
                    self.chat_id, BufferedInputFile(data, "screen.png"),
                    caption=caption[:1000] or None)
            except Exception as e:  # pragma: no cover - شبکه
                last = e
                log.warning("send_photo try %d failed: %s: %s", attempt + 1,
                            type(e).__name__, str(e)[:120])
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        raise last

    # ── پرسش ──
    async def ask(self, prompt: str, options: list[tuple[str, str]] | None = None, *, accept_text=True,
                  secret=False, photo: bytes | None = None, back=False, timeout: int | None = None):
        """خروجی: ("text", متن) یا ("choice", value).

        دکمه‌ی «بازگشت» به‌طور خودکار اضافه نمی‌شود (پیش‌فرض back=False): حین فرایند،
        کیبورد پایین ربات فقط «بازگشت به منوی اصلی» و «لغو عملیات» است و سؤال‌ها
        فقط گزینه‌های خودِ همان مرحله را نشان می‌دهند. اگر جایی نیاز به دکمه‌ی بازگشت
        داخل سؤال باشد، back=True بدهید.
        """
        self._seq += 1
        options = list(options or [])
        if back:
            options.append(("__back__", T.BACK))
        rows = [[(label, f"j:{self.id}:{self._seq}:{i}")] for i, (_, label) in enumerate(options)]
        kb = K.inline(rows) if rows else None
        loop = asyncio.get_running_loop()
        exp = _Expect(self._seq, accept_text, secret, options, loop.create_future())
        self._expect = exp
        if photo:
            msg = await self.bot.send_photo(self.chat_id, BufferedInputFile(photo, "captcha.png"),
                                            caption=prompt, reply_markup=kb)
        else:
            msg = await self.say(prompt, kb)
        try:
            kind, value = await asyncio.wait_for(exp.future, timeout or config.LOGIN_STEP_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            raise UserTimeout()
        finally:
            self._expect = None
            if msg is not None:
                await self._strip_kb(msg)
        if kind == "choice" and value == "__back__":
            raise JobCancelled()
        return kind, value

    async def ask_choice(self, prompt, options, **kw) -> str:
        _, v = await self.ask(prompt, options, accept_text=False, **kw)
        return v

    async def ask_text(self, prompt, validator=None, **kw) -> str:
        """validator(text) → (value, None) یا (None, پیام_خطا)."""
        while True:
            kind, v = await self.ask(prompt, accept_text=True, **kw)
            if kind != "text":
                continue
            if not validator:
                return v.strip()
            val, err = validator(v)
            if val is not None:
                return val
            prompt = f"{err}\nدوباره ارسال کنید:"

    async def ask_secret(self, name: str, prompt: str, validator=None, masker=None,
                         extra_options=None) -> str | tuple[str, str]:
        """دریافت مقدار حساس: حذف پیام کاربر ← نمایش ماسک‌شده ← «تأیید / ویرایش / بازگشت».

        مقدار تأییدشده فقط در vault ذخیره می‌شود و نام آن برگردانده می‌شود.
        اگر extra_options داده شود و کاربر یکی از آن‌ها را بزند، ("choice", value) برمی‌گردد.
        """
        while True:
            kind, v = await self.ask(prompt, extra_options, accept_text=True, secret=True)
            if kind == "choice":
                return ("choice", v)
            value = v.strip()
            if validator:
                ok, err = validator(value)
                if ok is None:
                    prompt = f"{err}"
                    value = ""
                    continue
                value = ok
            shown = masker(value) if masker else "رمز دریافت شد " + "•" * 8
            c = await self.ask_choice(f"مقدار دریافتی: {shown}\nدرست است؟", [("ok", T.CONFIRM), ("edit", T.EDIT)])
            if c == "ok":
                vault.put(self.owner, name, value)
                value = ""
                return name
            value = ""
            prompt = "مقدار جدید را ارسال کنید:"

    async def _strip_kb(self, msg):
        try:
            if msg.reply_markup:
                await self.bot.edit_message_reply_markup(chat_id=self.chat_id, message_id=msg.message_id,
                                                         reply_markup=None)
        except Exception:
            pass

    # ── تحویل ورودی از هندلرها ──
    def waiting_secret(self) -> bool:
        return bool(self._expect and self._expect.secret)

    def deliver_text(self, text: str) -> bool:
        e = self._expect
        if not e or not e.accept_text or e.future.done():
            return False
        e.future.set_result(("text", text))
        return True

    def deliver_callback(self, seq: int, idx: int) -> bool:
        e = self._expect
        if not e or e.seq != seq or e.future.done() or not (0 <= idx < len(e.options)):
            return False
        e.future.set_result(("choice", e.options[idx][0]))
        return True


class JobManager:
    def __init__(self):
        self.jobs: dict[int, Job] = {}

    def get(self, user_id) -> Job | None:
        j = self.jobs.get(user_id)
        if j and j.task and j.task.done():
            self.jobs.pop(user_id, None)
            return None
        return j

    def busy(self, user_id) -> bool:
        return self.get(user_id) is not None

    def start(self, job: Job, coro_factory) -> bool:
        if self.busy(job.user_id):
            return False
        self.jobs[job.user_id] = job

        async def runner():
            # شروع فرایند: کیبورد پایین ربات فقط «بازگشت به منوی اصلی» و «لغو عملیات»
            await job.say(T.FLOW_STARTED, kb=K.flow_kb())
            try:
                await asyncio.wait_for(coro_factory(job), config.JOB_TOTAL_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                await job.say(T.USER_TIMEOUT)
            finally:
                vault.wipe(job.owner)
                self.jobs.pop(job.user_id, None)
                # پایان فرایند (موفق/لغو/خطا/مهلت): بازگشت خودکار به منوی اصلی
                # shield: اگر همین‌جا دوباره لغو شد، پیام منو در پس‌زمینه ارسال می‌شود
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(job.say(T.AUTO_MAIN, kb=K.main_menu()))

        job.task = asyncio.create_task(runner(), name=f"job-{job.kind}-{job.user_id}")
        return True

    def cancel(self, user_id) -> bool:
        j = self.get(user_id)
        if not j:
            return False
        j.task.cancel()
        return True

    async def shutdown(self):
        for j in list(self.jobs.values()):
            if j.task:
                j.task.cancel()
        vault.wipe_all()


jobs = JobManager()
