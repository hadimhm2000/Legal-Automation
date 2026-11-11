"""اسکلت مشترک هر کار مرورگری: اعلان و تأیید ← مرورگر ← ورود ← کار ← پاک‌سازی تضمینی."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from .. import config, texts as T
from . import error_reporter
from .browser import Browser
from .sana_login import SanaLogin, collect_credentials
from .session import FlowError, Job, JobCancelled, UserTimeout, vault

log = logging.getLogger(__name__)


class RunCtx:
    def __init__(self, job: Job, db, kind: str, trigger="manual"):
        self.job, self.db, self.kind, self.trigger = job, db, kind, trigger
        self.bot = job.bot
        self.run_id = None
        self.cur_step = "L01"
        self.new_items = 0

    async def start(self):
        self.run_id = await self.db.create_run(self.job.user_id, self.kind, self.trigger)
        self.job.run_id = self.run_id

    async def step(self, code):
        self.cur_step = code
        if self.run_id:
            await self.db.run_step(self.run_id, code)

    async def report(self, category, message=""):
        r = await self.db.one("SELECT steps_ok FROM check_runs WHERE id=?", (self.run_id,)) if self.run_id else None
        await error_reporter.report(self.bot, self.db, run_id=self.run_id, user_id=self.job.user_id,
                                    step=self.cur_step, category=category, message=message,
                                    steps_ok=(r or {}).get("steps_ok", ""))


class QueueNotice:
    """یک پیام «جایگاه شما در صف» که با جابه‌جایی صف ویرایش می‌شود (نه پیام‌های پشت‌سرهم)."""

    def __init__(self, job: Job):
        self.job = job
        self.msg = None
        self.last = 0.0
        self.pos = None
        self.done = False
        self._lock = asyncio.Lock()

    async def __call__(self, pos: int):
        async with self._lock:
            if not self.done:
                await self._show(pos)

    async def _show(self, pos: int):
        loop = asyncio.get_running_loop()
        now = loop.time()
        text = T.QUEUE_WAIT.format(pos=pos)
        if self.msg is None:
            self.msg = await self.job.say(text)
        elif pos < (self.pos or pos + 1) and now - self.last >= config.QUEUE_NOTIFY_MIN_SEC:
            with contextlib.suppress(Exception):
                await self.job.bot.edit_message_text(text, chat_id=self.job.chat_id,
                                                     message_id=self.msg.message_id)
        else:
            return
        self.pos, self.last = pos, now

    async def started(self):
        async with self._lock:
            self.done = True
        if self.msg is not None:
            with contextlib.suppress(Exception):
                await self.job.bot.edit_message_text(T.QUEUE_GO, chat_id=self.job.chat_id,
                                                     message_id=self.msg.message_id)


async def run_with_browser(ctx: RunCtx, target: str, work, *, consent=True):
    """work(ctx, br, login, page) را با ورود به `target` اجرا می‌کند."""
    job = ctx.job
    await ctx.start()
    login = None
    creds_asked = False
    try:
        if consent:
            await ctx.step("L03")
            await job.ask_choice(T.CONSENT_TEXT, [("ok", T.CONFIRM)])
        # بعد از تأیید کاربر: بازخورد فوری تا کاربر بداند باید منتظر بماند
        # (مرورگر باز می‌شود و تا اولین پیام ورود ممکن است چند لحظه طول بکشد)
        creds_asked = True
        await collect_credentials(job, ctx)
        await job.say(T.PLEASE_WAIT)
        notice = QueueNotice(job)
        async with Browser(on_queue=notice) as br:
            await notice.started()
            login = SanaLogin(ctx, br, target)
            page = await login.run()
            await job.say(T.LOGIN_OK)
            await ctx.step("L09")
            await work(ctx, br, login, page)
            await ctx.step("L12")
        await ctx.db.finish_run(ctx.run_id, "done", new_items=ctx.new_items)
    except JobCancelled:
        await ctx.db.finish_run(ctx.run_id, "cancelled", "CANCELLED")
        await job.say(T.CANCELLED)
    except UserTimeout:
        await ctx.report("USER_TIMEOUT")
        await job.say(T.USER_TIMEOUT)
    except asyncio.CancelledError:
        await ctx.db.finish_run(ctx.run_id, "cancelled", "CANCELLED")
        raise
    except FlowError as e:
        await ctx.report(e.category, str(e))
        await job.say(e.user_message or T.SITE_DOWN)
    except Exception as e:  # کرش مرورگر یا خطای پیش‌بینی‌نشده
        log.exception("job crashed")
        mod = type(e).__module__ or ""
        name = type(e).__name__
        if "aiogram" in mod or name.startswith("Telegram") or "telegram" in str(e).lower():
            cat = "SEND_FAILED"  # خطای ارسال به بله — سایت مقصر نیست
        elif "playwright" in mod:
            cat = "BROWSER_CRASH"
        else:
            cat = "UNKNOWN"
        await ctx.report(cat, f"{name}: {str(e)[:200]}")
        await job.say(T.SEND_FAILED_USER if cat == "SEND_FAILED" else T.SITE_DOWN)
    finally:
        vault.wipe(job.owner)
        if creds_asked or (login is not None and login.used_credentials):
            try:
                await asyncio.shield(job.say(T.CREDS_WIPED))
            except BaseException:
                pass
