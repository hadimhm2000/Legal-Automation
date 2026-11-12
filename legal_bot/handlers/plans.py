"""پلن‌های نهایی ربات (آبان ۱۴۰۵): انتخاب پلن ← قوانین ← تایید ← پرداخت کارت‌به‌کارت.

شروع رایگان با تأیید شماره موبایل فعال می‌شود؛ پلن‌های شخصی اعتبار استعلام می‌خرند و
پلن‌های حرفه‌ای دوره‌ی ماهانه/۳ماهه با سهمیه ماهانه و پیگیری خودکار دارند.
"""
from __future__ import annotations

import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import now_iso, parse_iso
from ..services import subscription as sub
from ..utils import fa_date, fmt_toman, to_fa_digits
from .common import safe_answer, show_plans
from .payment import show_invoice

router = Router(name="plans")

# کاربرانی که منتظر ارسال شماره موبایل برای شروع رایگان هستند: uid → انقضا
awaiting_phone: dict[int, float] = {}
_PHONE_WAIT_SEC = 10 * 60

_PLAN_RANK = {"base": 1, "select": 2, "pro": 3, "expert": 4, "org": 5}


def _rules_kb(then: str):
    return K.inline([[(T.RULES_ACCEPT, f"rul:ok:{then}")], [("🔙 بازگشت به پلن‌ها", "nav:plans")]])


async def _send_rules(target, then: str):
    """قوانین دقیق کارفرما + دکمه‌ی تایید؛ پرداخت/فعال‌سازی فقط بعد از تایید."""
    await target.answer("پیش از ادامه، قوانین زیر را مطالعه و تایید کنید:")
    await target.answer(T.RULES_TEXT, reply_markup=_rules_kb(then))


@router.callback_query(F.data == "nav:plans")
async def nav_plans(cb: CallbackQuery):
    await safe_answer(cb)
    await show_plans(cb.bot, cb.message.chat.id)


# ── انتخاب پلن ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(cb: CallbackQuery, db):
    await safe_answer(cb)
    p = cb.data.split(":")[1]
    if p not in sub.PLANS:
        await show_plans(cb.bot, cb.message.chat.id)
        return
    uid = cb.from_user.id
    s = await sub.get(db, uid)

    if p == "free":
        if await sub.free_used(db, uid):
            await cb.message.answer("🎁 شروع رایگان قبلاً برای این حساب فعال شده است "
                                    "(قاعده ۵: هر اشتراک فقط برای یک حساب کاربری است).",
                                    reply_markup=K.plans_kb())
            return
        if not await sub.phone_verified(db, uid):
            awaiting_phone[uid] = time.time() + _PHONE_WAIT_SEC
            await cb.message.answer(T.PHONE_ASK, reply_markup=K.phone_kb())
            return
        await _send_rules(cb.message, "free:go")
        return

    if p in ("pro", "expert", "org"):
        active_sub = (s["status"] == "PAID_ACTIVE" and s["plan"] in sub.SUB_PLANS
                      and parse_iso(s["paid_until"]) and parse_iso(s["paid_until"]) > sub.utcnow())
        if active_sub:
            cur = s["plan"]
            if p == cur:
                await _renewal_view(cb.message, p)
                return
            if _PLAN_RANK.get(p, 0) > _PLAN_RANK.get(cur, 0):
                await _upgrade_view(cb.message, db, uid, cur, p)
                return
            await cb.message.answer(
                f"پلن فعلی شما («{sub.plan_title(cur)}») بالاتر از این پلن است؛ "
                "برای تغییر، ابتدا دوره‌ی فعلی به پایان برسد یا از «💳 اشتراک من» تمدید کنید.",
                reply_markup=K.plans_kb())
            return
        # خرید پلن حرفه‌ای جدید ← قوانین ← انتخاب دوره
        await _send_rules(cb.message, f"bill:{p}")
        return

    # پلن‌های شخصی (پایه/برگزیده): قوانین ← فاکتور
    await _send_rules(cb.message, f"inv:new:{p}:credit")


def _billing_kb(plan: str, kind: str = "new"):
    m = sub.plan_meta(plan)
    return K.inline([
        [(f"ماهانه: {fmt_toman(m['monthly'])}", f"inv:{kind}:{plan}:monthly")],
        [(f"۳ ماهه: {fmt_toman(m['quarterly'])} (۱۰٪ تخفیف)", f"inv:{kind}:{plan}:quarterly")],
        [("🔙 بازگشت به پلن‌ها", "nav:plans")],
    ])


async def _renewal_view(target, plan: str):
    m = sub.plan_meta(plan)
    await target.answer(
        f"🔁 تمدید پلن «{m['title']}»\n"
        f"📊 سهمیه هر ماه از نو شروع می‌شود (قاعده ۳) و روزهای باقی‌مانده‌ی دوره‌ی فعلی از دست نمی‌رود.",
        reply_markup=_billing_kb(plan, "renew"))


async def _upgrade_view(target, db, uid: int, cur: str, new: str):
    s = await sub.get(db, uid)
    left = max(0, (parse_iso(s["paid_until"]) - sub.utcnow()).days) if s["paid_until"] else 0
    m_new = sub.plan_meta(new)
    amt_m = sub.upgrade_amount(cur, left, new, "monthly")
    amt_q = sub.upgrade_amount(cur, left, new, "quarterly")
    await target.answer(
        f"⬆️ ارتقای «{sub.plan_title(cur)}» به «{m_new['title']}» — {to_fa_digits(left)} روز از دوره‌ی فعلی "
        f"باقی مانده (قاعده ۹: مابه‌التفاوت به‌صورت نسبی حساب می‌شود).\n\n"
        f"ماهانه: {fmt_toman(amt_m)}\n۳ ماهه: {fmt_toman(amt_q)}",
        reply_markup=K.inline([
            [(f"⬆️ ارتقای ماهانه — {fmt_toman(amt_m)}", f"inv:upgrade:{new}:monthly")],
            [(f"⬆️ ارتقای ۳ ماهه — {fmt_toman(amt_q)}", f"inv:upgrade:{new}:quarterly")],
            [("🔙 بازگشت به پلن‌ها", "nav:plans")],
        ]))


# ── تایید قوانین ← ادامه‌ی همان مسیر ───────────────────────────────────────
@router.callback_query(F.data.startswith("rul:ok:"))
async def rules_accepted(cb: CallbackQuery, db):
    await safe_answer(cb, "✅")
    then = cb.data.split(":", 2)[2]
    await db.execute("UPDATE subscriptions SET rules_ack_at=?, rules_version=1 WHERE bale_id=?",
                     (now_iso(), cb.from_user.id))
    if then == "free:go":
        if not await sub.activate_free(db, cb.from_user.id):
            await cb.message.answer("🎁 شروع رایگان قبلاً برای این حساب فعال شده است.",
                                    reply_markup=K.plans_kb())
            return
        await cb.message.answer(T.FREE_ACTIVATED, reply_markup=K.main_menu())
        return
    if then.startswith("bill:"):
        plan = then.split(":")[1]
        m = sub.plan_meta(plan)
        await cb.message.answer(
            f"⚖️ {m['title']}\n"
            f"📊 {to_fa_digits(m['quota']) if m['quota'] else 'نامحدود'} استعلام در ماه + "
            f"پیگیری خودکار تا {to_fa_digits(m['cases'])} پرونده\n"
            "دوره‌ی پرداخت را انتخاب کنید:",
            reply_markup=_billing_kb(plan, "new"))
        return
    # inv:<kind>:<plan>:<cycle>
    await _do_invoice(cb, db, then)


async def _do_invoice(cb, db, data: str):
    parts = data.split(":")           # inv, kind, plan, cycle
    if len(parts) != 4:
        await show_plans(cb.bot, cb.message.chat.id)
        return
    _, kind, plan, cycle = parts
    if kind == "renew":
        kind = "renewal"
    if plan not in sub.PLANS or (cycle not in ("monthly", "quarterly", "credit")):
        await show_plans(cb.bot, cb.message.chat.id)
        return
    inv = await sub.create_invoice(db, cb.from_user.id, kind, plan, cycle,
                                   is_admin=cb.from_user.id == config.ADMIN_ID)
    await show_invoice(cb.bot, cb.message.chat.id, inv)


@router.callback_query(F.data.startswith("inv:"))
async def invoice(cb: CallbackQuery, db):
    await safe_answer(cb)
    await _do_invoice(cb, db, cb.data)


# ── تأیید شماره موبایل (شروع رایگان) ──────────────────────────────────────
def _phone_waiting(uid: int) -> bool:
    until = awaiting_phone.get(uid)
    if not until:
        return False
    if until < time.time():
        awaiting_phone.pop(uid, None)
        return False
    return True


async def _phone_done(message: Message, db, phone: str, via_contact: bool):
    uid = message.from_user.id
    awaiting_phone.pop(uid, None)
    other = await sub.phone_taken_by_other(db, uid, phone)
    if other is not None:
        await sub.report_violation(
            message.bot, db, uid, "تلاش برای دریافت دوباره‌ی شروع رایگان با یک شماره موبایل",
            f"شماره {to_fa_digits(phone)} قبلاً برای حساب {to_fa_digits(other)} ثبت شده است (قاعده ۵)")
        await message.answer(T.PHONE_TAKEN, reply_markup=K.plans_kb())
        return
    await sub.save_phone(db, uid, phone)
    await message.answer("✅ شماره موبایل شما ثبت و تایید شد"
                         + (" (از مخاطب حساب بله)" if via_contact else "") + ".",
                         reply_markup=K.main_menu())
    await _send_rules(message, "free:go")


@router.message(F.contact)
async def phone_contact(message: Message, db):
    if not _phone_waiting(message.from_user.id):
        await message.answer("برای تأیید شماره موبایل، ابتدا از «💳 اشتراک من» یا پلن‌ها "
                             "«🎁 شروع رایگان» را انتخاب کنید.", reply_markup=K.main_menu())
        return
    phone = sub.normalize_phone(message.contact.phone_number or "")
    if not phone:
        await message.answer(T.PHONE_BAD)
        return
    await _phone_done(message, db, phone, via_contact=True)


@router.message(F.text, F.from_user.id.func(_phone_waiting))
async def phone_text(message: Message, db):
    if message.text in T.MENU_TEXTS:
        return
    phone = sub.normalize_phone(message.text)
    if not phone:
        await message.answer(T.PHONE_BAD)
        return
    await _phone_done(message, db, phone, via_contact=False)


# ── اشتراک من ──────────────────────────────────────────────────────────────
@router.message(F.text == T.M_SUB)
async def my_sub(message: Message, db):
    uid = message.from_user.id
    s = await sub.get(db, uid)
    names = {"NEW": "فعال نشده", "FREE_ACTIVE": "🎁 شروع رایگان", "PAID_ACTIVE": "فعال (پولی)",
             "LOCKED": "🔒 قفل"}
    m = sub.plan_meta(s["plan"])
    lines = [f"💳 وضعیت: {names.get(s['status'], s['status'])}"]
    if s["plan"]:
        lines.append(f"پلن: {m.get('title', s['plan'])}"
                     + (f" ({sub.CYCLE_FA.get(s['cycle'], '')})" if s["cycle"] else ""))
    # سهمیه
    if s["status"] in sub.ACTIVE:
        if (s["inquiries_left"] or 0) > 0:
            lines.append(f"📊 اعتبار استعلام: {to_fa_digits(s['inquiries_left'])}")
        if s["plan"] in sub.SUB_PLANS:
            if (s["quota_total"] or 0) > 0:
                lines.append(f"📊 استعلام این ماه: {to_fa_digits(s['quota_used'] or 0)} از "
                             f"{to_fa_digits(s['quota_total'])} (باقی‌مانده: "
                             f"{to_fa_digits(s['quota_total'] - (s['quota_used'] or 0))})")
            else:
                today_n = await db.manual_done_since(uid, 24, sub.INQUIRY_KINDS)
                lines.append(f"📊 استعلام نامحدود — دستی امروز: {to_fa_digits(today_n)} از "
                             f"{to_fa_digits(config.PLAN_ORG_DAILY_CAP)}")
    end = None
    if s["status"] == "PAID_ACTIVE" and s["paid_until"]:
        end = parse_iso(s["paid_until"])
    elif s["plan"] == "free":
        end = None
    if end:
        lines.append(f"پایان دوره: {fa_date(end.date())} (پرونده‌های ثبت‌شده تا "
                     f"{to_fa_digits(config.SUB_GRACE_DAYS)} روز بعد از آن نگه داشته می‌شوند)")
    if s.get("restricted_until") and parse_iso(s["restricted_until"]) > sub.utcnow():
        lines.append("⛔ محدودیت موقت فعال است تا " + fa_date(parse_iso(s["restricted_until"]).date()))
    n_tracked = len(await db.tracked(uid) or [])
    cap = await sub.case_cap(db, uid)
    if cap or n_tracked:
        lines.append(f"📂 پرونده‌های ثبت‌شده برای بررسی روزانه: {to_fa_digits(n_tracked)}"
                     + (f" از {to_fa_digits(cap)}" if cap else ""))
    rows = [[("📋 انتخاب / تغییر پلن", "nav:plans")]]
    if s["status"] == "PAID_ACTIVE" and s["plan"] in sub.SUB_PLANS and end and end > sub.utcnow():
        rows.append([(f"🔁 تمدید «{m.get('title')}»", f"plan:{s['plan']}")])
        higher = [p for p in ("expert", "org") if _PLAN_RANK.get(p, 0) > _PLAN_RANK.get(s["plan"], 0)]
        for p in higher:
            rows.append([(f"⬆️ ارتقا به {sub.plan_title(p)}", f"plan:{p}")])
    await message.answer("\n".join(lines), reply_markup=K.inline(rows))
    if s["status"] == "NEW":
        await show_plans(message.bot, message.chat.id)
