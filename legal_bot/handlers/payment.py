"""پرداخت کارت‌به‌کارت (همان الگوی ربات اصلی online.judicial.services.ble — فقط بخش کارت‌به‌کارت):

  فاکتور + تصویر کارت بانکی ← دکمه‌های «کپی شماره کارت» / «کپی مبلغ» / «ارسال تصویر رسید»
  ← کاربر عکس یا فایل تصویر/PDF رسید را می‌فرستد ← رسید با جزئیات برای مدیر می‌رود
  ← مدیر: ✅ تایید / ❌ رد (با دلیل) / 💸 کسری (مبلغ واریزی کمتر از فاکتور)
  ← با تایید، پلن فعال می‌شود. در حالت کسری فقط باقی‌مانده از کاربر خواسته می‌شود.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import parse_iso
from ..services import error_reporter, subscription as sub
from ..services.card_image import render_card_image
from ..utils import fa_date, fmt_toman, to_fa_digits
from .common import safe_answer

router = Router(name="payment")
log = logging.getLogger(__name__)

armed_receipt: dict[int, tuple[str, float]] = {}   # bale_id → (کد فاکتور، انقضای مجوز ارسال رسید)
awaiting_reason: dict[int, str] = {}               # مدیر → کد فاکتور برای رد با دلیل دلخواه
awaiting_shortfall: dict[int, str] = {}            # مدیر → کد فاکتور برای مبلغ کسری

KIND_FA = {"new": "خرید پلن", "upgrade": "ارتقای پلن", "renewal": "تمدید", "turn": "ثبت نوبت قضائی"}
REJECT_REASONS = {
    "amt": "مبلغ واریزی با مبلغ فاکتور مطابقت ندارد",
    "bad": "تصویر رسید نامعتبر یا ناخوانا است",
    "nf": "واریزی با این مشخصات در حساب یافت نشد",
    "oth": "رسید توسط پشتیبانی تایید نشد",
}


def _due_toman(inv) -> int:
    """مبلغی که کاربر اکنون باید واریز کند — در حالت کسری، فقط باقی‌مانده."""
    if inv["status"] == "shortfall_wait" and inv["shortfall_toman"]:
        return int(inv["shortfall_toman"])
    return int(inv["amount_toman"] or 0)


def _plan_line(inv) -> str:
    if inv["kind"] == "turn":
        return ""
    p = sub.plan_title(inv["plan"])
    return f"🏷 پلن: {p}" + (f" ({sub.CYCLE_FA.get(inv['cycle'], '')})" if inv["cycle"] else "") + "\n"


def invoice_caption(inv) -> str:
    due = _due_toman(inv)
    short = ("💸 این مبلغ، باقی‌مانده‌ی فاکتور پس از واریز ناقص است.\n\n"
             if inv["status"] == "shortfall_wait" and inv["shortfall_toman"] else "")
    return (
        "💳 پرداخت از طریق کارت به کارت\n\n"
        f"🧾 فاکتور {inv['code']} — {KIND_FA.get(inv['kind'], inv['kind'])}\n"
        + _plan_line(inv)
        + f"💰 مبلغ: {fmt_toman(due)}  ({to_fa_digits(f'{due * 10:,}')} ریال)\n\n"
        + short
        + "🔢 شماره کارت:\n`" + (config.CARD_NUMBER or "—") + "`\n"
        f"👤 به نام: {config.CARD_HOLDER or '—'}"
        + (f"   🏦 {config.CARD_BANK}" if config.CARD_BANK else "") + "\n\n"
        "📸 پس از واریز، تصویر رسید را همین‌جا ارسال کنید تا پس از تایید پشتیبانی، "
        "پلن شما فعال شود.\n"
        f"⏳ مهلت پرداخت: {to_fa_digits(config.INVOICE_EXPIRE_HOURS)} ساعت")


def _offer_kb(code: str):
    return K.inline([
        [("📋 کپی شماره کارت", f"cpay:cc:{code}"), ("💰 کپی مبلغ", f"cpay:ca:{code}")],
        [("📸 ارسال تصویر رسید", f"cpay:up:{code}")],
        [(T.BACK, "nav:main")],
    ])


async def _card_image(amount_toman: int) -> bytes | None:
    if not config.CARD_NUMBER:
        return None
    try:
        return await asyncio.to_thread(
            render_card_image, config.CARD_NUMBER, config.CARD_HOLDER or "—", amount_toman,
            config.CARD_BANK or None, config.CARD_PAY_BRAND)
    except Exception as e:
        log.error("card image render failed: %s", type(e).__name__)
        return None


async def show_invoice(bot, chat_id: int, inv):
    """فاکتور کارت‌به‌کارت: تصویر کارت بانکی + دکمه‌های کپی/ارسال رسید (مثل ربات اصلی)."""
    img = await _card_image(_due_toman(inv))
    if img:
        try:
            await bot.send_photo(chat_id, BufferedInputFile(img, "card.png"),
                                 caption=invoice_caption(inv), parse_mode="Markdown",
                                 reply_markup=_offer_kb(inv["code"]))
            return
        except Exception as e:
            log.warning("send_photo failed (%s) — fallback to text", type(e).__name__)
    await bot.send_message(chat_id, invoice_caption(inv), parse_mode="Markdown",
                           reply_markup=_offer_kb(inv["code"]))


# ── دکمه‌های کاربر: کپی شماره کارت / کپی مبلغ / مجوز ارسال رسید ────────────
@router.callback_query(F.data.startswith("cpay:cc:"))
async def copy_card(cb: CallbackQuery):
    await safe_answer(cb, f"شماره کارت: {config.CARD_NUMBER}", alert=True)
    # پیام جداگانه فقط با شماره — با لمس/نگه‌داشتن در بله کپی می‌شود
    await cb.message.answer(f"`{config.CARD_NUMBER}`", parse_mode="Markdown")


@router.callback_query(F.data.startswith("cpay:ca:"))
async def copy_amount(cb: CallbackQuery, db):
    code = cb.data.split(":", 2)[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=?", (code, cb.from_user.id))
    if not inv or inv["status"] not in ("pending", "shortfall_wait"):
        await safe_answer(cb, "این فاکتور دیگر معتبر نیست.", alert=True)
        return
    due = _due_toman(inv)
    await safe_answer(cb, f"مبلغ: {due:,} تومان = {due * 10:,} ریال".replace(",", "٬"), alert=True)
    await cb.message.answer(f"`{to_fa_digits(due * 10)}`\n☝️ مبلغ به ریال ({fmt_toman(due)})",
                            parse_mode="Markdown")


@router.callback_query(F.data.startswith("cpay:up:"))
async def arm_receipt(cb: CallbackQuery, db):
    import time

    code = cb.data.split(":", 2)[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=?", (code, cb.from_user.id))
    if not inv or inv["status"] not in ("pending", "shortfall_wait") or \
            parse_iso(inv["expires_at"]) < sub.utcnow():
        if inv and inv["status"] == "receipt_sent":
            await safe_answer(cb, "رسید شما قبلاً ارسال شده و در حال بررسی است.", alert=True)
        else:
            await safe_answer(cb, "این فاکتور دیگر معتبر نیست یا منقضی شده است.", alert=True)
        return
    armed_receipt[cb.from_user.id] = (code, time.time() + config.RECEIPT_ARM_SECONDS)
    await safe_answer(cb)
    await cb.message.answer("📸 لطفاً *تصویر رسید واریز* را همین حالا ارسال کنید (عکس یا فایل تصویر/PDF).",
                            parse_mode="Markdown")


def _is_receipt_media(message: Message) -> bool:
    if message.photo:
        return True
    doc = message.document
    if doc:
        mime = (doc.mime_type or "").lower()
        name = (doc.file_name or "").lower()
        return mime.startswith("image/") or mime == "application/pdf" or name.endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic"))
    return False


def _armed_code(uid: int) -> str | None:
    import time

    got = armed_receipt.get(uid)
    if not got:
        return None
    code, until = got
    if until < time.time():
        armed_receipt.pop(uid, None)
        return None
    return code


async def _process_receipt(message: Message, db, inv) -> None:
    uid = message.from_user.id
    if message.photo:
        file_id, uniq, kind = message.photo[-1].file_id, message.photo[-1].file_unique_id, "photo"
    else:
        file_id, uniq, kind = message.document.file_id, message.document.file_unique_id, "document"
    is_shortfall = inv["status"] == "shortfall_wait"
    dup_col = "shortfall_receipt_file_unique_id" if is_shortfall else "receipt_file_unique_id"
    dup = await db.one(f"SELECT code FROM invoices WHERE {dup_col}=?", (uniq,))
    if dup:
        await message.answer("⚠️ این رسید قبلاً ارسال شده است. لطفاً رسید همین پرداخت را بفرستید.")
        return
    if is_shortfall:
        await db.execute("UPDATE invoices SET status='receipt_sent', shortfall_receipt_file_id=?, "
                         "shortfall_receipt_file_unique_id=? WHERE code=?", (file_id, uniq, inv["code"]))
    else:
        await db.execute("UPDATE invoices SET status='receipt_sent', receipt_file_id=?, "
                         "receipt_file_unique_id=? WHERE code=?", (file_id, uniq, inv["code"]))
    armed_receipt.pop(uid, None)
    await message.answer(
        ("✅ رسید باقی‌مانده‌ی مبلغ دریافت شد و برای بررسی به پشتیبانی ارسال گردید.\n"
         if is_shortfall else
         "✅ رسید شما دریافت شد و برای بررسی به پشتیبانی ارسال گردید.\n")
        + "⏳ پس از تایید، پلن شما به‌صورت خودکار فعال می‌شود.")
    await _send_to_admin(message.bot, db, await db.one("SELECT * FROM invoices WHERE code=?", (inv["code"],)),
                         message.from_user.full_name, kind, file_id, is_shortfall)


async def _send_to_admin(bot, db, inv, full_name, kind, file_id, is_shortfall):
    due = inv["amount_toman"] or 0
    caption = (
        ("🧾 رسید باقی‌مانده‌ی مبلغ (کسری) کارت‌به‌کارت" if is_shortfall else "🧾 رسید کارت‌به‌کارت جدید")
        + "\n\n"
        f"📄 نوع درخواست: {KIND_FA.get(inv['kind'], inv['kind'])}\n"
        + _plan_line(inv)
        + f"💰 مبلغ فاکتور: {due:,} تومان ({due * 10:,} ریال)".replace(",", "٬") + "\n"
        + (f"💸 کسری اعلام‌شده به کاربر: {inv['shortfall_toman']:,} تومان\n".replace(",", "٬")
           if inv["shortfall_toman"] else "")
        + f"\n👤 کاربر: {full_name or '—'}\n"
        f"🆔 شناسه بله: {inv['bale_id']}\n"
        f"🔖 کد پیگیری: {inv['code']}\n\n"
        "لطفاً مبلغ واریزی رسید را با مبلغ فاکتور تطبیق دهید.")
    kb = K.inline([
        [("✅ تایید پرداخت", f"adm:ok:{inv['code']}"), ("❌ رد رسید", f"adm:no:{inv['code']}")],
        [("💸 مبلغ واریزی کمتر از فاکتور است (کسری)", f"adm:sf:{inv['code']}")],
    ])
    try:
        if kind == "photo":
            await bot.send_photo(config.ADMIN_ID, file_id, caption=caption, reply_markup=kb)
        else:
            await bot.send_document(config.ADMIN_ID, file_id, caption=caption, reply_markup=kb)
    except Exception as e:
        await error_reporter.report(bot, db, run_id=None, user_id=inv["bale_id"], step="P01",
                                    category="PAYMENT",
                                    message=f"send receipt to admin failed: {type(e).__name__}")


@router.message(F.photo | F.document)
async def receipt_media(message: Message, db):
    uid = message.from_user.id
    code = _armed_code(uid)
    if not code:
        await message.answer("برای ارسال رسید، ابتدا در فاکتور روی «📸 ارسال تصویر رسید» بزنید.")
        return
    if not _is_receipt_media(message):
        await message.answer("لطفاً تصویر رسید (عکس یا فایل تصویر/PDF) را بفرستید.")
        return
    inv = await db.one("SELECT * FROM invoices WHERE code=? AND bale_id=?", (code, uid))
    if not inv or inv["status"] not in ("pending", "shortfall_wait") or \
            parse_iso(inv["expires_at"]) < sub.utcnow():
        armed_receipt.pop(uid, None)
        await message.answer("این فاکتور دیگر معتبر نیست.")
        return
    await _process_receipt(message, db, inv)


# ── تصمیم مدیر: تایید / رد / کسری ──────────────────────────────────────────
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
    await safe_answer(cb, "تایید شد")
    try:
        if cb.message.photo or cb.message.document:
            await cb.message.edit_caption(caption=(cb.message.caption or "") + "\n\n✅ تایید شد")
        else:
            await cb.message.edit_text((cb.message.text or "") + "\n\n✅ تایید شد")
    except Exception:
        pass
    user = await db.get_user(inv["bale_id"])
    if inv["kind"] == "turn":
        await cb.bot.send_message(user["chat_id"], "✅ پرداخت شما تایید شد. برای شروع ثبت نوبت دکمه‌ی زیر را بزنید.",
                                  reply_markup=K.inline([[("▶️ شروع ثبت نوبت", f"turn:go:{code}")]]))
        return
    s = await sub.get(db, inv["bale_id"])
    m = sub.plan_meta(s["plan"])
    if m.get("kind") == "credit":
        body = (f"✅ پرداخت تایید شد؛ پلن «{sub.plan_title(s['plan'])}» فعال است.\n"
                f"📊 اعتبار استعلام باقی‌مانده: {to_fa_digits(s['inquiries_left'])}")
    elif s["plan"]:
        quota = m.get("quota", 0)
        qtxt = ("استعلام نامحدود (سقف روزانه: " + to_fa_digits(config.PLAN_ORG_DAILY_CAP) + ")"
                if quota <= 0 else f"{to_fa_digits(quota)} استعلام در ماه")
        body = (f"✅ پرداخت تایید شد؛ پلن «{sub.plan_title(s['plan'])}» "
                f"({sub.CYCLE_FA.get(s['cycle'], '')}) تا {fa_date(parse_iso(s['paid_until']).date())} فعال است.\n"
                f"📊 سهمیه: {qtxt}\n"
                f"📂 پیگیری خودکار تا {to_fa_digits(m.get('cases', 0))} پرونده")
    else:
        body = "✅ پرداخت تایید شد."
    await cb.bot.send_message(user["chat_id"], body + "\n\n" +
                              "مرحله‌ی بعد: در هر بررسی، ربات برای ورود به اطلاعات سامانه نیاز دارد؛ "
                              "این اطلاعات ذخیره نمی‌شود.", reply_markup=K.main_menu())


@router.callback_query(F.data.startswith("adm:no:"))
async def admin_no(cb: CallbackQuery, db):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    code = cb.data.split(":")[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] not in ("receipt_sent", "shortfall_wait"):
        await safe_answer(cb, "این رسید دیگر در انتظار بررسی نیست.", alert=True)
        return
    await safe_answer(cb)
    rows = [[(r, f"adm:rr:{code}:{k}")] for k, r in REJECT_REASONS.items()]
    rows.append([("✍️ دلیل دیگر", f"adm:rw:{code}")])
    await cb.message.answer("دلیل رد رسید را انتخاب کنید:", reply_markup=K.inline(rows))


@router.callback_query(F.data.startswith("adm:rr:"))
async def admin_reject_reason(cb: CallbackQuery, db):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    _, _, code, key = cb.data.split(":")
    reason = REJECT_REASONS.get(key, "رسید تایید نشد")
    await _reject(cb.bot, cb.message, db, code, reason)


@router.callback_query(F.data.startswith("adm:rw:"))
async def admin_reject_custom(cb: CallbackQuery):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    code = cb.data.split(":")[2]
    awaiting_reason[cb.from_user.id] = code
    await safe_answer(cb)
    await cb.message.answer("دلیل رد را بنویسید:")


async def _reject(bot, target, db, code, reason):
    """target: پیامی که دکمه/متن رد روی آن آمده (answer دارد)."""
    inv = await sub.reject_invoice(db, code, target.from_user.id, reason)
    if not inv:
        await target.answer("این فاکتور در وضعیت قابل رد نیست.")
        return
    user = await db.get_user(inv["bale_id"])
    await bot.send_message(
        user["chat_id"],
        f"❌ رسید فاکتور {code} تایید نشد.\nدلیل: {reason}\n"
        "در صورت پرداخت صحیح، رسید درست را دوباره ارسال کنید.",
        reply_markup=_offer_kb(code))
    await target.answer("✅ رد شد و به کاربر اطلاع داده شد.")


@router.message(F.text, F.from_user.id.func(lambda uid: uid in awaiting_reason))
async def admin_reason_text(message: Message, db):
    code = awaiting_reason.pop(message.from_user.id)
    await _reject(message.bot, message, db, code, message.text[:300])


# ── کسری: مبلغ واریزی کمتر از فاکتور ───────────────────────────────────────
@router.callback_query(F.data.startswith("adm:sf:"))
async def admin_shortfall(cb: CallbackQuery, db):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, "فقط مدیر", alert=True)
        return
    code = cb.data.split(":")[2]
    inv = await db.one("SELECT * FROM invoices WHERE code=?", (code,))
    if not inv or inv["status"] != "receipt_sent":
        await safe_answer(cb, "این رسید دیگر در انتظار بررسی نیست.", alert=True)
        return
    awaiting_shortfall[cb.from_user.id] = code
    await safe_answer(cb)
    await cb.message.answer(f"مبلغ کسری (باقی‌مانده‌ی پرداخت کاربر) را به تومان بنویسید — "
                            f"فاکتور {code}:")


@router.message(F.text, F.from_user.id.func(lambda uid: uid in awaiting_shortfall))
async def admin_shortfall_amount(message: Message, db):
    from ..utils import clean_digits

    code = awaiting_shortfall.pop(message.from_user.id)
    raw = clean_digits(message.text)
    if not raw or not raw.isdigit():
        awaiting_shortfall[message.from_user.id] = code
        await message.answer("❌ فقط عدد (تومان) بفرستید؛ مثلاً 250000")
        return
    inv = await sub.declare_shortfall(db, code, message.from_user.id, int(raw))
    if not inv:
        await message.answer("مبلغ کسری باید کمتر از مبلغ فاکتور و بزرگ‌تر از صفر باشد.")
        return
    await message.answer(f"✅ کسری {fmt_toman(int(raw))} برای کاربر ثبت شد؛ پس از رسید باقی‌مانده، "
                         f"فاکتور با همان دکمه‌ی تایید نهایی می‌شود.")
    user = await db.get_user(inv["bale_id"])
    await message.bot.send_message(
        user["chat_id"],
        "⚠️ مبلغ واریزی شما کمتر از مبلغ فاکتور بود.\n"
        f"💸 باقی‌مانده‌ی قابل پرداخت: {fmt_toman(int(raw))}\n"
        "لطفاً مبلغ باقی‌مانده را واریز کنید و تصویر رسید آن را بفرستید "
        "(دکمه‌ی «ارسال تصویر رسید» در فاکتور زیر):")
    await show_invoice(message.bot, user["chat_id"], inv)
