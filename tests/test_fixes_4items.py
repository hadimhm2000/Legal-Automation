"""تست‌های اصلاحیه‌ی چهارگانه (دستور کارفرما):

۱) بخش پشتیبانی: پیش‌نویس + «تایید و ارسال» دوطرفه (کاربر ↔ مدیر).
۲) فاکتور پرداخت‌شده‌ی نوبت (status=used) در پنل ادمین دیده شود و درآمد شمرده شود.
۳) گزارش خطای دقیق به مدیر + اسکرین‌شات لحظه‌ی خطا.
۴) جریان پرداخت الگوی ربات اصلی: فاکتور ← درگاه بله ← تایید خودکار ← فعال‌سازی؛
   پس از ۱۰ دقیقه بدون پرداخت ← تصویر کارت‌به‌کارت خودکار.
"""
import asyncio
import datetime as dt
import itertools
import json

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Document, Message, PhotoSize, SuccessfulPayment, Update, User

from legal_bot import config, texts as T
from legal_bot.db import DB
from legal_bot.handlers import payment as pay
from legal_bot.handlers import support as sup
from legal_bot.services import error_reporter, subscription as sub
from legal_bot.utils import now_tehran

ADMIN = 777


# ── ربات/نشست ساختگی ────────────────────────────────────────────────────────
class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._ids = itertools.count(1000)

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

    def method_names(self):
        return [type(m).__name__ for m in self.calls]


@pytest.fixture
async def env(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    monkeypatch.setattr(config, "BETA_IDS", {ADMIN})
    monkeypatch.setattr(config, "BETA_OPEN_TO_ALL", False)
    monkeypatch.setattr(config, "ADMIN_FREE", False)
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "")
    import bot_main

    sess = FakeSession()
    bot = Bot("1:x", session=sess)
    dp = bot_main.build_dispatcher(db)
    dp["bot"] = bot
    yield bot, dp, sess
    from legal_bot.services.session import jobs
    await jobs.shutdown()
    for r in dp.sub_routers:
        r._parent_router = None


user = User(id=ADMIN, is_bot=False, first_name="Admin")
_uid = itertools.count(1)


async def send(bot, dp, text=None, photo=False, document=None, successful_payment=None):
    kw = {}
    if photo:
        kw["photo"] = [PhotoSize(file_id="PF1", file_unique_id="PU1", width=99, height=99)]
    if document:
        kw["document"] = document
    if successful_payment:
        kw["successful_payment"] = successful_payment
    m = Message(message_id=next(_uid), date=dt.datetime.now(), chat=Chat(id=ADMIN, type="private"),
                from_user=user, text=text, **kw)
    await dp.feed_update(bot, Update(update_id=next(_uid), message=m))
    await asyncio.sleep(0.05)


async def press(bot, dp, data, uid=ADMIN):
    u = User(id=uid, is_bot=False, first_name="Admin" if uid == ADMIN else "کاربر")
    msg = Message(message_id=1, date=dt.datetime.now(), chat=Chat(id=uid, type="private"), from_user=u, text="x")
    cb = CallbackQuery(id=str(next(_uid)), from_user=u, chat_instance="c", data=data, message=msg)
    await dp.feed_update(bot, Update(update_id=next(_uid), callback_query=cb))
    await asyncio.sleep(0.05)


# ═══════════════════════════════════════════════════════════════════════════
# ۱) پشتیبانی
# ═══════════════════════════════════════════════════════════════════════════
async def test_support_full_flow_user_to_admin_and_reply(env, db):
    bot, dp, sess = env
    await db.upsert_user(ADMIN, ADMIN, "Admin")

    # کاربر بخش پشتیبانی را باز می‌کند
    await send(bot, dp, T.M_SUPPORT)
    assert any(t and "پیش‌نویس" in t for t in sess.texts())
    assert sup.composing.get(ADMIN) is not None

    # متن و فایل به پیش‌نویس اضافه می‌شود — هنوز هیچ‌چیز برای مدیر نرفته
    await send(bot, dp, "سلام، در بخش ابلاغیه‌ها مشکل دارم.")
    await send(bot, dp, photo=True)
    await send(bot, dp, document=Document(file_id="DF1", file_unique_id="DU1",
                                          file_name="screenshot.png", mime_type="image/png"))
    d = sup.composing[ADMIN]
    assert len(d.texts) == 1 and len(d.files) == 2
    assert not any(t and "پیام پشتیبانی جدید" in t for t in sess.texts())

    # تایید و ارسال ← پیام (متن + فایل‌ها) برای مدیر می‌رود و در دیتابیس ثبت می‌شود
    await press(bot, dp, "sup:send")
    assert any(t and "پیام پشتیبانی جدید" in t for t in sess.texts())
    assert any(t and "سلام، در بخش ابلاغیه‌ها مشکل دارم." in t for t in sess.texts())
    assert sess.method_names().count("SendPhoto") >= 1
    assert sess.method_names().count("SendDocument") >= 1
    assert any(t and T.SUPPORT_SENT_USER in t for t in sess.texts())
    rows = await db.all("SELECT * FROM support_messages WHERE bale_id=?", (ADMIN,))
    assert len(rows) == 1 and rows[0]["sender"] == "user"
    assert "مشکل دارم" in rows[0]["body"]
    assert len(json.loads(rows[0]["files"])) == 2
    assert sup.composing.get(ADMIN) is None

    # مدیر پاسخ می‌دهد: دکمه‌ی پاسخ ← پیش‌نویس مدیر ← تایید ← ارسال برای کاربر
    await press(bot, dp, f"sup:reply:{ADMIN}")
    assert sup.composing.get(ADMIN) is not None and sup.composing[ADMIN].to_admin is False
    await send(bot, dp, "پاسخ پشتیبانی: در حال بررسی هستیم.")
    await send(bot, dp, photo=True)
    await press(bot, dp, "sup:send")
    assert any(t and "پاسخ پشتیبانی" in t and "در حال بررسی" in t for t in sess.texts())
    assert any(t and T.SUPPORT_SENT_ADMIN in t for t in sess.texts())
    rows = await db.all("SELECT * FROM support_messages WHERE bale_id=? AND sender='admin'", (ADMIN,))
    assert len(rows) == 1 and "در حال بررسی" in rows[0]["body"]


async def test_support_empty_draft_and_cancel(env, db):
    bot, dp, sess = env
    await db.upsert_user(ADMIN, ADMIN, "Admin")
    await send(bot, dp, T.M_SUPPORT)
    # پیش‌نویس خالی → هشدار
    await press(bot, dp, "sup:send")
    assert not any(t and "پیام پشتیبانی جدید" in t for t in sess.texts())
    # انصراف
    await press(bot, dp, "sup:cancel")
    assert sup.composing.get(ADMIN) is None
    # دکمه‌ی لغو کیبورد حین پیش‌نویس
    await send(bot, dp, T.M_SUPPORT)
    await send(bot, dp, "متن تست")
    await send(bot, dp, T.M_CANCEL)
    assert sup.composing.get(ADMIN) is None
    assert any(t and T.SUPPORT_CANCELLED in t for t in sess.texts())


async def test_support_menu_text_cancels_draft_silently(env, db):
    bot, dp, sess = env
    await db.upsert_user(ADMIN, ADMIN, "Admin")
    await send(bot, dp, T.M_SUPPORT)
    await send(bot, dp, "متن پیش‌نویس")
    assert sup.composing.get(ADMIN) is not None
    # یک دکمه‌ی منو (ابلاغیه‌ها) ← پیش‌نویس بی‌صدا لغو و مسیر عادی خودش می‌رود
    await send(bot, dp, T.M_NOTICES)
    assert sup.composing.get(ADMIN) is None
    # ربات پاسخ عادی خودش را داده (منوی ابلاغیه یا راهنمای پلن — بسته به اشتراک)
    assert sess.texts()[-1] is not None


# ═══════════════════════════════════════════════════════════════════════════
# ۴) جریان پرداخت: فاکتور ← درگاه ← تایید خودکار ← کارت‌به‌کارت پس از ۱۰ دقیقه
# ═══════════════════════════════════════════════════════════════════════════
class MiniBot:
    """ربات ساختگی برای فراخوانی مستقیم توابع پرداخت."""

    def __init__(self):
        self.calls = []   # (method, chat_id, kwargs)

    async def send_message(self, chat_id, text=None, **kw):
        self.calls.append(("message", chat_id, text, kw))
        return True

    async def send_photo(self, chat_id, photo=None, caption=None, **kw):
        self.calls.append(("photo", chat_id, caption, kw))
        return True

    async def send_document(self, chat_id, document=None, caption=None, **kw):
        self.calls.append(("document", chat_id, caption, kw))
        return True

    async def send_invoice(self, **kw):
        self.calls.append(("invoice", kw.get("chat_id"), kw.get("payload"), kw))
        return True

    def texts(self):
        return [c[2] for c in self.calls if c[0] == "message"]

    def all_texts(self):
        """همه‌ی متن‌ها و کپشن‌ها (پیام/عکس/فایل)."""
        return [c[2] for c in self.calls if c[2]]

    def card_offers(self):
        """پیام‌های فاکتور کارت‌به‌کارت (عکس یا متن — با کپشن مشخص فاکتور)."""
        return [c for c in self.calls if c[2] and "پرداخت از طریق کارت به کارت" in c[2]]

    def photos(self):
        return [c for c in self.calls if c[0] == "photo"]

    def invoices(self):
        return [c for c in self.calls if c[0] == "invoice"]


async def test_offer_payment_without_gateway_card_immediate(db, monkeypatch):
    """بدون توکن درگاه ← همان لحظه کارت‌به‌کارت (رفتار قبلی حفظ می‌شود)."""
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "")
    await db.upsert_user(41, 41, "کاربر")
    bot = MiniBot()
    inv = await sub.create_invoice(db, 41, "new", plan="base")
    res = await pay.offer_payment(bot, db, 41, inv)
    assert res == "card"
    assert len(bot.card_offers()) == 1        # فاکتور کارت‌به‌کارت همان لحظه
    row = await db.one("SELECT card_sent_at, gateway_sent_at FROM invoices WHERE code=?", (inv["code"],))
    assert row["card_sent_at"] is not None and row["gateway_sent_at"] is None


async def test_offer_payment_with_gateway_then_auto_fallback(db, monkeypatch):
    """با توکن درگاه: فاکتور درگاهی ارسال می‌شود؛ کارت‌به‌کارت فقط پس از مهلت ۱۰ دقیقه."""
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "TEST-TOKEN")
    monkeypatch.setattr(config, "PAY_CARD_FALLBACK_MINUTES", 10)
    await db.upsert_user(42, 42, "کاربر دو")
    bot = MiniBot()
    inv = await sub.create_invoice(db, 42, "new", plan="base")
    res = await pay.offer_payment(bot, db, 42, inv)
    assert res == "gateway"
    assert len(bot.invoices()) == 1 and bot.invoices()[0][2] == f"pay:{inv['code']}"
    assert bot.invoices()[0][3]["provider_token"] == "TEST-TOKEN"
    assert bot.invoices()[0][3]["currency"] == "IRR"
    # مبلغ درگاه = مبلغ فاکتور به ریال
    assert bot.invoices()[0][3]["prices"][0].amount == inv["amount_toman"] * 10
    assert any(t and "درگاه بله" in t for t in bot.texts())
    row = await db.one("SELECT card_sent_at, gateway_sent_at FROM invoices WHERE code=?", (inv["code"],))
    assert row["gateway_sent_at"] is not None and row["card_sent_at"] is None
    assert not bot.card_offers()              # هنوز کارت‌به‌کارت نرفته

    # زیر مهلت: تیک حلقه چیزی نمی‌فرستد
    assert await pay.card_fallback_tick(bot, db) == 0
    assert not bot.card_offers()

    # پس از گذشت ۱۱ دقیقه از ایجاد فاکتور ← کارت‌به‌کارت خودکار (یک بار)
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=11)).isoformat(timespec="seconds")
    await db.execute("UPDATE invoices SET created_at=? WHERE code=?", (old, inv["code"]))
    assert await pay.card_fallback_tick(bot, db) == 1
    assert len(bot.card_offers()) == 1
    assert T.CARD_FALLBACK_NOTE.split("\n")[0] in bot.card_offers()[0][2]
    # تیک بعدی: تکراری ارسال نمی‌شود
    assert await pay.card_fallback_tick(bot, db) == 0
    assert len(bot.card_offers()) == 1


class PayMsg:
    """Message ساختگی برای هندلر successful_payment."""

    def __init__(self, uid, payload, charge="CH-1", total=600_000 * 10):
        from types import SimpleNamespace

        self.from_user = SimpleNamespace(id=uid, full_name="کاربر درگاه")
        self.bot = MiniBot()
        self.successful_payment = SuccessfulPayment(
            currency="IRR", total_amount=total, invoice_payload=payload,
            telegram_payment_charge_id=charge, provider_payment_charge_id=charge)
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append(text)


async def test_gateway_payment_auto_approves_and_activates_plan(db, monkeypatch):
    """پرداخت درگاهی ← تایید خودکار + فعال‌سازی پلن + اطلاع کاربر و مدیر."""
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "TEST-TOKEN")
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    await db.upsert_user(43, 43, "کاربر سه")
    inv = await sub.create_invoice(db, 43, "new", plan="base")
    msg = PayMsg(43, f"pay:{inv['code']}")
    await pay.gateway_payment_done(msg, db)

    row = await db.one("SELECT status FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "approved"
    s = await sub.get(db, 43)
    assert s["status"] == "PAID_ACTIVE" and s["plan"] == "base"
    assert s["inquiries_left"] == config.PLAN_BASE_INQUIRIES
    # اطلاع خودکار به کاربر و مدیر
    assert any("خودکار تایید شد" in a for a in msg.answers)
    assert any(t and "پرداخت درگاه بله (تایید خودکار)" in t for t in msg.bot.texts())
    assert any(t and "پلن" in t for t in msg.bot.texts())       # پیام فعال‌سازی به کاربر


async def test_gateway_payment_turn_invoice_readies_booking(db, monkeypatch):
    """فاکتور نوبت با درگاه پرداخت شد ← تایید خودکار + دکمه‌ی شروع ثبت نوبت."""
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "TEST-TOKEN")
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    await db.upsert_user(44, 44, "کاربر چهار")
    inv = await sub.create_invoice(db, 44, "turn", payload="case:140513920000890035",
                                   amount=config.PRICE_TURN * 4)     # مثل ۴ نوبت = ۲۸۰٬۰۰۰
    msg = PayMsg(44, f"pay:{inv['code']}", total=config.PRICE_TURN * 4 * 10)
    await pay.gateway_payment_done(msg, db)
    row = await db.one("SELECT status FROM invoices WHERE code=?", (inv["code"],))
    assert row["status"] == "approved"
    # دکمه‌ی شروع ثبت نوبت برای کاربر رفته (notify_paid)
    assert any(t and "برای شروع ثبت نوبت" in t for t in msg.bot.texts())


async def test_gateway_duplicate_payment_warns_admin(db, monkeypatch):
    monkeypatch.setattr(config, "BALE_WALLET_TOKEN", "TEST-TOKEN")
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    await db.upsert_user(45, 45, "کاربر پنج")
    inv = await sub.create_invoice(db, 45, "new", plan="base")
    await db.execute("UPDATE invoices SET status='approved' WHERE code=?", (inv["code"],))
    msg = PayMsg(45, f"pay:{inv['code']}")
    await pay.gateway_payment_done(msg, db)
    assert any(t and "پرداخت تکراری" in t for t in msg.bot.texts())
    assert any("قبلاً پرداخت شده" in a for a in msg.answers)


# ═══════════════════════════════════════════════════════════════════════════
# ۳) گزارش خطای دقیق + اسکرین‌شات
# ═══════════════════════════════════════════════════════════════════════════
async def test_error_report_sends_screenshot_and_precise_details(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    monkeypatch.setattr(config, "ERROR_SHOT_TO_ADMIN", True)
    bot = MiniBot()
    bot.send_photo = MiniBot().send_photo            # امضای یکسان
    sent = []
    orig_photo = bot.send_photo

    async def fake_photo(chat_id, photo=None, caption=None, **kw):
        sent.append((chat_id, caption))
        return True

    bot.send_photo = fake_photo
    uid = 5001
    run_id = await db.create_run(uid, "notices_new", "manual")
    await error_reporter.report(bot, db, run_id=run_id, user_id=uid, step="L07",
                                category="SANA_DOWN", message="net error xyz",
                                steps_ok="L04,L05,L06", screenshot=b"FAKE-PNG",
                                kind="notices_new", user_name="کاربر تست")
    assert sent, "اسکرین‌شات برای مدیر ارسال نشد"
    chat_id, caption = sent[0]
    assert chat_id == ADMIN
    # «دقیقاً در چه مرحله‌ای»: شماره + نام + کارِ مرحله
    assert "L07" in caption and "رمز موقت" in caption
    assert error_reporter.STEP_DETAILS["L07"] in caption
    # «بابت چه موردی»: علت فارسی دسته‌ی خطا
    assert error_reporter.CATEGORY_FA["SANA_DOWN"] in caption
    # زنجیره‌ی مراحل + نوع کار + نام کاربر
    assert "❌L07" in caption and "✅L06" in caption
    assert error_reporter.KIND_FA["notices_new"] in caption
    assert "کاربر تست" in caption
    # ثبت در دیتابیس خطاها
    err = await db.one("SELECT * FROM error_events WHERE bale_id=? ORDER BY id DESC", (uid,))
    assert err["step"] == "L07" and err["category"] == "SANA_DOWN"
    run = await db.one("SELECT * FROM check_runs WHERE id=?", (run_id,))
    assert run["status"] == "failed"


async def test_error_report_without_screenshot_sends_text(db, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_ID", ADMIN)
    bot = MiniBot()
    await error_reporter.report(bot, db, run_id=13, user_id=5002, step="L11",
                                category="SEND_FAILED", message="x", screenshot=None, kind="turn")
    assert any(t and "L11" in t for t in bot.texts())
    assert not any(c[0] == "photo" for c in bot.calls)


async def test_runctx_error_screenshot_of_active_page(db, monkeypatch):
    """RunCtx از صفحه‌ی فعالِ همان لحظه اسکرین‌شات می‌گیرد (و خطا آن را نمی‌شکند)."""
    from legal_bot.services.flow import RunCtx
    from types import SimpleNamespace

    class FakePage:
        async def screenshot(self, timeout=None):
            return b"SHOT"

    class DeadPage:
        async def screenshot(self, timeout=None):
            raise RuntimeError("closed")

    job = SimpleNamespace(bot=MiniBot(), user_id=1, chat_id=1, user_name="u", run_id=None)
    ctx = RunCtx(job, db, "notices_new")
    ctx.page = FakePage()
    assert await ctx.error_screenshot() == b"SHOT"
    ctx.page = DeadPage()
    assert await ctx.error_screenshot() is None
    ctx.page = None
    assert await ctx.error_screenshot() is None


# ═══════════════════════════════════════════════════════════════════════════
# ۲) پنل ادمین: فاکتور used در فهرست و درآمد
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from legal_admin import server, settings

    monkeypatch.setattr(settings, "PASSWORD", "test-pass-123456")
    monkeypatch.setattr(settings, "SECRET", "s3cret")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    server._login_fails.clear()
    with TestClient(server.app) as c:
        yield c


H = {"X-Panel-CSRF": "1"}


def _login(client):
    assert client.post("/api/login", json={"password": "test-pass-123456"}, headers=H).status_code == 200


async def _panel_db(client):
    """اتصال مستقیم به همان دیتابیس پنل (مسیر از تنظیمات فعلی config)."""
    d = await DB(config.DB_PATH).connect()
    return d


@pytest.mark.asyncio
async def test_panel_invoice_used_visible_and_revenue(client, monkeypatch):
    """پرداخت ۲۸۰ هزار تومانی نوبتِ مصرف‌شده (used) در پنل: فهرست + درآمد."""
    _login(client)
    d = await _panel_db(client)
    try:
        await d.upsert_user(61, 61, "کاربر نوبت")
        inv = await sub.create_invoice(d, 61, "turn", payload="case:1234",
                                       amount=280_000)       # ۴ نوبت × ۷۰٬۰۰۰
        # شبیه‌سازی: رسید تایید شد و نوبت ثبت شد ← status='used'
        await d.execute("UPDATE invoices SET status='used', reviewed_at=? WHERE code=?",
                        (sub.now_iso(), inv["code"]))
        # فهرست پیش‌فرض (بدون فیلتر وضعیت) باید فاکتور used را نشان دهد
        r = client.get("/api/invoices", headers=H)
        assert r.status_code == 200
        codes = [row["code"] for row in r.json()["rows"]]
        assert inv["code"] in codes, "فاکتور پرداخت‌شده‌ی نوبت در فهرست پنل نیست!"
        # فیلتر وضعیت used هم کار می‌کند
        r = client.get("/api/invoices?status=used", headers=H)
        assert inv["code"] in [row["code"] for row in r.json()["rows"]]
        # درآمد ۷ روزه فاکتور used را می‌شمارد (همراه سهم کیف پول)
        await d.execute("UPDATE invoices SET wallet_used=20000, amount_toman=260000 WHERE code=?",
                        (inv["code"],))
        s = client.get("/api/stats", headers=H).json()
        assert s["kpis"]["revenue_toman"] >= 280_000
        assert s["kpis"]["approved_inv"] >= 1
    finally:
        await d.close()


async def test_panel_support_section_lists_messages(client, monkeypatch):
    _login(client)
    d = await _panel_db(client)
    try:
        await d.upsert_user(62, 62, "کاربر پشتیبانی")
        await d.execute(
            "INSERT INTO support_messages(bale_id,sender,body,files,created_at) VALUES(?,?,?,?,?)",
            (62, "user", "سلام مشکل دارم", json.dumps([{"file_id": "F1", "kind": "photo"}]),
             sub.now_iso()))
        r = client.get("/api/support", headers=H)
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["bale_id"] == 62 and rows[0]["sender"] == "user"
        assert rows[0]["files_count"] == 1
        st = client.get("/api/support/stats", headers=H).json()
        assert st["total"] == 1 and st["users"] == 1
    finally:
        await d.close()
