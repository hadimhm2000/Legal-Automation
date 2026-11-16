from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..services import subscription as sub, turn
from ..services.flow import RunCtx, run_with_browser
from ..services.session import Job, JobCancelled, UserTimeout, jobs
from ..utils import (to_en_digits, to_fa_digits, validate_archive_number, validate_case_number)
from .common import safe_answer, start_job
from .payment import show_invoice

router = Router(name="turn")


def _multi_numbers_validator(by: str):
    """اعتبارسنجی فهرست شماره‌ها برای «ثبت چند نوبت» — خروجی: فهرستِ تمیزشده."""

    def validate(v: str):
        parts = [p.strip() for p in re.split(r"[،,\n;]+", to_en_digits(v or "")) if p.strip()]
        if not parts:
            return None, "حداقل یک شماره بفرستید."
        if len(parts) > config.TURN_MAX_MULTI:
            return None, (f"حداکثر {to_fa_digits(config.TURN_MAX_MULTI)} شماره در هر درخواست؛ "
                          f"شما {to_fa_digits(len(parts))} شماره فرستادید.")
        validator = validate_case_number if by == "case" else validate_archive_number
        bad, out = [], []
        for p in parts:
            val, err = validator(p)
            if err:
                bad.append(p)
            elif val not in out:
                out.append(val)
        if bad:
            return None, "این شماره‌ها معتبر نیستند: " + "، ".join(to_fa_digits(b) for b in bad)
        if not out:
            return None, "شماره‌ی معتبری پیدا نشد؛ دوباره بفرستید."
        return out, None

    return validate


@router.message(F.text == T.M_TURN)
async def menu(message: Message, db):
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return
    inv = await sub.usable_turn_invoice(db, message.from_user.id)
    if inv:
        nums = (inv["payload"] or "case:").split(":", 1)[1]
        n = len([x for x in nums.split(",") if x.strip()])
        await message.answer(f"یک درخواست پرداخت‌شده‌ی استفاده‌نشده دارید "
                             f"({to_fa_digits(n)} نوبت: {to_fa_digits(nums)}).",
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
            # تکی / چند نوبت (دستور کارفرما — آبان ۱۴۰۵): چند نوبت = همان روندِ
            # ضبط steps برای هر شماره، پشت سر هم در همان نشست.
            mode = await job.ask_choice(T.TURN_MODE, [("single", T.TURN_MODE_SINGLE),
                                                      ("multi", T.TURN_MODE_MULTI)])
            if mode == "multi":
                numbers = await job.ask_text(
                    T.TURN_MULTI_ASK.format(max=to_fa_digits(config.TURN_MAX_MULTI)),
                    _multi_numbers_validator(by))
            elif by == "case":
                numbers = [await job.ask_text(T.ASK_CASE_NUMBER, validate_case_number)]
            else:
                numbers = [await job.ask_text(T.ASK_ARCHIVE, validate_archive_number)]
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        # چند نوبت = قیمت هر نوبت × تعداد (فاکتور کارت‌به‌کارت)
        inv = await sub.create_invoice(db, job.user_id, "turn", payload=f"{by}:{','.join(numbers)}",
                                       amount=config.PRICE_TURN * len(numbers),
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
    by, nums = (inv["payload"] or "case:").split(":", 1)
    numbers = [n.strip() for n in nums.split(",") if n.strip()]

    async def coro(job: Job):
        ctx = RunCtx(job, db, "turn")

        async def on_booked(_number: str):
            # به‌محض اولین ثبتِ موفق فاکتور «استفاده‌شده» می‌شود تا با دکمه‌ی
            # «شروع با همین پرداخت» نوبتِ ثبت‌شده دوباره ثبت نشود.
            await db.execute("UPDATE invoices SET status='used' WHERE code=? AND status='approved'", (code,))

        async def w(ctx, br, login, page):
            await turn.work_turn(ctx, br, login, page, numbers, by, on_booked=on_booked)

        await run_with_browser(ctx, "turn", w)
        r = await db.one("SELECT status FROM invoices WHERE code=?", (code,))
        if r and r["status"] == "approved":
            await job.say("ℹ️ نوبت ثبت نشد؛ پرداخت شما محفوظ است و می‌توانید از «🗓 ثبت نوبت قضائی» دوباره امتحان کنید.")

    start_job(cb, db, "turn", coro)
