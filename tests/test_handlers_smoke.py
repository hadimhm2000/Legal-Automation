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
    assert T.PLAN_PROMPT in sess.texts()[-1]
    await press(bot, dp, "plan:1")
    await press(bot, dp, button(sess, "شروع تست"))
    assert T.TERMS_TEXT == sess.texts()[-1]
    await press(bot, dp, button(sess, "می‌پذیرم"))
    assert "تست رایگان" in sess.texts()[-1]

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
    await press(bot, dp, button(sess, T.BACK))
    await asyncio.sleep(0.1)
    assert T.CANCELLED in sess.texts()
    run = await db.one("SELECT * FROM check_runs ORDER BY id DESC LIMIT 1")
    assert run["status"] == "cancelled" and run["kind"] == "notices_case"

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
    assert inv["code"] in sess.texts()[-1]
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    await press(bot, dp, f"adm:ok:{inv['code']}")
    assert button(sess, "شروع ثبت نوبت") == f"turn:go:{inv['code']}"
    await press(bot, dp, f"adm:ok:{inv['code']}")       # تأیید دوباره بی‌اثر
    assert (await db.one("SELECT status FROM invoices WHERE code=?", (inv["code"],)))["status"] == "approved"


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
