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


def test_reminder_dates_validator():
    """اعتبارسنجی تاریخ‌های یادآوری دلخواه (دستور کارفرما): چند تاریخ با ویرگول/خط،
    تاریخ چسبیده («و») و تاریخ گذشته رد می‌شوند؛ تکراری یک‌بار شمرده می‌شود."""
    from legal_bot.handlers.notices import reminder_dates_validator
    from legal_bot.utils import today_tehran, to_jalali_str, parse_jalali

    d1 = today_tehran() + dt.timedelta(days=40)
    d2 = today_tehran() + dt.timedelta(days=80)
    # دو تاریخ جدا (ویرگول و خط جدید) — هر دو معتبر
    out, err = reminder_dates_validator(f"{to_jalali_str(d1)}، {to_jalali_str(d2)}")
    assert err is None and out == [d1, d2]
    # جداکننده‌های فارسی/متن ترکیبی
    out, err = reminder_dates_validator(f"{to_jalali_str(d1)}\n{to_jalali_str(d2)}")
    assert err is None and out == [d1, d2]
    # تاریخ چسبیده با «و» ← رد (یکی از تاریخ‌ها بی‌اعلام نماند)
    out, err = reminder_dates_validator(f"{to_jalali_str(d1)} و {to_jalali_str(d2)}")
    assert out is None and "معتبر نیست" in err
    # تاریخ گذشته ← رد
    out, err = reminder_dates_validator(to_jalali_str(today_tehran() - dt.timedelta(days=3)))
    assert out is None
    # امروز مجاز است
    out, err = reminder_dates_validator(to_jalali_str(today_tehran()))
    assert err is None and out == [today_tehran()]
    # تکراری ← یک‌بار
    out, err = reminder_dates_validator(f"{to_jalali_str(d1)}، {to_jalali_str(d1)}")
    assert err is None and out == [d1]
    # بیش از سقف هر پیام ← رد
    from legal_bot import config
    many = "، ".join(to_jalali_str(today_tehran() + dt.timedelta(days=i))
                     for i in range(1, config.MAX_REMINDER_DATES_PER_MSG + 2))
    out, err = reminder_dates_validator(many)
    assert out is None and "حداکثر" in err
    # تاریخ نامعتبر
    out, err = reminder_dates_validator("جلسه دادگاه")
    assert out is None


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
