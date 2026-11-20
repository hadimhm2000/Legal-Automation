"""تنظیمات مستقل پنل مدیریت — عمداً جدا از legal_bot/config.py تا پچ کوچک بماند.

متغیرها (در .env):
    ADMIN_PANEL_HOST      پیش‌فرض 127.0.0.1؛ برای دسترسی از بیرون VPS مقدار 0.0.0.0 (ترجیحاً پشت HTTPS)
    ADMIN_PANEL_PORT      پیش‌فرض 8300 — عمداً دور از 3000 و 3100
    ADMIN_PANEL_PASSWORD  رمز ورود پنل (الزامی)
    ADMIN_PANEL_SECRET    راز کوکی نشست (اختیاری؛ پیش‌فرض از توکن+رمز ساخته می‌شود)
"""
from __future__ import annotations

import hashlib
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


HOST = os.environ.get("ADMIN_PANEL_HOST", "127.0.0.1")   # امن‌ترین پیش‌فرض؛ برای دسترسی بیرونی صریحاً 0.0.0.0 بگذارید
PORT = _int("ADMIN_PANEL_PORT", 8300)
PASSWORD = os.environ.get("ADMIN_PANEL_PASSWORD", "")
SECRET = os.environ.get("ADMIN_PANEL_SECRET", "")
SESSION_HOURS = _int("ADMIN_PANEL_SESSION_HOURS", 12)
# 1 = کوکی نشست فقط روی HTTPS (پشت reverse proxy با TLS)؛ در حالت خودکار از X-Forwarded-Proto تشخیص داده می‌شود
COOKIE_SECURE = os.environ.get("ADMIN_PANEL_COOKIE_SECURE", "0") == "1"

# رمز پیش‌فرض در صورت خالی بودن راز: ترکیب پایدار توکن+رمز (تا ری‌استارت نشست‌ها را نبندد)
if not SECRET:
    from legal_bot import config as _bot_config

    SECRET = hashlib.sha256(
        f"{_bot_config.LEGAL_BOT_TOKEN}|{PASSWORD}".encode("utf-8")).hexdigest()
