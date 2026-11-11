from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import now_iso
from ..handoff import verify_token
from ..services import subscription as sub
from ..services.session import jobs
from .common import safe_answer, send_guide, show_main, show_plans

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, db):
    uid = message.from_user.id
    if message.chat.type != "private":
        return
    if not await db.is_beta(uid):
        await message.answer(T.COMING_SOON)
        return
    token = (command.args or "").strip()
    known = await db.get_user(uid)
    if config.REQUIRE_HANDOFF and not known and not verify_token(token, config.HANDOFF_SECRET, uid,
                                                                    config.HANDOFF_TTL_SEC):
        await message.answer(T.RELOGIN_FROM_MAIN)
        return
    await db.upsert_user(uid, message.chat.id, message.from_user.first_name or "")
    user = await db.get_user(uid)
    if not user.get("guide_ack_at"):
        await message.answer("👋 به ربات «اتوماسیون ویژه خدمات حقوقی» خوش آمدید.", reply_markup=K.main_menu())
        await send_guide(message.bot, db, message.chat.id)
        return
    await show_main(message, text="👋 خوش برگشتید.")


@router.callback_query(F.data == "guide:ack")
async def guide_ack(cb: CallbackQuery, db):
    await db.execute("UPDATE users SET guide_ack_at=?, guide_version=guide_version+1 WHERE bale_id=?",
                     (now_iso(), cb.from_user.id))
    await safe_answer(cb, "✅")
    s = await sub.get(db, cb.from_user.id)
    if s["status"] in sub.ACTIVE:
        await show_main(cb.message.chat.id, cb.bot)
    else:
        await show_plans(cb.bot, cb.message.chat.id)


@router.callback_query(F.data == "nav:main")
async def nav_main(cb: CallbackQuery):
    await safe_answer(cb)
    await show_main(cb.message.chat.id, cb.bot)


@router.message(F.text == T.M_GUIDE)
async def guide(message: Message, db):
    await send_guide(message.bot, db, message.chat.id)


@router.message(F.text.in_({T.M_CANCEL, T.M_CANCEL_OLD}))
async def cancel(message: Message):
    if jobs.cancel(message.from_user.id):
        # منوی اصلی را پایان‌کارِ Job به‌طور خودکار می‌فرستد
        await message.answer(T.CANCELLED)
    else:
        await message.answer("عملیات فعالی ندارید.", reply_markup=K.main_menu())


@router.message(F.text.in_({T.BACK, T.BACK_OLD}))
async def back(message: Message):
    if jobs.busy(message.from_user.id) and jobs.cancel(message.from_user.id):
        # حین فرایند، «بازگشت به منوی اصلی» یعنی لغو همین فرایند
        # منوی اصلی را پایان‌کارِ Job به‌طور خودکار می‌فرستد
        await message.answer(T.CANCELLED)
        return
    await show_main(message)


@router.message(F.text == T.M_WIPE)
async def wipe_ask(message: Message):
    await message.answer("همه‌ی ابلاغیه‌های ذخیره‌شده، یادآوری‌ها و پرونده‌های ثبت‌شده برای بررسی روزانه حذف شوند؟\n"
                         "(اطلاعات ورود شما اصلاً ذخیره نمی‌شود که نیاز به حذف داشته باشد.)",
                         reply_markup=K.inline([[("🗑 بله، حذف کن", "wipe:yes"), (T.BACK, "nav:main")]]))


@router.callback_query(F.data == "wipe:yes")
async def wipe_do(cb: CallbackQuery, db):
    await db.wipe_user_data(cb.from_user.id)
    await safe_answer(cb, "حذف شد")
    await cb.message.edit_text("✅ داده‌های شما حذف شد.")
