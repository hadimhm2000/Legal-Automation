"""گزارش مرحله‌ای خطا به مدیر (بخش ۱۳ سند). پیام هرگز مقدار واردشده‌ی کاربر را ندارد."""
from __future__ import annotations

import logging
import time

from .. import config
from ..utils import now_tehran, to_fa_digits

log = logging.getLogger(__name__)

STEPS = {
    "L01": "ثبت درخواست", "L02": "بررسی اشتراک/قفل", "L03": "اعلان و تأیید کاربر",
    "L04": "باز کردن مرورگر و صفحه‌ی ورود", "L05": "کدملی", "L06": "رمز شخصی",
    "L07": "رمز موقت", "L08": "تشخیص ورود موفق", "L09": "خواندن صفحات / چاپ",
    "L10": "مقایسه با دیتابیس", "L11": "ارسال به کاربر", "L12": "بستن مرورگر و پاک‌سازی",
    "P01": "پرداخت",
}
USER_ERRORS = {"LOGIN_BAD_CREDENTIALS", "OTP_WRONG", "OTP_RESEND_LIMIT", "USER_TIMEOUT", "CANCELLED"}
ACTIONS = {
    "SESSION_INVALID": "پایان همین بررسی", "SANA_DOWN": "توقف و اطلاع به کاربر",
    "TIMEOUT": "توقف و اطلاع به کاربر", "PARSE_CHANGED": "ادامه با موارد بعدی / توقف",
    "LOGIN_UI_CHANGED": "توقف", "BROWSER_CRASH": "بستن مرورگر", "PRINT_FAILED": "ادامه با ابلاغیه‌ی بعدی",
    "SEND_FAILED": "ثبت در گزارش", "PAYMENT": "اطلاع به مدیر", "UNKNOWN": "توقف",
    "NO_EXECUTION_BRANCH": "توقف؛ پرداخت نوبت استفاده‌نشده ماند", "CASE_NOT_FOUND": "توقف؛ پرداخت محفوظ",
    "NO_SLOT": "توقف؛ پرداخت محفوظ", "TURN_REJECTED": "توقف؛ پرداخت محفوظ",
    "SITE_BUSY": "توقف و اطلاع به کاربر", "SVC_DELAY": "توقف و اطلاع به کاربر",
}

_last: dict[tuple, float] = {}
_recent: list[tuple[float, int, str]] = []


def _redact(msg: str) -> str:
    """توکن، کوکی، پارامتر URL، «Call log» پلی‌رایت، input_value پایدانتیک، کدملی و مقادیر vault حذف می‌شوند."""
    import re

    from .session import vault

    msg = vault.scrub(msg or "")
    msg = msg.split("Call log")[0]                      # لاگ داخلی Playwright ممکن است مقدار فیلد را داشته باشد
    msg = re.sub(r"input_value=('[^']*'|\"[^\"]*\"|\S+)", "input_value=<hidden>", msg)
    msg = re.sub(r"(?<!\d)\d{10}(?!\d)", "<10digits>", msg)   # کدملی
    msg = re.sub(r"bot\d+:[\w-]+", "bot<TOKEN>", msg)
    msg = re.sub(r"(?i)(cookie|set-cookie|authorization)[^\n]*", r"\1: <hidden>", msg)
    msg = re.sub(r"https?://\S+\?\S+", lambda m: m.group(0).split("?")[0] + "?<params>", msg)
    return msg[:400]


async def report(bot, db, *, run_id, user_id, step, category, message="", steps_ok=""):
    message = _redact(message)
    try:
        await db.add_error(run_id, user_id, step, category, message)
        if run_id:
            await db.finish_run(run_id, "failed", category)
    except Exception:
        log.exception("db error while reporting")
    if category in USER_ERRORS or not config.ADMIN_ID:
        return
    now = time.time()
    key = (user_id, category, step)
    if now - _last.get(key, 0) < 300:
        return
    _last[key] = now
    _recent.append((now, user_id, step))
    _recent[:] = [r for r in _recent if now - r[0] < 600]
    same_step_users = {u for t, u, s in _recent if s == step}
    chain = " ".join([f"✅{s}" for s in (steps_ok or "").split(",") if s] + [f"❌{step}"])
    text = (f"⚠️ خطا در بررسی #{run_id or '-'} — مرحله {step}: {STEPS.get(step, '')}\n"
            f"👤 کاربر: {user_id}   🕒 {to_fa_digits(now_tehran().strftime('%H:%M'))}\n"
            f"{chain}\n🏷 نوع: {category}   🤖 اقدام ربات: {ACTIONS.get(category, '-')}\n📝 {message}")
    if len(same_step_users) >= 3:
        text = (f"🚨 احتمالاً مشکل از سامانه یا ساختار صفحه است: {len(same_step_users)} کاربر "
                f"در ۱۰ دقیقه‌ی اخیر در مرحله‌ی {step} خطا خوردند.\n\n") + text
    try:
        await bot.send_message(config.ADMIN_ID, text)
    except Exception:
        log.warning("could not notify admin")
