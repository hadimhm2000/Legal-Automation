"""ساخت تصویر «کارت بانکی» برای پرداخت کارت‌به‌کارت (برداشت از ربات اصلی —
online.judicial.services.ble / card_payment_image.py).

خروجی: PNG (bytes) شبیه کارت بانکی واقعی با:
  - نام بانک (تشخیص خودکار از ۶ رقم اول کارت یا CARD_BANK)
  - شماره کارت در ۴ گروه ۴ رقمی
  - نام صاحب حساب
  - مبلغ قابل پرداخت (تومان) در نوار پایین تصویر

متن فارسی با arabic_reshaper + python-bidi شکل‌دهی می‌شود؛ اگر نصب نباشند و
Pillow از raqm پشتیبانی کند، از شکل‌دهی داخلی Pillow استفاده می‌شود.
این ماژول هیچ وابستگی به aiogram ندارد و مستقل قابل تست است.
"""
from __future__ import annotations

import io
import logging
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from .. import config

logger = logging.getLogger(__name__)

_FONT_BOLD = config.FONT_BOLD          # assets/fonts/Vazirmatn-FD-Bold.ttf
_FONT_REGULAR = config.FONT_REGULAR    # assets/fonts/Vazirmatn-FD-Regular.ttf

# ── پیشوند ۶ رقمی کارت (BIN) → نام بانک ─────────────────────────────────
BANK_BINS = {
    "603799": "بانک ملی ایران", "589210": "بانک سپه", "627648": "بانک توسعه صادرات",
    "207177": "بانک توسعه صادرات", "627961": "بانک صنعت و معدن", "603770": "بانک کشاورزی",
    "639217": "بانک کشاورزی", "628023": "بانک مسکن", "627760": "پست بانک ایران",
    "502908": "بانک توسعه تعاون", "627412": "بانک اقتصاد نوین", "622106": "بانک پارسیان",
    "639194": "بانک پارسیان", "627884": "بانک پارسیان", "502229": "بانک پاسارگاد",
    "639347": "بانک پاسارگاد", "627488": "بانک کارآفرین", "502910": "بانک کارآفرین",
    "621986": "بانک سامان", "639346": "بانک سینا", "639607": "بانک سرمایه",
    "502806": "بانک شهر", "504706": "بانک شهر", "502938": "بانک دی",
    "603769": "بانک صادرات ایران", "610433": "بانک ملت", "991975": "بانک ملت",
    "627353": "بانک تجارت", "585983": "بانک تجارت", "589463": "بانک رفاه کارگران",
    "627381": "بانک انصار", "505785": "بانک ایران زمین", "636214": "بانک آینده",
    "606373": "بانک قرض‌الحسنه مهر ایران", "504172": "بانک قرض‌الحسنه رسالت",
    "505801": "موسسه اعتباری کوثر", "606256": "موسسه اعتباری ملل",
    "628157": "موسسه اعتباری توسعه", "507677": "موسسه اعتباری نور",
}


def detect_bank(card_number: str) -> str:
    """نام بانک از روی ۶ رقم اول کارت؛ در صورت عدم تشخیص رشتهٔ خالی."""
    digits = "".join(ch for ch in str(card_number or "") if ch.isdigit())
    return BANK_BINS.get(digits[:6], "")


def group_card_number(card_number: str, sep: str = " ") -> str:
    """۶۲۱۹۸۶۱۹۳۶۹۲۹۳۵۴ → «6219 8619 3692 9354»"""
    digits = "".join(ch for ch in str(card_number or "") if ch.isdigit())
    return sep.join(digits[i:i + 4] for i in range(0, len(digits), 4))


# ── شکل‌دهی متن فارسی ────────────────────────────────────────────────────
_HAS_RAQM = features.check("raqm")
try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore

    _HAS_RESHAPER = True
except Exception:  # pragma: no cover - بستگی به محیط دارد
    _HAS_RESHAPER = False


def _fa(text: str, font=None) -> tuple[str, dict]:
    if _HAS_RESHAPER:
        return get_display(arabic_reshaper.reshape(str(text))), {}
    if _HAS_RAQM and (font is None or getattr(font, "layout_engine", None) == ImageFont.Layout.RAQM):
        return str(text), {"direction": "rtl", "language": "fa"}
    return str(text), {}


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        logger.warning("[CARD-IMG] فونت %s پیدا نشد — فونت پیش‌فرض استفاده می‌شود", path)
        return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font, **kw) -> int:
    box = draw.textbbox((0, 0), text, font=font, **kw)
    return box[2] - box[0]


def _draw_rtl(draw, right_x: int, y: int, text: str, font, fill, **extra):
    """رسم متن فارسی با تراز راست روی نقطهٔ right_x."""
    shaped, kw = _fa(text, font)
    kw.update(extra)
    w = _text_w(draw, shaped, font, **kw)
    draw.text((right_x - w, y), shaped, font=font, fill=fill, **kw)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _gradient(size: tuple[int, int], c1, c2) -> Image.Image:
    """گرادیان مورب c1 (بالا-چپ) → c2 (پایین-راست)."""
    w, h = size
    base = Image.new("RGB", (w, h), c1)
    px = base.load()
    denom = float(w + h)
    for y in range(h):
        for x in range(w):
            t = (x + y) / denom
            px[x, y] = (_lerp(c1[0], c2[0], t), _lerp(c1[1], c2[1], t), _lerp(c1[2], c2[2], t))
    return base


def render_card_image(
    card_number: str,
    holder_name: str,
    amount_toman: int | None = None,
    bank_name: str | None = None,
    brand_name: str = "",
    scale: int = 1,
) -> bytes:
    """تصویر PNG کارت بانکی را برمی‌گرداند (bytes).

    card_number: شماره کارت ۱۶ رقمی (فاصله/خط تیره مجاز است)
    holder_name: نام صاحب حساب
    amount_toman: مبلغ قابل پرداخت به تومان — None یعنی نوار مبلغ رسم نشود
    bank_name: نام بانک؛ None یعنی تشخیص خودکار از روی BIN
    brand_name: نام برند سرویس (بالای تصویر، اختیاری)
    """
    bank = bank_name if bank_name is not None else detect_bank(card_number)

    s = max(1, int(scale))
    W, H = 1000 * s, (720 if amount_toman is not None else 600) * s
    card_x0, card_y0 = 60 * s, 50 * s
    card_w, card_h = 880 * s, 520 * s
    card_x1, card_y1 = card_x0 + card_w, card_y0 + card_h
    radius = 44 * s

    # ── پس‌زمینهٔ تیره با هاله‌های رنگی ──
    canvas = Image.new("RGB", (W, H), (6, 8, 15))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-160 * s, -200 * s, 460 * s, 380 * s), fill=(70, 105, 255, 120))
    gd.ellipse((W - 420 * s, H - 380 * s, W + 180 * s, H + 180 * s), fill=(140, 70, 255, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(90 * s))
    canvas.paste(glow, (0, 0), glow)

    # ── سایهٔ کارت ──
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (card_x0 + 10 * s, card_y0 + 26 * s, card_x1 - 10 * s, card_y1 + 26 * s),
        radius=radius, fill=(0, 0, 0, 200))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28 * s))
    canvas.paste(shadow, (0, 0), shadow)

    # ── بدنهٔ کارت (گرادیان آبی → بنفش) ──
    body = _gradient((card_w, card_h), (78, 108, 255), (150, 82, 255))
    deco = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    dd.ellipse((card_w - 360 * s, -260 * s, card_w + 220 * s, 300 * s), fill=(255, 255, 255, 34))
    dd.ellipse((-240 * s, card_h - 230 * s, 300 * s, card_h + 260 * s), fill=(20, 10, 60, 60))
    body = body.convert("RGBA")
    body.alpha_composite(deco)
    mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=radius, fill=255)
    canvas.paste(body, (card_x0, card_y0), mask)

    draw = ImageDraw.Draw(canvas)
    # حاشیهٔ درخشان
    draw.rounded_rectangle((card_x0, card_y0, card_x1 - 1, card_y1 - 1), radius=radius,
                           outline=(210, 220, 255), width=max(1, 2 * s))

    white = (255, 255, 255)
    soft = (226, 232, 255)

    # ── نام بانک (بالا راست) ──
    f_bank = _font(_FONT_BOLD, 40 * s)
    _draw_rtl(draw, card_x1 - 52 * s, card_y0 + 40 * s, bank or "کارت بانکی", f_bank, white)

    # برند سرویس (بالا چپ)
    if brand_name:
        f_brand = _font(_FONT_REGULAR, 26 * s)
        shaped, kw = _fa(brand_name, f_brand)
        draw.text((card_x0 + 52 * s, card_y0 + 50 * s), shaped, font=f_brand, fill=soft, **kw)

    # ── تراشه (چیپ) ──
    cx0, cy0 = card_x0 + 60 * s, card_y0 + 140 * s
    chip = (cx0, cy0, cx0 + 110 * s, cy0 + 82 * s)
    draw.rounded_rectangle(chip, radius=14 * s, fill=(236, 200, 120), outline=(190, 150, 70), width=2 * s)
    for i in range(1, 3):
        yy = cy0 + i * 27 * s
        draw.line((cx0 + 8 * s, yy, cx0 + 102 * s, yy), fill=(190, 150, 70), width=2 * s)
    draw.line((cx0 + 55 * s, cy0 + 6 * s, cx0 + 55 * s, cy0 + 76 * s), fill=(190, 150, 70), width=2 * s)

    # نماد بی‌سیم کنار چیپ
    for i, r in enumerate((20, 34, 48)):
        rr = r * s
        ox, oy = cx0 + 150 * s, cy0 + 41 * s
        draw.arc((ox - rr, oy - rr, ox + rr, oy + rr), start=-45, end=45,
                 fill=(235, 238, 255), width=max(1, 4 * s - i * s))

    # ── شماره کارت: ۴ گروه، چپ‌به‌راست، کل عرض کارت ──
    f_num = _font(_FONT_BOLD, 66 * s)
    groups = group_card_number(card_number).split(" ")
    inner_x0, inner_x1 = card_x0 + 60 * s, card_x1 - 60 * s
    slot = (inner_x1 - inner_x0) / max(1, len(groups))
    ny = card_y0 + 272 * s
    for i, g in enumerate(groups):
        gw = _text_w(draw, g, f_num)
        gx = inner_x0 + slot * i + (slot - gw) / 2
        draw.text((gx + 2 * s, ny + 3 * s), g, font=f_num, fill=(30, 20, 90))
        draw.text((gx, ny), g, font=f_num, fill=white)

    # ── صاحب حساب (پایین راست) ──
    f_label = _font(_FONT_REGULAR, 24 * s)
    f_holder = _font(_FONT_BOLD, 36 * s)
    _draw_rtl(draw, card_x1 - 56 * s, card_y1 - 124 * s, "صاحب حساب", f_label, soft)
    _draw_rtl(draw, card_x1 - 56 * s, card_y1 - 88 * s, holder_name, f_holder, white)

    # ── نوار مبلغ (زیر کارت) ──
    if amount_toman is not None:
        bx0, by0 = card_x0, card_y1 + 34 * s
        bx1, by1 = card_x1, H - 30 * s
        draw.rounded_rectangle((bx0, by0, bx1, by1), radius=26 * s,
                               fill=(20, 26, 48), outline=(90, 110, 210), width=max(1, 2 * s))
        f_amt_label = _font(_FONT_REGULAR, 28 * s)
        f_amt = _font(_FONT_BOLD, 44 * s)
        mid = (by0 + by1) // 2
        _draw_rtl(draw, bx1 - 36 * s, mid - 22 * s, "مبلغ قابل پرداخت:", f_amt_label, (170, 182, 214))
        amount_txt = f"{int(amount_toman):,} تومان"
        shaped, kw = _fa(amount_txt, f_amt)
        draw.text((bx0 + 36 * s, mid - 32 * s), shaped, font=f_amt, fill=white, **kw)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


if __name__ == "__main__":  # تست دستی: python -m legal_bot.services.card_image
    data = render_card_image("6219861936929354", "هادی منتظران", 245000,
                             brand_name=config.CARD_PAY_BRAND)
    out_path = os.path.join(os.path.dirname(config.BASE_DIR), "card_preview.png")
    with open(out_path, "wb") as f:
        f.write(data)
    print("card_preview.png ساخته شد —", len(data), "bytes")
