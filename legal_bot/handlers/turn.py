from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..services import subscription as sub, turn, wallet
from ..services.flow import RunCtx, run_with_browser
from ..services.session import Job, JobCancelled, UserTimeout, jobs
from ..utils import (fmt_toman, to_en_digits, to_fa_digits, validate_archive_number, validate_case_number)
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


def _exact_count_validator(by: str, count: int):
    """اعتبارسنجی ویرایش شماره‌های فاکتورِ استفاده‌نشده: دقیقاً همان تعداد نوبتِ
    پرداخت‌شده (تک ← ۱ شماره؛ چند ← همه‌ی شماره‌ها) — دستور کارفرما."""

    def validate(v: str):
        parts = [p.strip() for p in re.split(r"[،,\n;]+", to_en_digits(v or "")) if p.strip()]
        if len(parts) != count:
            return None, T.TURN_RETRY_COUNT_MISMATCH.format(n=to_fa_digits(count))
        validator = validate_case_number if by == "case" else validate_archive_number
        out = []
        for p in parts:
            val, err = validator(p)
            if err:
                return None, "این شماره معتبر نیست: " + to_fa_digits(p)
            if val not in out:
                out.append(val)
        if len(out) != count:
            return None, "شماره‌های تکراری قابل ثبت نیستند؛ شماره‌های متفاوت بفرستید."
        return out, None

    return validate


async def _ask_numbers_again(job: Job, by: str, numbers: list[str]) -> list[str]:
    """درخواستِ (پرداخت‌شده‌ی) استفاده‌نشده: قبل از شروع، امکان ویرایش شماره پرونده
    (دستور کارفرما) — کاربر شماره‌ی اشتباه را اصلاح می‌کند و بعد از تأیید، مراحل
    شروع می‌شود."""
    kind = T.TURN_RETRY_KIND_CASE if by == "case" else T.TURN_RETRY_KIND_ARCHIVE
    plural = "های" if len(numbers) > 1 else ""
    shown = "، ".join(to_fa_digits(n) for n in numbers)
    act = await job.ask_choice(T.TURN_RETRY_ASK.format(plural=plural, nums=shown),
                               [("keep", T.TURN_RETRY_KEEP), ("edit", T.TURN_RETRY_EDIT)])
    if act == "keep":
        return numbers
    while True:
        if len(numbers) > 1:
            new = await job.ask_text(T.TURN_RETRY_EDIT_ASK_MULTI.format(
                n=to_fa_digits(len(numbers)), kind=kind), _exact_count_validator(by, len(numbers)))
        else:
            new = [await job.ask_text(T.TURN_RETRY_EDIT_ASK.format(kind=kind),
                                      validate_case_number if by == "case" else validate_archive_number)]
        c = await job.ask_choice(
            T.TURN_RETRY_CONFIRM.format(plural=plural, nums="، ".join(to_fa_digits(n) for n in new)),
            [("ok", T.TURN_RETRY_CONFIRM_OK), ("edit", T.TURN_RETRY_CONFIRM_EDIT)])
        if c == "ok":
            return new


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
                             f"({to_fa_digits(n)} نوبت: {to_fa_digits(nums)}).\n"
                             "در صورت اشتباه بودن شماره، بعد از زدن «شروع» می‌توانید آن را ویرایش کنید.",
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
                                       amount=0 if job.user_id in config.FREE_TURN_IDS else config.PRICE_TURN * len(numbers),
                                       is_admin=job.user_id == config.ADMIN_ID)
        if job.user_id in config.FREE_TURN_IDS:
            # معافیت از هزینه برای آیدی‌های مشخص (FREE_TURN_IDS): فاکتور بدون پرداخت تأیید می‌شود
            await db.execute("UPDATE invoices SET status='approved', reviewed_by=?, reviewed_at=? WHERE code=?",
                             (job.user_id, sub.now_iso(), inv["code"]))
            await job.bot.send_message(
                job.chat_id, "✅ ثبت نوبت برای شما رایگان است. برای شروع، دکمه‌ی زیر را بزنید.",
                reply_markup=K.inline([[("▶️ شروع ثبت نوبت", f"turn:go:{inv['code']}")]]))
            return
        # کیف پول: موجودی از مبلغ کل کسر می‌شود و فاکتور فقط برای مابقی صادر می‌شود
        used = await wallet.use_for_invoice(db, inv)
        if used:
            inv = await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],))
            left = await wallet.balance(db, job.user_id)
            await job.say(T.WALLET_APPLIED.format(used=fmt_toman(used), left=fmt_toman(left)))
            if int(inv["amount_toman"] or 0) <= 0:
                await db.execute("UPDATE invoices SET status='approved', reviewed_by=?, reviewed_at=? "
                                 "WHERE code=? AND status='pending'", (job.user_id, sub.now_iso(), inv["code"]))
                await job.bot.send_message(
                    job.chat_id, T.WALLET_ALL,
                    reply_markup=K.inline([[("▶️ شروع ثبت نوبت", f"turn:go:{inv['code']}")]]))
                return
        await show_invoice(job.bot, job.chat_id, inv)

    start_job(m, db, "turn_prepare", coro)


async def _settle_system_failure(job: Job, db, ctx: RunCtx, code: str, numbers: list[str]) -> None:
    """توقف به‌خاطر خطای شناسایی‌شده‌ی سامانه ← ٪TURN_FEE_PCT هزینه کسر و مابقی به کیف پول.

    فقط خطاهای config.TURN_REFUND_CATEGORIES (خطای سامانه/ربات) — نه خطای کاربر
    (شماره اشتباه، نوبت تکراری، لغو، مهلت پاسخ) و نه ظرفیت پر (پرداخت محفوظ می‌ماند)."""
    failed = set(ctx.sys_failed_numbers)
    if ctx.error_category in config.TURN_REFUND_CATEGORIES:
        remaining = set(numbers) - set(ctx.done_numbers) - set(ctx.booked_numbers)
        failed |= remaining
    failed -= set(ctx.booked_numbers)
    if not failed:
        return
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] not in ("approved", "used"):
        return
    res = await wallet.refund_failed(db, inv, len(failed))
    if not res:
        return
    fee, back, bal = res
    await db.execute("UPDATE invoices SET status='used' WHERE code=?", (code,))   # دیگر قابل استفاده‌ی مجدد نیست
    await job.say(T.WALLET_REFUND.format(fee_pct=to_fa_digits(config.TURN_FEE_PCT), fee=fmt_toman(fee),
                                         back=fmt_toman(back), bal=fmt_toman(bal)))


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
        # دستور کارفرما: وقتی درخواستِ (پرداخت‌شده‌ی) استفاده‌نشده برای همان
        # پرونده را انتخاب می‌کند، امکان ویرایش شماره پرونده هست (شماره‌ی قبلی
        # اشتباه بوده) و بعد از تأیید، مراحل شروع می‌شود.
        try:
            numbers_final = await _ask_numbers_again(job, by, numbers)
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        if numbers_final != numbers:
            await db.execute("UPDATE invoices SET payload=? WHERE code=?",
                             (f"{by}:{','.join(numbers_final)}", code))
        ctx = RunCtx(job, db, "turn")

        async def on_booked(_number: str):
            # به‌محض اولین ثبتِ موفق فاکتور «استفاده‌شده» می‌شود تا با دکمه‌ی
            # «شروع با همین پرداخت» نوبتِ ثبت‌شده دوباره ثبت نشود.
            await db.execute("UPDATE invoices SET status='used' WHERE code=? AND status='approved'", (code,))

        async def w(ctx, br, login, page):
            await turn.work_turn(ctx, br, login, page, numbers_final, by, on_booked=on_booked)

        await run_with_browser(ctx, "turn", w)
        await _settle_system_failure(job, db, ctx, code, numbers_final)
        r = await db.one("SELECT status FROM invoices WHERE code=?", (code,))
        if r and r["status"] == "approved":
            await job.say("ℹ️ نوبت ثبت نشد؛ پرداخت شما محفوظ است و می‌توانید از «🗓 ثبت نوبت قضائی» دوباره امتحان کنید.")

    start_job(cb, db, "turn", coro)
