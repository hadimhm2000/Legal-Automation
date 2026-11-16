"""رسید کارت‌به‌کارت — تشخیص «رسید تکراری» فقط با تطبیق کاملِ فایل (دستور کارفرما):

بله گاهی برای عکس‌های «مختلف» file_unique_id یکسان می‌دهد؛ عکسِ جدید نباید با پیام
«این رسید قبلاً ارسال شده است» رد شود. تکراریِ واقعی = همان file_id و file_unique_idِ
فاکتورِ دیگری که رسیدش در حال بررسی/تأییدشده است.
"""
import types

import pytest

from legal_bot.handlers import payment
from legal_bot.services import subscription as sub


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, file_id, caption=None, reply_markup=None, **kw):
        self.sent.append(("photo", file_id))

    async def send_document(self, chat_id, file_id, caption=None, reply_markup=None, **kw):
        self.sent.append(("doc", file_id))


def make_msg(uid=1, fid="F1", fuid="U1", doc=False):
    m = types.SimpleNamespace(
        from_user=types.SimpleNamespace(id=uid, full_name="کاربر تست"),
        bot=FakeBot(),
        photo=None,
        document=None,
        answers=[],
    )
    if doc:
        m.document = types.SimpleNamespace(file_id=fid, file_unique_id=fuid)
    else:
        m.photo = [types.SimpleNamespace(file_id=fid, file_unique_id=fuid)]

    async def answer(text, **kw):
        m.answers.append(text)

    m.answer = answer
    return m


async def _inv(db, uid, kind="new"):
    return await sub.create_invoice(db, uid, kind, plan="base" if kind != "turn" else None)


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    from legal_bot import config
    monkeypatch.setattr(config, "ADMIN_ID", 777)


async def test_new_photo_with_colliding_unique_id_is_accepted(db):
    """عکس جدید (file_id متفاوت) حتی با file_unique_id تکراری پذیرفته می‌شود."""
    await db.upsert_user(1, 1)
    inv1 = await _inv(db, 1)
    m1 = make_msg(1, "F1", "U1")
    await payment._process_receipt(m1, db, inv1)
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv1["code"],)))["status"] \
        == "receipt_sent"

    # فاکتور دوم + عکسِ «مختلف» که بله برایش همان file_unique_id را داده
    inv2 = await _inv(db, 1, kind="turn")
    m2 = make_msg(1, "F2", "U1")            # ← قبلاً اینجا به‌نادرست «تکراری» اعلام می‌شد
    await payment._process_receipt(m2, db, inv2)
    assert not any("تکراری" in a for a in m2.answers)
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv2["code"],)))["status"] \
        == "receipt_sent"
    assert ("photo", "F2") in m2.bot.sent    # برای مدیر هم رفت


async def test_real_duplicate_photo_for_other_invoice_is_rejected(db):
    """همان فایل (file_id + file_unique_id یکسان) برای فاکتور دوم → رد می‌شود."""
    await db.upsert_user(1, 1)
    inv1 = await _inv(db, 1)
    await payment._process_receipt(make_msg(1, "F1", "U1"), db, inv1)

    inv2 = await _inv(db, 1, kind="turn")
    m2 = make_msg(1, "F1", "U1")
    await payment._process_receipt(m2, db, inv2)
    assert any("قبلاً" in a and inv1["code"] in a for a in m2.answers)
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv2["code"],)))["status"] \
        == "pending"


async def test_same_invoice_resubmission_after_reject_is_accepted(db):
    """بعد از رد رسید توسط مدیر، ارسال دوباره‌ی همان/همان‌ند عکس مجاز است."""
    await db.upsert_user(1, 1)
    inv1 = await _inv(db, 1)
    await payment._process_receipt(make_msg(1, "F1", "U1"), db, inv1)
    await sub.reject_invoice(db, inv1["code"], 777, "تصویر ناخوانا")

    m2 = make_msg(1, "F1", "U1")
    await payment._process_receipt(m2, db, inv1)
    assert not any("تکراری" in a or "قبلاً" in a for a in m2.answers)
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv1["code"],)))["status"] \
        == "receipt_sent"


async def test_no_unique_index_on_receipt_file_unique_id(db):
    """ایندکس یکتا حذف شده: دو فاکتور با file_unique_id یکسان بدون خطا ثبت می‌شوند."""
    await db.upsert_user(1, 1)
    inv1, inv2 = await _inv(db, 1), await _inv(db, 1, kind="turn")
    await db.execute("UPDATE invoices SET receipt_file_unique_id='SAME' WHERE code=?", (inv1["code"],))
    await db.execute("UPDATE invoices SET receipt_file_unique_id='SAME' WHERE code=?", (inv2["code"],))
    rows = await db.all("SELECT code FROM invoices WHERE receipt_file_unique_id='SAME'")
    assert {r["code"] for r in rows} == {inv1["code"], inv2["code"]}
    idx = await db.all("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ux_receipt%'")
    assert not idx


async def test_otp_resend_marked_in_db(db):
    """زمان ارسال دستیِ «ارسال رمز موقت» در دیتابیس ثبت می‌ماند (گزارش مدیر).

    (دستور کارفرما — آبان ۱۴۰۵: نمایش دکمه‌ی ارسال فقط به پیامِ «رمز موقت جدید
    ... ارسال شد» خودِ سامانه بستگی دارد؛ این ثبت فقط برای گزارش است.)"""
    import time

    from legal_bot.services import sana_login as sl

    sl._OTP_RESEND_RAM.clear()
    ctx = types.SimpleNamespace(db=db)
    assert not (await db.get_setting("otp_resend:7"))
    before = time.time()
    await sl.otp_mark_resend(ctx, 7)
    saved = float(await db.get_setting("otp_resend:7"))
    assert before <= saved <= time.time()
    sl._OTP_RESEND_RAM.clear()                 # RAM پاک شد → مهر زمانی در دیتابیس مانده
    assert float(await db.get_setting("otp_resend:7")) == saved
    sl._OTP_RESEND_RAM.clear()
