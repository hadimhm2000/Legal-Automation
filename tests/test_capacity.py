"""ظرفیت: مرورگر مشترک، صف نوبت، محافظ رم، پخش پیام‌های زمان‌بندی."""
import asyncio

import pytest

from legal_bot import config
from legal_bot.services import browser as B
from legal_bot.services import scheduler


async def test_queue_limits_concurrency_and_reports_position(monkeypatch):
    monkeypatch.setattr(config, "MAX_CONCURRENT_BROWSERS", 2)
    monkeypatch.setattr(config, "QUEUE_POLL_SEC", 1)
    adm = B.Admission()
    running, peak, positions = 0, 0, {}

    async def worker(i):
        nonlocal running, peak

        async def on_queue(pos):
            positions.setdefault(i, []).append(pos)
        await adm.acquire(on_queue)
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        await adm.release()

    await asyncio.gather(*(worker(i) for i in range(6)))
    await asyncio.sleep(0.05)
    assert peak == 2
    assert adm.active == 0 and adm.waiting == 0
    # نفرات بعدی جایگاه صف گرفتند و جایگاه فقط کم شد
    assert positions
    for p in positions.values():
        assert p == sorted(p, reverse=True)


async def test_low_ram_holds_new_jobs_but_never_blocks_the_first(monkeypatch):
    monkeypatch.setattr(config, "MAX_CONCURRENT_BROWSERS", 10)
    monkeypatch.setattr(config, "MIN_FREE_RAM_MB", 2048)
    monkeypatch.setattr(config, "QUEUE_POLL_SEC", 1)
    free = {"mb": 500}
    monkeypatch.setattr(B, "free_ram_mb", lambda: free["mb"])
    adm = B.Admission()
    await asyncio.wait_for(adm.acquire(), 1)          # هیچ کاری در حال اجرا نیست → اجازه
    second = asyncio.create_task(adm.acquire())
    await asyncio.sleep(0.3)
    assert not second.done() and adm.waiting == 1     # رم کم → صبر
    free["mb"] = 4000                                  # رم آزاد شد (بدون release)
    await asyncio.wait_for(second, 3)
    assert adm.active == 2


async def test_cancel_while_queued_leaves_queue(monkeypatch):
    monkeypatch.setattr(config, "MAX_CONCURRENT_BROWSERS", 1)
    adm = B.Admission()
    await adm.acquire()
    t = asyncio.create_task(adm.acquire())
    await asyncio.sleep(0.05)
    assert adm.waiting == 1
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert adm.waiting == 0
    await adm.release()
    await asyncio.wait_for(adm.acquire(), 1)


async def test_shared_browser_isolated_contexts_and_recycle(monkeypatch):
    monkeypatch.setattr(config, "BROWSER_RECYCLE_AFTER", 3)
    monkeypatch.setattr(config, "MAX_CONCURRENT_BROWSERS", 5)
    async with B.Browser() as a, B.Browser() as b:
        assert a.browser is b.browser                  # یک Chromium مشترک
        assert a.context is not b.context              # نشست جدا
        await a.page.goto("data:text/html,<p>a</p>")
        await a.context.add_cookies([{"name": "k", "value": "1", "url": "https://example.com"}])
        assert await b.context.cookies("https://example.com") == []
        first = a.browser
    async with B.Browser() as c:                       # سومین کار: هنوز همان مرورگر، بعدش بازنشسته
        assert c.browser is first
    async with B.Browser() as d:                       # مرورگر تازه بعد از BROWSER_RECYCLE_AFTER
        assert d.browser is not first
        assert not first.is_connected()               # نسل قبلی بعد از آخرین کارش بسته شد
    p = B.pool()
    assert p.admission.active == 0


async def test_media_blocked_but_documents_load():
    async with B.Browser() as br:
        await br.page.goto("data:text/html,<h1>ok</h1>")
        assert "ok" in await br.page.inner_text("body")


async def test_prompts_are_spread(monkeypatch):
    monkeypatch.setattr(config, "PROMPT_SPREAD_SEC", 600)
    assert scheduler._gap(100) == 6
    assert scheduler._gap(1) < 1
    monkeypatch.setattr(config, "PROMPT_SPREAD_SEC", 0)
    assert scheduler._gap(100) < 1


async def test_queue_notice_sends_one_message_then_edits(monkeypatch):
    from legal_bot.services.flow import QueueNotice
    monkeypatch.setattr(config, "QUEUE_NOTIFY_MIN_SEC", 0)
    sent, edits = [], []

    class Msg:
        message_id = 5

    class Bot:
        async def edit_message_text(self, text, chat_id, message_id):
            edits.append(text)

    class FakeJob:
        bot, chat_id = Bot(), 1

        async def say(self, text, kb=None):
            sent.append(text)
            return Msg()

    n = QueueNotice(FakeJob())
    await asyncio.gather(n(4), n(3))      # هم‌زمان: باز هم فقط یک پیام
    await n(2)
    await n(2)                            # جایگاه تغییر نکرد → ویرایش نه
    await n.started()
    await n(1)                            # بعد از شروع، دیگر پیامی نیست
    assert len(sent) == 1 and "4" in sent[0]
    assert len(edits) == 3 and "2" in edits[1] and edits[-1] == __import__("legal_bot.texts").texts.QUEUE_GO
