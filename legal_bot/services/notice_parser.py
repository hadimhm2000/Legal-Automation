"""استخراج اطلاعات مهم از متن نسخه‌ی چاپی ابلاغیه (Report/ENoticePrint.aspx).

نمونه‌ها: 3333.pdf (تاریخ و ساعت حضور دارد) و 2323.pdf («مهلت حضور : ۱۰روز»، بدون تاریخ حضور).
ورودی: متن صفحه (innerText) و در صورت امکان جدول «تاریخ حضور/ساعت حضور» که در مرورگر خوانده شده.
"""
from __future__ import annotations

import re

from ..utils import hhmm_to_time, normalize_fa, parse_jalali

_NUM_WORDS = {"یک": 1, "دو": 2, "سه": 3, "چهار": 4, "پنج": 5, "شش": 6, "هفت": 7, "هشت": 8, "نه": 9,
              "ده": 10, "یازده": 11, "دوازده": 12, "سیزده": 13, "چهارده": 14, "پانزده": 15, "بیست": 20,
              "سی": 30, "چهل": 40, "شصت": 60}

_D = r"(1[34]\d{2}\s*/\s*\d{1,2}\s*/\s*\d{1,2})"


def _field(text, label, pat=r"(\d{5,20})"):
    m = re.search(label + r"\s*[:：]?\s*" + pat, text)
    return m.group(1).strip() if m else None


def parse_notice_text(raw: str, table: dict | None = None) -> dict:
    t = normalize_fa(raw)
    info = {
        "notice_number": _field(t, r"شماره\s*ابلاغیه"),
        "case_number": _field(t, r"شماره\s*پرونده"),
        "archive_number": _field(t, r"شماره\s*بایگانی", r"(\d{3,15})"),
        "issue_date": parse_jalali(_field(t, r"تاریخ\s*تنظیم", _D) or ""),
        "branch": None, "notice_type": None,
        "hearing_date": None, "hearing_time": None, "deadline_days": None, "sent_date": None,
        "hearing_place": None,
    }
    head = t.split("مشخصات ابلاغ")[0] if "مشخصات ابلاغ" in t else t[:600]
    m = re.search(r"(شعبه\s*\d+[^\n\t:]*)", head) or re.search(r"(شعبه\s*\d+[^\n\t:]*)", t)
    if m:
        info["branch"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
    m = re.search(r"نوع\s*ابلاغیه\s*[:：]\s*([^\n]+)", t)
    if m:
        info["notice_type"] = m.group(1).strip()[:150]

    # ۱) جدول (دقیق‌ترین)
    if table:
        d = parse_jalali(table.get("date") or "")
        if d:
            info["hearing_date"] = d
        tm = hhmm_to_time(table.get("time") or "")
        if tm:
            info["hearing_time"] = tm.strftime("%H:%M")
        if table.get("place"):
            info["hearing_place"] = normalize_fa(table["place"]).strip()[:200]
    # ۲) متن ابلاغیه: «تاریخ حضور: ۱۳۹۹/۰۹/۰۹  ساعت حضور : ۱۰:۰۰»
    if not info["hearing_date"]:
        m = re.search(r"تاریخ\s*حضور\s*[:：]\s*" + _D, t)
        if m:
            info["hearing_date"] = parse_jalali(m.group(1))
    if not info["hearing_time"]:
        m = re.search(r"ساعت\s*حضور\s*[:：]\s*(\d{1,2}\s*:\s*\d{2})", t)
        if m:
            tm = hhmm_to_time(m.group(1))
            info["hearing_time"] = tm.strftime("%H:%M") if tm else None
    # «وقت رسیدگی ... به تاریخ X ساعت Y» (متن‌های آزاد)
    if not info["hearing_date"]:
        m = re.search(r"(?:وقت\s*رسیدگی|جلسه\s*رسیدگی)[^\n]{0,40}?" + _D + r"[^\n]{0,20}?ساعت\s*(\d{1,2}:\d{2})", t)
        if m:
            info["hearing_date"] = parse_jalali(m.group(1))
            info["hearing_time"] = m.group(2)

    # ۳) مهلت: «مهلت حضور : ۱۰روز» / «ظرف مهلت ده روز»
    m = re.search(r"مهلت\s*(?:حضور|اقدام|قانونی)?\s*[:：]?\s*(\d{1,3})\s*روز", t)
    if m:
        info["deadline_days"] = int(m.group(1))
    else:
        m = re.search(r"(?:ظرف|مهلت)\s*(?:مدت\s*)?(" + "|".join(_NUM_WORDS) + r")\s*روز", t)
        if m:
            info["deadline_days"] = _NUM_WORDS[m.group(1)]

    m = re.search(r"ابلاغیه\s*در\s*تاریخ\s*" + _D + r"\s*به\s*سامانه", t)
    if m:
        info["sent_date"] = parse_jalali(m.group(1))
    if info["hearing_date"]:
        info["deadline_days"] = None  # جلسه‌ی مشخص بر مهلت مقدم است
    return info


# جدول «تاریخ حضور | ساعت حضور | محل حضور | نوع علت حضور» را در مرورگر می‌خواند
TABLE_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  for (const table of document.querySelectorAll('table')) {
    const rows = Array.from(table.querySelectorAll('tr'));
    for (let i = 0; i < rows.length - 1; i++) {
      const head = Array.from(rows[i].children).map(c => norm(c.innerText));
      const di = head.findIndex(h => h.includes('تاریخ حضور'));
      if (di < 0 || head.length > 8) continue;
      const vals = Array.from(rows[i + 1].children).map(c => norm(c.innerText));
      const ti = head.findIndex(h => h.includes('ساعت حضور'));
      const pi = head.findIndex(h => h.includes('محل حضور'));
      return {date: vals[di] || '', time: ti >= 0 ? (vals[ti] || '') : '', place: pi >= 0 ? (vals[pi] || '') : ''};
    }
  }
  return null;
}
"""
