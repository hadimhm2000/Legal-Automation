"""مسیر کاربر از طریق Dispatcher واقعی aiogram با session ساختگی (بدون شبکه)."""
import asyncio
import datetime as dt
import itertools

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Document, Message, Update, User

from legal_bot import config, texts as T
from legal_bot.handoff import make_token

ADMIN = 777


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._ids = itertools.count(100)

    async def close(self):
        pass

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        chat = Chat(id=ADMIN, type="private")
        if name in ("SendMessage", "SendDocument", "SendPhoto"):
            kw = {}
            if name == "SendDocument":
                kw["document"] = Document(file_id="F1", file_unique_id="U1")
            rm = getattr(method, "reply_markup", None)
            rm = rm if hasattr(rm, "inline_keyboard") else None
            return Message(message_id=next(self._ids), date=dt.datetime.now(), chat=chat,
                           text=getattr(method, "text", None), reply_markup=rm, **kw)
        return True

    def texts(self):
        return [getattr(m, "text", None) or getattr(m, "caption", None) for m in self.calls]

    def last_markup(self):
        for m in reversed(self.calls):
            if getattr(m, "reply_markup", None) is not None and hasattr(m.reply_markup, "inline_keyboard"):
                return m.reply_markup


@pytest.fixture
async def env(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    monkeypatch.setattr(config, "BETA_IDS", {ADMIN})
    monkeypatch.setattr(config, "HANDOFF_SECRET", "hs")
    import bot_main

    sess = FakeSession()
    bot = Bot("1:x", session=sess)
    dp = bot_main.build_dispatcher(db)
    dp["bot"] = bot
    yield bot, dp, sess
    from legal_bot.services.session import jobs
    await jobs.shutdown()
    for r in dp.sub_routers:  # روترها در سطح ماژول‌اند؛ برای تست بعدی جدا می‌شوند
        r._parent_router = None


user = User(id=ADMIN, is_bot=False, first_name="Admin")
_uid = itertools.count(1)


async def send(bot, dp, text):
    m = Message(message_id=next(_uid), date=dt.datetime.now(), chat=Chat(id=ADMIN, type="private"),
                from_user=user, text=text)
    await dp.feed_update(bot, Update(update_id=next(_uid), message=m))
    await asyncio.sleep(0.05)


async def press(bot, dp, data):
    msg = Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=ADMIN, type="private"), from_user=user, text="x")
    cb = CallbackQuery(id=str(next(_uid)), from_user=user, chat_instance="c", data=data, message=msg)
    await dp.feed_update(bot, Update(update_id=next(_uid), callback_query=cb))
    await asyncio.sleep(0.05)


def button(sess, label_part):
    for row in sess.last_markup().inline_keyboard:
        for b in row:
            if label_part in b.text:
                return b.callback_data
    raise AssertionError(f"no button {label_part}: {sess.last_markup()}")


async def test_user_journey(env, db):
    bot, dp, sess = env
    await send(bot, dp, "/start")                       # بدون توکن → رد
    assert T.RELOGIN_FROM_MAIN in sess.texts()[-1]
    await send(bot, dp, f"/start {make_token(ADMIN, 'hs')}")
    assert any(T.GUIDE_CAPTION == t for t in sess.texts())
    assert await db.get_setting("guide_file_id") == "F1"
    await press(bot, dp, "guide:ack")
    assert "شروع رایگان" in sess.texts()[-1]           # نمای پلن‌های جدید
    await press(bot, dp, "plan:free")
    assert T.PHONE_ASK == sess.texts()[-1]              # شروع رایگان ← تأیید شماره موبایل
    await send(bot, dp, "09121234567")                  # شماره به‌صورت متن
    assert T.RULES_TEXT == sess.texts()[-1]             # قوانین بعد از انتخاب پلن (دستور کارفرما)
    await press(bot, dp, button(sess, "تایید قوانین"))  # تایید ← فعال‌سازی
    assert "شروع رایگان فعال شد" in sess.texts()[-1]
    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (ADMIN,))
    assert s["status"] == "FREE_ACTIVE" and s["inquiries_left"] == 2 and s["phone"] == "09121234567"

    # ابلاغیه ← جستجو با شماره پرونده: اعتبارسنجی پیش از لمس سایت
    await send(bot, dp, T.M_NOTICES)
    await send(bot, dp, T.N_BY_CASE)
    assert T.ASK_CASE_NUMBER in sess.texts()[-1]
    await send(bot, dp, "14051392000089003")
    assert "۱۸ رقمی" in sess.texts()[-1]
    await send(bot, dp, T.M_CASES)                       # منو وسط کار → «در حال انجام»
    assert T.JOB_BUSY == sess.texts()[-1]
    await send(bot, dp, "140513920000890035")
    assert T.CONSENT_TEXT == sess.texts()[-1]            # تا «تأیید» نزند مرورگری باز نمی‌شود
    await send(bot, dp, T.BACK)                          # دکمه‌ی پایین ربات ← لغو فرایند
    await asyncio.sleep(0.1)
    assert T.CANCELLED in sess.texts()
    assert T.AUTO_MAIN in sess.texts()                   # بازگشت خودکار به منوی اصلی
    run = await db.one("SELECT * FROM check_runs ORDER BY id DESC LIMIT 1")
    assert run["status"] == "cancelled" and run["kind"] == "notices_case"

    # ابلاغیه ← جستجو با شماره ابلاغیه (گزینه‌ی جدید — دستور کارفرما)
    await send(bot, dp, T.M_NOTICES)

    def reply_kb_has(text_part):
        for m in sess.calls:
            rm = getattr(m, "reply_markup", None)
            if rm is not None and hasattr(rm, "keyboard"):
                for row in rm.keyboard:
                    for b in row:
                        if b and text_part in (b.text or ""):
                            return True
        return False

    assert reply_kb_has(T.N_BY_NOTICE)                  # در منوی ابلاغیه‌ها دیده می‌شود
    await send(bot, dp, T.N_BY_NOTICE)
    assert T.ASK_NOTICE_NUMBER in sess.texts()[-1]
    await send(bot, dp, "12345")                         # کوتاه → خطای اعتبارسنجی
    assert "۱۲ تا ۲۰ رقم" in sess.texts()[-1]
    await send(bot, dp, "9910103593004809")              # معتبر ← رضایت داده‌ها
    assert T.CONSENT_TEXT == sess.texts()[-1]
    await send(bot, dp, T.BACK)
    await asyncio.sleep(0.1)
    assert T.CANCELLED in sess.texts()
    run = await db.one("SELECT * FROM check_runs ORDER BY id DESC LIMIT 1")
    assert run["status"] == "cancelled" and run["kind"] == "notices_notice"

    # رمز ارسالی خارج از جریان ← حذف + هشدار
    await send(bot, dp, "4420160616")
    assert any(type(c).__name__ == "DeleteMessage" for c in sess.calls)
    assert T.SECRET_OUTSIDE_FLOW == sess.texts()[-1]


async def test_turn_invoice_and_admin_approval(env, db):
    bot, dp, sess = env
    await send(bot, dp, f"/start {make_token(ADMIN, 'hs')}")
    await send(bot, dp, T.M_TURN)
    await press(bot, dp, button(sess, "شماره بایگانی"))
    await send(bot, dp, "0500732")
    inv = await db.one("SELECT * FROM invoices WHERE kind='turn'")
    assert inv["amount_toman"] == 70_000 and inv["payload"] == "archive:0500732"
    for _ in range(100):  # ساخت تصویر کارت چند ثانیه طول می‌کشد
        if any(inv["code"] in (t or "") for t in sess.texts()):
            break
        await asyncio.sleep(0.1)
    assert any(inv["code"] in (t or "") for t in sess.texts())   # فاکتور + منوی اصلی خودکار بعد از پایان Job
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await press(bot, dp, f"adm:ok:{inv['code']}")
    assert button(sess, "شروع ثبت نوبت") == f"turn:go:{inv['code']}"
    await press(bot, dp, f"adm:ok:{inv['code']}")       # تأیید دوباره بی‌اثر
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv["code"],)))["status"] == "approved"


async def send_photo(bot, dp, file_id, fuid):
    from aiogram.types import PhotoSize

    m = Message(message_id=next(_uid), date=dt.datetime.now(), chat=Chat(id=ADMIN, type="private"),
                from_user=user,
                photo=[PhotoSize(file_id=file_id, file_unique_id=fuid, width=800, height=600)])
    await dp.feed_update(bot, Update(update_id=next(_uid), message=m))
    await asyncio.sleep(0.05)


async def test_card_to_card_payment_flow(env, db):
    """جریان کامل کارت‌به‌کارت (مثل ربات اصلی): قوانین ← فاکتور + دکمه‌های کپی ←
    رسید ← کسری ← رسید باقی‌مانده ← تایید مدیر ← فعال شدن پلن."""
    bot, dp, sess = env
    await send(bot, dp, f"/start {make_token(ADMIN, 'hs')}")
    await press(bot, dp, "guide:ack")
    await press(bot, dp, "plan:base")                     # پلن شخصی پایه
    assert T.RULES_TEXT == sess.texts()[-1]               # قوانین بعد از انتخاب پلن
    await press(bot, dp, button(sess, "تایید قوانین"))    # تایید ← فاکتور
    inv = await db.one("SELECT * FROM invoices WHERE kind='new'")
    assert inv["plan"] == "base" and inv["amount_toman"] == config.PLAN_BASE_PRICE
    # دکمه‌های کارت‌به‌کارت روی فاکتور هستند
    assert button(sess, "کپی شماره کارت") == f"cpay:cc:{inv['code']}"
    assert button(sess, "کپی مبلغ") == f"cpay:ca:{inv['code']}"
    assert button(sess, "ارسال تصویر رسید") == f"cpay:up:{inv['code']}"
    # عکس بدون زدن دکمه‌ی «ارسال تصویر رسید» ← راهنمایی (نه رسید)
    await send_photo(bot, dp, "P1", "U-P1")
    assert "ابتدا" in sess.texts()[-1]
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv["code"],)))["status"] == "pending"
    # زدن دکمه ← مجوز ۱۵ دقیقه‌ای ← عکس رسید ← رفتن به مدیر
    await press(bot, dp, f"cpay:up:{inv['code']}")
    await send_photo(bot, dp, "P1", "U-P1")
    row = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "receipt_sent" and row["receipt_file_unique_id"] == "U-P1"
    assert any("رسید کارت‌به‌کارت" in (t or "") for t in sess.texts())
    assert button(sess, "کسری") == f"adm:sf:{inv['code']}"
    # عکس تکراری: دکمه‌ی ارسال رسید در حال بررسی مجوز نمی‌دهد
    await press(bot, dp, f"cpay:up:{inv['code']}")
    ans = [c for c in sess.calls if type(c).__name__ == "AnswerCallbackQuery"][-1]
    assert "در حال بررسی" in ans.text
    await send_photo(bot, dp, "P2", "U-P1")
    assert "ابتدا" in sess.texts()[-1]
    # مدیر کسری اعلام می‌کند ← کاربر فقط باقی‌مانده را می‌پردازد
    await press(bot, dp, f"adm:sf:{inv['code']}")
    await send(bot, dp, "50000")
    row = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "shortfall_wait" and row["shortfall_toman"] == 50_000
    assert any("کمتر از مبلغ فاکتور" in (t or "") for t in sess.texts())
    # رسید باقی‌مانده ← تایید نهایی مدیر ← پلن فعال
    await press(bot, dp, f"cpay:up:{inv['code']}")
    await send_photo(bot, dp, "P3", "U-P3")
    row = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "receipt_sent" and row["shortfall_receipt_file_unique_id"] == "U-P3"
    await press(bot, dp, f"adm:ok:{inv['code']}")
    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (ADMIN,))
    assert s["status"] == "PAID_ACTIVE" and s["inquiries_left"] == config.PLAN_BASE_INQUIRIES
    assert any("پلن پایه" in (t or "") for t in sess.texts())


async def test_card_payment_reject_with_reason(env, db):
    bot, dp, sess = env
    await send(bot, dp, f"/start {make_token(ADMIN, 'hs')}")
    await press(bot, dp, "guide:ack")
    await press(bot, dp, "plan:select")
    await press(bot, dp, button(sess, "تایید قوانین"))
    inv = await db.one("SELECT * FROM invoices WHERE kind='new'")
    await press(bot, dp, f"cpay:up:{inv['code']}")
    await send_photo(bot, dp, "P9", "U-P9")
    # مدیر ← منوی دلایل رد ← دلیل آماده
    await press(bot, dp, f"adm:no:{inv['code']}")
    assert button(sess, "مطابقت ندارد") == f"adm:rr:{inv['code']}:amt"
    await press(bot, dp, f"adm:rr:{inv['code']}:amt")
    row = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "pending" and row["receipt_file_unique_id"] is None
    assert any("تایید نشد" in (t or "") for t in sess.texts())
    # دکمه‌ی «ارسال تصویر رسید» دوباره در دسترس است
    assert button(sess, "ارسال تصویر رسید") == f"cpay:up:{inv['code']}"


async def test_admin_commands_and_permissions(env, db, monkeypatch):
    bot, dp, sess = env
    # مدیر حتی پیش از /start دستورات را دارد
    for cmd in ("/legal_help", "/legal_runs", "/legal_errors", "/legal_user 777", "/legal_tick"):
        n = len(sess.calls)
        await send(bot, dp, cmd)
        assert len(sess.calls) > n, cmd
    assert "دستورات مدیر" in sess.texts()[-5]
    await send(bot, dp, "/legal_allow 555")
    assert await db.is_beta(555)
    await send(bot, dp, "/legal_deny 555")
    assert not await db.is_beta(555)

    # کاربر بتای غیرمدیر: دستورات مدیر و تأیید رسید کار نمی‌کند
    monkeypatch.setattr(config, "BETA_IDS", {ADMIN, 555})
    global user
    saved = user
    user = User(id=555, is_bot=False, first_name="U")
    try:
        await db.upsert_user(555, 555)
        inv = await db.execute("INSERT INTO invoices(code,bale_id,kind,amount_toman,status,created_at,expires_at) "
                               "VALUES('INV-T1',555,'new',1,'receipt_sent','x','9999')")
        await send(bot, dp, "/legal_allow 999")
        assert not await db.is_beta(999)
        await press(bot, dp, "adm:ok:INV-T1")
        assert (await db.one("SELECT status FROM invoices WHERE code='INV-T1'"))["status"] == "receipt_sent"
        ans = [c for c in sess.calls if type(c).__name__ == "AnswerCallbackQuery"][-1]
        assert ans.text == "فقط مدیر"
    finally:
        user = saved
