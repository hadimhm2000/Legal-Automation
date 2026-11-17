from __future__ import annotations

import datetime as dt
import re

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import parse_iso
from ..services import eblagh, reports
from ..services import subscription as sub
from ..services.reminders import done_kb, reminder_text
from ..services.session import Job, JobCancelled, UserTimeout, jobs
from ..utils import (clean_digits, count_jalali_dates, fa_date, parse_jalali, to_en_digits, to_fa_digits,
                     today_tehran, validate_archive_number, validate_case_number, validate_notice_number,
                     weekday_fa)
from .common import browser_job, require_inquiry, require_inquiry_cb, require_service, safe_answer, show_plans, start_job

router = Router(name="notices")


async def _busy(message) -> bool:
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return True
    return False


@router.message(F.text == T.M_NOTICES)
async def menu(message: Message, db):
    if await _busy(message):
        return
    if await require_service(message, db, "notices"):
        await message.answer(T.NOTICES_MENU, reply_markup=K.notices_menu())


async def start_new_check(message_or_cb, db, trigger="manual"):
    uid = message_or_cb.from_user.id
    if await db.runs_today(uid) >= config.MAX_CHECKS_PER_USER_PER_DAY:
        await message_or_cb.bot.send_message(uid, "⛔ سقف بررسی امروز شما پر شده است؛ فردا دوباره امتحان کنید.")
        return
    start_job(message_or_cb, db, "notices_new",
              browser_job(db, "notices_new", "eblagh", eblagh.work_new, trigger=trigger))


@router.message(F.text == T.N_CHECK)
async def check_new(message: Message, db):
    if await _busy(message) or not await require_inquiry(message, db):
        return
    await start_new_check(message, db)


@router.callback_query(F.data.in_({"chk:go:scheduled_08", "chk:go:scheduled_18", "chk:go:manual"}))
async def check_from_prompt(cb: CallbackQuery, db):
    await safe_answer(cb)
    if jobs.busy(cb.from_user.id):
        await cb.message.answer(T.JOB_BUSY)
        return
    trigger = cb.data.split(":")[2]
    if trigger == "manual" or not await sub.has_auto_tracking(db, cb.from_user.id):
        # استعلام دستی ← گیت سهمیه؛ دکمه‌ی زمان‌بندی‌شده‌ی قدیمی هم مثل دستی رفتار می‌شود
        if not await require_inquiry_cb(cb, db):
            return
        trigger = "manual"
    elif not await sub.has_service(db, cb.from_user.id, "notices"):
        await cb.message.answer("🔒 سرویس ابلاغیه برای شما فعال نیست.")
        return
    await cb.message.edit_reply_markup(reply_markup=None)
    await start_new_check(cb, db, trigger=trigger)


@router.callback_query(F.data == "chk:skip")
async def skip(cb: CallbackQuery):
    await safe_answer(cb, "باشه")
    await cb.message.edit_text("⏭ این نوبت بررسی انجام نشد. هر وقت خواستید از منوی ابلاغیه‌ها «بررسی» را بزنید.")


@router.message(F.text == T.N_BY_CASE)
async def by_case(message: Message, db):
    if await _busy(message) or not await require_inquiry(message, db):
        return

    async def pre(job: Job):
        num = await job.ask_text(T.ASK_CASE_NUMBER, validate_case_number)
        return {"case_number": num}

    start_job(message, db, "notices_case",
              browser_job(db, "notices_case", "eblagh", eblagh.work_by_case, pre=pre))


@router.message(F.text == T.N_BY_NOTICE)
async def by_notice(message: Message, db):
    """جستجوی ابلاغیه‌های صادره براساس شماره ابلاغیه (دستور کارفرما — فایل آبان ۱۴۰۵):
    درست مثل جستجو با شماره پرونده، فقط مقدار در فیلد «شماره ابلاغیه» می‌رود."""
    if await _busy(message) or not await require_inquiry(message, db):
        return

    async def pre(job: Job):
        num = await job.ask_text(T.ASK_NOTICE_NUMBER, validate_notice_number)
        return {"notice_number": num}

    start_job(message, db, "notices_notice",
              browser_job(db, "notices_notice", "eblagh", eblagh.work_by_notice, pre=pre))


def _date_validator(v):
    d = parse_jalali(v)
    return (d, None) if d else (None, T.BAD_DATE)


@router.message(F.text == T.N_BY_RANGE)
async def by_range(message: Message, db):
    if await _busy(message) or not await require_inquiry(message, db):
        return

    async def pre(job: Job):
        start = await job.ask_text(T.ASK_RANGE_FROM, _date_validator)
        end = await job.ask_text(T.ASK_RANGE_TO, _date_validator)
        if end < start:
            start, end = end, start
        n = (end - start).days + 1
        if n > config.DATE_WINDOW_DAYS:
            await job.say(f"ℹ️ بازه‌ی شما {to_fa_digits(n)} روز است؛ چون سامانه حداکثر ۳۰ روز را می‌پذیرد، "
                          f"جستجو در {to_fa_digits(-(-n // config.DATE_WINDOW_DAYS))} مرحله‌ی ۳۰ روزه انجام می‌شود.")
        return {"start": start, "end": end}

    start_job(message, db, "notices_range",
              browser_job(db, "notices_range", "eblagh", eblagh.work_by_range, pre=pre))


# ── گزارش‌ها و یادآوری‌ها ──
@router.message(F.text.in_({T.N_REPORTS, T.M_REMINDERS}))
async def reports_menu(message: Message):
    await message.answer("🖨 گزارش‌ها و یادآوری‌ها:", reply_markup=K.reports_menu())


@router.message(F.text.in_({T.R_CURRENT, T.R_DONE, T.R_ALL}))
async def cases_report(message: Message, db):
    which = {T.R_CURRENT: "current", T.R_DONE: "done", T.R_ALL: "all"}[message.text]
    pdf, name = await reports.cases_report(db, message.from_user.id, which)
    await message.answer_document(BufferedInputFile(pdf, name), caption=message.text)


@router.message(F.text == T.R_HEARINGS)
async def hearings(message: Message, db):
    pdf = await reports.hearings_report(db, message.from_user.id)
    await message.answer_document(BufferedInputFile(pdf, "jalasat.pdf"), caption=T.R_HEARINGS)


@router.message(F.text == T.R_OPEN_REMINDERS)
async def open_reminders(message: Message, db):
    rows = await db.all("SELECT * FROM reminders WHERE bale_id=? AND status='open' ORDER BY due_date",
                        (message.from_user.id,))
    if not rows:
        await message.answer("یادآوری بازی ندارید.")
        return
    today = today_tehran()
    for r in rows[:20]:
        await message.answer(reminder_text(r, today), reply_markup=done_kb(r["id"]))


@router.callback_query(F.data.startswith("rem:done:"))
async def rem_done(cb: CallbackQuery, db):
    r = await db.close_reminder(int(cb.data.split(":")[2]), cb.from_user.id, "done")
    await safe_answer(cb, "بسته شد" if r else "یافت نشد")
    if r:
        await cb.message.edit_text((cb.message.text or "") + "\n\n✅ مراجعه و انجام شد — یادآوری بسته شد.")


@router.callback_query(F.data == "rem:no")
async def rem_no(cb: CallbackQuery):
    await safe_answer(cb, "باشه")
    await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("rem:add:"))
async def rem_add(cb: CallbackQuery, db):
    """یادآوری دلخواه: «آخرین مهلت اقدام» به تاریخ یا تعداد روز از امروز + توضیح اختیاری."""
    await safe_answer(cb)
    nid = int(cb.data.split(":")[2])
    n = await db.one("SELECT * FROM notices WHERE id=? AND bale_id=?", (nid, cb.from_user.id))
    if not n:
        return
    if jobs.busy(cb.from_user.id):
        await cb.message.answer(T.JOB_BUSY)
        return
    await cb.message.edit_reply_markup(reply_markup=None)

    async def coro(job: Job):
        try:
            mode = await job.ask_choice("چطور مهلت را تعیین می‌کنید؟",
                                        [("date", "📅 تاریخ نهایی انجام (مثلاً ۱۴۰۵/۰۸/۳۰)"),
                                         ("days", "🔢 مدت زمان انجام از امروز (تعداد روز)")])
            today = today_tehran()
            if mode == "date":
                def future_date(v):
                    d = parse_jalali(v)
                    if not d:
                        return None, T.BAD_DATE
                    if d < today:
                        return None, "❌ این تاریخ گذشته است؛ تاریخی از امروز به بعد بفرستید."
                    return d, None

                due = await job.ask_text("آخرین مهلت اقدام را به شمسی بفرستید (مثلاً ۱۴۰۵.۰۸.۳۰):", future_date)
            else:
                kind, v = await job.ask("چند روز تا آخرین مهلت دارید؟ یک گزینه را بزنید یا عدد بفرستید:",
                                        [("5", "۵ روز"), ("10", "۱۰ روز"), ("15", "۱۵ روز"), ("20", "۲۰ روز"),
                                         ("30", "۳۰ روز")])
                days = int(clean_digits(v) or 0) or 10
                due = today + dt.timedelta(days=min(days, 365))
            note_kind, note = await job.ask("توضیحی برای این یادآوری دارید؟ بنویسید یا «بدون توضیح» را بزنید.",
                                            [("-", "بدون توضیح")])
            note = None if note_kind == "choice" else note.strip()[:300]
            await db.add_reminder(job.user_id, "custom", due, notice_id=nid, note=note, start_date=today,
                                  case_number=n["case_number"], archive_number=n["archive_number"],
                                  branch=n["branch"], external_id=n["external_id"])
            await job.say(f"✅ یادآوری ثبت شد: آخرین مهلت {fa_date(due)} — ۵ روز مانده، روز قبل و روز آخر به شما "
                          "اعلام می‌شود.")
        except (JobCancelled, UserTimeout):
            await job.say("ثبت یادآوری لغو شد.")

    start_job(cb, db, "reminder", coro)


# ── ثبت یادآوری دلخواه (دستور کارفرما): کاربر خودش برای تاریخ‌هایی اعلام ──
def reminder_dates_validator(v: str) -> tuple[list[dt.date] | None, str | None]:
    """اعتبارسنجی «یک یا چند تاریخ شمسی از امروز به بعد» — جدا با ویرگول/خط جدید.

    بخشی که دو تاریخ دارد (مثل «۱۴۰۵/۰۹/۱۰ و ۱۴۰۵/۰۹/۲۰») رد می‌شود تا یکی از
    تاریخ‌ها بی‌اعلام نماند؛ تاریخ تکراری فقط یک‌بار شمرده می‌شود.
    """
    today = today_tehran()
    parts = [p.strip() for p in re.split(r"[،,\n؛;]+", to_en_digits(v or "")) if p.strip()]
    if not parts:
        return None, T.BAD_DATE
    if len(parts) > config.MAX_REMINDER_DATES_PER_MSG:
        return None, T.R_REM_TOO_MANY_DATES.format(max=to_fa_digits(config.MAX_REMINDER_DATES_PER_MSG))
    out: list[dt.date] = []
    bad: list[str] = []
    for p in parts:
        d = parse_jalali(p)
        if d is None or d < today or count_jalali_dates(p) != 1:
            bad.append(p)
        elif d not in out:
            out.append(d)
    if bad or not out:
        return None, T.R_REM_BAD_DATES.format(list="، ".join(to_fa_digits(b) for b in bad) or "-")
    return out, None


@router.message(F.text == T.R_NEW_REMINDER)
async def new_reminder(message: Message, db):
    """«➕ ثبت یادآوری جدید» — فقط کاربرانی که حداقل یک اشتراک فعال دارند (دستور کارفرما)."""
    if await _busy(message):
        return
    ok, why = await sub.has_active_subscription(db, message.from_user.id)
    if not ok:
        if why == "restricted":
            s = await sub.get(db, message.from_user.id)
            until = parse_iso(s.get("restricted_until"))
            await message.answer(T.restricted_until_text(fa_date(until.date()) if until else "-"),
                                 reply_markup=K.main_menu())
        else:
            await show_plans(message.bot, message.chat.id, T.REMINDERS_NEED_PLAN)
        return

    async def coro(job: Job):
        async def ask_days() -> int:
            """«چند روز دیگر؟» — دکمه‌های آماده یا عدد آزاد (۱ تا ۳۶۵)."""
            while True:
                kind, v = await job.ask(T.R_REM_ASK_DAYS,
                                        [("5", "۵ روز"), ("10", "۱۰ روز"), ("15", "۱۵ روز"),
                                         ("20", "۲۰ روز"), ("30", "۳۰ روز")])
                days = int(v) if kind == "choice" else int(clean_digits(v) or 0)
                if 1 <= days <= 365:
                    return days
                await job.say(T.R_REM_BAD_DAYS)

        try:
            mode = await job.ask_choice(T.R_REM_ASK_MODE, [("date", T.R_REM_MODE_DATE),
                                                           ("days", T.R_REM_MODE_DAYS)])
            today = today_tehran()
            if mode == "date":
                dates = await job.ask_text(T.R_REM_ASK_DATES, reminder_dates_validator)
            else:
                dates = [today + dt.timedelta(days=await ask_days())]
            # سقف یادآوری بازِ دلخواه (ضد انباشت بی‌سقف)
            open_rows = await db.all(
                "SELECT id FROM reminders WHERE bale_id=? AND kind='custom' AND status='open'", (job.user_id,))
            if len(open_rows) + len(dates) > config.MAX_CUSTOM_REMINDERS_OPEN:
                await job.say(T.R_REM_CAP_FULL.format(max=to_fa_digits(config.MAX_CUSTOM_REMINDERS_OPEN)))
                return
            # شماره پرونده/بایگانی اختیاری
            case_number = archive_number = None
            while case_number is None and archive_number is None:
                kind, v = await job.ask(T.R_REM_ASK_CASE, [("-", T.R_REM_NO_CASE)])
                if kind == "choice":
                    break
                val, _ = validate_case_number(v)
                if val:
                    case_number = val
                    break
                val, _ = validate_archive_number(v)
                if val:
                    archive_number = val
                    break
                await job.say(T.R_REM_BAD_CASE)
            # توضیح اختیاری
            kind, note_v = await job.ask(T.R_REM_ASK_NOTE, [("-", T.R_REM_NO_NOTE)])
            note = None if kind == "choice" else note_v.strip()[:300]
            # تأیید نهایی
            lines = [T.R_REM_CONFIRM]
            for i, d in enumerate(dates, 1):
                lines.append(f"{to_fa_digits(i)}. {weekday_fa(d)} {fa_date(d)}")
            if case_number:
                lines.append(f"پرونده: {to_fa_digits(case_number)}")
            if archive_number:
                lines.append(f"شماره بایگانی: {to_fa_digits(archive_number)}")
            if note:
                lines.append(f"📝 {note}")
            while True:
                c = await job.ask_choice("\n".join(lines),
                                         [("ok", T.R_REM_CONFIRM_OK), ("edit", T.R_REM_CONFIRM_EDIT)])
                if c == "ok":
                    break
                if mode == "date":
                    dates = await job.ask_text(T.R_REM_ASK_DATES, reminder_dates_validator)
                else:
                    dates = [today + dt.timedelta(days=await ask_days())]
                lines = [T.R_REM_CONFIRM]
                for i, d in enumerate(dates, 1):
                    lines.append(f"{to_fa_digits(i)}. {weekday_fa(d)} {fa_date(d)}")
            # ویرایش می‌تواند تعداد تاریخ‌ها را زیاد کند ← سقف دوباره چک می‌شود
            if len(open_rows) + len(dates) > config.MAX_CUSTOM_REMINDERS_OPEN:
                await job.say(T.R_REM_CAP_FULL.format(max=to_fa_digits(config.MAX_CUSTOM_REMINDERS_OPEN)))
                return
            for d in dates:
                await db.add_reminder(job.user_id, "custom", d, note=note, case_number=case_number,
                                      archive_number=archive_number, start_date=today)
            await job.say(T.R_REM_DONE.format(n=to_fa_digits(len(dates))))
        except (JobCancelled, UserTimeout):
            await job.say(T.R_REM_CANCELLED)

    start_job(message, db, "reminder_new", coro)
