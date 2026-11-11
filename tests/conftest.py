import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("HANDOFF_SECRET", "test-secret")
# تست‌ها: بدون نمایشگر + تاخیرهای انسانی تقریباً صفر (ضریب سرعت ۰٫۰۲)
os.environ.setdefault("HEADLESS", "1")
os.environ.setdefault("SPEED_FACTOR", "0.02")
os.environ.setdefault("PAGE_SETTLE_MS", "30")
# اطلاع‌رسانی پرونده: تلاش‌های مجدد بدون انتظار (صف پردازش / تاخیر سرویس / تب جزئیات)
os.environ.setdefault("RC_QUEUE_WAIT_SEC", "0")
os.environ.setdefault("RC_SVC_RETRY_SEC", "0")
os.environ.setdefault("RC_TAB_INFO_WAIT_SEC", "2")
os.environ.setdefault("RC_SVC_MAX_TRIES", "2")

import pytest_asyncio  # noqa: E402

from legal_bot.db import DB  # noqa: E402


@pytest_asyncio.fixture
async def db():
    d = await DB(":memory:").connect()
    yield d
    await d.close()


@pytest_asyncio.fixture(autouse=True)
async def _close_browser_pool():
    """مرورگر مشترک هر تست در پایان همان تست بسته می‌شود."""
    yield
    from legal_bot.services.browser import shutdown_pool
    await shutdown_pool()
