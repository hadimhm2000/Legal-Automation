from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..services import subscription as sub, turn
from ..services.flow import RunCtx, run_with_browser
from ..services.session import Job, JobCancelled, UserTimeout, jobs
from ..utils import to_fa_digits, validate_archive_number, validate_case_number
from .common import safe_answer, start_job
from .payment import show_invoice

router = Router(name="turn")


@router.message(F.text == T.M_TURN)
async def menu(message: Message, db):
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return
    inv = await sub.usable_turn_invoice(db, message.from_user.id)
    if inv:
        by, num = (inv["payload"] or "case:").split(":", 1)
        await message.answer(f"یک درخواست پرداخت‌شده‌ی استفاده‌نشده دارید ({to_fa_digits(num)}).",
                             reply_markup=K.inline([[("▶️ شروع ثبت نوبت با همین پرداخت", f"turn:go:{inv['code']}")],
                                                    [("➕ درخواست جدید", "turn:new")]]))
        return
    await _new(message, db)


@router.callback_query(F.data == "turn:new")
async def new_cb(cb: CallbackQuery, db):
    await safe_answer(cb)
    await _new(cb, db)


async def _new(m, db):
    async def coro(job: Job):
        try:
            by = await job.ask_choice(T.TURN_INTRO, [("case", T.TURN_BY_CASE), ("archive", T.TURN_BY_ARCHIVE)])
            if by == "case":
                num = await job.ask_text(T.ASK_CASE_NUMBER, validate_case_number)
            else:
                num = await job.ask_text(T.ASK_ARCHIVE, validate_archive_number)
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        inv = await sub.create_invoice(db, job.user_id, "turn", payload=f"{by}:{num}",
                                       is_admin=job.user_id == config.ADMIN_ID)
        await show_invoice(job.bot, job.chat_id, inv)

    start_job(m, db, "turn_prepare", coro)


@router.callback_query(F.data.startswith("turn:go:"))
async def go(cb: CallbackQuery, db):
    code = cb.data.split(":")[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=? AND kind='turn'", (code, cb.from_user.id))
    if not inv or inv["status"] != "approved":
        await safe_answer(cb, "این پرداخت قابل استفاده نیست (یا قبلاً استفاده شده).", alert=True)
        return
    if jobs.busy(cb.from_user.id):
        await safe_answer(cb, T.JOB_BUSY, alert=True)
        return
    await safe_answer(cb)
    by, num = inv["payload"].split(":", 1)

    async def coro(job: Job):
        ctx = RunCtx(job, db, "turn")

        async def w(ctx, br, login, page):
            await turn.work_turn(ctx, br, login, page, num, by)
            await db.execute("UPDATE invoices SET status='used' WHERE code=?", (code,))

        await run_with_browser(ctx, "turn", w)
        r = await db.one("SELECT status FROM invoices WHERE code=?", (code,))
        if r and r["status"] == "approved":
            await job.say("ℹ️ نوبت ثبت نشد؛ پرداخت شما محفوظ است و می‌توانید از «🗓 ثبت نوبت قضائی» دوباره امتحان کنید.")

    start_job(cb, db, "turn", coro)
