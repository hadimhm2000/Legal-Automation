"""ربات دوم «اتوماسیون ویژه خدمات حقوقی» — تک‌پروسه: ربات + scheduler + مرورگر (Playwright).

اجرا:  python bot_main.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.memory import MemoryStorage

from legal_bot import config
from legal_bot.db import DB
from legal_bot.handlers import admin, cases, job_input, notices, payment, plans, start, turn
from legal_bot.handlers.common import BetaGate
from legal_bot.services import error_reporter, scheduler
from legal_bot.services.session import jobs, vault


class RedactFilter(logging.Filter):
    """توکن بله، کوکی و پارامترهای URL هرگز در لاگ نمی‌روند."""
    _pats = [(re.compile(r"bot\d+:[\w-]+"), "bot<TOKEN>"),
             (re.compile(r"(?i)(cookie|set-cookie|authorization)\s*[:=]\s*\S+"), r"\1=<hidden>"),
             (re.compile(r"(https?://[^\s?]+)\?\S+"), r"\1?<params>")]

    def filter(self, record):
        try:
            msg = vault.scrub(record.getMessage())
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = vault.scrub(record.exc_text).split("Call log")[0]
            for p, r in self._pats:
                msg = p.sub(r, msg)
            if config.LEGAL_BOT_TOKEN:
                msg = msg.replace(config.LEGAL_BOT_TOKEN, "<TOKEN>")
            record.msg, record.args = msg, None
        except Exception:
            pass
        return True


def setup_logging():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = [logging.StreamHandler(sys.stdout),
                RotatingFileHandler(os.path.join(config.LOG_DIR, "legal_bot.log"), maxBytes=5_000_000,
                                    backupCount=5, encoding="utf-8")]
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(RedactFilter())
        root.addHandler(h)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_dispatcher(db) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    gate = BetaGate()
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    # ترتیب مهم است: پاسخ‌های Job و مدیر اول، fallback آخر
    for r in (admin.router, job_input.router, payment.router, start.router, plans.router, notices.router,
              cases.router, turn.router, job_input.fallback):
        dp.include_router(r)

    @dp.errors()
    async def on_error(event):
        logging.getLogger("legal_bot").error("unhandled: %s", type(event.exception).__name__)
        upd = event.update
        uid = None
        for part in (upd.message, upd.callback_query):
            if part and part.from_user:
                uid = part.from_user.id
        await error_reporter.report(dp["bot"], db, run_id=None, user_id=uid, step="L01", category="UNKNOWN",
                                    message=f"handler error: {type(event.exception).__name__}: {str(event.exception)[:150]}")
        return True

    return dp


async def main():
    setup_logging()
    missing = config.missing_required()
    if missing:
        sys.exit("❌ متغیرهای محیطی لازم تنظیم نشده‌اند: " + ", ".join(missing))
    db = await DB().connect()
    # ری‌استارت: هر بررسی نیمه‌تمام لغو می‌شود (اطلاعات ورودی در RAM بوده و از بین رفته است)
    await db.execute("UPDATE check_runs SET status='cancelled', error_code='RESTART' WHERE status='running'")
    session = AiohttpSession(api=TelegramAPIServer.from_base(config.BALE_API_BASE))
    bot = Bot(config.LEGAL_BOT_TOKEN, session=session)
    dp = build_dispatcher(db)
    dp["bot"] = bot
    stop = asyncio.Event()
    sched = asyncio.create_task(scheduler.run(bot, db, stop))
    logging.info("legal bot started (API: %s)", config.BALE_API_BASE)
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        stop.set()
        await jobs.shutdown()
        sched.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
