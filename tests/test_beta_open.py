"""BETA_IDS=* ← ربات برای همهٔ کاربران باز است؛ بدون ستاره رفتار قبلی (فهرست بتا) حفظ می‌شود."""
import pytest

from legal_bot import config


@pytest.mark.parametrize("raw,expected", [
    ("*", True),
    ("all", True),
    ("ALL", True),
    ("111, *", True),
    ("111،*", True),
    ("", False),
    ("111,222", False),
    ("allow", False),
])
def test_open_to_all_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("BETA_IDS", raw)
    assert config._open_to_all("BETA_IDS") is expected


async def test_is_beta_open_to_all(db, monkeypatch):
    monkeypatch.setattr(config, "BETA_IDS", {config.ADMIN_ID})
    monkeypatch.setattr(config, "BETA_OPEN_TO_ALL", False)
    assert not await db.is_beta(424242)
    monkeypatch.setattr(config, "BETA_OPEN_TO_ALL", True)
    assert await db.is_beta(424242)
