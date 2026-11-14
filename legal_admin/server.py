"""سرور پنل مدیریت Legal-Automation — FastAPI + همان دیتابیس SQLite ربات.

تمام اعمال حساس (تأیید/رد/کسری فاکتور، محدودسازی، بتا) از توابع خود
legal_bot.services.subscription استفاده می‌کنند تا منطق یکسان بماند.

نکته امنیتی: کوکی نشست امضای HMAC دارد؛ درخواست‌های POST هدر
`X-Panel-CSRF: 1` لازم دارند (ضد CSRF). ورود ناموفق: ۵ تلاش، ۱۰ دقیقه قفل.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import settings
from .notify import bot_ok, send_message

log = logging.getLogger("legal_admin")

STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE = "la_admin"

# ── نشست و امنیت ────────────────────────────────────────────────────────────
_login_fails: dict[str, list[float]] = {}          # ip -> زمان تلاش‌ها


def _sign(payload: str) -> str:
    return hmac.new(settings.SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _make_session() -> str:
    exp = int(time.time()) + settings.SESSION_HOURS * 3600
    return f"{exp}.{_sign(str(exp))}"


def _valid_session(value: str | None) -> bool:
    try:
        exp_s, sig = value.split(".", 1)
        exp = int(exp_s)
    except Exception:
        return False
    return hmac.compare_digest(sig, _sign(exp_s)) and exp > time.time()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _login_blocked(ip: str) -> bool:
    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < 600]
    _login_fails[ip] = fails
    return len(fails) >= 5


def _record_fail(ip: str):
    _login_fails.setdefault(ip, []).append(time.time())


def require_auth(request: Request):
    if not _valid_session(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="نشست معتبر نیست؛ دوباره وارد شوید.")
    if request.method == "POST" and request.headers.get("X-Panel-CSRF") != "1":
        raise HTTPException(status_code=403, detail="درخواست فاقد هدر CSRF است.")


# ── کمکی‌ها ─────────────────────────────────────────────────────────────────
def _iso(s) -> str:
    try:
        return (s or "")[:16].replace("T", " ")
    except Exception:
        return s or ""


def _fa_date(iso_s) -> str:
    """تاریخ شمسی خوانا برای نمایش در جدول‌ها."""
    if not iso_s:
        return "-"
    try:
        from legal_bot.db import parse_iso
        from legal_bot.utils import to_jalali_str

        d = parse_iso((iso_s or "").replace(" ", "T"))
        return to_jalali_str(d.date()) if d else "-"
    except Exception:
        return (iso_s or "")[:10]


def _row_fa(rows: list[dict], *keys):
    """برای هر سطر، نسخه شمسی از ستون‌های تاریخ می‌سازد (کلید + "_fa")."""
    for r in rows:
        for k in keys:
            if k in r:
                r[f"{k}_fa"] = _fa_date(r[k])
                r[k] = _iso(r[k])
    return rows


def _toman(n) -> str:
    try:
        return f"{int(n or 0):,}".replace(",", "٬")
    except Exception:
        return "-"


# ── برنامه ──────────────────────────────────────────────────────────────────
app = FastAPI(title="پنل مدیریت — اتوماسیون ویژه خدمات حقوقی", docs_url=None, redoc_url=None)
_db = None


@app.on_event("startup")
async def _startup():
    global _db
    if not settings.PASSWORD:
        raise SystemExit("❌ ADMIN_PANEL_PASSWORD در .env تنظیم نشده است؛ پنل بدون رمز اجرا نمی‌شود.")
    from legal_bot.db import DB

    _db = await DB().connect()
    log.info("admin panel db connected: %s", _db.path)


@app.on_event("shutdown")
async def _shutdown():
    if _db:
        await _db.close()


def db():
    if _db is None:
        raise HTTPException(503, "دیتابیس هنوز آماده نیست.")
    return _db


# ── صفحه و فایل‌های ثابت ────────────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/style.css")
async def style():
    return FileResponse(STATIC_DIR / "style.css", media_type="text/css; charset=utf-8")


@app.get("/app.js")
async def js():
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript; charset=utf-8")


# ── احراز هویت ───────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    password: str


@app.post("/api/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = _client_ip(request)
    if _login_blocked(ip):
        raise HTTPException(429, "تلاش زیاد؛ ۱۰ دقیقه صبر کنید.")
    if not secrets.compare_digest(body.password, settings.PASSWORD):
        _record_fail(ip)
        raise HTTPException(401, "رمز اشتباه است.")
    _login_fails.pop(ip, None)
    response.set_cookie(COOKIE, _make_session(), httponly=True, samesite="Lax",
                        max_age=settings.SESSION_HOURS * 3600)
    return {"ok": True}


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    require_auth(request)
    response.delete_cookie(COOKIE)
    return {"ok": True}


# ── داشبورد ─────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def stats(request: Request):
    require_auth(request)
    d = db()
    now = dt.datetime.now(dt.timezone.utc)
    day0 = now.date()
    since24 = (now - dt.timedelta(hours=24)).isoformat(timespec="seconds")
    since7 = (now - dt.timedelta(days=7)).isoformat(timespec="seconds")
    since7d = day0 - dt.timedelta(days=6)

    users = (await d.one("SELECT COUNT(*) c FROM users"))["c"]
    subs_rows = await d.all(
        "SELECT COALESCE(plan,'-') plan, COUNT(*) c FROM subscriptions "
        "WHERE status IN ('FREE_ACTIVE','PAID_ACTIVE') GROUP BY plan")
    pending_inv = (await d.one(
        "SELECT COUNT(*) c FROM invoices WHERE status IN ('pending','receipt_sent','shortfall_wait')"))["c"]
    revenue = (await d.one(
        "SELECT COALESCE(SUM(amount_toman),0) s FROM invoices WHERE status='approved' "
        "AND created_at>=?", (since7,)))["s"]
    approved_inv = (await d.one(
        "SELECT COUNT(*) c FROM invoices WHERE status='approved' AND created_at>=?", (since7,)))["c"]
    runs24 = (await d.one("SELECT COUNT(*) c FROM check_runs WHERE started_at>=?", (since24,)))["c"]
    errors24 = (await d.one("SELECT COUNT(*) c FROM error_events WHERE created_at>=?", (since24,)))["c"]
    restricted = (await d.one(
        "SELECT COUNT(*) c FROM subscriptions WHERE restricted_until IS NOT NULL"))["c"]

    # نمودار: ۷ روز اخیر — بررسی موفق/ناموفق و خطا
    chart = []
    for i in range(6, -1, -1):
        day = since7d + dt.timedelta(days=i)
        a = day.isoformat()
        b = (day + dt.timedelta(days=1)).isoformat()
        ok = (await d.one(
            "SELECT COUNT(*) c FROM check_runs WHERE started_at>=? AND started_at<? AND status='done'",
            (a, b)))["c"]
        bad = (await d.one(
            "SELECT COUNT(*) c FROM check_runs WHERE started_at>=? AND started_at<? AND status!='done'",
            (a, b)))["c"]
        from legal_bot.utils import weekday_fa

        chart.append({"day": _fa_date(a), "wd": weekday_fa(day), "ok": ok, "bad": bad})

    events = _row_fa(await d.all(
        "SELECT pe.*, u.first_name FROM plan_events pe LEFT JOIN users u ON u.bale_id=pe.bale_id "
        "ORDER BY pe.id DESC LIMIT 12"), "created_at")

    plan_counts = {r["plan"]: r["c"] for r in subs_rows}
    return {
        "kpis": {
            "users": users, "pending_inv": pending_inv, "approved_inv": approved_inv,
            "revenue_toman": int(revenue), "runs24": runs24, "errors24": errors24,
            "restricted": restricted, "active": sum(plan_counts.values()),
            "free": plan_counts.get("free", 0), "credit": plan_counts.get("-", 0),
        },
        "plans": [{"plan": r["plan"], "c": r["c"]} for r in subs_rows],
        "chart": chart,
        "events": events,
    }


@app.get("/api/system")
async def system(request: Request):
    require_auth(request)
    from legal_bot import config

    b = await bot_ok()
    info = {"bot": b, "db_path": os.path.basename(config.DB_PATH),
            "port": settings.PORT, "plans_cfg": {
                "base": config.PLAN_BASE_INQUIRIES, "select": config.PLAN_SELECT_INQUIRIES,
                "pro_quota": config.PLAN_PRO_QUOTA, "expert_quota": config.PLAN_EXPERT_QUOTA,
                "org_cases": config.PLAN_ORG_CASES, "turn_price": _toman(config.PRICE_TURN)}}
    try:
        import psutil

        info["ram"] = {"free_mb": int(psutil.virtual_memory().available / 1048576),
                       "total_mb": int(psutil.virtual_memory().total / 1048576),
                       "pct": psutil.virtual_memory().percent}
        info["cpu"] = psutil.cpu_percent(interval=0.3)
    except Exception:
        info["ram"] = None
    return info


# ── کاربران ─────────────────────────────────────────────────────────────────
@app.get("/api/users")
async def users_list(request: Request, q: str = "", page: int = 1, plan: str = "", status: str = ""):
    require_auth(request)
    d = db()
    where, params = [], []
    if q.strip():
        like = f"%{q.strip()}%"
        cond = "(u.first_name LIKE ? OR CAST(s.bale_id AS TEXT) LIKE ? OR s.phone LIKE ?)"
        where.append(cond)
        params += [like, like, like]
    if plan:
        if plan == "-":
            where.append("(s.plan IS NULL OR s.plan='')")
        else:
            where.append("s.plan=?")
            params.append(plan)
    if status:
        where.append("s.status=?")
        params.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = (await d.one(f"SELECT COUNT(*) c FROM users u JOIN subscriptions s ON s.bale_id=u.bale_id {w}",
                         tuple(params)))["c"]
    limit, offset = 25, (max(1, page) - 1) * 25
    rows = await d.all(
        f"SELECT u.bale_id, u.first_name, u.created_at, s.status, s.plan, s.cycle, "
        f"s.inquiries_left, s.quota_used, s.quota_total, s.phone, s.restricted_until, "
        f"s.restriction_reason, s.paid_until, s.free_used "
        f"FROM users u JOIN subscriptions s ON s.bale_id=u.bale_id {w} "
        f"ORDER BY u.bale_id DESC LIMIT ? OFFSET ?", tuple(params + [limit, offset]))
    return {"total": total, "rows": _row_fa(rows, "created_at", "paid_until", "restricted_until")}


@app.get("/api/users/{uid}")
async def user_detail(uid: int, request: Request):
    require_auth(request)
    d = db()
    u = await d.get_user(uid)
    if not u:
        raise HTTPException(404, "کاربر یافت نشد.")
    s = await d.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    events = _row_fa(await d.all(
        "SELECT * FROM plan_events WHERE bale_id=? ORDER BY id DESC LIMIT 20", (uid,)), "created_at")
    invoices = _row_fa(await d.all(
        "SELECT code, kind, amount_toman, status, plan, cycle, created_at, reviewed_at "
        "FROM invoices WHERE bale_id=? ORDER BY id DESC LIMIT 15", (uid,)), "created_at", "reviewed_at")
    notices = _row_fa(await d.all(
        "SELECT external_id, case_number, branch, notice_type, sent_date, status "
        "FROM notices WHERE bale_id=? ORDER BY id DESC LIMIT 10", (uid,)), "sent_date")
    cases = _row_fa(await d.all(
        "SELECT case_number, portal, last_change, last_checked FROM tracked_cases "
        "WHERE bale_id=? ORDER BY created_at", (uid,)), "last_checked")
    beta = await d.is_beta(uid)
    return {"user": _row_fa([u], "created_at")[0], "sub": _row_fa([s], "paid_until", "restricted_until")[0] if s else None,
            "events": events, "invoices": invoices, "notices": notices, "cases": cases, "beta": beta}


class RestrictIn(BaseModel):
    hours: int
    reason: str = "محدودسازی از پنل مدیریت (قاعده ۶)"


class DmIn(BaseModel):
    text: str


@app.post("/api/users/{uid}/message")
async def user_message(uid: int, body: DmIn, request: Request):
    """پیام مستقیم مدیر به یک کاربر از طریق بله."""
    require_auth(request)
    if not body.text.strip():
        raise HTTPException(422, "متن پیام خالی است.")
    u = await db().get_user(uid)
    if not u:
        raise HTTPException(404, "کاربر یافت نشد.")
    if not u.get("chat_id"):
        raise HTTPException(409, "این کاربر chat_id ندارد (هنوز با ربات /start نکرده).")
    res = await send_message(u["chat_id"], body.text[:4000])
    if res and res.get("ok"):
        return {"ok": True}
    raise HTTPException(502, "ارسال به بله ناموفق بود (توکن یا دسترسی را ببینید).")


@app.post("/api/users/{uid}/restrict")
async def user_restrict(uid: int, body: RestrictIn, request: Request):
    require_auth(request)
    from legal_bot import config
    from legal_bot.services import subscription as sub

    await sub.restrict(db(), uid, max(1, min(body.hours, 720)), body.reason[:300])
    await sub.report_violation(None, db(), uid, "محدودسازی از پنل", body.reason[:300])
    u = await db().get_user(uid)
    if u and u.get("chat_id"):
        await send_message(u["chat_id"],
                          f"⛔ حساب شما به مدت {body.hours} ساعت محدود شد.\nدلیل: {body.reason[:200]}")
    return {"ok": True}


@app.post("/api/users/{uid}/unrestrict")
async def user_unrestrict(uid: int, request: Request):
    require_auth(request)
    from legal_bot.services import subscription as sub

    await sub.unrestrict(db(), uid)
    u = await db().get_user(uid)
    if u and u.get("chat_id"):
        await send_message(u["chat_id"], "✅ محدودیت حساب شما برداشته شد.")
    return {"ok": True}


# ── فاکتورها ────────────────────────────────────────────────────────────────
@app.get("/api/invoices")
async def invoices_list(request: Request, status: str = "", q: str = "", page: int = 1):
    require_auth(request)
    d = db()
    where, params = [], []
    if status:
        where.append("i.status=?")
        params.append(status)
    else:
        where.append("i.status NOT IN ('expired','used')")
    if q.strip():
        like = f"%{q.strip()}%"
        cond = "(i.code LIKE ? OR CAST(i.bale_id AS TEXT) LIKE ? OR u.first_name LIKE ?)"
        where.append(cond)
        params += [like, like, like]
    w = "WHERE " + " AND ".join(where)
    total = (await d.one(
        f"SELECT COUNT(*) c FROM invoices i LEFT JOIN users u ON u.bale_id=i.bale_id {w}",
        tuple(params)))["c"]
    limit, offset = 25, (max(1, page) - 1) * 25
    rows = await d.all(
        f"SELECT i.id, i.code, i.bale_id, i.kind, i.amount_toman, i.status, i.plan, i.cycle, "
        f"i.payload, i.created_at, i.expires_at, i.reviewed_at, i.reject_reason, i.shortfall_toman, "
        f"u.first_name FROM invoices i LEFT JOIN users u ON u.bale_id=i.bale_id {w} "
        f"ORDER BY i.id DESC LIMIT ? OFFSET ?", tuple(params + [limit, offset]))
    return {"total": total, "rows": _row_fa(rows, "created_at", "expires_at", "reviewed_at")}


async def _invoice_notify(inv: dict, text: str, reply_markup: dict | None = None):
    u = await db().get_user(inv["bale_id"]) if inv else None
    if u and u.get("chat_id"):
        await send_message(u["chat_id"], text, reply_markup)


@app.post("/api/invoices/{code}/approve")
async def invoice_approve(code: str, request: Request):
    require_auth(request)
    from legal_bot import config
    from legal_bot.db import parse_iso
    from legal_bot.services import subscription as sub
    from legal_bot.utils import fa_date, to_fa_digits

    inv = await sub.approve_invoice(db(), code, config.ADMIN_ID)
    if not inv:
        raise HTTPException(409, "این فاکتور قبلاً بررسی شده یا وضعیتش مناسب تأیید نیست.")
    if inv["kind"] == "turn":
        await _invoice_notify(inv, "✅ پرداخت شما تایید شد. برای شروع ثبت نوبت دکمه‌ی زیر را بزنید.",
                              {"inline_keyboard": [[
                                  {"text": "▶️ شروع ثبت نوبت",
                                   "callback_data": f"turn:go:{code}"}]]})
        return {"ok": True, "kind": "turn"}
    s = await sub.get(db(), inv["bale_id"])
    m = sub.plan_meta(s["plan"])
    if m.get("kind") == "credit":
        body = (f"✅ پرداخت تایید شد؛ پلن «{sub.plan_title(s['plan'])}» فعال است.\n"
                f"📊 اعتبار استعلام باقی‌مانده: {to_fa_digits(s['inquiries_left'])}")
    elif s["plan"]:
        quota = m.get("quota", 0)
        qtxt = ("استعلام نامحدود (سقف روزانه: " + to_fa_digits(config.PLAN_ORG_DAILY_CAP) + ")"
                if quota <= 0 else f"{to_fa_digits(quota)} استعلام در ماه")
        body = (f"✅ پرداخت تایید شد؛ پلن «{sub.plan_title(s['plan'])}» "
                f"({sub.CYCLE_FA.get(s['cycle'], '')}) تا {fa_date(parse_iso(s['paid_until']).date())} فعال است.\n"
                f"📊 سهمیه: {qtxt}\n📂 پیگیری خودکار تا {to_fa_digits(m.get('cases', 0))} پرونده")
    else:
        body = "✅ پرداخت تایید شد."
    await _invoice_notify(inv, body + "\n\nمرحله‌ی بعد: در هر بررسی، ربات برای ورود به اطلاعات سامانه "
                                        "نیاز دارد؛ این اطلاعات ذخیره نمی‌شود.")
    return {"ok": True, "kind": inv["kind"]}


class RejectIn(BaseModel):
    reason: str


@app.post("/api/invoices/{code}/reject")
async def invoice_reject(code: str, body: RejectIn, request: Request):
    require_auth(request)
    from legal_bot import config
    from legal_bot.services import subscription as sub

    if not body.reason.strip():
        raise HTTPException(422, "دلیل رد را بنویسید.")
    inv = await sub.reject_invoice(db(), code, config.ADMIN_ID, body.reason[:300])
    if not inv:
        raise HTTPException(409, "این فاکتور قابل رد نیست (وضعیت مناسب نیست).")
    await _invoice_notify(inv, f"❌ رسید شما رد شد.\nدلیل: {body.reason[:300]}\n"
                               "می‌توانید رسید درست را دوباره ارسال کنید.")
    return {"ok": True}


class ShortfallIn(BaseModel):
    amount: int


@app.post("/api/invoices/{code}/shortfall")
async def invoice_shortfall(code: str, body: ShortfallIn, request: Request):
    require_auth(request)
    from legal_bot import config
    from legal_bot.services import subscription as sub
    from legal_bot.utils import to_fa_digits

    inv = await sub.declare_shortfall(db(), code, config.ADMIN_ID, body.amount)
    if not inv:
        raise HTTPException(409, "کسری قابل اعلام نیست (مبلغ نامعتبر یا وضعیت فاکتور مناسب نیست).")
    await _invoice_notify(inv, f"💸 مبلغ واریزی کمتر از فاکتور است.\n"
                               f"لطفاً {to_fa_digits(body.amount)} تومان باقی‌مانده را واریز و "
                               "تصویر رسید آن را ارسال کنید.")
    return {"ok": True}


# ── گزارش‌ها ────────────────────────────────────────────────────────────────
@app.get("/api/runs")
async def runs_list(request: Request, status: str = "", q: str = "", page: int = 1):
    require_auth(request)
    d = db()
    where, params = [], []
    if status:
        where.append("r.status=?")
        params.append(status)
    if q.strip().isdigit():
        where.append("r.bale_id=?")
        params.append(int(q.strip()))
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = (await d.one(f"SELECT COUNT(*) c FROM check_runs r {w}", tuple(params)))["c"]
    limit, offset = 30, (max(1, page) - 1) * 30
    rows = await d.all(
        f"SELECT r.id, r.bale_id, u.first_name, r.kind, r.trigger, r.status, r.step, r.steps_ok, "
        f"r.new_items, r.error_code, r.started_at, r.finished_at FROM check_runs r "
        f"LEFT JOIN users u ON u.bale_id=r.bale_id {w} ORDER BY r.id DESC LIMIT ? OFFSET ?",
        tuple(params + [limit, offset]))
    return {"total": total, "rows": _row_fa(rows, "started_at", "finished_at")}


@app.get("/api/errors")
async def errors_list(request: Request, page: int = 1):
    require_auth(request)
    d = db()
    total = (await d.one("SELECT COUNT(*) c FROM error_events"))["c"]
    limit, offset = 30, (max(1, page) - 1) * 30
    rows = await d.all(
        "SELECT e.id, e.run_id, e.bale_id, u.first_name, e.step, e.category, e.message, e.created_at "
        "FROM error_events e LEFT JOIN users u ON u.bale_id=e.bale_id ORDER BY e.id DESC LIMIT ? OFFSET ?",
        (limit, offset))
    return {"total": total, "rows": _row_fa(rows, "created_at")}


@app.get("/api/notices")
async def notices_list(request: Request, q: str = "", page: int = 1):
    require_auth(request)
    d = db()
    where, params = [], []
    if q.strip():
        like = f"%{q.strip()}%"
        cond = "(n.case_number LIKE ? OR n.external_id LIKE ? OR n.branch LIKE ? OR CAST(n.bale_id AS TEXT) LIKE ?)"
        where.append(cond)
        params += [like, like, like, like]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = (await d.one(f"SELECT COUNT(*) c FROM notices n {w}", tuple(params)))["c"]
    limit, offset = 30, (max(1, page) - 1) * 30
    rows = await d.all(
        f"SELECT n.id, n.bale_id, u.first_name, n.external_id, n.case_number, n.branch, n.notice_type, "
        f"n.sent_date, n.status FROM notices n LEFT JOIN users u ON u.bale_id=n.bale_id {w} "
        f"ORDER BY n.id DESC LIMIT ? OFFSET ?", tuple(params + [limit, offset]))
    return {"total": total, "rows": _row_fa(rows, "sent_date")}


@app.get("/api/cases")
async def cases_list(request: Request, page: int = 1):
    require_auth(request)
    d = db()
    total = (await d.one("SELECT COUNT(*) c FROM tracked_cases"))["c"]
    limit, offset = 30, (max(1, page) - 1) * 30
    rows = await d.all(
        "SELECT t.bale_id, u.first_name, t.case_number, t.portal, t.last_change, t.last_checked, "
        "t.created_at FROM tracked_cases t LEFT JOIN users u ON u.bale_id=t.bale_id "
        "ORDER BY t.created_at DESC LIMIT ? OFFSET ?", (limit, offset))
    return {"total": total, "rows": _row_fa(rows, "last_checked", "created_at", "last_change")}


# ── پیام همگانی ────────────────────────────────────────────────────────────
class BroadcastIn(BaseModel):
    text: str
    target: str = "all"          # all | active | paid | free | beta


@app.post("/api/broadcast")
async def broadcast(body: BroadcastIn, request: Request):
    require_auth(request)
    if not body.text.strip():
        raise HTTPException(422, "متن پیام خالی است.")
    d = db()
    cond = {"all": "", "active": "JOIN subscriptions s ON s.bale_id=u.bale_id "
                                 "WHERE s.status IN ('FREE_ACTIVE','PAID_ACTIVE')",
            "paid": "JOIN subscriptions s ON s.bale_id=u.bale_id WHERE s.status='PAID_ACTIVE'",
            "free": "JOIN subscriptions s ON s.bale_id=u.bale_id WHERE s.status='FREE_ACTIVE'",
            "beta": "JOIN beta_allow b ON b.bale_id=u.bale_id"}
    join = cond.get(body.target, "")
    rows = await d.all(f"SELECT u.bale_id, u.chat_id, u.first_name FROM users u {join}")
    sent = failed = 0
    for r in rows:
        if not r["chat_id"]:
            failed += 1
            continue
        res = await send_message(r["chat_id"], body.text[:4000])
        if res and res.get("ok"):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)          # آهسته: نرخ ۲۰ پیام در ثانیه
    return {"ok": True, "sent": sent, "failed": failed, "total": len(rows)}


# ── فهرست بتا و تنظیمات ────────────────────────────────────────────────────
@app.get("/api/beta")
async def beta_list(request: Request):
    require_auth(request)
    rows = await db().all(
        "SELECT b.bale_id, u.first_name, u.created_at FROM beta_allow b "
        "LEFT JOIN users u ON u.bale_id=b.bale_id ORDER BY b.bale_id")
    return {"rows": _row_fa(rows, "created_at")}


class BetaIn(BaseModel):
    bale_id: int


@app.post("/api/beta")
async def beta_add(body: BetaIn, request: Request):
    require_auth(request)
    if body.bale_id <= 0:
        raise HTTPException(422, "آیدی عددی نامعتبر است.")
    await db().execute("INSERT OR IGNORE INTO beta_allow(bale_id) VALUES(?)", (body.bale_id,))
    return {"ok": True}


@app.delete("/api/beta/{bale_id}")
async def beta_del(bale_id: int, request: Request):
    require_auth(request)
    await db().execute("DELETE FROM beta_allow WHERE bale_id=?", (bale_id,))
    return {"ok": True}


@app.get("/api/settings")
async def settings_view(request: Request):
    require_auth(request)
    from legal_bot import config

    d = db()
    guide_ver = await d.get_setting("guide_version", "1")
    guide_file = await d.get_setting("guide_file_id", "")

    def mask(v, keep=4):
        v = str(v or "")
        return v if len(v) <= keep else v[:keep] + "•" * 8

    return {
        "card": {"number": mask(config.CARD_NUMBER, 6), "holder": config.CARD_HOLDER,
                 "bank": config.CARD_BANK, "brand": config.CARD_PAY_BRAND},
        "prices": {"turn": _toman(config.PRICE_TURN),
                   "base": _toman(config.PLAN_BASE_PRICE), "select": _toman(config.PLAN_SELECT_PRICE),
                   "pro_m": _toman(config.PLAN_PRO_MONTHLY), "pro_q": _toman(config.PLAN_PRO_QUARTERLY),
                   "expert_m": _toman(config.PLAN_EXPERT_MONTHLY),
                   "expert_q": _toman(config.PLAN_EXPERT_QUARTERLY),
                   "org_m": _toman(config.PLAN_ORG_MONTHLY),
                   "org_q": _toman(config.PLAN_ORG_QUARTERLY)},
        "limits": {"free_inquiries": config.FREE_INQUIRIES, "expire_hours": config.INVOICE_EXPIRE_HOURS,
                   "abuse_per_hour": config.ABUSE_MANUAL_PER_HOUR, "restrict_hours": config.RESTRICT_HOURS,
                   "org_daily_cap": config.PLAN_ORG_DAILY_CAP, "grace_days": config.SUB_GRACE_DAYS,
                   "max_concurrent_browsers": config.MAX_CONCURRENT_BROWSERS,
                   "min_free_ram": config.MIN_FREE_RAM_MB},
        "times": {"checks": config.CHECK_TIMES, "case_track": config.CASE_TRACK_TIME,
                  "reminder": config.REMINDER_TIME},
        "support": {"phone": config.SUPPORT_PHONE, "lavayeh_bot": config.LAVAYEH_BOT},
        "admin_free": config.ADMIN_FREE, "guide_version": guide_ver,
        "guide_file_set": bool(guide_file), "panel_port": settings.PORT,
    }


@app.exception_handler(HTTPException)
async def http_err(request, exc):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled(request, exc):            # هر خطای دیگر بدون لو رفتن توکن
    log.exception("unhandled: %s", type(exc).__name__)
    return JSONResponse({"detail": "خطای داخلی سرور پنل."}, status_code=500)
