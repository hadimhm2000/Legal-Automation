from __future__ import annotations

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, FSInputFile, Message

from .. import config, keyboards as K, texts as T
from ..db import now_iso
from ..services import subscription as sub
from ..services.flow import RunCtx, run_with_browser
from ..services.session import Job, jobs


class BetaGate(BaseMiddleware):
    """فقط کاربران فهرست بتا (فعلاً فقط مدیر) — /start جداگانه بررسی می‌شود."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        db = data["db"]
        if user is None:
            return
        chat = event.chat if isinstance(event, Message) else (event.message.chat if event.message else None)
        if chat is not None and chat.type != "private":
            return
        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)
        if user.id == config.ADMIN_ID:
            return await handler(event, data)
        if not await db.is_beta(user.id) or not await db.get_user(user.id):
            if isinstance(event, Message):
                await event.answer(T.COMING_SOON if not await db.is_beta(user.id) else T.RELOGIN_FROM_MAIN)
            else:
                await event.answer(T.COMING_SOON, show_alert=True)
            return
        return await handler(event, data)


async def send_guide(bot: Bot, db, chat_id: int):
    fid = await db.get_setting("guide_file_id")
    doc = fid or FSInputFile(config.GUIDE_PDF_PATH, filename="rahnama.pdf")
    msg = await bot.send_document(chat_id, doc, caption=T.GUIDE_CAPTION, reply_markup=K.guide_kb())
    if not fid and msg.document:
        await db.set_setting("guide_file_id", msg.document.file_id)


async def show_main(message_or_chat, bot: Bot | None = None, text="منوی اصلی:"):
    if isinstance(message_or_chat, Message):
        await message_or_chat.answer(text, reply_markup=K.main_menu())
    else:
        await bot.send_message(message_or_chat, text, reply_markup=K.main_menu())


async def show_plans(bot: Bot, chat_id: int, prefix=""):
    await bot.send_message(chat_id, (prefix + "\n\n" if prefix else "") + T.PLAN_PROMPT, reply_markup=K.plans_kb())


async def require_service(message: Message, db, service: str) -> bool:
    if await sub.has_service(db, message.from_user.id, service):
        return True
    s = await sub.get(db, message.from_user.id)
    why = "🔒 اشتراک شما قفل است." if s["status"] == "LOCKED" else "این سرویس برای شما فعال نیست."
    await show_plans(message.bot, message.chat.id, why)
    return False


def start_job(message_or_cb, db, kind: str, coro) -> bool:
    """coro(job) را به‌عنوان تنها کار فعال کاربر اجرا می‌کند."""
    u = message_or_cb.from_user
    chat_id = message_or_cb.chat.id if isinstance(message_or_cb, Message) else message_or_cb.message.chat.id
    job = Job(bot=message_or_cb.bot, user_id=u.id, chat_id=chat_id, kind=kind)
    return jobs.start(job, coro)


def browser_job(db, kind, target, work, *, pre=None, trigger="manual", consent=True):
    """کارخانه‌ی coroutine: (اختیاری) پرسش‌های پیش از ورود ← run_with_browser."""

    async def coro(job: Job):
        args = {}
        if pre:
            from ..services.session import JobCancelled, UserTimeout

            try:
                args = await pre(job) or {}
            except JobCancelled:
                await job.say(T.CANCELLED)
                return
            except UserTimeout:
                await job.say(T.USER_TIMEOUT)
                return
        ctx = RunCtx(job, db, kind, trigger)

        async def w(ctx, br, login, page):
            return await work(ctx, br, login, page, **args)

        await run_with_browser(ctx, target, w, consent=consent)

    return coro


async def ack_terms_needed(db, uid) -> bool:
    u = await db.get_user(uid)
    return not (u and u.get("terms_ack_at"))


async def set_terms(db, uid):
    await db.execute("UPDATE users SET terms_ack_at=?, terms_version=1 WHERE bale_id=?", (now_iso(), uid))


async def safe_answer(cb: CallbackQuery, text: str | None = None, alert=False):
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:
        pass
