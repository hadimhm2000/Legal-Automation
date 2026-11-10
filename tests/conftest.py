import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ADMIN_ID", "777")
os.environ.setdefault("HANDOFF_SECRET", "test-secret")

import pytest_asyncio  # noqa: E402

from legal_bot.db import DB  # noqa: E402


@pytest_asyncio.fixture
async def db():
    d = await DB(":memory:").connect()
    yield d
    await d.close()
