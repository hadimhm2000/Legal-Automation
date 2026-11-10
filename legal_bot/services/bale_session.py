"""جلسه‌ی aiogram سازگار با API بله (tapi.bale.ai).

مشکل: aiogram برای ارسال فایل، مقدار فیلد را «attach://file0» می‌فرستد و بایت‌ها را
در یک پارت جداگانه‌ی «file0». API بله مکانیزم attach:// را پشتیبانی نمی‌کند، رشته‌ی
«attach://file0» را آدرس اینترنتی فرض می‌کند و خطای زیر را برمی‌گرداند:

    TelegramBadRequest: Telegram server says - Bad Request: failed to get HTTP URL content

(این دقیقاً خطای مرحله‌ی L11 «ارسال به کاربر» است.)

راه‌حل: وقتی مقدارِ خودِ پارامتر (document/photo/…) یک InputFile باشد، بایت‌ها
مستقیماً زیر همان نام فیلد ارسال می‌شوند — همان قالبی که curl و مستندات رسمی بله
استفاده می‌کنند. تلگرام هم این قالب را می‌پذیرد، پس این جلسه برای هر دو امن است.
منبع راه‌حل: بررسی مقایسه‌ی بدنه‌ی خام درخواست موفق curl و درخواست ناموفق aiogram.
"""
from __future__ import annotations

import logging

from aiohttp import FormData
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods.base import TelegramMethod
from aiogram.types import InputFile

log = logging.getLogger(__name__)


class BaleDirectUploadSession(AiohttpSession):
    """فایل‌ها به‌جای ارجاع attach:// مستقیماً داخل فیلد خودشان آپلود می‌شوند."""

    def build_form_data(self, bot: Bot, method: TelegramMethod) -> FormData:
        try:
            return self._direct_form_data(bot, method)
        except Exception:  # اگر نسخه‌ی aiogram ساختار داخلی را عوض کرد
            log.exception("direct-upload form failed; falling back to aiogram default")
            return super().build_form_data(bot, method)

    def _direct_form_data(self, bot: Bot, method: TelegramMethod) -> FormData:
        form = FormData(quote_fields=False)
        files: dict[str, InputFile] = {}
        for key, value in method.model_dump(warnings=False).items():
            if isinstance(value, InputFile):
                # ⭐ تفاوت با نسخه‌ی پیش‌فرض aiogram: بایت‌ها مستقیم زیر نام فیلد
                form.add_field(key, value.read(bot), filename=value.filename or key)
                continue
            prepared = self.prepare_value(value, bot=bot, files=files)
            if not prepared:
                continue
            form.add_field(key, prepared)
        for key, value in files.items():  # فایل‌های تودرتو (در این پروژه استفاده نمی‌شوند)
            form.add_field(key, value.read(bot), filename=value.filename or key)
        return form
