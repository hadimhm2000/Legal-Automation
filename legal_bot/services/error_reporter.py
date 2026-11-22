"""گزارش مرحله‌ای خطا به مدیر (بخش ۱۳ سند). پیام هرگز مقدار واردشده‌ی کاربر را ندارد.

اصلاحیه (دستور کارفرما): هر خطا در هر مرحله باید «دقیقاً در چه مرحله‌ای» و «بابت چه
موردی» بوده باشد و «اسکرین‌شاتِ همان لحظه» هم برای مدیر ارسال شود —
  • مرحله: شماره + نام + توضیح کامل آن مرحله (STEP_DETAILS)
  • مورد: دسته‌ی خطا + علت به فارسی (CATEGORY_FA)
  • اسکرین‌شات: از صفحه‌ی فعالِ همان لحظه (RunCtx.page) گرفته و همراه پیام می‌رود
"""
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
# توضیح دقیق هر مرحله — «دقیقاً در چه مرحله‌ای» خطا خورده است
STEP_DETAILS = {
    "L01": "ثبت درخواست کاربر در سیستم و ساخت رکورد اجرا",
    "L02": "بررسی اشتراک/قفل حساب و سهمیه استعلام",
    "L03": "اعلان و گرفتن تأیید کاربر پیش از شروع کار",
    "L04": "باز کردن مرورگر، صفحه‌ی اصلی ادلیران و ورود به سامانه‌ی هدف",
    "L05": "تایپ کدملی در فرم ورود سامانه",
    "L06": "تایپ رمز شخصی در فرم ورود سامانه",
    "L07": "ورود رمز موقت (یک‌بارمصرف) پیامک‌شده",
    "L08": "تشخیص موفق بودن ورود و رسیدن به صفحه‌ی اصلی سامانه",
    "L09": "خواندن صفحات سامانه (ابلاغیه/پرونده/نوبت) و چاپ نتایج",
    "L10": "مقایسه‌ی نتایج جدید با دیتابیس برای پیدا کردن موارد تازه",
    "L11": "ارسال نتایج (PDF/متن/عکس) به کاربر در بله",
    "L12": "بستن مرورگر و پاک‌سازی اطلاعات ورود از حافظه",
    "P01": "صدور/ارسال فاکتور و دریافت رسید پرداخت",
}
# «بابت چه موردی» — علت فارسی هر دسته‌ی خطا
CATEGORY_FA = {
    "SESSION_INVALID": "اعتبار نشست ورود در سامانه منقضی شده بود",
    "SANA_DOWN": "سامانه‌ی عدل ایران پاسخ نمی‌داد (قطعی/کندی سامانه)",
    "TIMEOUT": "زمان انتظار همان مرحله تمام شد و نتیجه نتوانست بارگذاری شود",
    "PARSE_CHANGED": "ساختار صفحه‌ی سامانه تغییر کرده و اطلاعات خوانده نشد",
    "LOGIN_UI_CHANGED": "صفحه‌ی ورود سامانه تغییر کرده است",
    "LOGIN_BAD_CREDENTIALS": "اطلاعات ورود (کدملی/رمز شخصی) نادرست بود",
    "OTP_WRONG": "رمز موقت واردشده نادرست بود",
    "OTP_RESEND_LIMIT": "سقف درخواست ارسال مجدد رمز موقت پر شد",
    "BROWSER_CRASH": "خطای مرورگر اتوماسیون (کرش/بسته‌شدن ناگهانی)",
    "PRINT_FAILED": "چاپ نسخه‌ی چاپی/PDF از سامانه ناموفق بود",
    "SEND_FAILED": "ارسال پیام/فایل به کاربر در بله ناموفق بود",
    "PAYMENT": "خطا در فرایند پرداخت/فاکتور",
    "NO_EXECUTION_BRANCH": "شعبه‌ی اجرای احکام برای پرونده تعریف نشده بود",
    "CASE_NOT_FOUND": "پرونده‌ای با شماره‌ی اعلامی در سامانه یافت نشد",
    "NO_SLOT": "ظرفیت نوبت‌دهی شعبه تکمیل بود",
    "TURN_REJECTED": "سامانه علت مراجعه را نپذیرفت و نوبت ثبت نشد",
    "SITE_BUSY": "سامانه شلوغ/ترافیک بالا داشت",
    "SVC_DELAY": "سرویس سامانه با تاخیر پاسخ داد",
    "USER_TIMEOUT": "کاربر در مهلت مقرر پاسخ نداد",
    "CANCELLED": "کاربر عملیات را لغو کرد",
    "UNKNOWN": "خطای ناشناخته/پیش‌بینی‌نشده",
}
KIND_FA = {
    "notices_new": "بررسی ابلاغیه‌های جدید", "notices_case": "ابلاغیه پرونده",
    "notices_notice": "جستجوی ابلاغیه با شماره", "notices_range": "جستجوی ابلاغیه در بازه زمانی",
    "case_list": "فهرست پرونده‌ها", "case_detail": "جزئیات پرونده", "case_track": "پیگیری تغییرات پرونده",
    "turn": "ثبت نوبت قضائی", "turn_prepare": "آماده‌سازی فاکتور نوبت",
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


def _report_text(*, run_id, user_id, user_name, step, category, message, steps_ok, kind) -> str:
    """متن گزارش دقیق: مرحله + مورد + اقدام ربات (بدون هیچ مقدار ورودی کاربر)."""
    chain = " ".join([f"✅{s}" for s in (steps_ok or "").split(",") if s] + [f"❌{step}"])
    head = f"⚠️ خطا در {KIND_FA.get(kind, 'بررسی')}"
    if run_id:
        head += f" #{run_id}"
    step_line = f"📍 مرحله {step}: {STEPS.get(step, '')}"
    detail = STEP_DETAILS.get(step)
    if detail:
        step_line += f"\n🎯 کارِ این مرحله: {detail}"
    user_line = f"👤 کاربر: {user_id}"
    if user_name:
        user_line += f" ({user_name})"
    return (
        f"{head}\n"
        f"{step_line}\n"
        f"{chain}\n"
        f"🏷 نوع خطا: {category} — {CATEGORY_FA.get(category, 'نامشخص')}\n"
        f"🤖 اقدام ربات: {ACTIONS.get(category, '-')}\n"
        f"{user_line}   🕒 {to_fa_digits(now_tehran().strftime('%H:%M'))}\n"
        f"📝 {message}"
    )


async def report(bot, db, *, run_id, user_id, step, category, message="", steps_ok="",
                 screenshot: bytes | None = None, kind: str = "", user_name: str = ""):
    """ثبت خطا + پیام فوری به مدیر.

    screenshot: تصویرِ صفحه‌ی همان لحظه (اگر مرورگر باز بود) — همراه پیام برای مدیر
    می‌رود تا دقیقاً ببیند صفحه در لحظه‌ی خطا چه وضعیتی داشت.
    kind / user_name: برای گزارش دقیق‌تر «در کدام کار» و «چه کاربری».
    """
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
    text = _report_text(run_id=run_id, user_id=user_id, user_name=user_name, step=step,
                        category=category, message=message, steps_ok=steps_ok, kind=kind)
    if len(same_step_users) >= 3:
        text = (f"🚨 احتمالاً مشکل از سامانه یا ساختار صفحه است: {len(same_step_users)} کاربر "
                f"در ۱۰ دقیقه‌ی اخیر در مرحله‌ی {step} خطا خوردند.\n\n") + text
    try:
        sent = False
        if screenshot and config.ERROR_SHOT_TO_ADMIN:
            try:
                from aiogram.types import BufferedInputFile

                await bot.send_photo(
                    config.ADMIN_ID, BufferedInputFile(screenshot, "error_step.png"),
                    caption=text[:1000])
                sent = True
            except Exception as e:
                log.warning("error screenshot send failed (%s) — falling back to text", type(e).__name__)
        if not sent:
            await bot.send_message(config.ADMIN_ID, text)
    except Exception:
        log.warning("could not notify admin")
