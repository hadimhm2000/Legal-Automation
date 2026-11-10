"""تست جلسه‌ی بله: فایل باید مستقیماً داخل فیلد خودش آپلود شود (نه ارجاع attach://).

بله مکانیزم attach:// را نمی‌فهمد و خطای «Bad Request: failed to get HTTP URL content»
می‌دهد — همان خطای مرحله‌ی L11 (ارسال به کاربر).
"""
import asyncio

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import SendDocument, SendPhoto
from aiogram.types import BufferedInputFile

from legal_bot.services.bale_session import BaleDirectUploadSession

PDF = b"%PDF-1.4 test-content"


def _form_parts(form):
    """[(نام فیلد, مقدار)] از FormData خام aiohttp — با هر دو چیدمان نسخه‌های aiohttp."""
    parts = []
    for field in getattr(form, "_fields", []):
        headers = field[0] if not isinstance(field[0], str) else field[1]
        name = None
        if hasattr(headers, "get"):
            name = headers.get("name") or headers.get("Content-Disposition")
        if name and "name=" in str(name) and '"' in str(name):
            # چیدمان قدیمی: «form-data; name="document"»
            for piece in str(name).split(";"):
                piece = piece.strip()
                if piece.startswith("name="):
                    name = piece[5:].strip('"')
        parts.append((str(name) if name is not None else None, field[-1]))
    return parts


def _bot():
    # نمونه‌ی واقعی Bot (بدون شبکه) چون prepare_value به bot.default نیاز دارد
    return Bot(token="123456:TEST", session=AiohttpSession())


def test_default_aiogram_uses_attach_reference():
    """مستندسازی علت خطا: نسخه‌ی پیش‌فرض aiogram مقدار attach://file0 می‌فرستد."""
    session = AiohttpSession()
    method = SendDocument(chat_id=1, document=BufferedInputFile(PDF, filename="a.pdf"), caption="x")
    parts = _form_parts(session.build_form_data(_bot(), method))
    values = {n: v for n, v in parts}
    assert any(isinstance(v, str) and v.startswith("attach://") for v in values.values())


def test_bale_session_uploads_document_directly():
    session = BaleDirectUploadSession()
    method = SendDocument(chat_id=1, document=BufferedInputFile(PDF, filename="report.pdf"), caption="سلام")
    parts = _form_parts(session.build_form_data(_bot(), method))
    # هیچ مقدار attach:// نباشد
    assert not any(isinstance(v, str) and v.startswith("attach://") for _, v in parts)
    # خودِ بایت‌های PDF مستقیماً زیر نام «document» بروند (مثل curl)
    doc = next(v for n, v in parts if n == "document")
    if hasattr(doc, "__anext__"):

        async def read_all():
            out = b""
            async for chunk in doc:
                out += chunk
            return out

        import asyncio
        doc = asyncio.run(read_all())
    assert doc == PDF


def test_bale_session_uploads_photo_directly():
    session = BaleDirectUploadSession()
    method = SendPhoto(chat_id=2, photo=BufferedInputFile(b"PNGDATA", filename="captcha.png"))
    parts = _form_parts(session.build_form_data(_bot(), method))
    assert not any(isinstance(v, str) and v.startswith("attach://") for _, v in parts)
    names = [n for n, _ in parts]
    assert "photo" in names
