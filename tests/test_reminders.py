import datetime as dt

from legal_bot.services.reminders import daily_tick, should_notify

D = dt.date


def test_hearing_two_and_one_day_before():
    due = D(2026, 12, 20)
    hits = [d for d in range(1, 21) if should_notify("hearing", due, D(2026, 12, d))]
    assert hits == [18, 19, 20]


def test_deadline_every_three_days_and_day_before():
    start, due = D(2026, 12, 1), D(2026, 12, 11)  # مهلت ۱۰ روز
    hits = [d for d in range(1, 13) if should_notify("deadline", due, D(2026, 12, d), start)]
    assert hits == [4, 7, 10, 11]


def test_custom_five_days_and_day_before():
    due = D(2026, 11, 21)
    hits = [d for d in range(10, 23) if should_notify("custom", due, D(2026, 11, d))]
    assert hits == [16, 20, 21]


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


async def test_daily_tick_sends_once_and_done_closes(db):
    await db.upsert_user(1, 1)
    nid = await db.save_notice(1, {"notice_number": "991", "case_number": "9909983593000595"})
    rid = await db.add_reminder(1, "hearing", D(2026, 12, 20), notice_id=nid, due_time="10:00",
                                case_number="9909983593000595", archive_number="9900630", branch="شعبه 10")
    bot = FakeBot()
    assert await daily_tick(bot, db, D(2026, 12, 18)) == 1
    assert "۲ روز مانده" in bot.sent[0][1] and "شماره بایگانی" in bot.sent[0][1]
    assert bot.sent[0][2].inline_keyboard[0][0].callback_data == f"rem:done:{rid}"
    assert await daily_tick(bot, db, D(2026, 12, 18)) == 0  # همان روز تکرار نمی‌شود
    await db.close_reminder(rid, 1)
    assert await daily_tick(bot, db, D(2026, 12, 19)) == 0
    n = await db.one("SELECT status FROM notices WHERE id=?", (nid,))
    assert n["status"] == "done"
    await db.add_reminder(1, "hearing", D(2026, 12, 1), case_number="x")
    await daily_tick(bot, db, D(2026, 12, 5))
    r = await db.one("SELECT status FROM reminders WHERE due_date='2026-12-01'")
    assert r["status"] == "expired"
