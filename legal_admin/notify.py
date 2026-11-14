"""ارسال پیام به کاربران از طریق API بله — بدون وابستگی جدید (فقط کتابخانه استاندارد).

در فرایند مستقل پنل، آبجکت ربات (aiogram) در دسترس نیست؛ برای همین sendMessage
مستقیم با POST ساده روی BALE_API_BASE زده می‌شود. راز توکن هرگز در پاسخ‌های API نمی‌آید.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

from legal_bot import config

log = logging.getLogger("legal_admin.notify")


def _api_url(method: str) -> str:
    base = (config.BALE_API_BASE or "https://tapi.bale.ai").rstrip("/")
    return f"{base}/bot{config.LEGAL_BOT_TOKEN}/{method}"


def _post_json(url: str, payload: dict, timeout: float = 15.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - آدرس از تنظیمات است
        return json.loads(resp.read().decode("utf-8") or "{}")


async def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict | None:
    """ارسال پیام متنی (با دکمه اختیاری)؛ خروجی: پاسخ API یا None (هرگز exception نمی‌دهد)."""
    if not config.LEGAL_BOT_TOKEN or not chat_id:
        return None
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return await asyncio.to_thread(_post_json, _api_url("sendMessage"), payload)
    except Exception as e:
        log.warning("sendMessage failed (chat=%s): %s", chat_id, e)
        return None


async def bot_ok() -> dict:
    """بررسی سلامت توکن با getMe — برای ویجت وضعیت بالای پنل."""
    if not config.LEGAL_BOT_TOKEN:
        return {"ok": False, "reason": "LEGAL_BOT_TOKEN تنظیم نشده است"}
    try:
        r = await asyncio.to_thread(_post_json, _api_url("getMe"), {})
        return {"ok": bool(r.get("ok")), "reason": "" if r.get("ok") else "پاسخ API نامعتبر"}
    except Exception as e:
        return {"ok": False, "reason": f"عدم دسترسی به API بله ({type(e).__name__})"}
