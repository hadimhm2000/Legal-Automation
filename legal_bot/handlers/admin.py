from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import config

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
    await message.answer(f"user={u}\nsub={s}\nnotices={n['c'] if n else 0}")


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


@router.message(Command("legal_help"))
async def help_(message: Message):
    await message.answer(
        "🛠 دستورات مدیر\n"
        "/legal_runs — ۱۵ بررسی آخر (نوع، کاربر، وضعیت، آخرین مرحله، خطا)\n"
        "/legal_errors — ۱۵ خطای آخر\n"
        "/legal_user <id> — اشتراک و تعداد ابلاغیه‌های یک کاربر\n"
        "/legal_allow <id> — افزودن به فهرست بتا (در ربات اصلی هم LEGAL_BETA_IDS لازم است)\n"
        "/legal_deny <id> — حذف از فهرست بتا\n"
        "/legal_guide — جایگزینی PDF راهنما (بعد از دستور، فایل را بفرستید)\n"
        "/legal_tick — ارسال دستی یادآوری‌های امروز\n"
        "/legal_load — بار سرور: کارهای هم‌زمان، صف و رم آزاد\n"
        "تأیید/رد رسیدها با دکمه‌های زیر هر رسید انجام می‌شود.")
