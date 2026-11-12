from aiogram.types import (InlineKeyboardButton as IB, InlineKeyboardMarkup, KeyboardButton as KB,
                           ReplyKeyboardMarkup)

from . import texts as T


def reply(rows):
    return ReplyKeyboardMarkup(keyboard=[[KB(text=t) for t in r] for r in rows], resize_keyboard=True)


def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[IB(text=t, callback_data=d) for t, d in r] for r in rows])


def main_menu():
    return reply([[T.M_NOTICES], [T.M_CASES], [T.M_TURN], [T.M_REMINDERS, T.M_SUB],
                  [T.M_GUIDE, T.M_CANCEL], [T.M_WIPE]])


def notices_menu():
    return reply([[T.N_CHECK], [T.N_BY_CASE], [T.N_BY_NOTICE], [T.N_BY_RANGE], [T.N_REPORTS],
                  [T.BACK, T.M_CANCEL]])


def reports_menu():
    return reply([[T.R_CURRENT], [T.R_DONE], [T.R_ALL], [T.R_HEARINGS], [T.R_OPEN_REMINDERS],
                  [T.BACK, T.M_CANCEL]])


def cases_menu():
    return reply([[T.C_ALL], [T.C_LIVE], [T.C_ARCHIVED], [T.C_DETAIL], [T.C_TRACK], [T.BACK, T.M_CANCEL]])


def flow_kb():
    """کیبورد ثابت حین هر فرایند: فقط «بازگشت به منوی اصلی» و «لغو عملیات»."""
    return reply([[T.BACK, T.M_CANCEL]])


def guide_kb():
    return inline([[(T.GUIDE_ACK, "guide:ack")], [(T.BACK, "nav:main")]])


def plans_kb():
    """پلن‌های نهایی ربات (آبان ۱۴۰۵)."""
    return inline([
        [("🎁 شروع رایگان (۲ استعلام)", "plan:free")],
        [("👤 پلن پایه — ۱۰ استعلام", "plan:base")],
        [("👤 پلن برگزیده — ۲۰ استعلام", "plan:select")],
        [("⚖️ پلن پیشرو — ۳۰ استعلام/ماه", "plan:pro")],
        [("⚖️ پلن تخصصی — ۶۰ استعلام/ماه", "plan:expert")],
        [("⚖️ پلن سازمانی — نامحدود", "plan:org")],
        [(T.BACK, "nav:main")],
    ])


def phone_kb():
    """کیبورد تأیید شماره موبایل برای شروع رایگان (دکمه‌ی اشتراک‌گذاری مخاطب + بازگشت)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KB(text=T.PHONE_SEND_BTN, request_contact=True)], [KB(text=T.BACK)]],
        resize_keyboard=True)
