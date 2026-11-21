from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import config
from ..utils import to_en_digits

router = Router(name="admin")
router.message.filter(F.from_user.id == config.ADMIN_ID if config.ADMIN_ID else F.from_user.id == -1)

_waiting_guide: set[int] = set()


@router.message(Command("legal_runs"))
async def runs(message: Message, db):
    rows = await db.all("SELECT * FROM check_runs ORDER BY id DESC LIMIT 15")
    lines = [f"#{r['id']} {r['kind']} u={r['bale_id']} {r['status']} {r['step']} {r['error_code'] or ''} "
             f"new={r['new_items']} {r['started_at'][5:16]}" for r in rows]
    await message.answer("\n".join(lines) or "-")


@router.message(Command("legal_errors"))
async def errors(message: Message, db):
    rows = await db.all("SELECT * FROM error_events ORDER BY id DESC LIMIT 15")
    await message.answer("\n".join(f"#{r['run_id']} u={r['bale_id']} {r['step']} {r['category']}: {r['message'][:80]}"
                                   for r in rows) or "-")


@router.message(Command("legal_user"))
async def user(message: Message, command: CommandObject, db):
    if not (command.args or "").strip().isdigit():
        await message.answer("/legal_user <id>")
        return
    uid = int(command.args)
    u = await db.get_user(uid)
    s = await db.one("SELECT * FROM subscriptions WHERE bale_id=?", (uid,))
    n = await db.one("SELECT COUNT(*) c FROM notices WHERE bale_id=?", (uid,))
    from ..services import subscription as sub

    lines = [f"user={u}"]
    if s:
        m = sub.plan_meta(s["plan"])
        lines.append(
            f"status={s['status']} plan={s['plan'] or '-'}"
            + (f" ({m.get('title')})" if m else "")
            + f" cycle={s['cycle'] or '-'}")
        lines.append(f"inquiries_left={s['inquiries_left']} quota={s['quota_used']}/{s['quota_total']} "
                     f"month={s['quota_month'] or '-'} free_used={s['free_used']} phone={s['phone'] or '-'}")
        lines.append(f"paid_until={s['paid_until']} restricted_until={s['restricted_until']} "
                     f"reason={s['restriction_reason'] or '-'}")
    from ..services import wallet

    lines.append(f"wallet={await wallet.balance(db, uid):,} تومان")
    from ..services import wallet

    lines.append(f"wallet={await wallet.balance(db, uid):,} تومان")
    lines.append(f"notices={n['c'] if n else 0}")
    await message.answer("\n".join(lines))


@router.message(Command("legal_restrict"))
async def restrict_cmd(message: Message, command: CommandObject, db):
    """قاعده ۶: محدودسازی موقت کاربر — /legal_restrict <id> <ساعت> [دلیل]"""
    args = (command.args or "").split()
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await message.answer("/legal_restrict <id> <hours> [دلیل]")
        return
    uid, hours = int(args[0]), min(int(args[1]), 24 * 365)
    reason = " ".join(args[2:]) or "محدودسازی توسط مدیر (قاعده ۶)"
    from ..services import subscription as sub

    await sub.restrict(db, uid, hours, reason)
    await sub.report_violation(message.bot, db, uid, "محدودسازی دستی توسط مدیر", reason)
    await message.answer(f"✅ کاربر {uid} برای {hours} ساعت محدود شد.\nدلیل: {reason}")


@router.message(Command("legal_unrestrict"))
async def unrestrict_cmd(message: Message, command: CommandObject, db):
    if not (command.args or "").strip().isdigit():
        await message.answer("/legal_unrestrict <id>")
        return
    from ..services import subscription as sub

    await sub.unrestrict(db, int(command.args))
    await message.answer(f"✅ محدودیت کاربر {command.args} برداشته شد.")


@router.message(Command("legal_events"))
async def events_cmd(message: Message, command: CommandObject, db):
    """رویدادهای پلن یک کاربر — تخلف‌ها، فعال‌سازی‌ها، مصرف سهمیه."""
    if not (command.args or "").strip().isdigit():
        await message.answer("/legal_events <id>")
        return
    rows = await db.all("SELECT * FROM plan_events WHERE bale_id=? ORDER BY id DESC LIMIT 20", (int(command.args),))
    await message.answer("\n".join(f"#{r['id']} {r['event']} {r['plan'] or ''} {r['created_at'][5:16]} "
                                   f"{r['detail'] or ''}" for r in rows) or "-")


@router.message(Command("legal_allow"))
async def allow(message: Message, command: CommandObject, db):
    if (command.args or "").strip().isdigit():
        await db.execute("INSERT OR IGNORE INTO beta_allow(bale_id) VALUES(?)", (int(command.args),))
        await message.answer("✅ به فهرست بتا اضافه شد.")


@router.message(Command("legal_deny"))
async def deny(message: Message, command: CommandObject, db):
    if (command.args or "").strip().isdigit():
        await db.execute("DELETE FROM beta_allow WHERE bale_id=?", (int(command.args),))
        await message.answer("✅ از فهرست بتا حذف شد.")


@router.message(Command("legal_guide"))
async def guide(message: Message):
    _waiting_guide.add(message.from_user.id)
    await message.answer("فایل PDF جدید راهنما را بفرستید.")


@router.message(F.document, F.from_user.id.func(lambda u: u in _waiting_guide))
async def guide_file(message: Message, db):
    _waiting_guide.discard(message.from_user.id)
    if (message.document.mime_type or "") != "application/pdf":
        await message.answer("فقط PDF.")
        return
    await db.set_setting("guide_file_id", message.document.file_id)
    v = int(await db.get_setting("guide_version", "1")) + 1
    await db.set_setting("guide_version", v)
    await message.answer(f"✅ راهنمای جدید (نسخه {v}) ثبت شد.")


@router.message(Command("legal_tick"))
async def tick(message: Message, db):
    """اجرای دستی یادآوری‌های امروز (برای تست مدیر)."""
    from ..services.reminders import daily_tick

    n = await daily_tick(message.bot, db)
    await message.answer(f"✅ {n} یادآوری ارسال شد.")


@router.message(Command("legal_load"))
async def load(message: Message):
    from ..services.browser import pool
    from ..services.session import jobs
    st = pool().stats()
    await message.answer(
        "📊 بار سرور (ربات حقوقی)\n"
        f"کار مرورگری در حال اجرا: {st['active']} از {config.MAX_CONCURRENT_BROWSERS}\n"
        f"در صف: {st['waiting']}\n"
        f"کاربرِ دارای فرایند باز: {len(jobs.jobs)}\n"
        f"رم آزاد سرور: {st['free_ram_mb']:,} مگابایت (حداقل لازم: {config.MIN_FREE_RAM_MB:,})")


_KIND_FA = {"refund": "استرداد خطای سامانه", "invoice_use": "کسر برای فاکتور",
            "invoice_release": "بازگشت فاکتور منقضی", "admin": "تغییر مدیر"}


def _toman(n: int) -> str:
    return f"{int(n):,} تومان"


@router.message(Command("legal_wallet"))
async def wallet_cmd(message: Message, command: CommandObject, db):
    from ..services import wallet

    arg = to_en_digits(command.args or "").strip()
    if not arg.isdigit():
        t = await wallet.totals(db)
        top = await db.all("SELECT bale_id, balance_toman FROM wallets WHERE balance_toman>0 "
                           "ORDER BY balance_toman DESC LIMIT 10")
        lines = [f"💼 کیف پول‌ها: {t['holders']} کاربر دارای موجودی — جمع {_toman(t['sum'])}"]
        lines += [f"{r['bale_id']}: {_toman(r['balance_toman'])}" for r in top]
        lines.append("جزئیات: /legal_wallet <id>")
        await message.answer("\n".join(lines))
        return
    uid = int(arg)
    rows = await wallet.history(db, uid, 10)
    lines = [f"💼 کاربر {uid} — موجودی: {_toman(await wallet.balance(db, uid))}"]
    for r in rows:
        sign = "+" if r["delta_toman"] > 0 else ""
        lines.append(f"{r['created_at'][5:16]} {sign}{int(r['delta_toman']):,} "
                     f"{_KIND_FA.get(r['kind'], r['kind'])} [{r['ref'][:14]}]")
    if not rows:
        lines.append("تراکنشی ندارد.")
    await message.answer("\n".join(lines))


@router.message(Command("legal_wallet_add"))
async def wallet_add(message: Message, command: CommandObject, db):
    from ..services import wallet
    from ..utils import to_en_digits

    parts = to_en_digits(command.args or "").split(None, 2)
    try:
        uid, amount = int(parts[0]), int(parts[1])
        if not amount:
            raise ValueError
    except Exception:
        await message.answer("/legal_wallet_add <id> <مبلغ تومان؛ منفی = کسر> [توضیح]")
        return
    ok = await wallet.adjust(db, uid, amount, parts[2] if len(parts) > 2 else "")
    if not ok:
        await message.answer("⚠️ انجام نشد (موجودی نمی‌تواند منفی شود).")
        return
    await message.answer(f"✅ انجام شد. موجودی {uid}: {_toman(await wallet.balance(db, uid))}")


@router.message(Command("legal_help"))
async def help_(message: Message):
    await message.answer(
        "🛠 دستورات مدیر\n"
        "/legal_runs — ۱۵ بررسی آخر (نوع، کاربر، وضعیت، آخرین مرحله، خطا)\n"
        "/legal_errors — ۱۵ خطای آخر\n"
        "/legal_user <id> — پلن، سهمیه و وضعیت یک کاربر\n"
        "/legal_events <id> — رویدادهای پلن کاربر (تخلف، فعال‌سازی، مصرف)\n"
        "/legal_restrict <id> <hours> [دلیل] — محدودیت موقت (قاعده ۶)\n"
        "/legal_unrestrict <id> — برداشتن محدودیت\n"
        "/legal_allow <id> — افزودن به فهرست بتا (در ربات اصلی هم LEGAL_BETA_IDS لازم است)\n"
        "/legal_deny <id> — حذف از فهرست بتا\n"
        "/legal_guide — جایگزینی PDF راهنما (بعد از دستور، فایل را بفرستید)\n"
        "/legal_wallet [id] — کیف پول‌ها / موجودی و تراکنش‌های یک کاربر\n"
        "/legal_wallet_add <id> <مبلغ> [توضیح] — شارژ یا کسر دستی کیف پول (مبلغ منفی = کسر)\n"
        "/legal_tick — ارسال دستی یادآوری‌های امروز\n"
        "/legal_load — بار سرور: کارهای هم‌زمان، صف و رم آزاد\n"
        "تایید/رد/کسری رسیدها با دکمه‌های زیر هر رسید انجام می‌شود؛ گزارش تخلف‌ها خودکار ارسال می‌شود.")
