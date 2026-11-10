"""تست تاخیرهای انسانی: بازه‌ی مجاز + احترام به ضریب سرعت (برای تست‌های سریع)."""
from legal_bot import config
from legal_bot.services.browser import human_ms


def test_human_ms_bounds():
    for _ in range(200):
        v = human_ms(1000)
        assert 1000 * config.SPEED_FACTOR <= v <= 1000 * (1 + config.HUMAN_JITTER) * config.SPEED_FACTOR + 1e-6


def test_human_ms_not_constant():
    """مکث‌ها نباید همیشه یکسان باشند (رفتار انسانی)."""
    vals = {round(human_ms(500), 3) for _ in range(60)}
    assert len(vals) > 5
