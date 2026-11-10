from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import parse_iso
from ..services import subscription as sub
from ..utils import fa_date, fmt_toman, to_fa_digits
from .common import ack_terms_needed, safe_answer, set_terms, show_plans
from .payment import show_invoice

router = Router(name="plans")

PLANS = {"1": (True, False), "2": (False, True), "3": (True, True)}


@router.callback_query(F.data == "nav:plans")
async def nav_plans(cb: CallbackQuery):
    await safe_answer(cb)
    await show_plans(cb.bot, cb.message.chat.id)


@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(cb: CallbackQuery, db):
    await safe_answer(cb)
    p = cb.data.split(":")[1]
    uid = cb.from_user.id
    s = await sub.get(db, uid)
    used = await sub.trial_used(db, uid)
    if s["status"] == "PAID_ACTIVE" and p == "3" and not (s["notices"] and s["case_alerts"]):
        left = max(0, (parse_iso(s["paid_until"]) - sub.utcnow()).days)
        amount = sub.upgrade_amount(bool(s["notices"]), bool(s["case_alerts"]), left)
        await cb.message.answer(f"⬆️ ارتقا به بسته‌ی دوتایی برای {to_fa_digits(left)} روز باقی‌مانده: {fmt_toman(amount)}",
                                reply_markup=K.inline([[("🧾 صدور فاکتور ارتقا", "inv:upgrade:3")], [(T.BACK, "nav:main")]]))
        return
    if s["status"] == "TRIAL_ACTIVE" and p in ("1", "2"):
        n, c = PLANS[p]
        await sub._set(db, uid, notices=int(n or s["notices"]), case_alerts=int(c or s["case_alerts"]))
        await cb.message.answer("✅ این سرویس هم در دوره‌ی تست شما روشن شد (مدت تست تمدید نمی‌شود).",
                                reply_markup=K.main_menu())
        return
    if p in ("1", "2") and not used:
        price = config.PRICE_NOTICES if p == "1" else config.PRICE_CASE_ALERTS
        await cb.message.answer(T.plan_trial_text(price),
                                reply_markup=K.inline([[("🎁 شروع تست رایگان", f"trial:{p}")], [(T.BACK, "nav:plans")]]))
        return
    if p == "3" and not used:
        await cb.message.answer(T.PLAN3_TEXT, reply_markup=K.inline(
            [[("🧾 صدور فاکتور", "inv:new:3")], [("🎁 برگشت برای تست", "nav:plans")], [(T.BACK, "nav:main")]]))
        return
    n, c = PLANS[p]
    await cb.message.answer(f"قیمت ماهانه: {fmt_toman(sub.plan_price(n, c))}",
                            reply_markup=K.inline([[("🧾 صدور فاکتور", f"inv:new:{p}")], [(T.BACK, "nav:plans")]]))


async def _terms(cb: CallbackQuery, db, then: str) -> bool:
    if await ack_terms_needed(db, cb.from_user.id):
        await cb.message.answer(T.TERMS_TEXT, reply_markup=K.inline([[(T.TERMS_ACCEPT, f"terms:{then}")],
                                                                    [(T.BACK, "nav:plans")]]))
        return False
    return True


@router.callback_query(F.data.startswith("terms:"))
async def terms_accept(cb: CallbackQuery, db):
    await set_terms(db, cb.from_user.id)
    await safe_answer(cb, "✅")
    then = cb.data.split(":", 1)[1]
    cb_data = then  # e.g. trial:1 / inv:new:3
    if cb_data.startswith("trial:"):
        await _do_trial(cb, db, cb_data.split(":")[1])
    elif cb_data.startswith("inv:"):
        await _do_invoice(cb, db, cb_data)


@router.callback_query(F.data.startswith("trial:"))
async def trial(cb: CallbackQuery, db):
    await safe_answer(cb)
    p = cb.data.split(":")[1]
    if await _terms(cb, db, f"trial:{p}"):
        await _do_trial(cb, db, p)


async def _do_trial(cb, db, p):
    n, c = PLANS[p]
    if not await sub.start_trial(db, cb.from_user.id, n, c):
        await cb.message.answer("شما قبلاً از تست رایگان استفاده کرده‌اید.")
        await show_plans(cb.bot, cb.message.chat.id)
        return
    await cb.message.answer(
        f"🎁 تست رایگان {to_fa_digits(config.TRIAL_DAYS)} روزه فعال شد. در همین مدت می‌توانید سرویس دیگر را هم "
        "از «💳 اشتراک من» روشن کنید.\n\n"
        "مرحله‌ی بعد: هر بار که بررسی انجام شود (ساعت ۸ و ۱۸ یا هر وقت خودتان بخواهید)، ربات اعلام می‌کند که "
        "برای ورود به سامانه به کدملی، رمز شخصی و رمز موقت نیاز دارد؛ این اطلاعات ذخیره نمی‌شود.",
        reply_markup=K.main_menu())


@router.callback_query(F.data.startswith("inv:"))
async def invoice(cb: CallbackQuery, db):
    await safe_answer(cb)
    if await _terms(cb, db, cb.data):
        await _do_invoice(cb, db, cb.data)


async def _do_invoice(cb, db, data):
    _, kind, p = data.split(":")
    n, c = PLANS.get(p, (True, True))
    s = await sub.get(db, cb.from_user.id)
    if kind == "renew":
        kind, n, c = "renewal", bool(s["notices"]), bool(s["case_alerts"])
    inv = await sub.create_invoice(db, cb.from_user.id, kind, n, c, is_admin=cb.from_user.id == config.ADMIN_ID)
    await show_invoice(cb.bot, cb.message.chat.id, inv)


@router.message(F.text == T.M_SUB)
async def my_sub(message: Message, db):
    s = await sub.get(db, message.from_user.id)
    names = {"NEW": "فعال نشده", "TRIAL_ACTIVE": "تست رایگان", "PAID_ACTIVE": "فعال (پولی)", "LOCKED": "🔒 قفل"}
    services = []
    if s["notices"]:
        services.append("ابلاغیه")
    if s["case_alerts"]:
        services.append("اطلاع‌رسانی پرونده")
    end = parse_iso(s["trial_ends_at"] if s["status"] == "TRIAL_ACTIVE" else s["paid_until"])
    lines = [f"💳 وضعیت: {names.get(s['status'], s['status'])}",
             f"سرویس‌ها: {'، '.join(services) or '-'}"]
    if end:
        lines.append(f"پایان: {fa_date(end.date())}")
    rows = [[("📋 انتخاب / تغییر سرویس", "nav:plans")]]
    if s["status"] in ("PAID_ACTIVE", "LOCKED") and (s["notices"] or s["case_alerts"]):
        rows.append([("🔁 تمدید یک‌ماهه", "inv:renew:0")])
    await message.answer("\n".join(lines), reply_markup=K.inline(rows))
    if s["status"] == "NEW":
        await show_plans(message.bot, message.chat.id)
