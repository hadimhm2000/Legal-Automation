from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import keyboards as K, texts as T
from ..services import resultcase
from ..services.flow import RunCtx, run_with_browser
from ..services.session import Job, JobCancelled, UserTimeout, jobs
from ..utils import to_en_digits, to_fa_digits, validate_case_number
from .common import require_service, safe_answer, start_job

router = Router(name="cases")

PORTALS = [("person", T.PORTAL_PERSON), ("lawyer", T.PORTAL_LAWYER)]


async def ask_portal(job: Job) -> str:
    return await job.ask_choice(T.ASK_PORTAL, PORTALS)


async def _guard(message: Message, db) -> bool:
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return False
    return await require_service(message, db, "case_alerts")


@router.message(F.text == T.M_CASES)
async def menu(message: Message, db):
    if jobs.busy(message.from_user.id):
        await message.answer(T.JOB_BUSY)
        return
    if await require_service(message, db, "case_alerts"):
        await message.answer(T.CASES_MENU, reply_markup=K.cases_menu())


def _list_job(db, which):
    async def coro(job: Job):
        try:
            portal = await ask_portal(job)
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        ctx = RunCtx(job, db, "case_list")

        async def w(ctx, br, login, page):
            await resultcase.work_list(ctx, br, login, page, which)

        await run_with_browser(ctx, f"resultcase_{portal}", w)
    return coro


@router.message(F.text.in_({T.C_ALL, T.C_LIVE, T.C_ARCHIVED}))
async def lists(message: Message, db):
    if not await _guard(message, db):
        return
    which = {T.C_ALL: "all", T.C_LIVE: "live", T.C_ARCHIVED: "archived"}[message.text]
    start_job(message, db, "case_list", _list_job(db, which))


@router.message(F.text == T.C_DETAIL)
async def detail(message: Message, db):
    if not await _guard(message, db):
        return

    async def coro(job: Job):
        try:
            num = await job.ask_text(T.ASK_CASE_NUMBER, validate_case_number)
            portal = await ask_portal(job)
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        ctx = RunCtx(job, db, "case_detail")

        async def w(ctx, br, login, page):
            await resultcase.work_detail(ctx, br, login, page, num)

        await run_with_browser(ctx, f"resultcase_{portal}", w)

    start_job(message, db, "case_detail", coro)


def _parse_many(text: str):
    ok, bad = [], []
    for tok in re.split(r"[\s,،]+", to_en_digits(text or "").strip()):
        if not tok:
            continue
        num, err = validate_case_number(tok)
        (ok.append(num) if num else bad.append((tok, err)))
    return ok, bad


@router.message(F.text == T.C_TRACK)
async def track(message: Message, db):
    if not await _guard(message, db):
        return

    async def coro(job: Job):
        try:
            portal = await ask_portal(job)

            def validator(v):
                ok, bad = _parse_many(v)
                if bad:
                    return None, "\n".join(f"❌ {to_fa_digits(t)}: {e}" for t, e in bad)
                return (ok or None), ("حداقل یک شماره پرونده بفرستید." if not ok else None)

            nums = await job.ask_text("شماره پرونده(ها) را بفرستید (چند شماره را با فاصله یا خط جدید جدا کنید):",
                                      validator)
        except (JobCancelled, UserTimeout):
            await job.say(T.CANCELLED)
            return
        for n in nums:
            await db.track_case(job.user_id, n, portal)
        await job.say("✅ ثبت شد. هر روز ساعت ۸ صبح برای بررسی آخرین تغییرات به شما پیام می‌دهم؛ "
                      "هر وقت هم خواستید «🔍 بررسی همین حالا» را بزنید.", tracked_kb())

    start_job(message, db, "case_track_add", coro)


def tracked_kb():
    return K.inline([[("🔍 بررسی همین حالا", "trk:go")], [("📋 پرونده‌های ثبت‌شده", "trk:list")]])


@router.callback_query(F.data == "trk:list")
async def trk_list(cb: CallbackQuery, db):
    await safe_answer(cb)
    rows = await db.tracked(cb.from_user.id)
    if not rows:
        await cb.message.answer("پرونده‌ای برای بررسی روزانه ثبت نکرده‌اید.")
        return
    kb = [[(f"🗑 {to_fa_digits(r['case_number'])}", f"trk:del:{r['case_number']}")] for r in rows[:30]]
    kb.append([("🔍 بررسی همین حالا", "trk:go")])
    await cb.message.answer("📋 پرونده‌های ثبت‌شده (برای حذف روی هر کدام بزنید):", reply_markup=K.inline(kb))


@router.callback_query(F.data.startswith("trk:del:"))
async def trk_del(cb: CallbackQuery, db):
    num = cb.data.split(":")[2]
    await db.execute("DELETE FROM tracked_cases WHERE bale_id=? AND case_number=?", (cb.from_user.id, num))
    await safe_answer(cb, "حذف شد")


@router.callback_query(F.data.in_({"trk:go", "trk:go:scheduled"}))
async def trk_go(cb: CallbackQuery, db):
    await safe_answer(cb)
    from ..services import subscription as sub

    if jobs.busy(cb.from_user.id):
        await cb.message.answer(T.JOB_BUSY)
        return
    if not await sub.has_service(db, cb.from_user.id, "case_alerts"):
        await cb.message.answer("🔒 سرویس اطلاع‌رسانی پرونده برای شما فعال نیست.")
        return
    rows = await db.tracked(cb.from_user.id)
    if not rows:
        await cb.message.answer("پرونده‌ای ثبت نشده است.")
        return
    trigger = "scheduled_08" if cb.data.endswith("scheduled") else "manual"

    async def coro(job: Job):
        for portal in ("person", "lawyer"):
            group = [r for r in rows if r["portal"] == portal]
            if not group:
                continue
            ctx = RunCtx(job, db, "case_track", trigger)

            async def w(ctx, br, login, page, group=group):
                await resultcase.work_track(ctx, br, login, page, group)

            await job.say(f"📂 بررسی {to_fa_digits(len(group))} پرونده در بخش "
                          f"{'اشخاص حقیقی' if portal == 'person' else 'وکلا'}…")
            await run_with_browser(ctx, f"resultcase_{portal}", w)

    start_job(cb, db, "case_track", coro)
