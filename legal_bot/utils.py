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
