"""تنظیمات ربات دوم (اتوماسیون ویژه خدمات حقوقی) — همه از متغیرهای محیطی.

این فایل عمداً در زمان import خطا نمی‌دهد (برخلاف ربات اصلی) تا تست‌ها بدون توکن اجرا شوند؛
بررسی الزامی بودن مقادیر در bot_main.validate_config انجام می‌شود.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def _ids(name):
    raw = os.environ.get(name, "") or ""
    out = set()
    for p in raw.replace("،", ",").split(","):
        p = p.strip()
        if p.lstrip("-").isdigit():
            out.add(int(p))
    return out


LEGAL_BOT_TOKEN = os.environ.get("LEGAL_BOT_TOKEN", "")
BALE_API_BASE = os.environ.get("BALE_API_BASE", "https://tapi.bale.ai")
ADMIN_ID = _int("ADMIN_ID", 0)
BETA_IDS = _ids("BETA_IDS") | ({ADMIN_ID} if ADMIN_ID else set())
HANDOFF_SECRET = os.environ.get("HANDOFF_SECRET", "")
HANDOFF_TTL_SEC = _int("HANDOFF_TTL_SEC", 300)
# اگر 0 باشد، /start بدون توکن هم برای اعضای بتا پذیرفته می‌شود (برای تست)
REQUIRE_HANDOFF = os.environ.get("REQUIRE_HANDOFF", "1") != "0"

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "data" / "legal.db"))
LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))

CARD_NUMBER = os.environ.get("CARD_NUMBER", "")
CARD_HOLDER = os.environ.get("CARD_HOLDER", "")
CARD_BANK = os.environ.get("CARD_BANK", "")
INVOICE_EXPIRE_HOURS = _int("INVOICE_EXPIRE_HOURS", 48)
TEST_PRICE_TOMAN = _int("TEST_PRICE_TOMAN", 0)  # فقط برای مدیر؛ 0 = غیرفعال

TRIAL_DAYS = _int("TRIAL_DAYS", 3)
PRICE_NOTICES = _int("PRICE_NOTICES", 500_000)
PRICE_CASE_ALERTS = _int("PRICE_CASE_ALERTS", 500_000)
PRICE_BOTH = _int("PRICE_BOTH", 800_000)
PRICE_TURN = _int("PRICE_TURN", 70_000)  # هر درخواست ثبت نوبت قضائی
SUB_DAYS = _int("SUB_DAYS", 30)

TZ = "Asia/Tehran"
CHECK_TIMES = [t.strip() for t in os.environ.get("CHECK_TIMES", "08:00,18:00").split(",") if t.strip()]
CASE_TRACK_TIME = os.environ.get("CASE_TRACK_TIME", "08:00")
REMINDER_TIME = os.environ.get("REMINDER_TIME", "09:00")
MAX_CHECKS_PER_USER_PER_DAY = _int("MAX_CHECKS_PER_USER_PER_DAY", 6)
MAX_CONCURRENT_BROWSERS = _int("MAX_CONCURRENT_BROWSERS", 2)

ADLIRAN_BASE_URL = os.environ.get("ADLIRAN_BASE_URL", "https://adliran.ir/")
EBLAGH_MAIN_URL = os.environ.get("EBLAGH_MAIN_URL", "http://eblagh1.adliran.ir")
RESULTCASE_PERSON_URL = "https://resultcase.adliran.ir/ResultCase/CaseListForPerson"
RESULTCASE_LAWYER_URL = "https://resultcase.adliran.ir/ResultCase/CaseListForLawyer"
TURN_URL = "https://adliran.ir/Turn/Index"

LOGIN_STEP_TIMEOUT_SEC = _int("LOGIN_STEP_TIMEOUT_SEC", 300)
LOGIN_TOTAL_TIMEOUT_SEC = _int("LOGIN_TOTAL_TIMEOUT_SEC", 900)
JOB_TOTAL_TIMEOUT_SEC = _int("JOB_TOTAL_TIMEOUT_SEC", 3600)
MAX_OTP_RESENDS = _int("MAX_OTP_RESENDS", 3)
MAX_PASSWORD_ATTEMPTS = _int("MAX_PASSWORD_ATTEMPTS", 3)
MAX_PORTAL_ENTRY_ATTEMPTS = _int("MAX_PORTAL_ENTRY_ATTEMPTS", 4)


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


# ── رفتار انسانی (سرعت پایین، مکث تصادفی، انتظار برای لود کامل) ──
TYPE_DELAY_MS = _int("TYPE_DELAY_MS", 120)        # پایه‌ی تاخیر تایپ هر نویسه
STEP_PAUSE_MS = _int("STEP_PAUSE_MS", 1500)       # پایه‌ی مکث بین مراحل
HUMAN_JITTER = _float("HUMAN_JITTER", 1.0)        # تا ۱۰۰٪ تصادفی اضافه بر پایه (تایپ ۱۲۰–۲۴۰، مکث ۱٫۵–۳ ثانیه)
SPEED_FACTOR = _float("SPEED_FACTOR", 1.0)        # ضریب کلی سرعت؛ بزرگ‌تر = کندتر (مثلاً ۱٫۵)
PAGE_SETTLE_MS = _int("PAGE_SETTLE_MS", 1500)     # مکث انسانی بعد از لود کامل هر صفحه
SEARCH_WAIT_MS = _int("SEARCH_WAIT_MS", 25000)    # حداکثر انتظار برای ظاهر شدن نتیجه/CTA بعد از جستجو
PRINT_RETRY_WAIT_SEC = _int("PRINT_RETRY_WAIT_SEC", 10)
PRINT_MAX_TRIES = _int("PRINT_MAX_TRIES", 3)
ATTACHMENT_WAIT_SEC = _int("ATTACHMENT_WAIT_SEC", 120)
ATTACHMENT_MAX_TRIES = _int("ATTACHMENT_MAX_TRIES", 3)
DATE_WINDOW_DAYS = _int("DATE_WINDOW_DAYS", 30)
TURN_MAX_SLOT_TRIES = _int("TURN_MAX_SLOT_TRIES", 8)

# ── مرورگر ──
# پیش‌فرض ۰ = مرورگر «قابل مشاهده» باز می‌شود تا رفتار ربات را ببینید.
# روی سرور بدون نمایشگر، خودکار به headless برمی‌گردد.
HEADLESS = os.environ.get("HEADLESS", "0") != "0"
# پنجره‌ی این ربات گوشه‌ی بالا-چپ و کمی بلندتر باز می‌شود تا با پنجره‌ی
# ربات اصلی (وسط صفحه، ۱۳۶۶×۷۶۸) قاطی نشود.
BROWSER_WINDOW_POSITION = os.environ.get("BROWSER_WINDOW_POSITION", "0,0")
BROWSER_WINDOW_SIZE = os.environ.get("BROWSER_WINDOW_SIZE", "1366x900")
# فقط در صورت ضرورت (گواهی خراب یک زیردامنه) — پیش‌فرض خاموش تا اطلاعات ورود فقط روی TLS معتبر برود
IGNORE_HTTPS_ERRORS = os.environ.get("IGNORE_HTTPS_ERRORS", "0") == "1"

SUPPORT_PHONE = os.environ.get("SUPPORT_PHONE", "09306186888")
LAVAYEH_BOT = os.environ.get("LAVAYEH_BOT", "@onlinejudicialservices_bot")

GUIDE_PDF_PATH = str(ASSETS_DIR / "guide.pdf")
FONT_REGULAR = str(ASSETS_DIR / "fonts" / "Vazirmatn-FD-Regular.ttf")
FONT_BOLD = str(ASSETS_DIR / "fonts" / "Vazirmatn-FD-Bold.ttf")


def missing_required():
    out = []
    for name, val in (("LEGAL_BOT_TOKEN", LEGAL_BOT_TOKEN), ("ADMIN_ID", ADMIN_ID)):
        if not val:
            out.append(name)
    if REQUIRE_HANDOFF and not HANDOFF_SECRET:
        out.append("HANDOFF_SECRET")
    return out
