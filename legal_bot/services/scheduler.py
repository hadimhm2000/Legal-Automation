"""زمان‌بندی (ساعت تهران): پیام بررسی ابلاغیه ۸ و ۱۸ (فقط پلن‌های حرفه‌ای — پیگیری خودکار)،
بررسی روزانه‌ی پرونده‌ها ۸، یادآوری‌ها، هشدار تمدید / قفل / فاکتور منقضی.
هر کار در روز فقط یک بار (کلید در جدول settings)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from .. import config, keyboards as K
from ..db import parse_iso
from ..utils import fa_date, now_tehran, to_fa_digits
from . import reminders, subscription as sub

log = logging.getLogger(__name__)


async def _once(db, key: str) -> bool:
    if await db.get_setting(key):
        return False
    await db.set_setting(key, "1")
    return True


async def _active_users(db):
    return await db.all("SELECT u.bale_id, u.chat_id FROM users u JOIN subscriptions s ON s.bale_id=u.bale_id "
                        "WHERE s.status IN ('FREE_ACTIVE','PAID_ACTIVE')")


async def _auto_tracking_users(db):
    """پیگیری خودکار روزانه فقط برای پلن‌های حرفه‌ایِ فعال (پیشرو/تخصصی/سازمانی)."""
    out = []
    for u in await _active_users(db):
        if await sub.has_auto_tracking(db, u["bale_id"]):
            out.append(u)
    return out


def _gap(n: int) -> float:
    """فاصله‌ی بین پیام‌ها تا کل پیام‌ها در PROMPT_SPREAD_SEC پخش شوند (همه با هم مرورگر نخواهند)."""
    return (config.PROMPT_SPREAD_SEC / n) if n > 1 and config.PROMPT_SPREAD_SEC > 0 else 0.05


async def notices_prompt(bot, db, slot: str):
    targets = []
    for u in await _auto_tracking_users(db):
        if await db.is_beta(u["bale_id"]):
            targets.append(u)
    gap = _gap(len(targets))
    for i, u in enumerate(targets):
        if i:
            await asyncio.sleep(gap)
        try:
            await bot.send_message(u["chat_id"], "📩 زمان بررسی ابلاغیه‌ها است. در صورت نیاز درخواست بررسی را ثبت کنید.",
                                   reply_markup=K.inline([[("🔍 بررسی کن", f"chk:go:scheduled_{slot}"),
                                                          ("⏭ این نوبت نه", "chk:skip")]]))
        except Exception:
            pass


async def tracking_prompt(bot, db):
    targets = []
    for u in await _auto_tracking_users(db):
        n = len(await db.tracked(u["bale_id"]) or [])
        if n:
            targets.append((u, n))
    gap = _gap(len(targets))
    # نیم‌گام جابه‌جا تا با پیام‌های ابلاغیه‌ی همان ساعت ۸ هم‌زمان نشود
    await asyncio.sleep(gap / 2 if len(targets) > 1 else 0)
    for i, (u, n) in enumerate(targets):
        if i:
            await asyncio.sleep(gap)
        try:
            await bot.send_message(u["chat_id"], f"📂 بررسی روزانه‌ی {n} پرونده‌ی ثبت‌شده: برای ورود و بررسی آخرین "
                                   "تغییرات دکمه‌ی زیر را بزنید.",
                                   reply_markup=K.inline([[("🔍 بررسی کن", "trk:go:scheduled")]]))
        except Exception:
            pass


async def subscription_tick(bot, db):
    now = dt.datetime.now(dt.timezone.utc)
    for s in await db.all("SELECT * FROM subscriptions WHERE status IN ('FREE_ACTIVE','PAID_ACTIVE')"):
        u = await db.get_user(s["bale_id"])
        if not u:
            continue
        # ── قاعده ۸: هشدار تمدید چند روز قبل از پایان (فقط پلن‌های حرفه‌ای) ──
        end = parse_iso(s["paid_until"]) if s["status"] == "PAID_ACTIVE" else None
        left_h = (end - now).total_seconds() / 3600 if end else None
        tag = None
        if left_h is not None:
            if 0 < left_h <= 24:
                tag = "0d"
            elif 24 < left_h <= 48:
                tag = "1d"
            elif 72 < left_h <= 96:
                tag = "3d"
        if tag and s["last_reminder"] != f"{end.date()}:{tag}":
            await db.execute("UPDATE subscriptions SET last_reminder=? WHERE bale_id=?",
                             (f"{end.date()}:{tag}", s["bale_id"]))
            title = sub.plan_title(s["plan"])
            try:
                await bot.send_message(
                    u["chat_id"],
                    f"⏳ اشتراک «{title}» شما رو به پایان است (پایان: {fa_date(end.date())}).\n"
                    "برای تمدید، فاکتور جدید صادر کنید؛ روزهای باقی‌مانده از دست نمی‌رود و پرونده‌های ثبت‌شده "
                    f"تا {to_fa_digits(config.SUB_GRACE_DAYS)} روز بعد از انقضا نگه داشته می‌شوند.",
                    reply_markup=K.inline([[(f"🔁 تمدید {title}", f"plan:{s['plan']}")]]))
            except Exception:
                pass
        # ── قفل/تنزل خودکار + پیام ──
        s2 = await sub.refresh(db, s)
        if s2["status"] == "LOCKED" and s["status"] != "LOCKED":
            try:
                await bot.send_message(u["chat_id"],
                                       "🔒 دوره‌ی شما تمام شد و سرویس قفل شد. برای ادامه، یکی از پلن‌ها را فعال کنید:",
                                       reply_markup=K.plans_kb())
            except Exception:
                pass
        elif s2["status"] == "PAID_ACTIVE" and not s2["plan"] and s["plan"]:
            try:
                await bot.send_message(
                    u["chat_id"],
                    "ℹ️ دوره‌ی اشتراک حرفه‌ای شما پایان یافت. اعتبار استعلام باقی‌مانده‌ی شما همچنان قابل "
                    "استفاده است؛ برای پیگیری خودکار روزانه، دوباره یکی از پلن‌های حرفه‌ای را فعال کنید.",
                    reply_markup=K.plans_kb())
            except Exception:
                pass
    # فاکتورهای منقضی
    await db.execute("UPDATE invoices SET status='expired' WHERE status IN ('pending','shortfall_wait') "
                     "AND expires_at<?", (now.isoformat(),))
    # قاعده ۸: پاک‌سازی داده‌های کاربران قفل‌شده چند روز بعد از انقضا (نه ۳۰ روز)
    cutoff = (now - dt.timedelta(days=config.SUB_GRACE_DAYS)).isoformat()
    for s in await db.all("SELECT bale_id FROM subscriptions WHERE status='LOCKED' AND locked_at<?", (cutoff,)):
        await db.wipe_user_data(s["bale_id"])


_tasks: set = set()


def _background(coro, name):
    """پیام‌های پخش‌شده در پس‌زمینه می‌روند تا حلقه‌ی زمان‌بندی (یادآوری‌ها، اشتراک) معطل نشود."""
    async def safe():
        try:
            await coro
        except Exception:
            log.exception("%s failed", name)
    t = asyncio.create_task(safe(), name=name)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def run(bot, db, stop: asyncio.Event):
    while not stop.is_set():
        try:
            now = now_tehran()
            hm, day = now.strftime("%H:%M"), now.date().isoformat()
            for t in config.CHECK_TIMES:
                if hm >= t and now.hour - int(t[:2]) < 1 and await _once(db, f"sched:notices:{day}:{t}"):
                    _background(notices_prompt(bot, db, t[:2]), f"notices-{t}")
            t = config.CASE_TRACK_TIME
            if hm >= t and now.hour - int(t[:2]) < 1 and await _once(db, f"sched:track:{day}"):
                _background(tracking_prompt(bot, db), "tracking")
            t = config.REMINDER_TIME
            if hm >= t and await _once(db, f"sched:rem:{day}"):
                await reminders.daily_tick(bot, db, now.date())
                await db.execute("DELETE FROM settings WHERE key LIKE 'sched:%' AND key NOT LIKE ?", (f"%{day}%",))
            if await _once(db, f"sched:sub:{day}:{now.hour}"):
                await subscription_tick(bot, db)
        except Exception:
            log.exception("scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass
