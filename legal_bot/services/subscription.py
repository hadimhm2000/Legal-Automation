"""قواعد اشتراک: تست ۳ روزه‌ی یک‌باره، قفل، فاکتور، ارتقای نسبی، تمدید (بخش ۸ سند)."""
from __future__ import annotations

import datetime as dt

from .. import config
from ..db import DB, new_code, now_iso, parse_iso

ACTIVE = ("TRIAL_ACTIVE", "PAID_ACTIVE")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def plan_price(notices: bool, case_alerts: bool) -> int:
    if notices and case_alerts:
        return config.PRICE_BOTH
    return config.PRICE_NOTICES if notices else config.PRICE_CASE_ALERTS


def upgrade_amount(current_notices: bool, current_case: bool, days_left: int) -> int:
    """(PRICE_BOTH − قیمت فعلی) × روزهای باقی‌مانده ÷ 30، گرد به نزدیک‌ترین ۱۰۰۰ تومان."""
    diff = config.PRICE_BOTH - plan_price(current_notices, current_case)
    raw = diff * max(0, days_left) / 30
    return int(round(raw / 1000.0)) * 1000


async def get(db: DB, uid: int) -> dict:
    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    if not s:
        await db.execute("INSERT OR IGNORE INTO subscriptions(bale_id,status,updated_at) VALUES(?,?,?)",
                         (uid, "NEW", now_iso()))
        s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    return await refresh(db, s)


async def refresh(db: DB, s: dict) -> dict:
    """قفل کردن خودکار وقتی تست یا دوره‌ی پولی تمام شده."""
    now = utcnow()
    if s["status"] == "TRIAL_ACTIVE" and parse_iso(s["trial_ends_at"]) and parse_iso(s["trial_ends_at"]) <= now:
        await _set(db, s["bale_id"], status="LOCKED", locked_at=now_iso())
    elif s["status"] == "PAID_ACTIVE" and parse_iso(s["paid_until"]) and parse_iso(s["paid_until"]) <= now:
        await _set(db, s["bale_id"], status="LOCKED", locked_at=now_iso())
    else:
        return s
    return await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (s["bale_id"],))


async def _set(db, uid, **kw):
    kw["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in kw)
    await db.execute(f"UPDATE subscriptions SET {cols} WHERE bale_id=?", (*kw.values(), uid))


async def has_service(db, uid, service: str) -> bool:
    """service: notices | case_alerts. در جریان ورود و scheduler هم صدا زده می‌شود (نه فقط منو)."""
    s = await get(db, uid)
    if s["status"] not in ACTIVE:
        return False
    if s["status"] == "TRIAL_ACTIVE":
        return True  # در تست هر دو سرویس قابل استفاده است
    return bool(s[service])


async def trial_used(db, uid) -> bool:
    return bool(await db.one("SELECT 1 FROM trial_usage WHERE bale_id=?", (uid,)))


async def start_trial(db, uid, notices: bool, case_alerts: bool) -> bool:
    if await trial_used(db, uid):
        return False
    now = utcnow()
    try:
        await db.execute("INSERT INTO trial_usage(bale_id,started_at) VALUES(?,?)", (uid, now.isoformat()))
    except Exception:
        return False
    await _set(db, uid, status="TRIAL_ACTIVE", notices=int(notices), case_alerts=int(case_alerts),
               trial_started_at=now.isoformat(), trial_ends_at=(now + dt.timedelta(days=config.TRIAL_DAYS)).isoformat())
    return True


async def create_invoice(db, uid, kind, notices=False, case_alerts=False, amount=None, payload=None,
                         is_admin=False) -> dict:
    if amount is None:
        if kind == "turn":
            amount = config.PRICE_TURN
        elif kind == "upgrade":
            s = await get(db, uid)
            left = max(0, (parse_iso(s["paid_until"]) - utcnow()).days) if s["paid_until"] else 0
            amount = upgrade_amount(bool(s["notices"]), bool(s["case_alerts"]), left)
        else:
            amount = plan_price(notices, case_alerts)
    if is_admin and config.TEST_PRICE_TOMAN:
        amount = config.TEST_PRICE_TOMAN
    # فاکتورهای در انتظارِ قبلی همان نوع منقضی می‌شوند
    if kind != "turn":
        await db.execute("UPDATE invoices SET status='expired' WHERE bale_id=? AND status='pending' AND kind!='turn'",
                         (uid,))
    now = utcnow()
    code = new_code("TRN" if kind == "turn" else "INV")
    await db.execute(
        "INSERT INTO invoices(code,bale_id,kind,notices,case_alerts,amount_toman,status,payload,created_at,expires_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (code, uid, kind, int(notices), int(case_alerts), amount, "pending", payload, now.isoformat(),
         (now + dt.timedelta(hours=config.INVOICE_EXPIRE_HOURS)).isoformat()))
    return await db.one("SELECT * FROM invoices WHERE code=?", (code,))


async def approve_invoice(db, code, admin_id) -> dict | None:
    """idempotent: تأیید دوباره بی‌اثر است. خروجی: فاکتور (فقط اگر همین الان تأیید شد)."""
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] not in ("receipt_sent", "pending"):
        return None
    cur = await db.execute("UPDATE invoices SET status='approved', reviewed_by=?, reviewed_at=? "
                           "WHERE code=? AND status IN ('receipt_sent','pending')", (admin_id, now_iso(), code))
    if cur.rowcount != 1:
        return None
    if inv["kind"] == "turn":
        return inv
    s = await get(db, inv["bale_id"])
    now = utcnow()
    if inv["kind"] == "upgrade" and s["status"] == "PAID_ACTIVE":
        await _set(db, inv["bale_id"], notices=1, case_alerts=1)
    else:
        base = parse_iso(s["paid_until"]) if s["status"] == "PAID_ACTIVE" and s["paid_until"] else now
        base = max(base, now)
        notices = bool(inv["notices"]) or (inv["kind"] == "renewal" and bool(s["notices"]))
        case = bool(inv["case_alerts"]) or (inv["kind"] == "renewal" and bool(s["case_alerts"]))
        await _set(db, inv["bale_id"], status="PAID_ACTIVE", notices=int(notices), case_alerts=int(case),
                   paid_until=(base + dt.timedelta(days=config.SUB_DAYS)).isoformat())
    return inv


async def reject_invoice(db, code, admin_id, reason):
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] != "receipt_sent":
        return None
    await db.execute("UPDATE invoices SET status='pending', receipt_file_unique_id=NULL, reviewed_by=?, "
                     "reviewed_at=?, reject_reason=? WHERE code=?", (admin_id, now_iso(), reason, code))
    return inv


async def usable_turn_invoice(db, uid) -> dict | None:
    return await db.one("SELECT * FROM invoices WHERE bale_id=? AND kind='turn' AND status='approved' "
                        "ORDER BY id DESC LIMIT 1", (uid,))
