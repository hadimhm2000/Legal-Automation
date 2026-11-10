"""پرداخت کارت‌به‌کارت کاملاً داخل ربات دوم: فاکتور ← عکس رسید ← مدیر تأیید/رد."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import parse_iso
from ..services import error_reporter, subscription as sub
from ..utils import fa_date, fmt_toman, to_fa_digits
from .common import safe_answer

router = Router(name="payment")
log = logging.getLogger(__name__)

awaiting_receipt: dict[int, str] = {}   # bale_id → کد فاکتور
awaiting_reason: dict[int, str] = {}    # admin → کد فاکتور برای رد

KIND_FA = {"new": "اشتراک جدید", "upgrade": "ارتقا", "renewal": "تمدید", "turn": "ثبت نوبت قضائی"}


def invoice_text(inv) -> str:
    services = []
    if inv["notices"]:
        services.append("ابلاغیه")
    if inv["case_alerts"]:
        services.append("اطلاع‌رسانی پرونده")
    return (f"🧾 فاکتور {inv['code']} — {KIND_FA.get(inv['kind'], inv['kind'])}\n"
            + (f"سرویس: {'، '.join(services)}\n" if services else "")
            + f"💰 مبلغ: {fmt_toman(inv['amount_toman'])}\n\n"
            f"💳 شماره کارت: {to_fa_digits(config.CARD_NUMBER or '—')}\n"
            f"👤 به نام: {config.CARD_HOLDER or '—'}   🏦 {config.CARD_BANK or ''}\n\n"
            f"پس از واریز، «📤 ارسال رسید» را بزنید و تصویر رسید را بفرستید.\n"
            f"⏳ مهلت پرداخت: {to_fa_digits(config.INVOICE_EXPIRE_HOURS)} ساعت")


async def show_invoice(bot, chat_id, inv):
    await bot.send_message(chat_id, invoice_text(inv), reply_markup=K.inline(
        [[("📤 ارسال رسید", f"pay:r:{inv['code']}")], [(T.BACK, "nav:main")]]))


@router.callback_query(F.data.startswith("pay:r:"))
async def ask_receipt(cb: CallbackQuery, db):
    code = cb.data.split(":")[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=?", (code, cb.from_user.id))
    if not inv or inv["status"] != "pending" or parse_iso(inv["expires_at"]) < sub.utcnow():
        await safe_answer(cb, "این فاکتور معتبر نیست یا منقضی شده است.", alert=True)
        if inv and inv["status"] == "pending":
            await db.execute("UPDATE invoices SET status='expired' WHERE code=?", (code,))
            await cb.message.answer("⌛ فاکتور منقضی شد.", reply_markup=K.inline([[("🧾 صدور فاکتور جدید", "nav:plans")]]))
        return
    awaiting_receipt[cb.from_user.id] = code
    await safe_answer(cb)
    await cb.message.answer(f"📸 لطفاً تصویر رسید فاکتور {code} را همین‌جا ارسال کنید.")


@router.message(F.photo, F.from_user.id.func(lambda uid: uid in awaiting_receipt))
async def receipt_photo(message: Message, db):
    uid = message.from_user.id
    code = awaiting_receipt.get(uid)
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=?", (code, uid))
    if not inv or inv["status"] != "pending" or parse_iso(inv["expires_at"]) < sub.utcnow():
        awaiting_receipt.pop(uid, None)
        await message.answer("این فاکتور دیگر معتبر نیست.")
        return
    photo = message.photo[-1]
    dup = await db.one("SELECT code FROM invoices WHERE receipt_file_unique_id=?", (photo.file_unique_id,))
    if dup:
        await message.answer("⚠️ این رسید قبلاً ارسال شده است. لطفاً رسید همین پرداخت را بفرستید.")
        return
    await db.execute("UPDATE invoices SET status='receipt_sent', receipt_file_id=?, receipt_file_unique_id=? "
                     "WHERE code=?", (photo.file_id, photo.file_unique_id, code))
    awaiting_receipt.pop(uid, None)
    caption = (f"🧾 رسید جدید\n👤 کاربر: {uid} ({message.from_user.full_name})\nفاکتور: {code}\n"
               f"نوع: {KIND_FA.get(inv['kind'])}\nمبلغ: {fmt_toman(inv['amount_toman'])}"
               + (f"\nپرونده/بایگانی: {inv['payload']}" if inv["payload"] else ""))
    try:
        await message.bot.send_photo(config.ADMIN_ID, photo.file_id, caption=caption, reply_markup=K.inline(
            [[("✅ تأیید", f"adm:ok:{code}"), ("❌ رد (با دلیل)", f"adm:no:{code}")]]))
    except Exception as e:
        await error_reporter.report(message.bot, db, run_id=None, user_id=uid, step="P01", category="PAYMENT",
                                    message=f"send receipt to admin failed: {type(e).__name__}")
    await message.answer("✅ رسید دریافت شد و برای بررسی به مدیر ارسال شد. نتیجه همین‌جا اعلام می‌شود.")


@router.message(F.photo)
async def stray_photo(message: Message):
    await message.answer("برای ارسال رسید، ابتدا در فاکتور روی «📤 ارسال رسید» بزنید.")


@router.callback_query(F.data.startswith("adm:ok:"))
async def admin_ok(cb: CallbackQuery, db):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    code = cb.data.split(":")[2]
    inv = await sub.approve_invoice(db, code, cb.from_user.id)
    if not inv:
        await safe_answer(cb, "قبلاً بررسی شده است.", alert=True)
        return
    await safe_answer(cb, "تأیید شد")
    try:
        await cb.message.edit_caption(caption=(cb.message.caption or "") + "\n\n✅ تأیید شد")
    except Exception:
        pass
    user = await db.get_user(inv["bale_id"])
    if inv["kind"] == "turn":
        await cb.bot.send_message(user["chat_id"], "✅ پرداخت شما تأیید شد. برای شروع ثبت نوبت دکمه‌ی زیر را بزنید.",
                                  reply_markup=K.inline([[("▶️ شروع ثبت نوبت", f"turn:go:{code}")]]))
        return
    s = await sub.get(db, inv["bale_id"])
    await cb.bot.send_message(
        user["chat_id"],
        f"✅ پرداخت تأیید شد؛ اشتراک شما تا {fa_date(parse_iso(s['paid_until']).date())} فعال است.\n\n"
        "مرحله‌ی بعد: در هر بررسی، ربات اعلام می‌کند که برای ورود به اطلاعات ورود نیاز دارد؛ این اطلاعات "
        "ذخیره نمی‌شود.", reply_markup=K.main_menu())


@router.callback_query(F.data.startswith("adm:no:"))
async def admin_no(cb: CallbackQuery):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    awaiting_reason[cb.from_user.id] = cb.data.split(":")[2]
    await safe_answer(cb)
    await cb.message.answer("دلیل رد را بنویسید:")


@router.message(F.text, F.from_user.id.func(lambda uid: uid in awaiting_reason))
async def admin_reason(message: Message, db):
    code = awaiting_reason.pop(message.from_user.id)
    inv = await sub.reject_invoice(db, code, message.from_user.id, message.text[:300])
    if not inv:
        await message.answer("این فاکتور در وضعیت قابل رد نیست.")
        return
    user = await db.get_user(inv["bale_id"])
    await message.bot.send_message(user["chat_id"], f"❌ رسید فاکتور {code} تأیید نشد.\nدلیل: {message.text[:300]}\n"
                                   "در صورت پرداخت صحیح، رسید درست را دوباره ارسال کنید.",
                                   reply_markup=K.inline([[("📤 ارسال رسید", f"pay:r:{code}")]]))
    await message.answer("✅ رد شد و به کاربر اطلاع داده شد.")
