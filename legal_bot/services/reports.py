"""گزارش‌های PDF فارسی (پرونده‌های جاری/به اتمام رسیده/همه، جلسات آینده، فهرست پرونده‌های اطلاع‌رسانی)."""
from __future__ import annotations

import datetime as dt
import io

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import config
from ..utils import fa_date, to_fa_digits, to_jalali_str, today_tehran

_fonts = False


def _ensure_fonts():
    global _fonts
    if not _fonts:
        pdfmetrics.registerFont(TTFont("Vazir", config.FONT_REGULAR))
        pdfmetrics.registerFont(TTFont("VazirB", config.FONT_BOLD))
        _fonts = True


def fa(text) -> str:
    return get_display(arabic_reshaper.reshape(to_fa_digits(str(text if text is not None else "-"))))


def table_pdf(title: str, headers: list[str], rows: list[list], subtitle: str = "") -> bytes:
    _ensure_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=10 * mm, leftMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm, title=title)
    h = ParagraphStyle("h", fontName="VazirB", fontSize=15, alignment=2, leading=22)
    s = ParagraphStyle("s", fontName="Vazir", fontSize=9, alignment=2, leading=14, textColor=colors.grey)
    cell = ParagraphStyle("c", fontName="Vazir", fontSize=8.5, alignment=2, leading=12)
    head = ParagraphStyle("hc", fontName="VazirB", fontSize=9, alignment=1, leading=12, textColor=colors.white)
    story = [Paragraph(fa(title), h)]
    story.append(Paragraph(fa(subtitle or f"تاریخ تهیه: {to_jalali_str(today_tehran())}"), s))
    story.append(Spacer(1, 5 * mm))
    # جدول راست‌به‌چپ: ستون‌ها معکوس می‌شوند
    data = [[Paragraph(fa(x), head) for x in reversed(headers)]]
    for r in rows:
        data.append([Paragraph(fa(x), cell) for x in reversed(r)])
    if len(data) == 1:
        data.append([Paragraph(fa("موردی یافت نشد"), cell)] + [""] * (len(headers) - 1))
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c7ced8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(fa("این گزارش صرفاً جنبه‌ی اطلاع‌رسانی دارد؛ ابلاغ رسمی فقط در سامانه‌ی ثنا معتبر است."), s))
    doc.build(story)
    return buf.getvalue()


def _d(iso):
    try:
        return fa_date(dt.date.fromisoformat(iso)) if iso else "-"
    except ValueError:
        return "-"


async def cases_report(db, bale_id: int, which: str) -> tuple[bytes, str]:
    """which: current | done | all"""
    where = {"current": "AND n.status='open'", "done": "AND n.status='done'", "all": ""}[which]
    title = {"current": "پرونده‌های جاری", "done": "پرونده‌های به اتمام رسیده", "all": "تمام پرونده‌ها"}[which]
    rows = await db.all(
        f"SELECT n.*, (SELECT MIN(due_date) FROM reminders r WHERE r.notice_id=n.id AND r.status='open') due "
        f"FROM notices n WHERE n.bale_id=? {where} ORDER BY n.created_at DESC", (bale_id,))
    data = []
    for i, n in enumerate(rows, 1):
        when = f"{_d(n['hearing_date'])} {n['hearing_time'] or ''}" if n["hearing_date"] else (
            f"مهلت {n['deadline_days']} روز" if n["deadline_days"] else "-")
        data.append([i, n["case_number"] or "-", n["archive_number"] or "-", n["branch"] or "-",
                     n["external_id"], (n["notice_type"] or "-")[:60], when, _d(n["due"]),
                     "جاری" if n["status"] == "open" else "انجام شد"])
    pdf = table_pdf(title, ["ردیف", "شماره پرونده", "شماره بایگانی", "شعبه", "شماره ابلاغیه", "نوع ابلاغیه",
                            "جلسه / مهلت", "موعد بعدی", "وضعیت"], data)
    return pdf, f"{which}_cases.pdf"


async def hearings_report(db, bale_id: int) -> bytes:
    today = today_tehran().isoformat()
    rows = await db.all("SELECT * FROM reminders WHERE bale_id=? AND kind='hearing' AND status='open' "
                        "AND due_date>=? ORDER BY due_date, due_time", (bale_id, today))
    data = [[i, _d(r["due_date"]), r["due_time"] or "-", r["case_number"] or "-", r["archive_number"] or "-",
             r["branch"] or "-"] for i, r in enumerate(rows, 1)]
    return table_pdf("لیست کامل جلسه‌های آینده",
                     ["ردیف", "تاریخ", "ساعت", "شماره پرونده", "شماره بایگانی", "شعبه"], data)


def resultcase_list_pdf(title: str, cases: list[dict]) -> bytes:
    data = [[i, c.get("case_number", "-"), c.get("sub_no", "-"), c.get("archive_number", "-"),
             c.get("branch", "-"), c.get("status", "-"), (c.get("extra") or "")[:80]] for i, c in enumerate(cases, 1)]
    return table_pdf(title, ["ردیف", "شماره پرونده", "ردیف فرعی", "شماره بایگانی", "شعبه", "وضعیت", "توضیحات"], data)
