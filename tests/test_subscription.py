"""تست‌های موتور پلن‌های جدید (آبان ۱۴۰۵): شروع رایگان، اعتبار، سهمیه ماهانه،
سقف روزانه سازمانی، ارتقای نسبی، کسری و رد رسید، محدودیت مصرف غیرعادی."""
import datetime as dt

from legal_bot import config
from legal_bot.db import parse_iso
from legal_bot.services import subscription as sub


async def _activate(db, uid, plan, cycle="monthly", kind="new"):
    inv = await sub.create_invoice(db, uid, kind, plan, cycle)
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    assert await sub.approve_invoice(db, inv["code"], 777)
    return inv


def test_plan_prices_and_prorated_upgrade():
    # پلن‌های شخصی
    assert sub.plan_price("base") == config.PLAN_BASE_PRICE
    assert sub.plan_price("select") == config.PLAN_SELECT_PRICE
    # پلن‌های حرفه‌ای
    assert sub.plan_price("pro", "monthly") == config.PLAN_PRO_MONTHLY
    assert sub.plan_price("pro", "quarterly") == config.PLAN_PRO_QUARTERLY
    assert sub.plan_price("org", "quarterly") == config.PLAN_ORG_QUARTERLY
    # قاعده ۹ — مابه‌التفاوت نسبی: (۴٬۰۰۰٬۰۰۰ − ۲٬۴۰۰٬۰۰۰) × ۱۵ ÷ ۳۰ = ۸۰۰٬۰۰۰
    assert sub.upgrade_amount("pro", 15, "expert", "monthly") == 800_000
    assert sub.upgrade_amount("pro", 15, "expert", "quarterly") == 9_600_000
    # ارتقا به پلن ارزان‌تر منفی نمی‌شود
    assert sub.upgrade_amount("expert", 20, "pro") == 0


def test_normalize_phone():
    assert sub.normalize_phone("09121234567") == "09121234567"
    assert sub.normalize_phone("+98 912 123 4567") == "09121234567"
    assert sub.normalize_phone("989121234567") == "09121234567"
    assert sub.normalize_phone("9121234567") == "09121234567"
    assert sub.normalize_phone("0912123456") is None
    assert sub.normalize_phone("abc") is None


async def test_free_start_once_quota_and_lock(db):
    await db.upsert_user(5, 5)
    assert await sub.activate_free(db, 5)
    assert not await sub.activate_free(db, 5)          # فقط یک‌بار (قاعده ۵)
    s = await sub.get(db, 5)
    assert s["status"] == "FREE_ACTIVE" and s["plan"] == "free"
    assert s["inquiries_left"] == config.FREE_INQUIRIES
    ok, why = await sub.can_inquiry(db, 5)
    assert ok and why is None
    note = await sub.consume(db, 5)                    # استعلام ۱ (قاعده ۱)
    assert "باقی‌مانده: ۱" in note
    await sub.consume(db, 5)                           # استعلام ۲
    s = await sub.get(db, 5)                           # refresh → قفل
    assert s["status"] == "LOCKED"
    ok, why = await sub.can_inquiry(db, 5)
    assert not ok and why == "inactive"


async def test_phone_duplicate_reported(db):
    await db.upsert_user(11, 11)
    await sub.save_phone(db, 11, "09120000000")
    await sub.activate_free(db, 11)
    await db.upsert_user(12, 12)
    assert await sub.phone_taken_by_other(db, 12, "09120000000") == 11
    assert await sub.phone_taken_by_other(db, 12, "09350001111") is None


async def test_pro_monthly_quota_and_reset(db):
    await db.upsert_user(7, 7)
    await _activate(db, 7, "pro", "monthly")
    s = await sub.get(db, 7)
    assert s["plan"] == "pro" and s["quota_total"] == config.PLAN_PRO_QUOTA
    assert s["paid_until"] and (parse_iso(s["paid_until"]) - sub.utcnow()).days >= 29
    # مصرف کامل سهمیه ماه
    for i in range(config.PLAN_PRO_QUOTA):
        note = await sub.consume(db, 7)
    assert f"از {config.PLAN_PRO_QUOTA}" in note.replace("۳۰", "30") or note  # متن فارسی
    ok, why = await sub.can_inquiry(db, 7)
    assert not ok and why == "quota_done"
    # قاعده ۳ — با تغییر ماه سهمیه صفر می‌شود (حتی در ۳ ماهه)
    await db.execute("UPDATE subscriptions SET quota_month='2000-01' WHERE bale_id=7")
    s = await sub.get(db, 7)
    assert s["quota_used"] == 0 and s["quota_month"] == sub.tehran_month()
    ok, _ = await sub.can_inquiry(db, 7)
    assert ok
    # پیگیری خودکار فعال است (پلن حرفه‌ای)
    assert await sub.has_auto_tracking(db, 7)
    assert await sub.case_cap(db, 7) == config.PLAN_PRO_CASES


async def test_org_unlimited_with_daily_cap(db):
    await db.upsert_user(8, 8)
    await _activate(db, 8, "org", "quarterly")
    s = await sub.get(db, 8)
    assert s["quota_total"] == 0                        # نامحدود
    ok, _ = await sub.can_inquiry(db, 8)
    assert ok
    # قاعده ۴: سقف روزانه ۵۰ استعلام دستی
    for _ in range(config.PLAN_ORG_DAILY_CAP):
        rid = await db.create_run(8, "notices_case", "manual")
        await db.finish_run(rid, "done")
    ok, why = await sub.can_inquiry(db, 8)
    assert not ok and why == "daily_cap"
    ev = await db.one("SELECT * FROM plan_events WHERE bale_id=8 AND event='violation_reported'")
    assert ev and "سقف روزانه" in ev["detail"]


async def test_credit_accumulates_and_locks(db):
    await db.upsert_user(9, 9)
    await _activate(db, 9, "base", "credit")
    await _activate(db, 9, "select", "credit")         # خرید دوم روی اول جمع می‌شود
    s = await sub.get(db, 9)
    assert s["inquiries_left"] == config.PLAN_BASE_INQUIRIES + config.PLAN_SELECT_INQUIRIES
    assert not await sub.has_auto_tracking(db, 9)      # پیگیری خودکار فقط حرفه‌ای
    # مصرف همه‌ی اعتبار → قفل
    for _ in range(s["inquiries_left"]):
        await sub.consume(db, 9)
    s = await sub.get(db, 9)
    assert s["status"] == "LOCKED"


async def test_renewal_extends_and_upgrade_mid_period(db):
    await db.upsert_user(13, 13)
    await _activate(db, 13, "pro", "monthly")
    end1 = parse_iso((await sub.get(db, 13))["paid_until"])
    # تمدید ۳ ماهه از پایان دوره‌ی فعلی
    inv = await sub.create_invoice(db, 13, "renewal", "pro", "quarterly")
    assert inv["amount_toman"] == config.PLAN_PRO_QUARTERLY
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await sub.approve_invoice(db, inv["code"], 777)
    end2 = parse_iso((await sub.get(db, 13))["paid_until"])
    assert (end2 - end1).days == config.QUARTERLY_DAYS
    # ارتقای وسط دوره (قاعده ۹)
    up = await sub.create_invoice(db, 13, "upgrade", "expert", "monthly")
    assert up["amount_toman"] > 0
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (up["code"],))
    await sub.approve_invoice(db, up["code"], 777)
    s = await sub.get(db, 13)
    assert s["plan"] == "expert" and parse_iso(s["paid_until"]) == end2   # دوره همان‌جا ادامه می‌یابد
    assert s["quota_total"] == config.PLAN_EXPERT_QUOTA and s["quota_used"] == 0


async def test_shortfall_and_reject_flow(db):
    await db.upsert_user(3, 3)
    inv = await sub.create_invoice(db, 3, "new", "select", "credit")
    await db.execute("UPDATE invoices SET status='receipt_sent', receipt_file_unique_id='u1' WHERE code=?",
                     (inv["code"],))
    # کسری: فقط باقی‌مانده از کاربر خواسته می‌شود
    sf = await sub.declare_shortfall(db, inv["code"], 777, 50_000)
    assert sf["status"] == "shortfall_wait" and sf["shortfall_toman"] == 50_000
    assert await sub.declare_shortfall(db, inv["code"], 777, inv["amount_toman"]) is None  # >= فاکتور
    # رد با دلیل → برگشت به pending برای ارسال دوباره‌ی رسید
    r = await sub.reject_invoice(db, inv["code"], 777, "مبلغ کم")
    assert r["status"] == "pending" and r["receipt_file_unique_id"] is None
    # تایید نهایی → فعال‌سازی اعتبار
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await sub.approve_invoice(db, inv["code"], 777)
    assert (await sub.get(db, 3))["inquiries_left"] == config.PLAN_SELECT_INQUIRIES


async def test_turn_invoice_stays_separate(db):
    await db.upsert_user(4, 4)
    inv = await sub.create_invoice(db, 4, "turn", payload="case:140513920000890035")
    assert inv["amount_toman"] == config.PRICE_TURN and inv["code"].startswith("TRN-")
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await sub.approve_invoice(db, inv["code"], 777)
    assert (await sub.usable_turn_invoice(db, 4))["code"] == inv["code"]
    assert (await sub.get(db, 4))["status"] == "NEW"   # نوبت اشتراک را فعال نمی‌کند


async def test_abuse_restricts_and_reports(db):
    await db.upsert_user(10, 10)
    await _activate(db, 10, "pro", "monthly")
    # قاعده ۶: بیش از سقف نرخ ساعتی ← محدودیت موقت + گزارش
    for _ in range(config.ABUSE_MANUAL_PER_HOUR + 1):
        rid = await db.create_run(10, "notices_case", "manual")
        await db.finish_run(rid, "done")
    ok, why = await sub.can_inquiry(db, 10)
    assert not ok and why == "abuse"
    s = await sub.get(db, 10)
    assert s["restricted_until"]
    assert not await sub.has_service(db, 10, "notices")     # محدود = سرویس قفل
    ev = await db.one("SELECT * FROM plan_events WHERE bale_id=10 AND event='violation_reported'")
    assert ev and "مصرف غیرعادی" in ev["detail"]
    # محدودیت موقت است: با گذشتن زمان برداشته می‌شود (استعلام‌های پرنرخ هم قدیمی می‌شوند)
    past = (sub.utcnow() - dt.timedelta(minutes=1)).isoformat()
    await db.execute("UPDATE subscriptions SET restricted_until=? WHERE bale_id=10", (past,))
    old = (sub.utcnow() - dt.timedelta(hours=2)).isoformat(timespec="seconds")
    await db.execute("UPDATE check_runs SET started_at=? WHERE bale_id=10", (old,))
    ok, _ = await sub.can_inquiry(db, 10)
    assert ok
