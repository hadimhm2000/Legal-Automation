"""دیتابیس SQLite (WAL) — بدون هیچ ستونی برای کدملی، رمز شخصی، رمز موقت، کوکی یا نشست ثنا.

قاعده (بخش ۲ و ۷ سند): اگر روزی ستونی با نامی شبیه password/otp/national/cookie
اضافه شود، تست tests/test_security.py شکست می‌خورد.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
import string

import aiosqlite

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    bale_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    first_name TEXT,
    guide_ack_at TEXT,
    guide_version INTEGER DEFAULT 0,
    terms_ack_at TEXT,
    terms_version INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS subscriptions (
    bale_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'NEW',
    notices INTEGER NOT NULL DEFAULT 0,
    case_alerts INTEGER NOT NULL DEFAULT 0,
    trial_started_at TEXT,
    trial_ends_at TEXT,
    paid_until TEXT,
    locked_at TEXT,
    last_reminder TEXT,
    -- ── مدل پلن‌های جدید (آبان ۱۴۰۵) ──
    plan TEXT,                       -- free | base | select | pro | expert | org | NULL(فقط اعتبار)
    cycle TEXT,                      -- monthly | quarterly | NULL
    inquiries_left INTEGER DEFAULT 0,  -- اعتبار استعلام (شروع رایگان/پلن‌های شخصی؛ اول از این کم می‌شود)
    quota_month TEXT,                -- ماه شمسی مالک سهمیه ماهانه (YYYY-MM)
    quota_used INTEGER DEFAULT 0,    -- استعلام‌های مصرف‌شده این ماه
    quota_total INTEGER DEFAULT 0,   -- سهمیه ماهانه (۰ = نامحدود/سازمانی)
    phone TEXT,
    phone_verified_at TEXT,
    free_used INTEGER DEFAULT 0,     -- شروع رایگان فقط یک‌بار برای هر حساب/شماره
    restricted_until TEXT,           -- قاعده ۶: محدودیت موقت
    restriction_reason TEXT,
    rules_ack_at TEXT,
    rules_version INTEGER DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS trial_usage (
    bale_id INTEGER PRIMARY KEY,
    started_at TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE,
    bale_id INTEGER,
    kind TEXT,             -- new | upgrade | renewal | turn
    notices INTEGER DEFAULT 0,
    case_alerts INTEGER DEFAULT 0,
    amount_toman INTEGER,
    status TEXT,           -- pending | receipt_sent | shortfall_wait | approved | rejected | expired | used
    payload TEXT,          -- فقط برای turn: شماره پرونده/بایگانی (بدون اطلاعات ورود)
    created_at TEXT,
    expires_at TEXT,
    receipt_file_id TEXT,
    receipt_file_unique_id TEXT,
    reviewed_by INTEGER,
    reviewed_at TEXT,
    reject_reason TEXT,
    -- ── کارت‌به‌کارت (مثل ربات اصلی) ──
    plan TEXT,
    cycle TEXT,
    shortfall_toman INTEGER,                 -- کسری اعلام‌شده توسط مدیر
    shortfall_receipt_file_id TEXT,
    shortfall_receipt_file_unique_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_receipt ON invoices(receipt_file_unique_id)
    WHERE receipt_file_unique_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS plan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bale_id INTEGER,
    event TEXT,            -- free_start | plan_activated | plan_upgraded | inquiry_used | quota_reset |
                           -- restricted | violation_reported | renewed | degraded | locked
    plan TEXT,
    detail TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bale_id INTEGER,
    kind TEXT,             -- notices_new | notices_case | notices_range | case_list | case_detail | case_track | turn
    trigger TEXT,          -- scheduled_08 | scheduled_18 | manual
    status TEXT,
    step TEXT,
    steps_ok TEXT DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    new_items INTEGER DEFAULT 0,
    error_code TEXT
);
CREATE TABLE IF NOT EXISTS run_items (      -- شماره ابلاغیه‌ها پیش از شروع (شناسه‌ی یکتا برای ادامه)
    run_id INTEGER,
    external_id TEXT,
    status TEXT DEFAULT 'pending',          -- pending | done | failed
    PRIMARY KEY(run_id, external_id)
);
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bale_id INTEGER,
    external_id TEXT,      -- شماره ابلاغیه
    case_number TEXT,
    archive_number TEXT,
    branch TEXT,
    notice_type TEXT,
    issue_date TEXT,       -- تاریخ تنظیم (میلادی ISO)
    sent_date TEXT,
    hearing_date TEXT,
    hearing_time TEXT,
    deadline_days INTEGER,
    status TEXT DEFAULT 'open',   -- open | done
    created_at TEXT,
    UNIQUE(bale_id, external_id)
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bale_id INTEGER,
    notice_id INTEGER,
    kind TEXT,             -- hearing | deadline | custom
    case_number TEXT,
    archive_number TEXT,
    branch TEXT,
    external_id TEXT,
    start_date TEXT,
    due_date TEXT,
    due_time TEXT,
    note TEXT,
    status TEXT DEFAULT 'open',   -- open | done | expired
    last_sent TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tracked_cases (
    bale_id INTEGER,
    case_number TEXT,
    portal TEXT DEFAULT 'person',  -- person | lawyer
    last_change TEXT,
    line_hashes TEXT,
    last_checked TEXT,
    created_at TEXT,
    PRIMARY KEY(bale_id, case_number)
);
CREATE TABLE IF NOT EXISTS error_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    bale_id INTEGER,
    step TEXT,
    category TEXT,
    message TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS beta_allow (bale_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_iso(s):
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def new_code(prefix="INV") -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(5))


_SUB_COLS = {
    "plan": "TEXT", "cycle": "TEXT", "inquiries_left": "INTEGER DEFAULT 0",
    "quota_month": "TEXT", "quota_used": "INTEGER DEFAULT 0", "quota_total": "INTEGER DEFAULT 0",
    "phone": "TEXT", "phone_verified_at": "TEXT", "free_used": "INTEGER DEFAULT 0",
    "restricted_until": "TEXT", "restriction_reason": "TEXT",
    "rules_ack_at": "TEXT", "rules_version": "INTEGER DEFAULT 0",
}
_INV_COLS = {
    "plan": "TEXT", "cycle": "TEXT", "shortfall_toman": "INTEGER",
    "shortfall_receipt_file_id": "TEXT", "shortfall_receipt_file_unique_id": "TEXT",
}


async def _migrate(conn) -> None:
    """افزودن ستون‌های مدل پلن جدید به دیتابیس‌های قدیمی + انتقال داده‌ی اولیه."""
    for table, cols in (("subscriptions", _SUB_COLS), ("invoices", _INV_COLS)):
        cur = await conn.execute(f"PRAGMA table_info({table})")
        have = {r[1] for r in await cur.fetchall()}
        for col, decl in cols.items():
            if col not in have:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    # ایندکس رسیدِ کسری بعد از افزودن ستون‌ها ساخته می‌شود (روی دیتابیس قدیمی ستون وجود ندارد)
    await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_receipt2 ON invoices(shortfall_receipt_file_unique_id) "
                       "WHERE shortfall_receipt_file_unique_id IS NOT NULL")
    # مدل قدیمی → مدل جدید:
    #   تست ۳ روزه → شروع رایگان (۲ استعلام، یک‌بار مصرف)
    #   پولی قدیمی (notices/case_alerts) → پلن پیشرو تا پایان دوره‌ی فعلی
    from .utils import now_tehran

    cur_month = f"{now_tehran().year:04d}-{now_tehran().month:02d}"
    await conn.execute(
        "UPDATE subscriptions SET status='FREE_ACTIVE', plan='free', free_used=1, "
        "inquiries_left=? WHERE status='TRIAL_ACTIVE'", (config.FREE_INQUIRIES,))
    await conn.execute(
        "UPDATE subscriptions SET plan='pro', cycle='monthly', quota_total=?, quota_month=?, quota_used=0 "
        "WHERE status='PAID_ACTIVE' AND paid_until IS NOT NULL AND plan IS NULL",
        (config.PLAN_PRO_QUOTA, cur_month))
    await conn.commit()


class DB:
    def __init__(self, path: str | None = None):
        self.path = path or config.DB_PATH
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        if self.path != ":memory:":
            import os

            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await _migrate(self.conn)
        await self.conn.commit()
        return self

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def execute(self, sql, params=()):
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    async def one(self, sql, params=()):
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def all(self, sql, params=()):
        cur = await self.conn.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

    # ── settings ──
    async def get_setting(self, key, default=None):
        r = await self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    async def set_setting(self, key, value):
        await self.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    # ── users ──
    async def upsert_user(self, bale_id, chat_id, first_name=""):
        await self.execute(
            "INSERT INTO users(bale_id,chat_id,first_name,created_at) VALUES(?,?,?,?) "
            "ON CONFLICT(bale_id) DO UPDATE SET chat_id=excluded.chat_id, first_name=excluded.first_name",
            (bale_id, chat_id, first_name, now_iso()))
        await self.execute("INSERT OR IGNORE INTO subscriptions(bale_id,status,updated_at) VALUES(?,?,?)",
                           (bale_id, "NEW", now_iso()))

    async def get_user(self, bale_id):
        return await self.one("SELECT * FROM users WHERE bale_id=?", (bale_id,))

    async def is_beta(self, bale_id) -> bool:
        if bale_id in config.BETA_IDS:
            return True
        return bool(await self.one("SELECT 1 FROM beta_allow WHERE bale_id=?", (bale_id,)))

    # ── runs ──
    async def create_run(self, bale_id, kind, trigger="manual"):
        cur = await self.execute(
            "INSERT INTO check_runs(bale_id,kind,trigger,status,step,started_at) VALUES(?,?,?,?,?,?)",
            (bale_id, kind, trigger, "running", "L01", now_iso()))
        return cur.lastrowid

    async def run_step(self, run_id, step, ok_prev=True):
        r = await self.one("SELECT step, steps_ok FROM check_runs WHERE id=?", (run_id,))
        if not r:
            return
        ok = r["steps_ok"] or ""
        if ok_prev and r["step"] and r["step"] != step and r["step"] not in ok.split(","):
            ok = ",".join([x for x in ok.split(",") if x] + [r["step"]])
        await self.execute("UPDATE check_runs SET step=?, steps_ok=? WHERE id=?", (step, ok, run_id))

    async def finish_run(self, run_id, status, error_code=None, new_items=0):
        await self.execute("UPDATE check_runs SET status=?, error_code=?, new_items=?, finished_at=? WHERE id=?",
                           (status, error_code, new_items, now_iso(), run_id))

    async def runs_today(self, bale_id) -> int:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        r = await self.one("SELECT COUNT(*) c FROM check_runs WHERE bale_id=? AND started_at>=? "
                           "AND kind LIKE 'notices%'", (bale_id, since))
        return r["c"] if r else 0

    async def manual_done_since(self, bale_id, hours: float, kinds: tuple[str, ...]) -> int:
        """استعلام‌های دستیِ موفق در `hours` ساعت اخیر (برای سقف روزانه/مصرف غیرعادی)."""
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
        qs = ",".join("?" for _ in kinds)
        r = await self.one(
            f"SELECT COUNT(*) c FROM check_runs WHERE bale_id=? AND started_at>=? AND trigger='manual' "
            f"AND status='done' AND kind IN ({qs})", (bale_id, since, *kinds))
        return r["c"] if r else 0

    async def add_plan_event(self, bale_id, event, plan=None, detail=""):
        await self.execute("INSERT INTO plan_events(bale_id,event,plan,detail,created_at) VALUES(?,?,?,?,?)",
                           (bale_id, event, plan, (detail or "")[:500], now_iso()))

    async def add_run_items(self, run_id, ids):
        for x in ids:
            await self.conn.execute("INSERT OR IGNORE INTO run_items(run_id,external_id) VALUES(?,?)", (run_id, x))
        await self.conn.commit()

    async def set_run_item(self, run_id, ext, status):
        await self.execute("UPDATE run_items SET status=? WHERE run_id=? AND external_id=?", (status, run_id, ext))

    # ── notices ──
    async def notice_exists(self, bale_id, ext) -> bool:
        return bool(await self.one("SELECT 1 FROM notices WHERE bale_id=? AND external_id=?", (bale_id, ext)))

    async def save_notice(self, bale_id, info: dict) -> int:
        await self.execute(
            "INSERT INTO notices(bale_id,external_id,case_number,archive_number,branch,notice_type,issue_date,"
            "sent_date,hearing_date,hearing_time,deadline_days,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(bale_id,external_id) DO UPDATE SET case_number=excluded.case_number, "
            "archive_number=excluded.archive_number, branch=excluded.branch, notice_type=excluded.notice_type, "
            "hearing_date=excluded.hearing_date, hearing_time=excluded.hearing_time, "
            "deadline_days=excluded.deadline_days",
            (bale_id, info.get("notice_number"), info.get("case_number"), info.get("archive_number"),
             info.get("branch"), info.get("notice_type"), _d(info.get("issue_date")), _d(info.get("sent_date")),
             _d(info.get("hearing_date")), info.get("hearing_time"), info.get("deadline_days"), now_iso()))
        r = await self.one("SELECT id FROM notices WHERE bale_id=? AND external_id=?",
                           (bale_id, info.get("notice_number")))
        return r["id"]

    # ── reminders ──
    async def add_reminder(self, bale_id, kind, due_date, *, notice_id=None, due_time=None, note=None,
                           case_number=None, archive_number=None, branch=None, external_id=None,
                           start_date=None):
        if notice_id:
            dup = await self.one("SELECT id FROM reminders WHERE notice_id=? AND kind=? AND due_date=?",
                                 (notice_id, kind, _d(due_date)))
            if dup:
                return dup["id"]
        cur = await self.execute(
            "INSERT INTO reminders(bale_id,notice_id,kind,case_number,archive_number,branch,external_id,"
            "start_date,due_date,due_time,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (bale_id, notice_id, kind, case_number, archive_number, branch, external_id,
             _d(start_date), _d(due_date), due_time, note, now_iso()))
        return cur.lastrowid

    async def open_reminders(self):
        return await self.all("SELECT * FROM reminders WHERE status='open'")

    async def close_reminder(self, rid, bale_id, status="done"):
        r = await self.one("SELECT * FROM reminders WHERE id=? AND bale_id=?", (rid, bale_id))
        if not r:
            return None
        await self.execute("UPDATE reminders SET status=? WHERE id=?", (status, rid))
        if status == "done" and r.get("notice_id"):
            await self.execute("UPDATE reminders SET status='done' WHERE notice_id=? AND bale_id=?",
                               (r["notice_id"], bale_id))
            await self.execute("UPDATE notices SET status='done' WHERE id=?", (r["notice_id"],))
        return r

    # ── tracked cases ──
    async def track_case(self, bale_id, case_number, portal):
        await self.execute("INSERT INTO tracked_cases(bale_id,case_number,portal,created_at) VALUES(?,?,?,?) "
                           "ON CONFLICT(bale_id,case_number) DO UPDATE SET portal=excluded.portal",
                           (bale_id, case_number, portal, now_iso()))

    async def tracked(self, bale_id):
        return await self.all("SELECT * FROM tracked_cases WHERE bale_id=? ORDER BY created_at", (bale_id,))

    async def update_tracked(self, bale_id, case_number, last_change, line_hashes):
        await self.execute("UPDATE tracked_cases SET last_change=?, line_hashes=?, last_checked=? "
                           "WHERE bale_id=? AND case_number=?",
                           (last_change, json.dumps(sorted(line_hashes)), now_iso(), bale_id, case_number))

    # ── errors ──
    async def add_error(self, run_id, bale_id, step, category, message):
        await self.execute("INSERT INTO error_events(run_id,bale_id,step,category,message,created_at) "
                           "VALUES(?,?,?,?,?,?)", (run_id, bale_id, step, category, message[:500], now_iso()))

    async def wipe_user_data(self, bale_id):
        for t in ("notices", "reminders", "tracked_cases"):
            await self.execute(f"DELETE FROM {t} WHERE bale_id=?", (bale_id,))


def _d(v):
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)
