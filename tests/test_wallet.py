"""کیف پول: استرداد ٪۵۰ برای خطای سامانه، کسر از درخواست بعدی، idempotent بودن."""
import pytest

from legal_bot import config
from legal_bot.services import subscription as sub, wallet

pytestmark = pytest.mark.asyncio


async def _inv(db, uid=5, n=1, price=70_000):
    nums = ",".join(str(1000 + i) for i in range(n))
    inv = await sub.create_invoice(db, uid, "turn", payload=f"case:{nums}", amount=price * n)
    await db.execute("UPDATE invoices SET status='approved' WHERE code=?", (inv["code"],))
    return await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))


async def test_refund_half_to_wallet_once(db):
    inv = await _inv(db)
    fee, back, bal = await wallet.refund_failed(db, inv, 1)
    assert (fee, back, bal) == (35_000, 35_000, 35_000)
    assert await wallet.refund_failed(db, inv, 1) is None      # دوباره اعتبار نمی‌گیرد
    assert await wallet.balance(db, 5) == 35_000


async def test_refund_partial_multi(db):
    inv = await _inv(db, n=3)
    fee, back, bal = await wallet.refund_failed(db, inv, 2)    # دو نوبت از سه
    assert back == 70_000 and fee == 70_000


async def test_next_invoice_uses_wallet_and_invoices_remainder(db):
    inv = await _inv(db)
    await wallet.refund_failed(db, inv, 1)
    new = await sub.create_invoice(db, 5, "turn", payload="case:2000", amount=70_000)
    used = await wallet.use_for_invoice(db, new)
    new = await db.one("SELECT * FROM invoices WHERE code=?", (new["code"],))
    assert used == 35_000 and new["amount_toman"] == 35_000 and new["wallet_used"] == 35_000
    assert await wallet.balance(db, 5) == 0


async def test_wallet_covers_everything(db):
    await wallet._tx(db, 5, 200_000, "refund", "SEED")
    new = await sub.create_invoice(db, 5, "turn", payload="case:2000", amount=70_000)
    assert await wallet.use_for_invoice(db, new) == 70_000
    r = await db.one("SELECT amount_toman FROM invoices WHERE code=?", (new["code"],))
    assert r["amount_toman"] == 0 and await wallet.balance(db, 5) == 130_000


async def test_expired_invoice_returns_wallet_share(db):
    await wallet._tx(db, 5, 30_000, "refund", "SEED")
    new = await sub.create_invoice(db, 5, "turn", payload="case:2000", amount=70_000)
    await wallet.use_for_invoice(db, new)
    await db.execute("UPDATE invoices SET expires_at='2000-01-01T00:00:00+00:00' WHERE code=?", (new["code"],))
    assert await wallet.release_expired(db) == 1
    assert await wallet.balance(db, 5) == 30_000
    assert await wallet.release_expired(db) == 0               # دوباره برنمی‌گردد


async def test_never_negative(db):
    assert not await wallet._tx(db, 5, -1, "invoice_use", "X")
    assert await wallet.balance(db, 5) == 0


async def test_free_invoice_no_refund(db):
    inv = await _inv(db, price=0)
    assert await wallet.refund_failed(db, inv, 1) is None
