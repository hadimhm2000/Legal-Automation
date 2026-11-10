"""زمان‌بندی (ساعت تهران): پیام بررسی ابلاغیه ۸ و ۱۸، بررسی روزانه‌ی پرونده‌ها ۸، یادآوری‌ها،
یادآوری پایان تست / قفل / فاکتور تمدید. هر کار در روز فقط یک بار (کلید در جدول settings)."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from .. import config, keyboards as K
from ..db import parse_iso
from ..utils import now_tehran
from . import reminders, subscription as sub

log = logging.getLogger(__name__)


async def _once(db, key: str) -> bool:
    if await db.get_setting(key):
        return False
    await db.set_setting(key, "1")
    return True


async def _active_users(db):
    return await db.all("SELECT u.bale_id, u.chat_id FROM users u JOIN subscriptions s ON s.bale_id=u.bale_id "
                        "WHERE s.status IN ('TRIAL_ACTIVE','PAID_ACTIVE')")


async def notices_prompt(bot, db, slot: str):
    for u in await _active_users(db):
        if not await db.is_beta(u["bale_id"]) or not await sub.has_service(db, u["bale_id"], "notices"):
            continue
        try:
            await bot.send_message(u["chat_id"], "📩 زمان بررسی ابلاغیه‌ها است. در صورت نیاز درخواست بررسی را ثبت کنید.",
                                   reply_markup=K.inline([[("🔍 بررسی کن", f"chk:go:scheduled_{slot}"),
                                                          ("⏭ این نوبت نه", "chk:skip")]]))
        except Exception:
            pass


async def tracking_prompt(bot, db):
    for u in await _active_users(db):
        if not await sub.has_service(db, u["bale_id"], "case_alerts") or not await db.tracked(u["bale_id"]):
            continue
        try:
            n = len(await db.tracked(u["bale_id"]))
            await bot.send_message(u["chat_id"], f"📂 بررسی روزانه‌ی {n} پرونده‌ی ثبت‌شده: برای ورود و بررسی آخرین "
                                   "تغییرات دکمه‌ی زیر را بزنید.",
                                   reply_markup=K.inline([[("🔍 بررسی کن", "trk:go:scheduled")]]))
        except Exception:
            pass


async def subscription_tick(bot, db):
    now = dt.datetime.now(dt.timezone.utc)
    for s in await db.all("SELECT * FROM subscriptions WHERE status IN ('TRIAL_ACTIVE','PAID_ACTIVE')"):
        u = await db.get_user(s["bale_id"])
        if not u:
            continue
        end = parse_iso(s["trial_ends_at"] if s["status"] == "TRIAL_ACTIVE" else s["paid_until"])
        if not end:
            continue
        left_h = (end - now).total_seconds() / 3600
        tag = None
        if s["status"] == "TRIAL_ACTIVE":
            tag = "24h" if 6 < left_h <= 24 else ("6h" if 0 < left_h <= 6 else None)
        else:
            if 0 < left_h <= 24:
                tag = "0d"
            elif 24 < left_h <= 48:
                tag = "1d"
            elif 72 < left_h <= 96:
                tag = "3d"
        if tag and s["last_reminder"] != f"{end.date()}:{tag}":
            await db.execute("UPDATE subscriptions SET last_reminder=? WHERE bale_id=?",
                             (f"{end.date()}:{tag}", s["bale_id"]))
            if s["status"] == "TRIAL_ACTIVE":
                text = "⏳ تست رایگان شما رو به پایان است. برای ادامه، یکی از سرویس‌ها را فعال کنید."
                kb = K.plans_kb()
            else:
                text = "⏳ اشتراک شما رو به پایان است؛ برای تمدید فاکتور جدید صادر کنید (روزهای باقی‌مانده از دست نمی‌رود)."
                kb = K.inline([[("🔁 تمدید یک‌ماهه", "inv:renew:0")]])
            try:
                await bot.send_message(u["chat_id"], text, reply_markup=kb)
            except Exception:
                pass
        if left_h <= 0:
            await sub.refresh(db, s)
            try:
                await bot.send_message(u["chat_id"], "🔒 دوره‌ی شما تمام شد و سرویس قفل شد. کدام مورد را فعال کنیم؟",
                                       reply_markup=K.plans_kb())
            except Exception:
                pass
    # فاکتورهای منقضی
    await db.execute("UPDATE invoices SET status='expired' WHERE status='pending' AND expires_at<?", (now.isoformat(),))
    # پاک‌سازی داده‌های کاربران قفل‌شده بعد از ۳۰ روز
    cutoff = (now - dt.timedelta(days=30)).isoformat()
    for s in await db.all("SELECT bale_id FROM subscriptions WHERE status='LOCKED' AND locked_at<?", (cutoff,)):
        await db.wipe_user_data(s["bale_id"])


async def run(bot, db, stop: asyncio.Event):
    while not stop.is_set():
        try:
            now = now_tehran()
            hm, day = now.strftime("%H:%M"), now.date().isoformat()
            for t in config.CHECK_TIMES:
                if hm >= t and now.hour - int(t[:2]) < 1 and await _once(db, f"sched:notices:{day}:{t}"):
                    await notices_prompt(bot, db, t[:2])
            t = config.CASE_TRACK_TIME
            if hm >= t and now.hour - int(t[:2]) < 1 and await _once(db, f"sched:track:{day}"):
                await tracking_prompt(bot, db)
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
