"""گزارش خطا به مدیر: قالب، زنجیره‌ی مراحل، پاک‌سازی اطلاعات حساس، خطای کاربر، جلوگیری از سیل."""
import logging

from legal_bot.services import error_reporter as er
from legal_bot.services.session import vault


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


async def test_report_format_and_scrub(db, monkeypatch):
    monkeypatch.setattr(er.config, "ADMIN_ID", 777)
    er._last.clear(); er._recent.clear()
    vault.put((5, "j"), "pw", "Sup3rPass")
    bot = Bot()
    run = await db.create_run(5, "notices_new")
    await er.report(bot, db, run_id=run, user_id=5, step="L07", category="BROWSER_CRASH",
                    message="TimeoutError: fill Sup3rPass into #x 4420160616\nCall log: typing \"Sup3rPass\" "
                            "https://iehraz.adliran.ir/Login?ReturnUrl=x bot123:ABC")
    vault.wipe((5, "j"))
    chat, text = bot.sent[0]
    assert chat == 777
    assert "مرحله L07" in text and "❌L07" in text and "BROWSER_CRASH" in text and f"#{run}" in text
    for leak in ("Sup3rPass", "4420160616", "ReturnUrl", "ABC", "Call log"):
        assert leak not in text, leak
    row = await db.one("SELECT * FROM error_events")
    assert "Sup3rPass" not in row["message"] and "4420160616" not in row["message"]
    assert (await db.one("SELECT status FROM check_runs WHERE id=?", (run,)))["status"] == "failed"


async def test_user_errors_not_sent_and_flood_control(db, monkeypatch):
    monkeypatch.setattr(er.config, "ADMIN_ID", 777)
    er._last.clear(); er._recent.clear()
    bot = Bot()
    await er.report(bot, db, run_id=None, user_id=1, step="L06", category="LOGIN_BAD_CREDENTIALS")
    assert bot.sent == []                                  # خطای کاربر: فقط ثبت آماری
    for _ in range(3):
        await er.report(bot, db, run_id=None, user_id=1, step="L09", category="PARSE_CHANGED")
    assert len(bot.sent) == 1                              # همان خطا در ۵ دقیقه یک بار
    await er.report(bot, db, run_id=None, user_id=2, step="L09", category="PARSE_CHANGED")
    await er.report(bot, db, run_id=None, user_id=3, step="L09", category="PARSE_CHANGED")
    assert "احتمالاً مشکل از سامانه" in bot.sent[-1][1]  # ≥۳ کاربر در یک مرحله


def test_log_filter_scrubs_vault_and_token(caplog):
    import bot_main

    vault.put((9, "k"), "otp", "918273")
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "typed %s at https://a.ir/p?nc=1 bot1:XYZ", ("918273",), None)
    bot_main.RedactFilter().filter(rec)
    vault.wipe((9, "k"))
    assert "918273" not in rec.msg and "nc=1" not in rec.msg and "XYZ" not in rec.msg
