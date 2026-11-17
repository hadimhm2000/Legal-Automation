"""توابع خالص و تست‌پذیر: ارقام، کدملی، شماره پرونده، تاریخ شمسی، ماسک، نرمال‌سازی متن."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی", "ة": "ه", "‌": " ", "‏": "", "‎": ""})


def to_en_digits(s: str) -> str:
    return (s or "").translate(_DIGITS)


def normalize_fa(s: str) -> str:
    """ارقام لاتین، ی و ک فارسی، نیم‌فاصله ← فاصله، فاصله‌های تکراری حذف."""
    s = to_en_digits(s or "").translate(_ARABIC_LETTERS)
    return re.sub(r"[ \t\xa0]+", " ", s)


def to_fa_digits(s) -> str:
    return str(s).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def fmt_toman(n: int) -> str:
    return to_fa_digits(f"{int(n):,}".replace(",", "٬")) + " تومان"


# ── کدملی ────────────────────────────────────────────────────────────
def clean_digits(s: str) -> str:
    return re.sub(r"\D", "", to_en_digits(s or ""))


def valid_national_code(code: str) -> bool:
    code = clean_digits(code)
    if len(code) != 10 or len(set(code)) == 1:
        return False
    check = int(code[9])
    s = sum(int(code[i]) * (10 - i) for i in range(9)) % 11
    return (s < 2 and check == s) or (s >= 2 and check == 11 - s)


def mask_national_code(code: str) -> str:
    code = clean_digits(code)
    if len(code) < 4:
        return "*" * len(code)
    return to_fa_digits(code[:2] + "*" * (len(code) - 4) + code[-2:])


# ── شماره پرونده ─────────────────────────────────────────────────────
def validate_case_number(raw: str) -> tuple[str | None, str | None]:
    """(شماره‌ی تمیز، None) یا (None، دلیل اشتباه).

    قاعده‌ی کارفرما: شروع با 14 → دقیقاً ۱۸ رقم؛ شروع با 9 → دقیقاً ۱۶ رقم.
    """
    txt = to_en_digits(raw or "").strip()
    num = re.sub(r"[\s\-_/]", "", txt)
    if not num.isdigit():
        return None, "شماره پرونده فقط باید شامل عدد باشد."
    if num.startswith("14"):
        if len(num) != 18:
            return None, (f"شماره پرونده‌ای که با ۱۴ شروع می‌شود باید ۱۸ رقمی باشد؛ "
                          f"شماره‌ی ارسالی شما {to_fa_digits(len(num))} رقم است.")
        return num, None
    if num.startswith("9"):
        if len(num) != 16:
            return None, (f"شماره پرونده‌ای که با ۹ شروع می‌شود باید ۱۶ رقمی باشد؛ "
                          f"شماره‌ی ارسالی شما {to_fa_digits(len(num))} رقم است.")
        return num, None
    return None, "شماره پرونده باید با ۱۴ (۱۸ رقمی) یا ۹ (۱۶ رقمی) شروع شود."


def validate_archive_number(raw: str) -> tuple[str | None, str | None]:
    num = clean_digits(raw)
    if not num or len(num) < 3 or len(num) > 12:
        return None, "شماره بایگانی معتبر نیست (فقط عدد، معمولاً ۷ رقم)."
    return num, None


# ── شماره ابلاغیه ────────────────────────────────────────────────────
def validate_notice_number(raw: str) -> tuple[str | None, str | None]:
    """شماره‌ی ابلاغیه در نمونه‌های کارفرما ۱۸ رقم است؛ بازه‌ی ۱۲ تا ۲۰ رقم پذیرفته می‌شود."""
    num = clean_digits(raw)
    if 12 <= len(num) <= 20:
        return num, None
    return None, (f"شماره ابلاغیه باید ۱۲ تا ۲۰ رقم باشد؛ "
                  f"شماره‌ی ارسالی شما {to_fa_digits(len(num))} رقم است.")


# ── تاریخ ────────────────────────────────────────────────────────────
def now_tehran() -> dt.datetime:
    return dt.datetime.now(TEHRAN)


def today_tehran() -> dt.date:
    return now_tehran().date()


_JDATE_RE = re.compile(r"(1[34]\d{2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})")


def parse_jalali(s: str) -> dt.date | None:
    """«1405/08/30» یا «۱۴۰۵.۰۸.۳۰» → date میلادی؛ نامعتبر → None."""
    m = _JDATE_RE.search(to_en_digits(s or ""))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return jdatetime.date(y, mo, d).togregorian()
    except ValueError:
        return None


def count_jalali_dates(s: str) -> int:
    """تعداد تاریخ‌های شمسی موجود در یک متن (برای اعتبارسنجی ورودی چندتایی:
    بخشی که دو تاریخ دارد — مثل «۱۴۰۵/۰۹/۱۰ و ۱۴۰۵/۰۹/۲۰» — رد می‌شود)."""
    return len(_JDATE_RE.findall(to_en_digits(s or "")))


def to_jalali_str(d: dt.date | None, sep: str = "/") -> str:
    if not d:
        return "-"
    j = jdatetime.date.fromgregorian(date=d)
    return f"{j.year:04d}{sep}{j.month:02d}{sep}{j.day:02d}"


def fa_date(d: dt.date | None) -> str:
    return to_fa_digits(to_jalali_str(d)) if d else "-"


WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]


def weekday_fa(d: dt.date) -> str:
    return WEEKDAYS_FA[d.weekday()]


# ── تقویم نوبت‌دهی (دستور کارفرما — آبان ۱۴۰۵) ─────────────────────────
JALALI_MONTHS_FA = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")

# تعطیلات رسمیِ با تاریخ ثابت شمسی (فروردین ۱-۴، ۱۲ و ۱۳؛ ۱۴ و ۱۵ خرداد؛
# ۲۲ بهمن؛ ۲۹ اسفند). تعطیلات قمری هر سال جابه‌جا می‌شوند و از پیام خطای خودِ
# سامانه هنگام انتخاب روز تشخیص داده می‌شوند (رد شدن به روز بعد).
OFFICIAL_HOLIDAYS_JALALI = {
    (1, 1), (1, 2), (1, 3), (1, 4),   # عید نوروز
    (1, 12), (1, 13),                 # روز جمهوری اسلامی / سیزده‌بدر
    (3, 14), (3, 15),                 # رحلت امام خمینی / قیام ۱۵ خرداد
    (11, 22),                         # پیروزی انقلاب اسلامی
    (12, 29),                         # ملی شدن صنعت نفت
}


def jalali_of(d: dt.date) -> jdatetime.date:
    return jdatetime.date.fromgregorian(date=d)


def is_off_day(d: dt.date) -> bool:
    """پنجشنبه/جمعه یا تعطیل رسمی شمسی؟ (دستور کارفرما: این روزها هرگز انتخاب نمی‌شوند)"""
    if d.weekday() in (3, 4):          # پنجشنبه=۳، جمعه=۴
        return True
    j = jalali_of(d)
    return (j.month, j.day) in OFFICIAL_HOLIDAYS_JALALI


def turn_candidate_days(lookahead: int = 14) -> list[dt.date]:
    """روزهای نامزد نوبت: از «فردا» (نه امروز — دستور کارفرما)، بدون پنجشنبه/جمعه/تعطیل رسمی."""
    out: list[dt.date] = []
    cur = today_tehran() + dt.timedelta(days=1)
    for _ in range(max(lookahead * 3, lookahead + 20)):
        if len(out) >= max(1, lookahead):
            break
        if not is_off_day(cur):
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


def parse_jalali_header(header: str) -> tuple[int, int] | None:
    """سربرگ تقویم («آبان ۱۴۰۵» / «۱۴۰۵ آبان») ← (سال، ماه)؛ ناخوانا ← None."""
    t = normalize_fa(header or "")
    m = re.search(r"(1[34]\d{2})", t)
    if not m:
        return None
    year = int(m.group(1))
    for i, name in enumerate(JALALI_MONTHS_FA, 1):
        if name in t:
            return year, i
    return None


def date_windows(start: dt.date, end: dt.date, days: int = 30) -> list[tuple[dt.date, dt.date]]:
    """بازه‌ی کاربر را به تکه‌های حداکثر `days` روزه (شامل هر دو سر) می‌شکند."""
    if end < start:
        start, end = end, start
    out = []
    cur = start
    while cur <= end:
        stop = min(cur + dt.timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + dt.timedelta(days=1)
    return out


def year_windows(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """شکستن بازه به پنجره‌های «یک‌ساله» با مرز سال شمسی (فروردین تا اسفند).

    برای استعلامِ بازه‌ی بیشتر در اطلاع‌رسانی پرونده: سامانه بازه‌ی بیش از یک سال را
    یک‌جا نمی‌پذیرد، پس سال‌به‌سال جدا و جدا استعلام می‌شود.
    """
    if end < start:
        start, end = end, start
    out = []
    cur = start
    one_day = dt.timedelta(days=1)
    while cur <= end:
        j = jdatetime.date.fromgregorian(date=cur)
        year_end = jdatetime.date(j.year + 1, 1, 1).togregorian() - one_day   # آخرین روز اسفند
        stop = min(year_end, end)
        out.append((cur, stop))
        cur = stop + one_day
    return out


def subtract_ranges(start: dt.date, end: dt.date,
                    exclude: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    """بازه‌ی [start, end] منهای بازه‌های `exclude` → بازه‌های باقی‌مانده (مرتب و بدون هم‌پوشانی).

    برای اینکه بازه‌ای که ابتدای کار استعلام شده، دوباره استعلام نشود.
    """
    if end < start:
        start, end = end, start
    one_day = dt.timedelta(days=1)

    def _clip(pair):
        s, e = pair
        return max(s, start), min(e, end)

    parts = sorted(_clip(p) for p in exclude if p[0] and p[1] and _clip(p)[0] <= _clip(p)[1])
    out, cur = [], start
    for s, e in parts:
        if s > cur:
            out.append((cur, min(s - one_day, end)))
        cur = max(cur, e + one_day)
    if cur <= end:
        out.append((cur, end))
    return [(s, e) for s, e in out if s <= e]


def hhmm_to_time(s: str) -> dt.time | None:
    m = re.search(r"(\d{1,2})\s*:\s*(\d{2})", to_en_digits(s or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return dt.time(h, mi)
    return None


def looks_like_secret(text: str) -> bool:
    """پیامی که خارج از جریان ورود فرستاده شده و شبیه کدملی/رمز است."""
    t = to_en_digits((text or "").strip())
    if not t or " " in t or len(t) > 32:
        return False
    if valid_national_code(t):
        return True
    return 4 <= len(t) <= 8 and t.isdigit()
