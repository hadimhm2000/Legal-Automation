import asyncio
import types

import pytest

from legal_bot import texts as T
from legal_bot.services.session import Job, JobCancelled, JobManager, UserTimeout, vault


class Bot:
    def __init__(self):
        self.texts = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.texts.append(text)
        return types.SimpleNamespace(message_id=1, reply_markup=reply_markup)

    async def edit_message_reply_markup(self, **kw):
        pass


async def _wait_expect(job):
    while not job._expect:
        await asyncio.sleep(0.01)
    return job._expect


async def test_stale_button_ignored_and_secret_in_vault():
    job = Job(bot=Bot(), user_id=1, chat_id=1, kind="t")
    t = asyncio.create_task(job.ask_secret("pw", "رمز؟"))
    e = await _wait_expect(job)
    old_seq = e.seq
    assert job.waiting_secret()
    job.deliver_text("S3cret")
    e2 = None
    while not e2 or e2.seq == old_seq:
        await asyncio.sleep(0.01)
        e2 = job._expect
    assert not job.deliver_callback(old_seq, 0)          # دکمه‌ی مرحله‌ی قبل بی‌اثر
    assert job.deliver_callback(e2.seq, 0)               # «تأیید»
    assert await t == "pw"
    assert vault.get(job.owner, "pw") == "S3cret"
    assert all("S3cret" not in x for x in job.bot.texts)
    vault.wipe(job.owner)


async def test_back_and_timeout():
    job = Job(bot=Bot(), user_id=2, chat_id=2, kind="t")
    # پیش‌فرض جدید: دکمه‌ی «بازگشت» به سؤال اضافه نمی‌شود (کیبورد پایین ربات وظیفه‌اش را دارد)
    t = asyncio.create_task(job.ask_choice("?", [("a", "A")]))
    e = await _wait_expect(job)
    assert [k for k, _ in e.options] == ["a"]
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    # با back=True مکانیزم بازگشت هنوز کار می‌کند
    t = asyncio.create_task(job.ask_choice("?", [("a", "A")], back=True))
    e = await _wait_expect(job)
    job.deliver_callback(e.seq, [k for k, _ in e.options].index("__back__"))
    with pytest.raises(JobCancelled):
        await t
    with pytest.raises(UserTimeout):
        await job.ask_text("?", timeout=0.05)


async def test_runner_swaps_flow_keyboard_and_returns_to_main():
    """شروع Job ← کیبورد فقط «بازگشت/لغو»؛ پایان Job ← منوی اصلی خودکار."""
    from legal_bot import keyboards as K

    class RecBot(Bot):
        def __init__(self):
            super().__init__()
            self.markups = []

        async def send_message(self, chat_id, text, reply_markup=None, **kw):
            self.texts.append(text)
            self.markups.append(reply_markup)
            return types.SimpleNamespace(message_id=1, reply_markup=reply_markup)

    m = JobManager()
    job = Job(bot=RecBot(), user_id=9, chat_id=9, kind="t")

    async def coro(j):
        await j.say("در حال انجام…")

    assert m.start(job, coro)
    await asyncio.sleep(0.05)
    assert job.bot.texts[0] == T.FLOW_STARTED
    assert job.bot.markups[0] == K.flow_kb()
    await asyncio.sleep(0.05)
    assert not m.busy(9)
    assert job.bot.texts[-1] == T.AUTO_MAIN
    assert job.bot.markups[-1] == K.main_menu()


async def test_manager_one_job_per_user_and_wipe_on_cancel():
    m = JobManager()
    job = Job(bot=Bot(), user_id=3, chat_id=3, kind="t")

    async def coro(j):
        vault.put(j.owner, "nc", "x")
        await asyncio.sleep(10)

    assert m.start(job, coro)
    assert not m.start(Job(bot=Bot(), user_id=3, chat_id=3, kind="t"), coro)
    await asyncio.sleep(0.05)
    assert m.cancel(3)
    await asyncio.sleep(0.05)
    assert vault.is_empty(job.owner) and not m.busy(3)
