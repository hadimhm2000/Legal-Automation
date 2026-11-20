"""کیف پول کاربر (استرداد خطای سامانه).

قاعده (دستور کارفرما): اگر روند ثبت نوبت به‌خاطر خطای شناسایی‌شده‌ی سامانه متوقف شد،
TURN_FEE_PCT٪ هزینه کسر و مابقی به کیف پول برمی‌گردد. در درخواست جدید، موجودی کیف پول
از مبلغ کل کم می‌شود و فاکتور فقط برای مابقی صادر می‌شود.
همه‌ی عملیات idempotent است (UNIQUE(kind, ref)) تا دوبار اعتبار/کسر نشود.
"""
from __future__ import annotations

import logging

from .. import config
from ..db import DB, now_iso

log = logging.getLogger(__name__)


async def balance(db: DB, uid: int) -> int:
    r = await db.one("SELECT balance_toman b FROM wallets WHERE bale_id=?", (uid,))
    return int(r["b"]) if r else 0


async def _tx(db: DB, uid: int, delta: int, kind: str, ref: str, note: str = "") -> bool:
    """یک تراکنش اتمیک؛ False اگر قبلاً ثبت شده یا موجودی کافی نیست."""
    conn = db.conn
    try:
        await conn.execute("INSERT OR IGNORE INTO wallets(bale_id,balance_toman,updated_at) VALUES(?,0,?)",
                           (uid, now_iso()))
        cur = await conn.execute(
            "INSERT OR IGNORE INTO wallet_tx(bale_id,delta_toman,kind,ref,note,created_at) VALUES(?,?,?,?,?,?)",
            (uid, delta, kind, ref, note[:200], now_iso()))
        if cur.rowcount != 1:
            await conn.rollback()
            return False
        cur = await conn.execute(
            "UPDATE wallets SET balance_toman=balance_toman+?, updated_at=? "
            "WHERE bale_id=? AND balance_toman+? >= 0", (delta, now_iso(), uid, delta))
        if cur.rowcount != 1:
            await conn.rollback()
            return False
        await conn.commit()
        return True
    except Exception:
        await conn.rollback()
        log.exception("wallet tx failed")
        return False


def split_fee(paid_per_item: int, n_failed: int) -> tuple[int, int]:
    """(کارمزد کسرشده، مبلغ برگشتی) برای n_failed نوبتِ ناموفق."""
    total = int(paid_per_item) * int(n_failed)
    fee = total * config.TURN_FEE_PCT // 100
    return fee, total - fee


async def refund_failed(db: DB, inv: dict, n_failed: int) -> tuple[int, int, int] | None:
    """بعد از توقف به‌خاطر خطای سامانه: مابقیِ مبلغ n_failed نوبت به کیف پول.

    خروجی: (کارمزد، برگشتی، موجودی جدید) یا None (چیزی برنگشت/قبلاً انجام شده).
    مبلغِ «پرداخت‌شده» = مبلغ فاکتور + سهمِ کیف پول؛ پس نوبتی که با کیف پول پرداخت شده هم
    همان قاعده را دارد.
    """
    items = max(1, len((inv.get("payload") or ":").split(":", 1)[1].split(",")))
    paid_total = int(inv.get("amount_toman") or 0) + int(inv.get("wallet_used") or 0)
    if paid_total <= 0 or n_failed <= 0:
        return None
    fee, back = split_fee(paid_total // items, min(n_failed, items))
    if back <= 0:
        return None
    ref = f"{inv['code']}:{min(n_failed, items)}"
    if not await _tx(db, inv["bale_id"], back, "refund", inv["code"], f"{ref} fee={fee}"):
        return None
    return fee, back, await balance(db, inv["bale_id"])


async def use_for_invoice(db: DB, inv: dict) -> int:
    """موجودی کیف پول را روی فاکتور (pending) اعمال می‌کند: wallet_used را ثبت و از amount کم می‌کند."""
    uid, amount = inv["bale_id"], int(inv["amount_toman"] or 0)
    if amount <= 0 or inv["status"] != "pending":
        return 0
    bal = await balance(db, uid)
    use = min(bal, amount)
    if use <= 0:
        return 0
    if not await _tx(db, uid, -use, "invoice_use", inv["code"], f"use {use}"):
        return 0
    await db.execute("UPDATE invoices SET wallet_used=?, amount_toman=? WHERE code=?",
                     (use, amount - use, inv["code"]))
    return use


async def release_invoice(db: DB, inv: dict) -> bool:
    """فاکتورِ پرداخت‌نشده منقضی شد ← سهم کیف پول برگردد."""
    used = int(inv.get("wallet_used") or 0)
    if used <= 0:
        return False
    ok = await _tx(db, inv["bale_id"], used, "invoice_release", inv["code"], f"release {used}")
    if ok:
        await db.execute("UPDATE invoices SET wallet_used=0 WHERE code=?", (inv["code"],))
    return ok


async def release_expired(db: DB) -> int:
    """فاکتورهای منقضی‌شده‌ی دارای سهم کیف پول (قبل از تغییر وضعیت به expired صدا بزنید)."""
    rows = await db.all("SELECT * FROM invoices WHERE status IN ('pending','shortfall_wait') "
                        "AND expires_at<? AND wallet_used>0", (now_iso(),))
    n = 0
    for r in rows:
        n += bool(await release_invoice(db, r))
    return n


async def history(db: DB, uid: int, limit: int = 10) -> list[dict]:
    return await db.all("SELECT * FROM wallet_tx WHERE bale_id=? ORDER BY id DESC LIMIT ?", (uid, limit))


async def adjust(db: DB, uid: int, delta: int, note: str = "") -> bool:
    """تغییر دستیِ موجودی توسط مدیر (شارژ یا کسر). ref یکتا برای هر بار."""
    import time
    return await _tx(db, uid, int(delta), "admin", f"adm:{uid}:{time.time_ns()}", note)


async def totals(db: DB) -> dict:
    r = await db.one("SELECT COUNT(*) n, COALESCE(SUM(balance_toman),0) s FROM wallets WHERE balance_toman>0")
    return {"holders": int(r["n"]), "sum": int(r["s"])}
