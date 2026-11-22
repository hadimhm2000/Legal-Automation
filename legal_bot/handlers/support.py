"""بخش پشتیبانی (اصلاحیه — دستور کارفرما): گفتگوی کاربر ↔ مدیر.

قاعده‌ی اصلی: هیچ پیامی مستقیم ارسال نمی‌شود. فرستنده (کاربر یا مدیر) متن و
تصویر/فایل‌هایش را می‌فرستد و همه در «پیش‌نویس» جمع می‌شود؛ فقط وقتی خودش
دکمه‌ی «✅ تایید و ارسال» را بزند، کل پیش‌نویس برای طرف مقابل ارسال می‌شود.

جریان کاربر:  منوی اصلی «🛟 پشتیبانی» ← متن/عکس/فایل‌ها ← ✅ تایید و ارسال ← برای مدیر.
جریان مدیر:  دکمه‌ی «↩️ پاسخ به کاربر» زیر پیام کاربر ← متن/عکس/فایل‌ها ← ✅ تایید و ارسال ← برای کاربر.

همه‌ی پیام‌های رسیده در جدول support_messages ثبت می‌شوند و در پنل مدیریت
(بخش «پشتیبانی») قابل مشاهده‌اند.

اولویت‌ها (تا پیش‌نویس با فلویهای دیگر تداخل نکند):
  • پاسخ‌های Job فعال (job_input) و دستورات مدیر (admin) قبل از این router پردازش می‌شوند.
  • پیام‌های منو، پیش‌نویس را بی‌صدا لغو می‌کنند و مسیر عادی خودشان را می‌روند.
  • ارسال رسید پرداخت (armed_receipt) و دیکته‌های مدیر (دلیل رد/مبلغ کسری) اولویت دارند.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards as K, texts as T
from ..db import now_iso
from ..utils import now_tehran, to_fa_digits
from .common import safe_answer

router = Router(name="support")
log = logging.getLogger(__name__)

MAX_TEXTS = 20          # سقف متن‌های هر پیش‌نویس
MAX_FILES = 10          # سقف فایل‌های هر پیش‌نویس
DRAFT_TTL = 30 * 60     # انقضای پیش‌نویسِ رهاشده (۳۰ دقیقه)
_CANCELISH = {T.M_CANCEL, T.M_CANCEL_OLD, T.BACK, T.BACK_OLD}


@dataclasses.dataclass
class Draft:
    uid: int                     # فرستنده‌ی پیش‌نویس
    chat_id: int                 # چت فرستنده (برای ویرایش پیام وضعیت)
    to_admin: bool               # True: کاربر → مدیر؛ False: مدیر → کاربر (target)
    target: int | None = None    # مقصد پاسخ مدیر (bale_id کاربر)
    texts: list[str] = dataclasses.field(default_factory=list)
    files: list[dict] = dataclasses.field(default_factory=list)
    created: float = dataclasses.field(default_factory=time.time)
    status_chat: int | None = None
    status_msg_id: int | None = None

    @property
    def label(self) -> str:
        return T.SUPPORT_TO_ADMIN if self.to_admin else T.SUPPORT_TO_USER


# uid → Draft (فقط در RAM؛ با تایید/انصراف/منو/انقضا پاک می‌شود)
composing: dict[int, Draft] = {}


def _alive(uid: int) -> Draft | None:
    d = composing.get(uid)
    if not d:
        return None
    if time.time() - d.created > DRAFT_TTL:
        composing.pop(uid, None)
        return None
    return d


class Composing(Filter):
    """پیام‌هایی که باید به پیش‌نویس پشتیبانی بروند (متن یا رسانه)."""

    def __init__(self, media: bool = False):
        super().__init__()
        self.media = media

    async def __call__(self, message: Message) -> bool:
        from . import payment as pay

        uid = message.from_user.id
        d = _alive(uid)
        if d is None:
            return False
        if self.media:
            # رسید پرداختِ مسلح‌شده اولویت دارد
            return uid not in pay.armed_receipt
        txt = message.text or ""
        if txt in _CANCELISH:
            return True              # لغو پیش‌نویس — هندلر cancel_by_keyboard
        if txt.startswith("/") or txt in T.MENU_TEXTS:
            # خروج از حالت پیش‌نویس: لغو بی‌صدا و ادامه‌ی مسیر عادی منو
            composing.pop(uid, None)
            return False
        # دیکته‌های در انتظار مدیر (دلیل رد / مبلغ کسری) اولویت دارند
        if uid in pay.awaiting_reason or uid in pay.awaiting_shortfall:
            return False
        return True


# ── ورود کاربر به بخش پشتیبانی ────────────────────────────────────────────
@router.message(F.text == T.M_SUPPORT)
async def open_support(message: Message, db):
    from ..services.session import jobs

    if jobs.busy(message.from_user.id):
        await message.answer(T.SUPPORT_BUSY_TEXT)
        return
    d = Draft(uid=message.from_user.id, chat_id=message.chat.id, to_admin=True)
    composing[message.from_user.id] = d
    await _send_status(message.bot, d, header=T.SUPPORT_INTRO_USER)


@router.callback_query(F.data.startswith("sup:reply:"))
async def admin_reply(cb: CallbackQuery, db):
    if cb.from_user.id != config.ADMIN_ID:
        await safe_answer(cb, T.SUPPORT_ONLY_ADMIN, alert=True)
        return
    try:
        target = int(cb.data.rsplit(":", 1)[1])
    except ValueError:
        await safe_answer(cb, "درخواست نامعتبر است.", alert=True)
        return
    user = await db.get_user(target)
    if not user or not user.get("chat_id"):
        await safe_answer(cb, "این کاربر دیگر فعال نیست (chat_id ندارد).", alert=True)
        return
    await safe_answer(cb)
    d = Draft(uid=cb.from_user.id, chat_id=cb.message.chat.id, to_admin=False, target=target)
    composing[cb.from_user.id] = d
    await _send_status(cb.bot, d, header=(
        f"🛟 پاسخ به کاربر {to_fa_digits(target)}"
        + (f" ({user.get('first_name') or '—'})" if user.get("first_name") else "")
        + "\n\nمتن و فایل‌های پاسخ را بفرستید؛ ارسال فقط با «✅ تایید و ارسال» انجام می‌شود."))


# ── افزودن آیتم به پیش‌نویس ────────────────────────────────────────────────
# نکته‌ی ترتیب: لغو با کیبورد باید قبل از افزودن متن ثبت شود (هر دو F.text دارند).
@router.message(F.text.in_(_CANCELISH), Composing())
async def cancel_by_keyboard(message: Message):
    composing.pop(message.from_user.id, None)
    await message.answer(T.SUPPORT_CANCELLED, reply_markup=K.main_menu())


@router.message(F.text, Composing())
async def add_text(message: Message):
    d = _alive(message.from_user.id)
    if d is None:
        return
    if len(d.texts) >= MAX_TEXTS:
        await message.answer(f"⚠️ حداکثر {to_fa_digits(MAX_TEXTS)} متن در هر پیش‌نویس؛ "
                             "اول پیش‌نویس فعلی را ارسال یا خالی کنید.")
        return
    d.texts.append(message.text[:3500])
    await _edit_status(message.bot, d, note=T.SUPPORT_ADDED)


@router.message(F.photo | F.document, Composing(media=True))
async def add_file(message: Message):
    d = _alive(message.from_user.id)
    if d is None:
        return
    if len(d.files) >= MAX_FILES:
        await message.answer(f"⚠️ حداکثر {to_fa_digits(MAX_FILES)} فایل در هر پیش‌نویس؛ "
                             "اول پیش‌نویس فعلی را ارسال یا خالی کنید.")
        return
    if message.photo:
        d.files.append({"file_id": message.photo[-1].file_id, "kind": "photo", "file_name": "photo.jpg"})
    else:
        doc = message.document
        d.files.append({"file_id": doc.file_id, "kind": "document",
                        "file_name": (doc.file_name or "file")[:120]})
    await _edit_status(message.bot, d, note=T.SUPPORT_ADDED)


# ── دکمه‌های پیش‌نویس: تایید و ارسال / خالی‌کردن / انصراف ─────────────────
def _draft_kb():
    return K.inline([
        [(T.SUPPORT_CONFIRM_BTN, "sup:send")],
        [(T.SUPPORT_CLEAR_BTN, "sup:clear"), (T.SUPPORT_CANCEL_BTN, "sup:cancel")],
    ])


def _status_text(d: Draft, note: str = "") -> str:
    return (T.SUPPORT_STATUS.format(to=d.label, texts=to_fa_digits(len(d.texts)),
                                    files=to_fa_digits(len(d.files)))
            + (f"\n\n{note}" if note else ""))


async def _send_status(bot, d: Draft, header: str = ""):
    msg = await bot.send_message(d.chat_id, (header + "\n\n" if header else "") + _status_text(d),
                                 reply_markup=_draft_kb())
    d.status_chat, d.status_msg_id = d.chat_id, msg.message_id


async def _edit_status(bot, d: Draft, note: str = ""):
    """به‌روزرسانی پیام وضعیت؛ اگر ویرایش نشد (پیام قدیمی)، پیام تازه ارسال می‌شود."""
    if d.status_msg_id:
        try:
            await bot.edit_message_text(_status_text(d, note), chat_id=d.status_chat,
                                        message_id=d.status_msg_id, reply_markup=_draft_kb())
            return
        except Exception:
            d.status_msg_id = None
    await _send_status(bot, d)


@router.callback_query(F.data == "sup:send")
async def confirm_send(cb: CallbackQuery, db):
    d = _alive(cb.from_user.id)
    if d is None:
        await safe_answer(cb, "پیش‌نویسی در جریان نیست؛ دوباره «🛟 پشتیبانی» را بزنید.", alert=True)
        return
    if not d.texts and not d.files:
        await safe_answer(cb, T.SUPPORT_DRAFT_EMPTY, alert=True)
        return
    await safe_answer(cb, "در حال ارسال…")
    composing.pop(cb.from_user.id, None)
    try:
        await _deliver(cb.bot, db, d, cb.from_user.full_name or "")
    except Exception:
        log.exception("support deliver failed")
        await cb.message.answer("⚠️ ارسال پیام پشتیبانی ناموفق بود؛ دوباره تلاش کنید.")
        composing[cb.from_user.id] = d


@router.callback_query(F.data == "sup:clear")
async def clear_draft(cb: CallbackQuery):
    d = _alive(cb.from_user.id)
    if d is None:
        await safe_answer(cb, "پیش‌نویسی در جریان نیست.", alert=True)
        return
    d.texts, d.files = [], []
    await safe_answer(cb)
    await _edit_status(cb.bot, d, note=T.SUPPORT_CLEARED)


@router.callback_query(F.data == "sup:cancel")
async def cancel_draft(cb: CallbackQuery):
    d = composing.pop(cb.from_user.id, None)
    if d is None:
        await safe_answer(cb, "پیش‌نویسی در جریان نیست.", alert=True)
        return
    await safe_answer(cb)
    await cb.message.answer(T.SUPPORT_CANCELLED, reply_markup=K.main_menu())


# ── لغو پیش‌نویس با دکمه‌های لغو/بازگشت کیبورد (cancel_by_keyboard بالا) ───


# ── تحویل پیش‌نویس تأییدشده ────────────────────────────────────────────────
async def _deliver(bot, db, d: Draft, sender_name: str):
    body = "\n".join(d.texts)[:4000]
    files_json = json.dumps(d.files, ensure_ascii=False)
    when = now_tehran().strftime("%H:%M")
    if d.to_admin:
        # کاربر → مدیر
        await db.execute(
            "INSERT INTO support_messages(bale_id,sender,body,files,created_at) VALUES(?,?,?,?,?)",
            (d.uid, "user", body, files_json, now_iso()))
        head = ("🛟 پیام پشتیبانی جدید\n"
                f"👤 کاربر: {sender_name or '—'} (آیدی {d.uid})\n"
                f"🕒 ساعت {to_fa_digits(when)}\n\n")
        await bot.send_message(config.ADMIN_ID, head + (body or "(بدون متن)")
                               + (f"\n\n📎 به‌همراه {to_fa_digits(len(d.files))} فایل (پیام بعدی)"
                                  if d.files else ""))
        for i, f in enumerate(d.files, 1):
            cap = (f"📎 پیوست {to_fa_digits(i)} از {to_fa_digits(len(d.files))}"
                   f" — پیام پشتیبانی کاربر {d.uid}")
            try:
                if f["kind"] == "photo":
                    await bot.send_photo(config.ADMIN_ID, f["file_id"], caption=cap)
                else:
                    await bot.send_document(config.ADMIN_ID, f["file_id"], caption=cap)
            except Exception as e:
                log.warning("support file forward failed: %s", type(e).__name__)
        await bot.send_message(
            config.ADMIN_ID,
            "برای پاسخ به این کاربر، دکمه‌ی زیر را بزنید. متن و فایل‌های شما هم ابتدا در "
            "پیش‌نویس جمع می‌شود و فقط با «✅ تایید و ارسال» برای کاربر می‌رود.",
            reply_markup=K.inline([[(T.SUPPORT_REPLY_BTN, f"sup:reply:{d.uid}")]]))
        await bot.send_message(d.chat_id, T.SUPPORT_SENT_USER, reply_markup=K.main_menu())
        return
    # مدیر → کاربر
    target = int(d.target or 0)
    user = await db.get_user(target)
    await db.execute(
        "INSERT INTO support_messages(bale_id,sender,body,files,created_at) VALUES(?,?,?,?,?)",
        (target, "admin", body, files_json, now_iso()))
    if not user or not user.get("chat_id"):
        await bot.send_message(d.chat_id, "⚠️ این کاربر دیگر قابل دسترسی نیست (chat_id ندارد).")
        return
    await bot.send_message(user["chat_id"], "🛟 پاسخ پشتیبانی:\n\n" + (body or "(بدون متن)"))
    for i, f in enumerate(d.files, 1):
        cap = f"📎 پیوست {to_fa_digits(i)} از {to_fa_digits(len(d.files))} — پشتیبانی"
        try:
            if f["kind"] == "photo":
                await bot.send_photo(user["chat_id"], f["file_id"], caption=cap)
            else:
                await bot.send_document(user["chat_id"], f["file_id"], caption=cap)
        except Exception as e:
            log.warning("support file to user failed: %s", type(e).__name__)
    await bot.send_message(d.chat_id, T.SUPPORT_SENT_ADMIN, reply_markup=K.main_menu())
