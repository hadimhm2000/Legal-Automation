import datetime as dt

from legal_bot import config
from legal_bot.db import parse_iso
from legal_bot.services import subscription as sub


def test_upgrade_example_from_spec():
    # ۲۰ روز مانده از گزینه‌ی ۱ → (۸۰۰٬۰۰۰ − ۵۰۰٬۰۰۰) × ۲۰ ÷ ۳۰ = ۲۰۰٬۰۰۰
    assert sub.upgrade_amount(True, False, 20) == 200_000
    assert sub.upgrade_amount(True, False, 7) == 70_000
    assert sub.plan_price(True, True) == config.PRICE_BOTH


async def test_trial_only_once_and_lock(db):
    await db.upsert_user(5, 5)
    assert await sub.start_trial(db, 5, True, False)
    assert await sub.has_service(db, 5, "case_alerts")  # در تست هر دو سرویس
    assert not await sub.start_trial(db, 5, False, True)
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    await db.execute("UPDATE subscriptions SET trial_ends_at=? WHERE bale_id=5", (past,))
    assert (await sub.get(db, 5))["status"] == "LOCKED"
    assert not await sub.has_service(db, 5, "notices")
    await db.execute("DELETE FROM users WHERE bale_id=5")
    await db.upsert_user(5, 5)  # حذف و Start دوباره → تست دوباره ندارد
    assert await sub.trial_used(db, 5)


async def test_invoice_approve_idempotent_and_renewal(db):
    await db.upsert_user(9, 9)
    inv = await sub.create_invoice(db, 9, "new", True, False)
    assert inv["amount_toman"] == config.PRICE_NOTICES and inv["code"].startswith("INV-")
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    assert await sub.approve_invoice(db, inv["code"], 777)
    assert await sub.approve_invoice(db, inv["code"], 777) is None  # دوباره بی‌اثر
    s = await sub.get(db, 9)
    end1 = parse_iso(s["paid_until"])
    assert s["status"] == "PAID_ACTIVE" and s["notices"] and not s["case_alerts"]
    ren = await sub.create_invoice(db, 9, "renewal", True, False)
    await sub.approve_invoice(db, ren["code"], 777)
    end2 = parse_iso((await sub.get(db, 9))["paid_until"])
    assert (end2 - end1).days == config.SUB_DAYS  # از پایان قبلی تمدید شد
    up = await sub.create_invoice(db, 9, "upgrade")
    assert up["amount_toman"] > 0
    await sub.approve_invoice(db, up["code"], 777)
    s = await sub.get(db, 9)
    assert s["notices"] and s["case_alerts"] and parse_iso(s["paid_until"]) == end2


async def test_turn_invoice_price_and_reject(db):
    await db.upsert_user(3, 3)
    inv = await sub.create_invoice(db, 3, "turn", payload="case:140513920000890035")
    assert inv["amount_toman"] == 70_000
    await db.execute("UPDATE invoices SET status='receipt_sent', receipt_file_unique_id='u1' WHERE code=?",
                     (inv["code"],))
    assert await sub.reject_invoice(db, inv["code"], 777, "مبلغ کم")
    r = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
    assert r["status"] == "pending" and r["receipt_file_unique_id"] is None
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await sub.approve_invoice(db, inv["code"], 777)
    assert (await sub.usable_turn_invoice(db, 3))["code"] == inv["code"]
    assert (await sub.get(db, 3))["status"] == "NEW"  # نوبت اشتراک را فعال نمی‌کند
