"""رگرسیون اصلاحات ممیزی امنیتی/باگ: پنل مدیریت، فاکتورها، شروع رایگان، سهمیه."""
import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from legal_bot import config
from legal_bot.services import subscription as sub

os.environ.setdefault("ADMIN_PANEL_PASSWORD", "test-pass-123456")


# ── منطق اشتراک ─────────────────────────────────────────────────────────────
async def test_free_start_does_not_overwrite_paid_plan(db):
    inv = await sub.create_invoice(db, 31, "new", "pro", "monthly")
    await db.execute("UPDATE invoices SET status='receipt_sent' WHERE code=?", (inv["code"],))
    assert await sub.approve_invoice(db, inv["code"], 777)
    assert not await sub.activate_free(db, 31)
    s = await sub.get(db, 31)
    assert s["status"] == "PAID_ACTIVE" and s["plan"] == "pro"


async def test_free_start_is_atomic_under_concurrency(db):
    await sub.get(db, 32)
    res = await asyncio.gather(*(sub.activate_free(db, 32) for _ in range(5)))
    assert res.count(True) == 1
    assert (await sub.get(db, 32))["inquiries_left"] == config.FREE_INQUIRIES


async def test_bot_button_cannot_approve_without_receipt(db):
    inv = await sub.create_invoice(db, 33, "new", "base", "credit")      # pending، بدون رسید
    assert await sub.approve_invoice(db, inv["code"], 777, only_receipt=True) is None
    assert await sub.approve_invoice(db, inv["code"], 777)               # پنل مدیریت هنوز می‌تواند


async def test_consume_never_goes_negative(db):
    await sub.get(db, 34)
    await sub.activate_free(db, 34)
    await asyncio.gather(*(sub.consume(db, 34) for _ in range(6)))
    row = await db.one("SELECT inquiries_left FROM subscriptions WHERE bale_id=34")
    assert row["inquiries_left"] >= 0


async def test_restrict_huge_hours_does_not_overflow(db):
    await sub.get(db, 35)
    await sub.restrict(db, 35, 10**9, "x")
    assert (await db.one("SELECT restricted_until FROM subscriptions WHERE bale_id=35"))["restricted_until"]


# ── پنل مدیریت ─────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch, tmp_path):
    from legal_admin import server, settings

    monkeypatch.setattr(settings, "PASSWORD", "test-pass-123456")
    monkeypatch.setattr(settings, "SECRET", "s3cret")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    server._login_fails.clear()
    with TestClient(server.app) as c:
        yield c


H = {"X-Panel-CSRF": "1"}


def test_login_non_ascii_password_is_401_not_500(client):
    r = client.post("/api/login", json={"password": "رمز-اشتباه"}, headers=H)
    assert r.status_code == 401


def test_login_cookie_flags_and_headers(client):
    r = client.post("/api/login", json={"password": "test-pass-123456"}, headers=H)
    assert r.status_code == 200
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=strict" in ck
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_delete_requires_csrf_header(client):
    client.post("/api/login", json={"password": "test-pass-123456"}, headers=H)
    assert client.delete("/api/beta/5").status_code == 403
    assert client.delete("/api/beta/5", headers=H).status_code == 200


def test_cross_origin_post_rejected(client):
    client.post("/api/login", json={"password": "test-pass-123456"}, headers=H)
    r = client.post("/api/beta", json={"bale_id": 5}, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_requires_login_and_validates_input(client):
    assert client.get("/api/users").status_code == 401
    client.post("/api/login", json={"password": "test-pass-123456"}, headers=H)
    assert client.post("/api/users/1/restrict", json={"hours": 10**9}, headers=H).status_code == 422
    assert client.post("/api/invoices/INV-X/shortfall", json={"amount": -5}, headers=H).status_code == 422
    assert client.get("/api/users?q=%25%25_&page=-3").status_code == 200


def test_login_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "x"}, headers=H).status_code == 401
    assert client.post("/api/login", json={"password": "test-pass-123456"}, headers=H).status_code == 429


# ── اعتبارسنجی فاکتور از داده‌ی دکمه ─────────────────────────────────────────
class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)

    async def send_photo(self, *a, **kw):
        self.sent.append("photo")


class _CB:
    def __init__(self, uid):
        from types import SimpleNamespace as NS
        self.bot = _Bot()
        self.from_user = NS(id=uid)
        self.message = NS(chat=NS(id=uid))


@pytest.mark.parametrize("data", [
    "inv:upgrade:org:monthly",      # ارتقا بدون اشتراک ← قبلاً فاکتور ۰ تومانی می‌ساخت
    "inv:new:free:monthly",         # پلن رایگان قابل خرید نیست ← قبلاً KeyError
    "inv:renew:pro:monthly",        # تمدید بدون اشتراک
    "inv:new:base:monthly",         # پلن اعتباری با دوره‌ی نادرست
    "inv:turn:pro:monthly",         # نوع نامعتبر
    "inv:new:nope:monthly",
])
async def test_invoice_from_button_is_validated(db, data):
    from legal_bot.handlers import plans

    cb = _CB(41)
    await sub.get(db, 41)
    await plans._do_invoice(cb, db, data)
    assert await db.one("SELECT 1 FROM invoices WHERE bale_id=41") is None


async def test_valid_invoice_still_created(db):
    from legal_bot.handlers import plans

    cb = _CB(42)
    await sub.get(db, 42)
    await plans._do_invoice(cb, db, "inv:new:base:credit")
    inv = await db.one("SELECT * FROM invoices WHERE bale_id=42")
    assert inv and inv["amount_toman"] == config.PLAN_BASE_PRICE
