"""پردازش متن «روند کار پرونده» (viewModel.caseInfo) و کارت‌های فهرست پرونده‌ها."""
from __future__ import annotations

import hashlib
import re

from ..utils import to_en_digits

_LAYEHE = re.compile(
    r"لایحه\s*به\s*شماره\s*(\d{10,20})\s*مورخ\s*(1[34]\d{2}/\d{1,2}/\d{1,2})\s*از\s*طرف\s*«([^»]+)»")


def extract_lavayeh(case_info: str) -> list[dict]:
    """لوایحی که شماره‌شان بعد از ۴ رقم اول حتماً «220» دارد (مثل 1405 220 876719741)."""
    t = to_en_digits(case_info or "")
    out, seen = [], set()
    for m in _LAYEHE.finditer(t):
        num, date, sender = m.group(1), m.group(2), re.sub(r"\s+", " ", m.group(3)).strip()
        if num[4:7] != "220" or num in seen:
            continue
        seen.add(num)
        out.append({"number": num, "date": date, "sender": sender})
    return out


def last_change(case_info: str) -> str | None:
    m = re.search(r"آخرین\s*تغییر\s*ثبت\s*شده[^\n]*?(1[34]\d{2}/\d{1,2}/\d{1,2})[^\n]*?(\d{1,2}:\d{2})",
                  to_en_digits(case_info or ""))
    return f"{m.group(1)} {m.group(2)}" if m else None


def next_hearing(case_info: str) -> tuple[str, str] | None:
    m = re.search(r"وقت\s*رسیدگی\s*به\s*تاریخ\s*(1[34]\d{2}/\d{1,2}/\d{1,2})\s*راس\s*ساعت\s*(\d{1,2}:\d{2})",
                  to_en_digits(case_info or ""))
    return (m.group(1), m.group(2)) if m else None


def numbered_lines(case_info: str) -> list[str]:
    """خطوط شماره‌دار «۱-…»؛ شماره‌ی ردیف حذف می‌شود تا جابه‌جایی ردیف‌ها تغییر حساب نشود."""
    out = []
    for line in to_en_digits(case_info or "").splitlines():
        line = line.strip()
        m = re.match(r"^\d+\s*[-–]\s*(.+)$", line)
        if m:
            out.append(re.sub(r"\s+", " ", m.group(1)))
    return out


def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()[:16]


def diff_new_lines(case_info: str, old_hashes: set[str]) -> list[str]:
    return [ln for ln in numbered_lines(case_info) if line_hash(ln) not in old_hashes]


def parse_case_card(text: str) -> dict | None:
    t = re.sub(r"\s+", " ", to_en_digits(text or ""))
    m = re.search(r"شماره\s*پرونده\s*[:：]?\s*(\d{14,20})", t)
    if not m:
        return None
    out = {"case_number": m.group(1)}
    for key, pat in (("sub_no", r"ردیف\s*فرعی\s*[:：]?\s*(\d{1,3})"),
                     ("archive_number", r"شماره\s*بایگانی\s*[:：]?\s*(\d{3,15})"),
                     ("branch", r"(شعبه\s*\d+[^:]{0,80}?)(?=\s+\S+\s*[:：]|$)")):
        mm = re.search(pat, t)
        if mm:
            out[key] = mm.group(1).strip()
    out["extra"] = t[:200]
    return out
