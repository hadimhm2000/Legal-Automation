"""ورود به سامانه‌های عدل ایران (iehraz.adliran.ir) با اطلاعاتی که کاربر همان لحظه می‌دهد.

تنها فایلی که اطلاعات ورود را در فرم می‌نویسد (قاعده‌ی ۸ بخش ۱۲ سند؛ تست test_security).

مسیر (مطابق دستور کارفرما و ضبط‌های واقعی):
  adliran.ir ← بستن پاپ‌آپ ← کارت سامانه ← لینک (تب جدید) ← صفحه‌ی ورود
  اگر تب جدید به صفحه‌ی ورود نرسید (مثل خطای «This site doesn't support a secure connection»)
  تب بسته و مراحل از ابتدا تکرار می‌شود.
  کدملی ← رمز شخصی (اگر کپچا ظاهر شد، تصویرش برای خود کاربر فرستاده می‌شود) ← Enter
  ← پاسخ CheckPersonLogin (200 موفق / 409 نادرست) ← رمز موقت ← پاسخ CheckPersonOtpLogin
  اگر بعد از ورود صفحه‌ی «خطای امنیتی / اعتبار شما منقضی شده است» آمد: دکمه‌ی
  «ورود به صفحه اصلی عدل ایران» ← صبر تا adliran.ir ← تکرار مراحل.
  اگر تبِ تازه به صفحه‌ی خطای سامانه (Login/ErrorPage) افتاد (دستور کارفرما —
  آبان ۱۴۰۵): تب بسته می‌شود و دوباره از «گزینه‌ی قبلی» (کارت همان سامانه در
  صفحه‌ی اصلی) وارد بخش می‌شویم؛ این کار تا MAX_PORTAL_ENTRY_ATTEMPTS بار.

کدملی و رمز شخصی (و آخرین رمز موقت) فقط در vault همین Job و فقط تا پایان همین Job در RAM
می‌مانند تا اگر سامانه وسط کار دوباره ورود خواست، از کاربر دوباره پرسیده نشود؛ در پایان Job
(هر نتیجه‌ای) پاک می‌شوند.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time

from playwright.async_api import Page

from .. import config, texts as T
from ..utils import clean_digits, mask_national_code, normalize_fa, valid_national_code
from . import selectors as S
from .browser import click_text, human_ms, human_pause, page_text, text_re, visible, wait_first, wait_ready
from .session import FlowError, vault

log = logging.getLogger(__name__)

TARGETS = {
    "eblagh": {"card": S.CARD_EBLAGH, "link": S.LINK_EBLAGH_MAIN, "direct": config.EBLAGH_MAIN_URL,
               "host": re.compile(r"eblagh1?\.adliran\.ir")},
    "resultcase_person": {"card": S.CARD_RESULTCASE, "link": S.LINK_RESULTCASE["person"],
                          "direct": config.RESULTCASE_PERSON_URL, "host": re.compile(r"resultcase\.adliran\.ir")},
    "resultcase_lawyer": {"card": S.CARD_RESULTCASE, "link": S.LINK_RESULTCASE["lawyer"],
                          "direct": config.RESULTCASE_LAWYER_URL, "host": re.compile(r"resultcase\.adliran\.ir")},
    "turn": {"card": S.CARD_TURN, "link": S.CARD_TURN, "direct": config.TURN_URL,
             "host": re.compile(r"(^|//)(www\.)?adliran\.ir/Turn", re.I)},
}


def _validate_nc(v):
    v = clean_digits(v)
    return (v, None) if valid_national_code(v) else (None, T.BAD_NATIONAL_CODE)


def _validate_pw(v):
    v = (v or "").strip()
    return (v, None) if 1 <= len(v) <= 64 else (None, "رمز خالی یا بیش از حد طولانی است.")


def _validate_otp(v):
    v = clean_digits(v)
    return (v, None) if 4 <= len(v) <= 10 else (None, "رمز موقت باید فقط عدد (معمولاً ۶ رقم) باشد.")


# ── قاعده‌ی کارفرما (آبان ۱۴۰۵ — ضبط steps 3): پیام «رمز موقت جدید برای شماره
# همراه شما ارسال شد...» روی صفحه‌ی ورود یعنی خود سامانه رمز تازه فرستاده ←
# دکمه‌ی «ارسال رمز موقت» به کاربر نمایش داده نمی‌شود؛ پیام نبود ← دکمه حتماً هست.
# قاعده‌ی کارفرما (تصویر ارسالی): بعد از یک‌بار «ارسال رمز موقت»، دکمه‌ی ارسال تا
# ۳ ساعت در پیام‌های بعدی نمایش داده نمی‌شود. زمان آخرین ارسالِ دستیِ رمز موقت
# هر کاربر در رم (سریع) و settings (ماندگار بین ری‌استارت‌ها) می‌ماند.
_OTP_RESEND_RAM: dict[int, float] = {}


async def otp_mark_resend(ctx, user_id: int):
    """ثبت زمان ارسال دستی رمز موقت (شروع قفل ۳ ساعته‌ی دکمه‌ی ارسال)."""
    now = time.time()
    _OTP_RESEND_RAM[user_id] = now
    db = getattr(ctx, "db", None)
    if db is not None:
        with contextlib.suppress(Exception):
            await db.set_setting(f"otp_resend:{user_id}", str(now))


async def otp_resend_in_cooldown(ctx, user_id: int) -> bool:
    """آیا ارسالِ دستیِ رمز موقت در ۳ ساعت اخیر بوده؟ (دستور کارفرما: بعد از یک
    ارسال دستی، دکمه‌ی «ارسال رمز موقت» تا ۳ ساعت در هیچ پیام بعدی نیست.)

    اول رمِ پردازش؛ نبود (مثل ری‌استارت ربات) ← از settings خوانده و دوباره
    کش می‌شود. بدون دیتابیس هم فقط رم کافی است."""
    now = time.time()
    last = _OTP_RESEND_RAM.get(user_id)
    if last is None:
        db = getattr(ctx, "db", None)
        raw = None
        if db is not None:
            with contextlib.suppress(Exception):
                raw = await db.get_setting(f"otp_resend:{user_id}")
        if raw:
            with contextlib.suppress(ValueError, TypeError):
                last = float(raw)
                _OTP_RESEND_RAM[user_id] = last
    return bool(last is not None and 0 <= now - last < config.OTP_RESEND_COOLDOWN_SEC)


async def collect_credentials(job, ctx):
    """کدملی و رمز شخصی پیش از گرفتن مرورگر پرسیده می‌شوند تا زمانِ صف و تایپ کاربر
    ظرفیت مرورگر را اشغال نکند (فقط در vault همین Job؛ در پایان Job پاک می‌شوند).
    رمز موقت (OTP) طبیعتاً بعد از باز شدن سامانه پرسیده می‌شود."""
    await ctx.step("L05")
    if vault.get(job.owner, "nc") is None:
        await job.ask_secret("nc", T.ASK_NATIONAL_CODE, _validate_nc, mask_national_code)
    await ctx.step("L06")
    if vault.get(job.owner, "pw") is None:
        await job.ask_secret("pw", T.ASK_PASSWORD, _validate_pw)


class _Restart(Exception):
    def __init__(self, reason: str = "expired"):
        super().__init__(reason)
        self.reason = reason


class SanaLogin:
    def __init__(self, ctx, br, target: str):
        self.ctx, self.br, self.target = ctx, br, target
        self.cfg = TARGETS[target]
        self.job = ctx.job
        self.used_credentials = False

    # ── ورود کامل ───────────────────────────────────────────────────
    async def run(self) -> Page:
        for _ in range(3):
            page = await self.enter_portal()
            try:
                await self.login(page)
                return page
            except _Restart as r:
                if r.reason != "errorpage":
                    await self.ctx.job.say("🔁 سامانه اعتبار ورود را منقضی اعلام کرد؛ از صفحه‌ی اصلی دوباره وارد می‌شوم…")
                continue
        raise FlowError("SESSION_INVALID", "expired-credential page repeated", T.SITE_DOWN)

    def is_target(self, page: Page) -> bool:
        return bool(self.cfg["host"].search(page.url or "")) and "iehraz" not in (page.url or "")

    @staticmethod
    def on_error_page(page) -> bool:
        """صفحه‌ی خطای سامانه (Login/ErrorPage — دستور کارفرما، آبان ۱۴۰۵)."""
        return S.ERROR_PAGE_URL_PART.lower() in (page.url or "").lower()

    async def recover_error_page(self, page) -> Page:
        """دستور کارفرما: اگر ورود به بخشی به صفحه‌ی Login/ErrorPage افتاد،
        تب بسته می‌شود و دوباره از «گزینه‌ی قبلی» (کارت همان سامانه در صفحه‌ی
        اصلی adliran.ir) وارد بخش می‌شویم."""
        await self.job.say(T.ERROR_PAGE_RETRY)
        if page is not self.br.page:
            with contextlib.suppress(Exception):
                await page.close()
        return await self.run()

    async def enter_portal(self) -> Page:
        await self.ctx.step("L04")
        home = self.br.page
        last_err = ""
        for attempt in range(config.MAX_PORTAL_ENTRY_ATTEMPTS):
            new = None
            try:
                await home.goto(config.ADLIRAN_BASE_URL, wait_until="domcontentloaded", timeout=45_000)
                await wait_ready(home)   # صبر برای لود کامل صفحه‌ی اصلی + مکث انسانی
                await click_text(home, *S.HOME_POPUP_CLOSE, timeout=4_000)
                await click_text(home, *self.cfg["card"], timeout=10_000)
                try:
                    async with self.br.context.expect_page(timeout=15_000) as pinfo:
                        if not await click_text(home, *self.cfg["link"], timeout=8_000, exact_role="link"):
                            if not await click_text(home, *self.cfg["link"], timeout=4_000):
                                raise RuntimeError("link not found")
                    new = await pinfo.value
                except Exception:
                    # برخی لینک‌ها در موبایل target=_self هستند؛ اگر تب جدید باز نشد خود صفحه را بررسی کن
                    if self.cfg["host"].search(home.url) or "iehraz" in home.url:
                        new = home
                    else:
                        new = await self.br.context.new_page()
                        await new.goto(self.cfg["direct"], wait_until="domcontentloaded", timeout=45_000)
                with contextlib.suppress(Exception):
                    await new.wait_for_load_state("domcontentloaded", timeout=30_000)
                await wait_ready(new, timeout_ms=30_000, settle=False)  # لود کامل تب تازه
                # نکته: errorpage قبل از بقیه بررسی می‌شود چون آدرسِ صفحه‌ی خطا روی
                # میزبانِ خودِ سامانه است و در غیر این صورت حالت «in» اشتباهی می‌شود.
                state = await wait_first({
                    "errorpage": lambda: asyncio.sleep(0, self.on_error_page(new)),
                    "login": lambda: visible(new.locator(S.NATIONAL_CODE)),
                    "in": lambda: asyncio.sleep(0, self.is_target(new) and "iehraz" not in new.url),
                    "expired": lambda: self._expired(new),
                }, timeout_ms=30_000)
                if state in ("login", "in"):
                    # login: فرم ورود آماده است / in: هنوز نشست قبلی (همین Job) معتبر است
                    return new
                if state == "errorpage":
                    # دستور کارفرما (آبان ۱۴۰۵): تبِ خطا بسته و دوباره از گزینه‌ی
                    # قبلی (کارت همان سامانه) وارد بخش می‌شویم.
                    await self.job.say(T.ERROR_PAGE_RETRY)
                last_err = f"entry state={state} url-host={_host(new.url)}"
            except Exception as e:
                last_err = f"{type(e).__name__}"
            # طبق دستور کارفرما: تب را ببند و مراحل قبل را دوباره طی کن
            if new is not None and new is not home:
                with contextlib.suppress(Exception):
                    await new.close()
            await asyncio.sleep(2 + attempt * 2)
        raise FlowError("SANA_DOWN", f"portal entry failed: {last_err}", T.SITE_DOWN)

    async def _expired(self, page) -> bool:
        txt = await page_text(page)
        return any(normalize_fa(w) in txt for w in S.EXPIRED_TEXT)

    async def _recover_expired(self, page):
        await click_text(page, *S.EXPIRED_BACK, timeout=8_000)
        with contextlib.suppress(Exception):
            await page.wait_for_url(re.compile(r"adliran\.ir/?($|\?|#)"), timeout=30_000)
        with contextlib.suppress(Exception):
            if page is not self.br.page:
                await page.close()
        raise _Restart()

    # ── نوشتن آرام و یکی‌یکی (مثل یک کاربر واقعی) ─────────────────────
    async def _type(self, page: Page, selector: str, secret_name: str):
        value = vault.get(self.job.owner, secret_name)
        if value is None:
            raise FlowError("UNKNOWN", f"vault empty for {secret_name}")
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=20_000)
        # تاخیر هر نویسه تصادفی است (انسان با سرعت ثابت تایپ نمی‌کند)
        await el.click()
        await el.fill("")
        await el.press_sequentially(value, delay=human_ms(config.TYPE_DELAY_MS))
        value = None
        await human_pause(page)

    async def _type_public(self, page: Page, selector: str, text: str):
        """تایپ آرام برای مقادیر غیر حساس (مثل کد کپچا)."""
        el = page.locator(selector).first
        await el.click()
        await el.fill("")
        await el.press_sequentially(text, delay=human_ms(config.TYPE_DELAY_MS))
        await human_pause(page)

    async def _submit(self, page, field, api) -> tuple[int | None, str]:
        """Enter روی فیلد و انتظار برای پاسخ API ورود؛ (status, متن پاسخ)."""
        try:
            async with page.expect_response(lambda r: api in r.url and r.request.method == "POST",
                                            timeout=25_000) as ri:
                await page.locator(field).first.press("Enter")
            resp = await ri.value
        except Exception:
            # Enter عمل نکرد → دکمه‌ی «مرحله بعد»
            try:
                async with page.expect_response(lambda r: api in r.url, timeout=25_000) as ri:
                    if not await click_text(page, *S.NEXT_STEP_BTN, timeout=5_000):
                        raise RuntimeError("no next-step button")
                resp = await ri.value
            except Exception:
                return None, ""
        body = ""
        with contextlib.suppress(Exception):
            # بعد از ناوبری، خواندن بدنه‌ی پاسخ ممکن است هیچ‌وقت تمام نشود
            body = normalize_fa(await asyncio.wait_for(resp.text(), 5))[:300]
        return resp.status, body

    # ── مراحل ─────────────────────────────────────────────────────
    async def login(self, page: Page, relogin: bool = False):
        job = self.job
        if self.is_target(page):
            return
        self.used_credentials = True
        # L05 کدملی
        await self.ctx.step("L05")
        if vault.get(job.owner, "nc") is None:
            await job.ask_secret("nc", T.ASK_NATIONAL_CODE, _validate_nc, mask_national_code)
        await self._type(page, S.NATIONAL_CODE, "nc")

        # L06 رمز شخصی (+ کپچا)
        await self.ctx.step("L06")
        attempts = 0
        prompt = T.ASK_PASSWORD
        while True:
            if vault.get(job.owner, "pw") is None:
                await job.ask_secret("pw", prompt, _validate_pw)
            await self._type(page, S.PASSWORD, "pw")
            if await visible(page.locator(S.CAPTCHA_INPUT)):
                await self._solve_captcha(page)
            status, body = await self._submit(page, S.PASSWORD, S.CHECK_LOGIN_API)
            if status == 200:
                break
            if status is None:
                raise FlowError("LOGIN_UI_CHANGED", "no CheckPersonLogin response", T.SITE_DOWN)
            if re.search(r"امنیتی|تصویر|captcha", body, re.I):
                await job.say("❌ کد امنیتی اشتباه بود؛ تصویر جدید ارسال می‌شود.")
                continue
            attempts += 1
            vault.pop(job.owner, "pw")
            if attempts >= config.MAX_PASSWORD_ATTEMPTS:
                raise FlowError("LOGIN_BAD_CREDENTIALS", "wrong password limit", T.TOO_MANY_PASSWORD)
            prompt = T.WRONG_PASSWORD
            if re.search(r"کد ?ملی", body):
                vault.pop(job.owner, "nc")
                await job.ask_secret("nc", "❌ سامانه کدملی یا رمز را نپذیرفت. کدملی را دوباره بفرستید:",
                                     _validate_nc, mask_national_code)
                await self._type(page, S.NATIONAL_CODE, "nc")

        state = await wait_first({
            "otp": lambda: visible(page.locator(S.OTP)),
            "in": lambda: asyncio.sleep(0, self.is_target(page)),
            "expired": lambda: self._expired(page),
        }, timeout_ms=30_000)
        if state == "expired":
            await self._recover_expired(page)
        if state == "in":
            await self._after_login(page)
            return
        if state != "otp":
            raise FlowError("LOGIN_UI_CHANGED", "otp field not shown", T.SITE_DOWN)

        # L07 رمز موقت (دستور کارفرما — آبان ۱۴۰۵، ضبط steps 3):
        # اگر خودِ سامانه پیام «رمز موقت جدید برای شماره همراه شما ارسال شد...»
        # را نشان داده باشد، یعنی رمز تازه پیامک شده ← دکمه‌ی «ارسال رمز موقت»
        # به کاربر نمایش داده نمی‌شود؛ اگر این پیام نیامده، دکمه حتماً هست.
        await self.ctx.step("L07")
        wrong = 0
        prompt = T.ASK_OTP_RELOGIN if relogin else T.ASK_OTP
        if await self._otp_auto_sent(page):
            # خود سامانه پیام «رمز موقت جدید ... ارسال شد» را نشان داده (steps 3)
            prompt = T.ASK_OTP_AUTO
        while True:
            if vault.get(job.owner, "otp") is None:
                # دکمه‌ی «ارسال رمز موقت» فقط وقتی هست که پیامِ ارسالِ خودکار روی
                # صفحه نباشد (دستور کارفرما — ضبط steps 3) و در ۳ ساعت اخیر
                # ارسالِ دستی نداشته باشیم (دستور کارفرما — یک‌بار ارسال ←
                # تا ۳ ساعت دکمه‌ی ارسال در پیام‌های بعدی نیست).
                hidden = await self._otp_auto_sent(page) or await otp_resend_in_cooldown(self.ctx, job.user_id)
                extra = None if hidden else [("resend", T.SEND_OTP_BTN)]
                res = await job.ask_secret("otp", prompt, _validate_otp, lambda v: "•" * len(v),
                                           extra_options=extra)
                if res == ("choice", "resend"):
                    await self._resend(page)
                    await otp_mark_resend(self.ctx, job.user_id)
                    prompt = T.OTP_SENT
                    continue
            await self._type(page, S.OTP, "otp")
            status, _ = await self._submit(page, S.OTP, S.CHECK_OTP_API)
            if status == 200:
                break
            if status is None:
                raise FlowError("LOGIN_UI_CHANGED", "no CheckPersonOtpLogin response", T.SITE_DOWN)
            vault.pop(job.owner, "otp")
            wrong += 1
            if wrong >= max(1, config.MAX_OTP_RESENDS):
                raise FlowError("OTP_RESEND_LIMIT", "wrong otp limit", T.OTP_LIMIT)
            # ارسال مجددِ خودکار انجام نمی‌شود؛ فقط دوباره پرسیده می‌شود (دستور کارفرما)
            prompt = T.OTP_WRONG
        await self._after_login(page)

    async def _after_login(self, page):
        await self.ctx.step("L08")
        state = await wait_first({
            "errorpage": lambda: asyncio.sleep(0, self.on_error_page(page)),
            "in": lambda: asyncio.sleep(0, self.is_target(page)),
            "expired": lambda: self._expired(page),
        }, timeout_ms=45_000)
        if state == "errorpage":
            # صفحه‌ی خطا بعد از ورود (دستور کارفرما): تب بسته و دوباره از گزینه‌ی
            # قبلی وارد می‌شویم؛ پیام مربوط همین‌جا ارسال شده و run() دوباره می‌رود.
            await self.job.say(T.ERROR_PAGE_RETRY)
            if page is not self.br.page:
                with contextlib.suppress(Exception):
                    await page.close()
            raise _Restart("errorpage")
        if state == "expired":
            await self._recover_expired(page)
        if state != "in":
            raise FlowError("TIMEOUT", f"no redirect after login (host={_host(page.url)})", T.SITE_DOWN)
        if await self._expired(page):
            await self._recover_expired(page)

    async def _resend(self, page):
        try:
            async with page.expect_response(lambda r: S.SEND_OTP_API in r.url, timeout=20_000):
                if not await click_text(page, *S.OTP_RESEND, timeout=8_000):
                    raise RuntimeError
        except Exception:
            # شاید سامانه پاسخ را با آدرس دیگری داد؛ کلیک انجام شده یا دکمه نیست
            if not await visible(page.get_by_text(text_re(*S.OTP_RESEND))):
                raise FlowError("LOGIN_UI_CHANGED", "resend otp link missing", T.SITE_DOWN)

    async def _otp_auto_sent(self, page) -> bool:
        """پیام خودِ سامانه روی صفحه‌ی ورود: «رمز موقت جدید برای شماره همراه شما
        ارسال شد. پس از دریافت، د...» (ضبط steps 3 — دستور کارفرما).

        این پیام که هست، خود سامانه رمز تازه فرستاده ← دکمه‌ی «ارسال رمز موقت»
        نمایش داده نمی‌شود؛ نبودش ← دکمه حتماً نمایش داده می‌شود."""
        try:
            txt = await asyncio.wait_for(page_text(page), 4)
        except Exception:
            return False
        txt = normalize_fa(txt)
        return all(w in txt for w in S.OTP_AUTO_SENT_WORDS)

    async def _solve_captcha(self, page):
        """تصویر کپچا (فقط خودِ تصویر، نه صفحه) برای کاربر فرستاده می‌شود تا خودش حل کند."""
        img = page.locator(S.CAPTCHA_IMAGE).first
        try:
            data = await img.screenshot(timeout=10_000)
        except Exception:
            raise FlowError("LOGIN_UI_CHANGED", "captcha image not found", T.SITE_DOWN)
        code = await self.job.ask_text(T.ASK_CAPTCHA, lambda v: (clean_digits(v) or None, "فقط عدد داخل تصویر را بفرستید."),
                                       photo=data)
        await self._type_public(page, S.CAPTCHA_INPUT, code)

    # ── وسط کار: اگر سامانه دوباره به صفحه‌ی ورود برد ─────────────────
    async def ensure(self, page: Page) -> Page:
        """اگر صفحه به ورود/خطای امنیتی/صفحه‌ی خطا رفته، دوباره وارد می‌شود و صفحه‌ی
        معتبر را برمی‌گرداند."""
        if self.on_error_page(page):
            # Login/ErrorPage (دستور کارفرما): تب بسته و ورود دوباره از گزینه‌ی قبلی
            return await self.recover_error_page(page)
        if await self._expired(page):
            with contextlib.suppress(_Restart):
                await self._recover_expired(page)
            return await self.run()
        if "iehraz" in (page.url or "") or await visible(page.locator(S.NATIONAL_CODE)):
            await self.job.say("🔁 سامانه دوباره ورود خواست؛ در حال ورود مجدد…")
            try:
                await self.login(page, relogin=True)
                return page
            except _Restart:
                return await self.run()
        return page


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else "-"
