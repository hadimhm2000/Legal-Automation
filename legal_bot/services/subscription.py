"""موتور پلن‌های درآمدی جدید (دستور کارفرما — آبان ۱۴۰۵).

مدل:
  🎁 شروع رایگان — ۲ استعلام برای هر دو بخش، با تأیید شماره موبایل، یک‌بار برای هر حساب/شماره.
  👤 پلن‌های شخصی (پایه/برگزیده) — اعتبار استعلام ۱۰/۲۰ عددی؛ تاریخ انقضا ندارند.
  ⚖️ پلن‌های حرفه‌ای (پیشرو/تخصصی/سازمانی) — دوره‌ی ماهانه/۳ماهه + سهمیه استعلام ماهانه +
     پیگیری خودکار روزانه تا سقف تعداد پرونده.

قواعد (متن قوانین ربات):
  ۱) هر استعلام = یک‌بار ورود ربات به سامانه و بازیابی نتیجه ← از سهمیه کم می‌شود.
  ۲) پیگیری‌های خودکار روزانه از سهمیه کم نمی‌شوند؛ فقط سقف تعداد پرونده دارند.
  ۳) سهمیه هر ماه صفر می‌شود و به ماه بعد منتقل نمی‌شود، حتی در اشتراک ۳ ماهه.
  ۴) پلن سازمانی: سقف روزانه ۵۰ استعلام دستی.
  ۵) هر اشتراک فقط برای یک حساب کاربری است.
  ۶) مصرف غیرعادی ← محدودیت موقت + گزارش به مدیر.
  ۷) بعد از فعال‌سازی و استفاده، وجه برگشت داده نمی‌شود.
  ۸) هشدار تمدید چند روز قبل از پایان؛ پرونده‌ها تا چند روز بعد از انقضا نگه داشته می‌شوند.
  ۹) ارتقای وسط دوره با مابه‌التفاوت نسبی.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import config
from ..db import DB, new_code, now_iso, parse_iso
from ..utils import now_tehran, to_fa_digits

log = logging.getLogger(__name__)

ACTIVE = ("FREE_ACTIVE", "PAID_ACTIVE")
INQUIRY_KINDS = ("notices_new", "notices_case", "notices_notice", "notices_range",
                 "case_list", "case_detail", "case_track")

# ── تعریف پلن‌ها ────────────────────────────────────────────────────────────
PLANS: dict[str, dict] = {
    "free": dict(title="شروع رایگان", kind="free", inquiries=config.FREE_INQUIRIES),
    "base": dict(title="پلن پایه", kind="credit", inquiries=config.PLAN_BASE_INQUIRIES,
                 price=config.PLAN_BASE_PRICE),
    "select": dict(title="پلن برگزیده", kind="credit", inquiries=config.PLAN_SELECT_INQUIRIES,
                   price=config.PLAN_SELECT_PRICE),
    "pro": dict(title="پلن پیشرو", kind="sub", quota=config.PLAN_PRO_QUOTA, cases=config.PLAN_PRO_CASES,
                monthly=config.PLAN_PRO_MONTHLY, quarterly=config.PLAN_PRO_QUARTERLY),
    "expert": dict(title="پلن تخصصی", kind="sub", quota=config.PLAN_EXPERT_QUOTA, cases=config.PLAN_EXPERT_CASES,
                   monthly=config.PLAN_EXPERT_MONTHLY, quarterly=config.PLAN_EXPERT_QUARTERLY),
    "org": dict(title="پلن سازمانی", kind="sub", quota=config.PLAN_ORG_QUOTA, cases=config.PLAN_ORG_CASES,
                monthly=config.PLAN_ORG_MONTHLY, quarterly=config.PLAN_ORG_QUARTERLY),
}
SUB_PLANS = ("pro", "expert", "org")          # پلن‌های دارای پیگیری خودکار
_CYCLE_DAYS = {"monthly": config.SUB_DAYS, "quarterly": config.QUARTERLY_DAYS}
CYCLE_FA = {"monthly": "ماهانه", "quarterly": "۳ ماهه", None: "", "credit": ""}


def plan_meta(plan: str | None) -> dict:
    return PLANS.get(plan or "", {})


def plan_title(plan: str | None) -> str:
    return plan_meta(plan).get("title", "بدون پلن")


def cycle_days(cycle: str | None) -> int:
    return _CYCLE_DAYS.get(cycle or "", config.SUB_DAYS)


def plan_price(plan: str, cycle: str | None = None) -> int:
    m = plan_meta(plan)
    if m.get("kind") == "credit":
        return m["price"]
    return m["monthly"] if (cycle or "monthly") == "monthly" else m["quarterly"]


def upgrade_amount(old_plan: str | None, days_left: int, new_plan: str, new_cycle: str | None = None) -> int:
    """قاعده ۹ — مابه‌التفاوت نسبی ارتقا وسط دوره (گرد به نزدیک‌ترین ۱۰۰۰ تومان).

    ارتقای ماهانه: (قیمت ماهانه‌ی جدید − قیمت ماهانه‌ی فعلی) × روزهای باقی‌مانده ÷ ۳۰
    ارتقای ۳ماهه: قیمت دوره‌ی جدید − ارزش روزهای باقی‌مانده‌ی دوره‌ی فعلی
    """
    new_cycle = new_cycle or "monthly"
    m_new, m_old = plan_meta(new_plan), plan_meta(old_plan)
    old_monthly = m_old.get("monthly", 0)
    if new_cycle == "quarterly":
        raw = m_new["quarterly"] - old_monthly * max(0, days_left) / 30
    else:
        raw = (m_new["monthly"] - old_monthly) * max(0, days_left) / 30
    return max(0, int(round(raw / 1000.0)) * 1000)


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def tehran_month() -> str:
    """«YYYY-MM» به وقت تهران — کلید سهمیه ماهانه (قاعده ۳)."""
    n = now_tehran()
    return f"{n.year:04d}-{n.month:02d}"


async def _get_raw(db: DB, uid: int) -> dict:
    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    if not s:
        await db.execute("INSERT OR IGNORE INTO subscriptions(bale_id,status,updated_at) VALUES(?,?,?)",
                         (uid, "NEW", now_iso()))
        s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    return await refresh(db, s)


def _is_admin_free(uid: int) -> bool:
    return bool(config.ADMIN_FREE and config.ADMIN_ID and uid == config.ADMIN_ID)


async def get(db: DB, uid: int) -> dict:
    s = await _get_raw(db, uid)
    if _is_admin_free(uid):
        far = utcnow() + dt.timedelta(days=3650)
        ok = (s["status"] == "PAID_ACTIVE" and s["plan"] == "org" and s["paid_until"]
              and parse_iso(s["paid_until"]) > utcnow() + dt.timedelta(days=3000)
              and not s.get("restricted_until"))
        if not ok:
            await _set(db, uid, status="PAID_ACTIVE", plan="org", cycle="quarterly",
                       paid_until=far.isoformat(), quota_total=0, quota_used=0,
                       quota_month=tehran_month(), restricted_until=None,
                       restriction_reason=None, locked_at=None)
            s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    return s


async def _set(db, uid, **kw):
    kw["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in kw)
    await db.execute(f"UPDATE subscriptions SET {cols} WHERE bale_id=?", (*kw.values(), uid))


async def refresh(db: DB, s: dict) -> dict:
    """قفل/تنزل خودکار + صفر شدن سهمیه ماهانه (قواعد ۳ و ۸)."""
    now = utcnow()
    s = await _ensure_month(db, s)
    uid = s["bale_id"]
    if s["status"] == "FREE_ACTIVE" and (s["inquiries_left"] or 0) <= 0:
        await _set(db, uid, status="LOCKED", locked_at=now_iso(), plan=None)
        await db.add_plan_event(uid, "locked", "free", "پایان شروع رایگان")
        s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    elif s["status"] == "PAID_ACTIVE":
        end = parse_iso(s["paid_until"]) if s["paid_until"] else None
        if end and end <= now:
            if (s["inquiries_left"] or 0) > 0:
                # دوره تمام شد اما اعتبار استعلام شخصی مانده → فقط اعتبار (قاعده ۸)
                if s["plan"]:  # هنوز تنزل نشده — رویداد فقط یک‌بار
                    await _set(db, uid, plan=None, cycle=None, quota_total=0, quota_used=0)
                    await db.add_plan_event(uid, "degraded", s["plan"], "پایان دوره؛ اعتبار باقی‌مانده فعال است")
                    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
            else:
                await _set(db, uid, status="LOCKED", locked_at=now_iso(), plan=None, cycle=None,
                           quota_total=0, quota_used=0)
                await db.add_plan_event(uid, "locked", s["plan"], "پایان دوره")
            s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
        elif not end and (s["inquiries_left"] or 0) <= 0 and s["plan"] not in (None, "free") \
                and s["plan"] not in SUB_PLANS:
            # پلن شخصی بدون دوره: اعتبار تمام شده → قفل
            await _set(db, uid, status="LOCKED", locked_at=now_iso(), plan=None)
            await db.add_plan_event(uid, "locked", s["plan"], "پایان اعتبار استعلام")
            s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    # پایان محدودیت موقت (قاعده ۶)
    if s.get("restricted_until") and parse_iso(s["restricted_until"]) <= now:
        await _set(db, uid, restricted_until=None, restriction_reason=None)
        s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    return s


async def _ensure_month(db: DB, s: dict) -> dict:
    """قاعده ۳ — با تغییر ماه شمسی، سهمیه صفر می‌شود (حتی در اشتراک ۳ ماهه)."""
    if s["status"] != "PAID_ACTIVE" or not s["plan"]:
        return s
    cur = tehran_month()
    if s["quota_month"] != cur:
        await _set(db, s["bale_id"], quota_month=cur, quota_used=0)
        await db.add_plan_event(s["bale_id"], "quota_reset", s["plan"],
                                f"شروع ماه {cur}؛ سهمیه صفر شد")
        s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (s["bale_id"],))
    return s


# ── دسترسی سرویس ───────────────────────────────────────────────────────────
async def has_service(db: DB, uid: int, service: str) -> bool:
    """service: notices | case_alerts — در مدل جدید هر دو بخش با هر پلن فعال قابل استفاده‌اند.
    سهمیه استعلام جداگانه در can_inquiry بررسی می‌شود."""
    s = await get(db, uid)
    if s["status"] not in ACTIVE:
        return False
    return not _is_restricted(s)


def _is_restricted(s: dict) -> bool:
    ru = s.get("restricted_until")
    return bool(ru and parse_iso(ru) > utcnow())


async def has_auto_tracking(db: DB, uid: int) -> bool:
    """پیگیری خودکار روزانه (ابلاغیه ۸/۱۸ + بررسی روزانه پرونده) فقط در پلن‌های حرفه‌ای."""
    s = await get(db, uid)
    if s["status"] != "PAID_ACTIVE" or s["plan"] not in SUB_PLANS:
        return False
    end = parse_iso(s["paid_until"]) if s["paid_until"] else None
    return bool(end and end > utcnow()) and not _is_restricted(s)


async def case_cap(db: DB, uid: int) -> int:
    """سقف ثبت پرونده برای بررسی روزانه (قاعده ۲: پیگیری خودکار سقف پرونده دارد)."""
    if await has_auto_tracking(db, uid):
        return int(plan_meta((await get(db, uid))["plan"]).get("cases", 0))
    return 0


# ── سهمیه استعلام ───────────────────────────────────────────────────────────
async def can_inquiry(db: DB, uid: int, bot=None) -> tuple[bool, str | None]:
    if _is_admin_free(uid):
        await get(db, uid)
        return True, None
    """بررسی پیش از شروع استعلام دستی. خروجی: (مجاز؟، علت عدم مجاز)."""
    s = await get(db, uid)
    if s["status"] not in ACTIVE:
        return False, "inactive"
    if _is_restricted(s):
        return False, "restricted"
    if s["plan"] not in SUB_PLANS:
        # شروع رایگان / پلن‌های شخصی / فقط اعتبار: اول اعتبار، بعد هیچ
        if (s["inquiries_left"] or 0) <= 0:
            return False, "exhausted"
        return True, None
    # پلن حرفه‌ای
    if (s["quota_total"] or 0) > 0 and (s["quota_used"] or 0) >= s["quota_total"]:
        return False, "quota_done"
    if s["plan"] == "org":
        done_today = await db.manual_done_since(uid, 24, INQUIRY_KINDS)
        if done_today >= config.PLAN_ORG_DAILY_CAP:
            # قاعده ۴ + ۶: عبور از سقف روزانه ← گزارش به مدیر
            await report_violation(bot, db, uid, "عبور از سقف روزانه استعلام پلن سازمانی",
                                   f"{to_fa_digits(done_today)} استعلام در ۲۴ ساعت اخیر "
                                   f"(سقف: {to_fa_digits(config.PLAN_ORG_DAILY_CAP)})")
            return False, "daily_cap"
    # قاعده ۶: مصرف غیرعادی (نرخ استعلام دستی در یک ساعت)
    recent = await db.manual_done_since(uid, 1, INQUIRY_KINDS)
    if recent > config.ABUSE_MANUAL_PER_HOUR:
        hours = config.RESTRICT_HOURS
        await restrict(db, uid, hours, f"مصرف غیرعادی: {recent} استعلام در یک ساعت")
        await report_violation(bot, db, uid, "مصرف غیرعادی ربات",
                               f"{recent} استعلام دستی در یک ساعت؛ حساب برای {to_fa_digits(hours)} ساعت محدود شد")
        return False, "abuse"
    return True, None


async def consume(db: DB, uid: int) -> str | None:
    if _is_admin_free(uid):
        return None
    """بعد از استعلام موفق: یک واحد از سهمیه کم می‌شود (قاعده ۱). خروجی: متن گزارش باقی‌مانده."""
    s = await get(db, uid)
    if s["status"] not in ACTIVE:
        return None
    m = plan_meta(s["plan"])
    if (s["inquiries_left"] or 0) > 0:
        left = s["inquiries_left"] - 1
        await _set(db, uid, inquiries_left=left)
        await db.add_plan_event(uid, "inquiry_used", s["plan"], f"اعتبار باقی‌مانده: {left}")
        return f"📊 یک استعلام از اعتبار شما کم شد؛ باقی‌مانده: {to_fa_digits(left)}"
    if s["plan"] in SUB_PLANS:
        if (s["quota_total"] or 0) <= 0:  # سازمانی (نامحدود)
            done_today = await db.manual_done_since(uid, 24, INQUIRY_KINDS)
            return (f"📊 استعلام‌های دستی امروز: {to_fa_digits(done_today)} از "
                    f"{to_fa_digits(config.PLAN_ORG_DAILY_CAP)}")
        used = (s["quota_used"] or 0) + 1
        await _set(db, uid, quota_used=used)
        await db.add_plan_event(uid, "inquiry_used", s["plan"], f"مصرف ماه: {used}/{s['quota_total']}")
        left = s["quota_total"] - used
        return f"📊 استعلام این ماه: {to_fa_digits(used)} از {to_fa_digits(s['quota_total'])} " \
               f"(باقی‌مانده: {to_fa_digits(left)})"
    return None


async def after_inquiry(db: DB, uid: int, bot=None) -> str | None:
    if _is_admin_free(uid):
        return None
    """پس از هر استعلام دستی موفق: کسر سهمیه + بررسی مصرف غیرعادی (قاعده ۶)."""
    note = await consume(db, uid)
    recent = await db.manual_done_since(uid, 1, INQUIRY_KINDS)
    if recent > config.ABUSE_MANUAL_PER_HOUR:
        hours = config.RESTRICT_HOURS
        await restrict(db, uid, hours, f"مصرف غیرعادی: {recent} استعلام در یک ساعت")
        await report_violation(bot, db, uid, "مصرف غیرعادی ربات",
                               f"{recent} استعلام دستی در یک ساعت؛ حساب برای {to_fa_digits(hours)} ساعت محدود شد")
        note = (note + "\n" if note else "") + \
            f"⛔ به دلیل مصرف غیرعادی، حساب شما به‌مدت {to_fa_digits(hours)} ساعت محدود شد."
    return note


# ── محدودیت و گزارش تخلف (قاعده ۶) ──────────────────────────────────────────
async def restrict(db: DB, uid: int, hours: int, reason: str):
    until = (utcnow() + dt.timedelta(hours=max(1, hours))).isoformat()
    await _set(db, uid, restricted_until=until, restriction_reason=reason[:300])
    await db.add_plan_event(uid, "restricted", None, reason[:300])


async def unrestrict(db: DB, uid: int):
    await _set(db, uid, restricted_until=None, restriction_reason=None)
    await db.add_plan_event(uid, "unrestricted", None, "برداشته‌شدن محدودیت توسط مدیر")


async def report_violation(bot, db: DB, uid: int, what: str, detail: str = ""):
    """هر اقدام خارج از قوانین ← ثبت رویداد + پیام فوری به مدیر."""
    await db.add_plan_event(uid, "violation_reported", None, f"{what} | {detail}")
    if bot is None or not config.ADMIN_ID:
        return
    try:
        await bot.send_message(
            config.ADMIN_ID,
            "🚨 گزارش نقض قوانین ربات\n"
            f"👤 کاربر: {uid}\n"
            f"📌 مورد: {what}\n"
            + (f"📝 جزئیات: {detail}\n" if detail else ""))
    except Exception:
        log.warning("could not notify admin about violation (uid=%s)", uid)


# ── شروع رایگان (با تأیید شماره موبایل) ────────────────────────────────────
def normalize_phone(raw: str) -> str | None:
    import re

    from ..utils import clean_digits
    d = clean_digits(raw or "")
    if d.startswith("98") and len(d) == 12:
        d = "0" + d[2:]
    if len(d) == 10 and d.startswith("9"):
        d = "0" + d
    return d if re.fullmatch(r"09\d{9}", d) else None


async def phone_verified(db: DB, uid: int) -> bool:
    s = await db.one("SELECT phone, phone_verified_at FROM subscriptions WHERE bale_id=?", (uid,))
    return bool(s and s["phone"] and s["phone_verified_at"])


async def save_phone(db: DB, uid: int, phone: str):
    await _set(db, uid, phone=phone, phone_verified_at=now_iso())


async def phone_taken_by_other(db: DB, uid: int, phone: str) -> int | None:
    r = await db.one("SELECT bale_id FROM subscriptions WHERE phone=? AND bale_id!=?", (phone, uid))
    return r["bale_id"] if r else None


async def free_used(db: DB, uid: int) -> bool:
    s = await db.one("SELECT free_used FROM subscriptions WHERE bale_id=?", (uid,))
    return bool(s and s["free_used"])


async def activate_free(db: DB, uid: int, bot=None) -> bool:
    if await free_used(db, uid):
        return False
    await _set(db, uid, status="FREE_ACTIVE", plan="free", cycle=None,
               inquiries_left=config.FREE_INQUIRIES, free_used=1,
               quota_total=0, quota_used=0, locked_at=None)
    await db.add_plan_event(uid, "free_start", "free",
                            f"{config.FREE_INQUIRIES} استعلام رایگان برای هر دو بخش")
    return True


# ── فاکتور و پرداخت ─────────────────────────────────────────────────────────
async def create_invoice(db: DB, uid: int, kind: str, plan: str | None = None, cycle: str | None = None,
                         amount: int | None = None, payload: str | None = None,
                         is_admin: bool = False) -> dict:
    if amount is None:
        if kind == "turn":
            amount = config.PRICE_TURN
        elif kind == "upgrade":
            s = await get(db, uid)
            left = max(0, (parse_iso(s["paid_until"]) - utcnow()).days) if s["paid_until"] else 0
            amount = upgrade_amount(s["plan"], left, plan, cycle)
        else:
            amount = plan_price(plan, cycle)
    if is_admin and config.TEST_PRICE_TOMAN:
        amount = config.TEST_PRICE_TOMAN
    # فاکتورهای در انتظارِ قبلی همان نوع منقضی می‌شوند
    if kind != "turn":
        await db.execute("UPDATE invoices SET status='expired' WHERE bale_id=? AND status='pending' AND kind!='turn'",
                         (uid,))
    now = utcnow()
    code = new_code("TRN" if kind == "turn" else "INV")
    await db.execute(
        "INSERT INTO invoices(code,bale_id,kind,notices,case_alerts,amount_toman,status,payload,created_at,"
        "expires_at,plan,cycle) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (code, uid, kind, 0, 0, amount, "pending", payload, now.isoformat(),
         (now + dt.timedelta(hours=config.INVOICE_EXPIRE_HOURS)).isoformat(), plan, cycle))
    return await db.one("SELECT * FROM invoices WHERE code=?", (code,))


async def approve_invoice(db: DB, code: str, admin_id: int) -> dict | None:
    """idempotent: تأیید دوباره بی‌اثر است. خروجی: فاکتور (فقط اگر همین الان تأیید شد)."""
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] not in ("receipt_sent", "pending", "shortfall_wait"):
        return None
    cur = await db.execute("UPDATE invoices SET status='approved', reviewed_by=?, reviewed_at=? "
                           "WHERE code=? AND status IN ('receipt_sent','pending','shortfall_wait')",
                           (admin_id, now_iso(), code))
    if cur.rowcount != 1:
        return None
    if inv["kind"] == "turn":
        return inv
    uid = inv["bale_id"]
    s = await get(db, uid)
    now = utcnow()
    plan, cycle = inv["plan"], inv["cycle"]
    if inv["kind"] == "upgrade" and s["status"] == "PAID_ACTIVE" and s["paid_until"]:
        # قاعده ۹: ارتقا وسط دوره — دوره همان‌جا ادامه می‌یابد، سهمیه از نو
        base = max(parse_iso(s["paid_until"]), now)
        await _set(db, uid, status="PAID_ACTIVE", plan=plan, cycle=cycle,
                   quota_total=plan_meta(plan).get("quota", 0), quota_month=tehran_month(), quota_used=0)
        await db.add_plan_event(uid, "plan_upgraded", plan,
                                f"ارتقا از {plan_title(s['plan'])}؛ پایان دوره: {base.date()}")
    elif inv["kind"] == "renewal":
        plan = plan or s["plan"]
        cycle = cycle or s["cycle"] or "monthly"
        base = parse_iso(s["paid_until"]) if s["status"] == "PAID_ACTIVE" and s["paid_until"] else now
        base = max(base, now)
        await _set(db, uid, status="PAID_ACTIVE", plan=plan, cycle=cycle,
                   paid_until=(base + dt.timedelta(days=cycle_days(cycle))).isoformat(),
                   quota_total=plan_meta(plan).get("quota", 0), quota_month=tehran_month(), quota_used=0,
                   locked_at=None)
        await db.add_plan_event(uid, "renewed", plan, f"تمدید {CYCLE_FA.get(cycle, cycle)}")
    elif plan_meta(plan).get("kind") == "credit":
        # پلن شخصی: اعتبار استعلام اضافه می‌شود (خریدهای قبلی جمع می‌شوند)
        add = plan_meta(plan)["inquiries"]
        cur_left = (s["inquiries_left"] or 0) if s["status"] in ACTIVE else 0
        await _set(db, uid, status="PAID_ACTIVE", inquiries_left=cur_left + add,
                   plan=(s["plan"] if s["plan"] in SUB_PLANS else plan),
                   locked_at=None)
        await db.add_plan_event(uid, "plan_activated", plan, f"اعتبار {add} استعلامی؛ جمع: {cur_left + add}")
    else:
        # پلن حرفه‌ی جدید
        await _set(db, uid, status="PAID_ACTIVE", plan=plan, cycle=cycle,
                   paid_until=(now + dt.timedelta(days=cycle_days(cycle))).isoformat(),
                   quota_total=plan_meta(plan).get("quota", 0), quota_month=tehran_month(), quota_used=0,
                   locked_at=None)
        await db.add_plan_event(uid, "plan_activated", plan, f"دوره {CYCLE_FA.get(cycle, cycle)}")
    return inv


async def reject_invoice(db: DB, code: str, admin_id: int, reason: str) -> dict | None:
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] not in ("receipt_sent", "shortfall_wait"):
        return None
    await db.execute(
        "UPDATE invoices SET status='pending', receipt_file_id=NULL, receipt_file_unique_id=NULL, "
        "reviewed_by=?, reviewed_at=?, reject_reason=? WHERE code=?", (admin_id, now_iso(), reason, code))
    return await db.one("SELECT * FROM invoices WHERE code=?", (code,))


async def declare_shortfall(db: DB, code: str, admin_id: int, toman: int) -> dict | None:
    """مدیر: «مبلغ واریزی کمتر از فاکتور است» ← فقط کسری از کاربر خواسته می‌شود."""
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] != "receipt_sent" or not 0 < toman < (inv["amount_toman"] or 0):
        return None
    await db.execute("UPDATE invoices SET status='shortfall_wait', shortfall_toman=?, reviewed_by=?, "
                     "reviewed_at=? WHERE code=?", (toman, admin_id, now_iso(), code))
    return await db.one("SELECT * FROM invoices WHERE code=?", (code,))


async def usable_turn_invoice(db: DB, uid: int) -> dict | None:
    return await db.one("SELECT * FROM invoices WHERE bale_id=? AND kind='turn' AND status='approved' "
                        "ORDER BY id DESC LIMIT 1", (uid,))
