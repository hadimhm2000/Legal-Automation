"""قواعد یادآوری (توابع خالص + ارسال روزانه).

- جلسه (hearing): ۲ روز قبل، ۱ روز قبل و صبح همان روز.
- مهلت (deadline، مثل «مهلت حضور ۱۰ روز»): هر ۳ روز یک‌بار از تاریخ ابلاغ، روز قبل و روز آخر.
- دلخواه کاربر (custom): ۵ روز مانده، روز قبل و روز آخر.
هر یادآوری دکمه‌ی «✅ مراجعه و انجام شد» دارد که آن را (و یادآوری‌های همان ابلاغیه را) می‌بندد.
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import keyboards as K
from ..utils import fa_date, to_fa_digits, today_tehran, weekday_fa

log = logging.getLogger(__name__)


def should_notify(kind: str, due: dt.date, today: dt.date, start: dt.date | None = None) -> bool:
    left = (due - today).days
    if left < 0:
        return False
    if kind == "hearing":
        return left in (2, 1, 0)
    if kind == "custom":
        return left in (5, 1, 0)
    if kind == "deadline":
        if left in (1, 0):
            return True
        if start is None:
            return False
        since = (today - start).days
        return since > 0 and since % 3 == 0
    return False


def is_expired(due: dt.date, today: dt.date) -> bool:
    return (due - today).days < 0


def reminder_text(r: dict, today: dt.date) -> str:
    due = dt.date.fromisoformat(r["due_date"])
    left = (due - today).days
    when = "امروز" if left == 0 else f"{to_fa_digits(left)} روز مانده"
    if r["kind"] == "hearing":
        head = f"⏰ یادآوری جلسه — {when}"
        line = f"📅 {weekday_fa(due)} {fa_date(due)} ساعت {to_fa_digits(r.get('due_time') or '-')}"
    elif r["kind"] == "deadline":
        head = f"⏳ یادآوری مهلت قانونی — {when}"
        line = f"آخرین مهلت: {weekday_fa(due)} {fa_date(due)}"
    else:
        head = f"🔔 یادآوری شما — {when}"
        line = f"آخرین مهلت اقدام: {weekday_fa(due)} {fa_date(due)}"
    parts = [head, line]
    if r.get("case_number"):
        parts.append(f"پرونده: {to_fa_digits(r['case_number'])}")
    if r.get("archive_number"):
        parts.append(f"شماره بایگانی: {to_fa_digits(r['archive_number'])}")
    if r.get("branch"):
        parts.append(f"شعبه: {to_fa_digits(r['branch'])}")
    if r.get("external_id"):
        parts.append(f"ابلاغیه: {to_fa_digits(r['external_id'])}")
    if r.get("note"):
        parts.append(f"📝 {r['note']}")
    return "\n".join(parts)


def done_kb(rid: int):
    return K.inline([[("✅ مراجعه و انجام شد", f"rem:done:{rid}")]])


async def daily_tick(bot, db, today: dt.date | None = None) -> int:
    today = today or today_tehran()
    sent = 0
    for r in await db.open_reminders():
        try:
            due = dt.date.fromisoformat(r["due_date"])
            start = dt.date.fromisoformat(r["start_date"]) if r.get("start_date") else None
        except (TypeError, ValueError):
            continue
        if is_expired(due, today):
            await db.execute("UPDATE reminders SET status='expired' WHERE id=?", (r["id"],))
            continue
        if r.get("last_sent") == today.isoformat() or not should_notify(r["kind"], due, today, start):
            continue
        user = await db.get_user(r["bale_id"])
        if not user:
            continue
        try:
            await bot.send_message(user["chat_id"], reminder_text(r, today), reply_markup=done_kb(r["id"]))
            await db.execute("UPDATE reminders SET last_sent=? WHERE id=?", (today.isoformat(), r["id"]))
            sent += 1
        except Exception as e:  # pragma: no cover
            log.warning("reminder send failed: %s", type(e).__name__)
    return sent
