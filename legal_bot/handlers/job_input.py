"""تحویل پاسخ‌های کاربر به Job فعال؛ حذف فوری پیام‌های حاوی اطلاعات ورود."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from .. import texts as T
from ..services.session import jobs
from ..utils import looks_like_secret
from .common import safe_answer

router = Router(name="job_input")


class JobWaitsText(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.text in T.MENU_TEXTS:
            return False
        j = jobs.get(message.from_user.id)
        return bool(j and j._expect and j._expect.accept_text)


@router.message(F.text, JobWaitsText())
async def deliver(message: Message):
    job = jobs.get(message.from_user.id)
    secret = job.waiting_secret()
    text = message.text
    if secret:
        try:
            await message.delete()
        except Exception:
            await message.answer(T.DELETE_FAILED)
    job.deliver_text(text)
    text = None


@router.callback_query(F.data.regexp(r"^j:[0-9a-f]+:\d+:\d+$"))
async def deliver_cb(cb: CallbackQuery):
    _, jid, seq, idx = cb.data.split(":")
    job = jobs.get(cb.from_user.id)
    if not job or job.id != jid or not job.deliver_callback(int(seq), int(idx)):
        await safe_answer(cb, "این دکمه دیگر معتبر نیست.")
        return
    await safe_answer(cb)


async def guard_secret_outside_flow(message: Message) -> bool:
    """پیام شبیه کدملی/رمز وقتی ربات منتظرش نیست ← حذف + هشدار."""
    if message.text and looks_like_secret(message.text):
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(T.SECRET_OUTSIDE_FLOW)
        return True
    return False


fallback = Router(name="fallback")


@fallback.message(F.text)
async def unknown_text(message: Message):
    if await guard_secret_outside_flow(message):
        return
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return
    from .. import keyboards as K

    await message.answer("لطفاً از منو انتخاب کنید.", reply_markup=K.main_menu())
