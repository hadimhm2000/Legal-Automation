"""ثبت نوبت قضائی (adliran.ir/Turn) — ملاقات با دادورز اجرای احکام.

روند (مطابق ضبط‌های واقعی کارفرما — steps / steps 2 / steps 3، آبان ۱۴۰۵):
  «اخذ نوبت بر اساس شماره پرونده» ← «فهرست پرونده های من» ← جستجو با شماره پرونده
  (#txtCaseNoSearch) یا شماره بایگانی (#txtArchiveNoSearch) ← «بازیابی پرونده»
  (استعلام) ← نتیجه برای تأیید کاربر فرستاده می‌شود ← ردیف ← «بررسی اطلاعات
  پرونده فوق» (#btnCheckUnitTurn) ← اگر خودِ سامانه سمت/دادورز را پر کرده بود
  مستقیم «مرحله ی بعدی»؛ وگرنه مثل قبل از کاربر پرسیده می‌شود ← «فهرست علت ها» ←
  همیشه ردیف ۱۵ «درخواست جلب متهم» (فهرست برای کاربر ارسال نمی‌شود — دستور
  کارفرما) ← «متوجه شدم» ← روز و ساعت ← «ثبت و دریافت نوبت» ← «بلی» ← «چاپ».

ثبت چند نوبت (دستور کارفرما): بعد از هر نوبت، «صفحه اصلی» (#btnHome) و همان
روند از ابتدا برای شماره‌ی بعدی — عین ضبط steps.

قواعد روز و ساعت (دستور کارفرما — آبان ۱۴۰۵):
  • روزِ جاری انتخاب نمی‌شود؛ همیشه از «فردا» شروع می‌شود.
  • پنجشنبه، جمعه و تعطیلات رسمی هرگز انتخاب نمی‌شوند؛ خطای «پنجشنبه ها / تعطیل» ← روز بعد.
  • دونه‌دونه روزها چک می‌شوند تا نوبت خالی پیدا شود (عین ضبط steps 2).
  • نوبت‌های «btn-time disable» (State==2، تکمیل ظرفیت) قابل انتخاب نیستند.
  • خطای «در تنظیمات نوبت دهی ... نمی توان علت مراجعه را ... انتخاب نمود» ←
    «مرحله ی قبلی» ← «فهرست علت ها» ← «ارائه دلائل»؛ باز هم نشد ← «پیگیری پرونده».
  • خطای «طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای X لغایت Y فعال
    است.» ← روزهای قبل از X رد می‌شوند؛ روزِ داخل/بعد از Y (بازه‌ی تمام‌شده) ← «ظرفیت
    نوبت‌دهی پر می باشد؛ ساعت ۸ صبح روز بعد مجدداً اقدام نمائید» (دستور کارفرما).
  • sweet-alert «هیچ سمتی ... تعریف نشده است»: در مرحله‌ی شماره پرونده/تعیین دادورز ←
    «امکان نوبت گرفتن نمی باشد»؛ حین ثبت نوبت ← «ظرفیت پر است؛ ساعت ۸ صبح روز بعد».

تقویم جدید سامانه (mds.bootstrap.calendar — HTML ارسالی کارفرما، آبان ۱۴۰۵):
  • تاریخِ هر سلول در data-number="YYYYMMDD" است؛ روز هدف با تطبیق دقیق همین تاریخ
    کلیک می‌شود — سلول‌های ماهِ مجاور (data-nm) و روزهای disabled هرگز کلیک نمی‌شوند
    (باگ: «26»یِ ماهِ گذشته به‌جای «26»یِ ماهِ جاری کلیک می‌شد و روزِ غلط انتخاب می‌شد).
  • ماهِ نمایش‌داده‌شده از دکمه‌ی انتخاب ماه («آبان - 1405») خوانده می‌شود و جلو رفتن
    ماه با دکمه‌ی «ماه بعد» (data-changedatebutton) انجام می‌شود.
  • خطای «با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.» ← همان روز
    ادامه داده نمی‌شود و مستقیم روزِ بعد انتخاب می‌شود (دستور کارفرما)؛ همین روال تا
    نمایش «تأیید و چاپ» (ثبت موفق) ادامه می‌یابد.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re

from playwright.async_api import Page

from .. import config
from .. import texts as T
from ..utils import (fa_date, jalali_of, normalize_fa, parse_jalali, parse_jalali_header, to_fa_digits,
                     turn_candidate_days, weekday_fa)
from . import selectors as S
from .browser import click_text, human_pause, page_text, pdf_of, text_re, visible, wait_first
from .session import FlowError, JobCancelled, UserTimeout

log = logging.getLogger(__name__)

# ردیف‌های «فهرست پرونده های من» که شماره را دارند + دکمه‌ی انتخاب‌شان.
# شماره می‌تواند چند صورت داشته باشد (مثل 0501667 و 501667 — صفرِ ابتدایی).
ROWS_JS = r"""
(nums) => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                              .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660);
  const rows = Array.from(document.querySelectorAll('tr, .card, .list-group-item')).filter(vis);
  const out = [];
  rows.forEach((r, i) => {
    const t = norm(r.innerText || '').replace(/\s+/g, ' ');
    if (!nums || !nums.some(n => n && t.includes(n))) return;
    if (r.querySelector('tr')) return;           // فقط درونی‌ترین ردیف
    const b = r.querySelector('button, a, input[type=radio], input[type=checkbox]');
    if (!b) return;
    b.setAttribute('data-tr', String(i));
    out.push({idx: String(i), text: t.slice(0, 400)});
  });
  return out;
}
"""

# گزینه‌های منوی بازشده (ngMultiSelect / bootstrap dropdown / listbox / مودال)
# متن کامل (تا ۳۰۰ نویسه) برمی‌گردد تا نام کامل دادورز برای کاربر نمایش داده شود.
MENU_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  // برچسب‌های کهنه‌ی منوی قبلی پاک می‌شوند تا کلیک روی عنصر پنهان نرود
  document.querySelectorAll('[data-mi]').forEach(el => el.removeAttribute('data-mi'));
  const menus = Array.from(document.querySelectorAll(
      '.dropdown-menu, [role=listbox], .multiselect-container, .modal.show, .modal.in'))
      .filter(vis);
  const out = [];
  let n = 0;
  for (const m of menus) {
    for (const a of m.querySelectorAll('a, li, label, [role=option], tr, button')) {
      if (!vis(a) || a.querySelector('a, li, label, [role=option]')) continue;
      const t = (a.innerText || '').replace(/\s+/g, ' ').trim();
      if (!t || t.length < 3 || /^(جستجو|بستن|انتخاب همه|حذف همه|×)$/.test(t)) continue;
      a.setAttribute('data-mi', String(n));
      out.push({idx: String(n++), text: t.slice(0, 300)});
    }
  }
  return out;
}
"""

# تقویم روزها: سلول‌های td با شماره‌ی روز + سربرگ ماه/سال + دکمه‌ی ماهِ بعد.
#
# تقویم جدید سامانه (mds.bootstrap.calendar — HTML ارسالی کارفرما، آبان ۱۴۰۵):
#   • تاریخ هر سلول در data-number="YYYYMMDD" است ← روز هدف با تطبیق دقیق همین
#     تاریخ انتخاب می‌شود؛
#   • سلول‌های ماهِ مجاور (ویژگی data-nm) هرگز کلیک نمی‌شوند — «26»یِ ماهِ گذشته
#     در DOM پیش از «26»یِ ماهِ جاری است و باگِ انتخابِ روزِ غلط می‌سازد؛
#   • روزهای غیرقابل انتخاب (گذشته/جمعه/تعطیل) ویژگی disabled دارند؛
#   • ماهِ نمایش‌داده‌شده در دکمه‌ی #…MonthSelectorButon («آبان - 1405») است — نه در
#     سربرگِ تاریخِ انتخاب‌شده («دوشنبه، 25 آبان 1405») که با جلو رفتن ماه عوض نمی‌شود؛
#   • جلو رفتن ماه با دکمه‌ی «ماه بعد» (data-changedatebutton) است.
# روزهای غیرفعال (disabled/old/past/...) حذف می‌شوند؛ انتخاب همیشه از «فردا» است.
DAYS_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                              .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660).trim();
  const out = {cells: [], header: '', has_next: false};
  document.querySelectorAll('td').forEach((el, i) => {
    if (!vis(el)) return;
    const t = norm(el.innerText);
    if (!/^\d{1,2}$/.test(t) || +t < 1 || +t > 31) return;
    if (el.hasAttribute('data-nm')) return;    // روزِ ماهِ مجاور (تقویم mds) — هرگز
    const cls = (el.className + ' ' + (el.parentElement ? el.parentElement.className : '')).toLowerCase();
    if (/disabled|old|off|past|holiday|unavailable|text-muted/.test(cls)) return;
    if (el.hasAttribute('disabled')) return;   // روزهای گذشته/جمعه (تقویم mds)
    if (el.getAttribute('aria-disabled') === 'true') return;
    el.setAttribute('data-lb-day', String(i));
    out.cells.push({idx: String(i), day: t,
                    number: norm(el.getAttribute('data-number') || '')});
  });
  // ماهِ نمایش‌داده‌شده: اول دکمه‌ی انتخاب ماهِ تقویم mds («آبان - 1405»)؛
  // وگرنه سربرگ‌های قدیمی (th/strong/... با سال شمسی — تقویم‌های bootstrap).
  const mbtn = document.querySelector('#mdsBootstrapPersianDatetimePickerMonthSelectorButon');
  if (mbtn && vis(mbtn)) {
    const t = norm(mbtn.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && /1[34]\d{2}/.test(t)) out.header = t;
  }
  if (!out.header) {
    for (const el of document.querySelectorAll('th, strong, b, .datepicker-switch, .switch, .uib-title, [role=columnheader]')) {
      if (!vis(el)) continue;
      const t = norm(el.innerText || '').replace(/\s+/g, ' ').trim();
      if (t && /1[34]\d{2}/.test(t) && t.length <= 40) { out.header = t; break; }
    }
  }
  // فلشِ «ماه بعد»: تقویم mds (button[data-changedatebutton] با عنوان «ماه بعد»)
  // یا انتخابگرهای قدیمی bootstrap — فقط دکمه‌ی فعال و قابل‌مشاهده.
  const nextSel = ['button[data-changedatebutton][title="ماه بعد"]',
                   'button[data-changedatebutton][tooltip="ماه بعد"]',
                   'th button[ng-click="move(1)"]', '.next', 'th.next',
                   'button.next', 'a.next', '.glyphicon-chevron-right', '.glyphicon-chevron-left'];
  for (const sel of nextSel) {
    try {
      for (const el of document.querySelectorAll(sel)) {
        if (vis(el) && !el.disabled && el.getAttribute('disabled') === null) {
          el.setAttribute('data-lb-next', '1'); out.has_next = true; return out;
        }
      }
    } catch (e) {}
  }
  return out;
}
"""

# جدول ساعت‌های روزِ انتخابی (TheDailyTurnList): هر نوبت یک div.btn-time است.
# کلاس «disable» یعنی State==2 (تکمیل ظرفیت) و قابل انتخاب نیست — این ساعت‌ها
# کلیک نمی‌شوند و اگر همه‌ی ساعت‌های روز disable بود، روز بعدی انتخاب می‌شود.
TIMES_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                              .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660).trim();
  const out = [];
  document.querySelectorAll('div, span, button, a, label').forEach((el, i) => {
    if (!vis(el) || el.children.length) return;
    const t = norm(el.innerText);
    const m = t.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);   // «11:-51» نامعتبر رد می‌شود
    if (!m) return;
    const cls = ' ' + (el.className || '').toString().toLowerCase() + ' ';
    const full = /[\s"](disable|disabled|reserved|full|taken)[\s"]/.test(cls)
                 || el.getAttribute('aria-disabled') === 'true';
    el.setAttribute('data-time', String(i));
    out.push({idx: String(i), time: t, full: full});
  });
  return out;
}
"""

# پنهان‌کردن پیام کهنه‌ی سامانه (مثل <p style="display:block;"> خطای علت مراجعه یا
# بازه‌ی فعال نوبت‌دهی) تا در بررسی‌های بعدی همان پیام دوباره خوانده نشود.
# فقط عنصرهای برگِ قابل‌مشاهده‌ای که «همه‌ی» واژه‌های خواسته‌شده را دارند.
HIDE_MSG_JS = r"""
(words) => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  let n = 0;
  document.querySelectorAll('p, div, span, label, h2, h3').forEach(el => {
    if (!vis(el) || el.children.length) return;
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 400) return;
    if (words.every(w => t.indexOf(w) !== -1)) { el.style.display = 'none'; n++; }
  });
  return n;
}
"""


def is_execution_branch(text: str) -> bool:
    t = normalize_fa(text)
    return any(normalize_fa(w) in t for w in S.EXECUTION_WORDS)


def branch_of(text: str) -> str:
    t = normalize_fa(text)
    m = re.search(r"((?:اجرای?\s*احکام\s*)?شعبه\s*\d+[^|\n]{0,80})", t)
    return (m.group(1) if m else t[:120]).strip()


def _is_range_error(txt: str) -> bool:
    """«طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای ... فعال است.»"""
    t = normalize_fa(txt or "")
    return all(w in t for w in S.RANGE_ERROR_WORDS)


def _is_capacity_error(txt: str) -> bool:
    """«با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.» (HTML
    ارسالی کارفرما): ظرفیتِ روزِ انتخاب‌شده تمام شده ← مستقیم روزِ بعد."""
    t = normalize_fa(txt or "")
    return all(w in t for w in S.CAPACITY_ERROR_WORDS)


class Turn:
    def __init__(self, ctx, br, login, page: Page):
        self.ctx, self.br, self.login, self.page = ctx, br, login, page
        self.job = ctx.job
        # وضعیت هر پرونده (در select_case برای هر نوبتِ تازه از نو مقدار می‌گیرد):
        self._reset_case_state()

    def _reset_case_state(self):
        """هر پرونده/بایگانی از نو شروع می‌شود (ثبت چند نوبت — ضبط steps)."""
        # علت‌های جایگزینِ خطای علت مراجعه: «ارائه دلائل» سپس «پیگیری پرونده»
        self._reason_fallbacks: list[str] = list(S.TURN_REASON_FALLBACKS)
        self._active_range: tuple[dt.date | None, dt.date | None] = (None, None)
        self._last_create_error = ""                # متن هشدارِ آخرین ثبتِ ناموفق

    # ── پیام‌های سامانه (sweet-alert / alert-danger / h2) ──────────────
    async def _alert_text(self) -> str:
        """متن اولین پیام بازِ سامانه (sweet-alert و مانند آن)؛ نبود → خالی."""
        for sel in (S.ALERT_SWEET, ".alert-danger", "h2"):
            try:
                loc = self.page.locator(sel)
                for i in range(await loc.count()):
                    el = loc.nth(i)
                    if await el.is_visible():
                        t = normalize_fa(await el.inner_text(timeout=2_000)).strip()
                        if t:
                            return t
            except Exception:
                continue
        return ""

    async def _close_alert(self):
        """بستن پیام سامانه (دکمه‌ی «بستن» sweet-alert) تا مسیر ادامه پیدا کند."""
        await click_text(self.page, *S.TURN_CLOSE, timeout=3_000)

    async def _hide_message(self, words):
        """پنهان‌کردن پیام کهنه (خطای علت مراجعه/بازه‌ی فعال) روی خود صفحه."""
        with contextlib.suppress(Exception):
            await self.page.evaluate(HIDE_MSG_JS, list(words))

    async def _role_error(self) -> str:
        """sweet-alert «هیچ سمتی ... تعریف نشده است» (HTML ارسالی کارفرما)."""
        txt = await self._alert_text() or await page_text(self.page)
        if all(normalize_fa(w) in txt for w in S.ROLE_ERROR_WORDS):
            return txt
        return ""

    async def _role_or_raise(self):
        """خطای «هیچ سمتی» در مرحله‌ی شماره پرونده / تعیین دادورز (دستور کارفرما):
        به کاربر اعلام می‌شود که امکان نوبت گرفتن نمی باشد."""
        err = await self._role_error()
        if err:
            await self._close_alert()
            raise FlowError("TURN_NO_ROLE", err[:200], T.TURN_NO_ROLE)

    async def _day_error(self) -> str:
        """خطای روزِ انتخابی (پنجشنبه/تعطیل رسمی/عدم حضور دادورز) ← روز بعد انتخاب شود."""
        txt = await self._alert_text()
        if not txt:
            return ""
        if _is_capacity_error(txt):
            return ""                 # خطای ظرفیت است؛ جداگانه (روزِ بعد) رسیدگی می‌شود
        if "علت مراجعه" in txt or "هیچ سمتی" in txt:
            return ""                 # خطای علت مراجعه/سمت است؛ جداگانه رسیدگی می‌شود
        if any(w in txt for w in S.DAY_BLOCKED_WORDS):
            return txt
        if "نمی توان" in txt and "انتخاب" in txt:
            return txt
        return ""

    async def _reason_error(self) -> str:
        """خطای «در تنظیمات نوبت دهی ... نمی توان علت مراجعه را ... انتخاب نمود».

        متن خطا یک <p> ساده روی صفحه است، بنابراین کل متن صفحه بررسی می‌شود."""
        txt = await page_text(self.page)
        if "علت مراجعه" in txt and "نمی توان" in txt and "انتخاب" in txt:
            return txt
        return ""

    async def _capacity_error(self) -> str:
        """خطای «با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.»
        (دستور کارفرما — sweet-alert با <h2>، HTML ارسالی): ظرفیتِ همین روز تمام
        شده ← مستقیم روزِ بعد؛ ساعتِ بعدیِ همان روز امتحان نمی‌شود."""
        txt = await self._alert_text()
        return txt if _is_capacity_error(txt) else ""

    async def _range_error(self) -> str:
        """خطای بازه‌ی فعال نوبت‌دهی شعبه (ضبط steps 2 — دستور کارفرما):

        «طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای 1405/08/26 لغایت
        1405/09/05 فعال است.» — در هشدارِ آخرین ثبتِ ناموفق، sweet-alertِ باز یا
        متن صفحه (<p style="display:block;">) ظاهر می‌شود."""
        for txt in (self._last_create_error, await self._alert_text()):
            if _is_range_error(txt):
                self._last_create_error = ""
                return txt
        txt = await page_text(self.page)
        if _is_range_error(txt):
            for line in txt.splitlines():
                if _is_range_error(line):
                    return line.strip()[:300]
        return ""

    @staticmethod
    def _parse_active_range(txt: str) -> tuple[dt.date | None, dt.date | None]:
        """«روزهای 1405/08/26 لغایت 1405/09/05» ← (شروعِ بازه، پایانِ بازه)."""
        t = normalize_fa(txt or "")
        m = re.search(r"(\d{4}/\d{1,2}/\d{1,2})\s*لغایت\s*(\d{4}/\d{1,2}/\d{1,2})", t)
        if not m:
            return None, None
        return parse_jalali(m.group(1)), parse_jalali(m.group(2))

    async def _handle_range_error(self, txt: str, target: dt.date) -> bool:
        """رسیدگی به خطای بازه‌ی فعال (دستور کارفرما — ضبط steps 2).

        روزِ قبل از شروعِ بازه → True (این روز رد شود؛ پیاده‌رویِ دونه‌دونه از
        روزِ شروعِ بازه ادامه می‌یابد)؛ روزِ داخل/بعد از پایانِ بازه ← کلِ بازه‌ی
        فعال امتحان/پر شده ← پرش TURN_CAPACITY_FULL: «کامل پر است؛ ساعت ۸ صبح
        روز بعد مجدداً اقدام نمائید»."""
        await self._close_alert()
        start, end = self._parse_active_range(txt)
        self._active_range = (start, end)
        await self._hide_message(S.RANGE_ERROR_WORDS)   # پیام کهنه دوباره خوانده نشود
        if start and target < start:
            log.info("turn: day %s before active range %s..%s", target, start, end)
            return True
        raise FlowError("TURN_CAPACITY_FULL", f"active range full: {txt[:150]}", T.TURN_FULL_RANGE)

    # ── منوها ──
    async def _menu(self) -> list[dict]:
        await self.page.wait_for_timeout(900)
        return await self.page.evaluate(MENU_JS)

    async def _click_menu(self, idx):
        loc = self.page.locator(f'[data-mi="{idx}"]')
        # فقط عنصرِ قابل‌مشاهده کلیک می‌شود (برچسبِ کهسته‌ی منوی بسته‌شده ممکن است مانده باشد)
        with contextlib.suppress(Exception):
            for i in range(await loc.count()):
                el = loc.nth(i)
                if await el.is_visible():
                    await el.click()
                    await human_pause(self.page, 1200)
                    return
        await loc.first.click()
        await human_pause(self.page, 1200)

    async def _choose(self, items: list[dict], prompt: str, confirm_single: str) -> dict:
        """فهرست کامل متنِ هر گزینه در پیام نمایش داده می‌شود و دکمه‌ها فقط شماره‌دارند —
        متن کامل دادورزها (شعبه/میز کار/نام) برای کاربر بریده نمی‌شود (دستور کارفرما)."""
        if len(items) == 1:
            await self.job.ask_choice(confirm_single.format(to_fa_digits(items[0]["text"])),
                                      [("ok", "✅ تأیید")])
            return items[0]
        shown = items[:20]
        lines = [prompt]
        for i, it in enumerate(shown, 1):
            lines.append(f"{to_fa_digits(i)}. {to_fa_digits(it['text'])}")
        opts = [(it["idx"], to_fa_digits(i)) for i, it in enumerate(shown, 1)]
        idx = await self.job.ask_choice("\n".join(lines), opts, grid=4)
        return next(it for it in shown if it["idx"] == idx)

    # ── مراحل ──
    async def select_case(self, number: str, by: str):
        """جستجوی پرونده در «فهرست پرونده های من» (ضبط steps — دستور کارفرما):

        شماره بایگانی/پرونده در فیلد مربوطه پر می‌شود ← «بازیابی پرونده»
        (استعلام) ← نتیجه برای تأیید کاربر فرستاده می‌شود ← ردیف ← دکمه‌ی انتخاب
        ← «بررسی اطلاعات پرونده فوق».
        """
        self._reset_case_state()
        await human_pause(self.page, 2000)
        if not await click_text(self.page, *S.TURN_BY_CASE, timeout=15_000):
            raise FlowError("PARSE_CHANGED", "turn: 'by case number' card not found")
        await human_pause(self.page, 2000)
        rows = []
        if await visible(self.page.locator(S.TURN_MY_CASES), timeout=8000):
            await self.page.locator(S.TURN_MY_CASES).first.click()
            await human_pause(self.page, 1500)
            # جستجو با شماره پرونده (#txtCaseNoSearch) یا شماره بایگانی شعبه
            # (#txtArchiveNoSearch) — هر دو صورتِ شماره (با/بدون صفرِ ابتدایی) می‌گردد.
            field = S.TURN_MY_CASES_SEARCH if by == "case" else S.TURN_ARCHIVE_SEARCH
            box = self.page.locator(field).first
            if await visible(box, timeout=5000):
                await box.fill(number)
            if not await click_text(self.page, *S.TURN_MY_CASES_GO, timeout=6000):
                raise FlowError("PARSE_CHANGED", "turn: retrieve-cases button not found")
            await human_pause(self.page, 3000)
            nums = {number, (number or "").lstrip("0")} - {""}
            rows = await self.page.evaluate(ROWS_JS, sorted(nums))
            if not rows:
                # شاید sweet-alertِ «یافت نشد» باز باشد؛ بسته می‌شود تا پیام خطا بیاید
                await self._close_alert()
        if rows:
            if by == "case":
                ex = [r for r in rows if is_execution_branch(r["text"])]
                if not ex:
                    raise FlowError("NO_EXECUTION_BRANCH", "no execution branch",
                                    "⚠️ برای این پرونده شعبه‌ی «اجرای احکام» پیدا نشد؛ نوبت دادورز فقط برای پرونده‌های "
                                    "اجرای احکام ثبت می‌شود. مبلغ پرداختی توسط مدیر بررسی و پیگیری می‌شود.")
                items = [{"idx": r["idx"], "text": branch_of(r["text"])} for r in ex]
                chosen = await self._choose(items, "شعبه‌ی اجرای احکام مورد نظر را انتخاب کنید:",
                                            "شعبه‌ی استخراج‌شده:\n{}\nتأیید می‌کنید؟")
            else:
                # شماره بایگانی: نتیجه‌ی استعلام برای تأیید کاربر فرستاده می‌شود
                # (دستور کارفرما — «بعد برای کاربر میفرستی که تایید کند»)
                ex = [r for r in rows if is_execution_branch(r["text"])] or rows
                items = [{"idx": r["idx"], "text": r["text"]} for r in ex]
                chosen = await self._choose(items, "پرونده‌ی پیدا شده برای این شماره بایگانی:",
                                            "پرونده:\n{}\nتأیید می‌کنید؟")
            await self.page.locator(f'[data-tr="{chosen["idx"]}"]').first.click()
            await human_pause(self.page, 1200)
            # دکمه‌ی «انتخاب» همان ردیف (ضبط steps: td:nth-of-type(2) > button)
            with contextlib.suppress(Exception):
                row_btn = self.page.locator(f'[data-tr="{chosen["idx"]}"] button').first
                if await visible(row_btn, timeout=2500):
                    await row_btn.click()
                    await human_pause(self.page, 1200)
        elif by == "case" and await visible(self.page.locator(S.TURN_CASE_INPUT)):
            el = self.page.locator(S.TURN_CASE_INPUT).first
            await el.click()
            await el.fill(number)
        else:
            raise FlowError("CASE_NOT_FOUND", "case not in my-cases",
                            f"⚠️ پرونده‌ی {to_fa_digits(number)} در «فهرست پرونده‌های من» این حساب پیدا نشد.")
        if not await visible(self.page.locator(S.TURN_CHECK), timeout=8000):
            raise FlowError("PARSE_CHANGED", "turn: check button not found")
        await self.page.locator(S.TURN_CHECK).first.click()
        await human_pause(self.page, 3000)   # فرصت بررسی پرونده توسط سامانه
        await self._role_or_raise()          # «هیچ سمتی» در بخش شماره پرونده (دستور کارفرما)

    async def _placeholder_visible(self, words) -> bool:
        """آیا placeholder منوی سمت/دادورز (مثل «انتخاب سمت جهت ملاقات») هنوز دیده می‌شود؟"""
        try:
            loc = self.page.get_by_text(text_re(*words))
            for i in range(await loc.count()):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            pass
        return False

    async def _daadvarz_prefilled(self) -> bool:
        """آیا بعد از «بررسی اطلاعات پرونده فوق» سامانه خودش سمت/دادورز را پر کرده؟

        (دستور کارفرما — ضبط steps): اگر placeholderهای «انتخاب سمت جهت ملاقات» /
        «هیچ موردی انتخاب نشده» روی صفحه نباشند و «مرحله ی بعدی» آماده باشد،
        یعنی سامانه قسمت‌های دادورز را خودش تکمیل کرده ← مستقیم مرحله‌ی بعد."""
        for _ in range(10):                      # تا ~۸ ثانیه برای رندر مرحله‌ی بعد
            if await self._placeholder_visible(S.TURN_ROLE_PLACEHOLDER):
                return False
            if await self._placeholder_visible(S.TURN_PERSON_PLACEHOLDER):
                return False
            if await visible(self.page.locator(S.TURN_NEXT), timeout=600):
                return True
            await asyncio.sleep(0.8)
        return False

    async def select_daadvarz(self):
        # سامانه خودش سمت/دادورز را پر کرده ← فقط «مرحله ی بعدی» (دستور کارفرما)
        if await self._daadvarz_prefilled():
            await self.job.say(T.TURN_DAAVARZ_PREFILLED)
            await self.page.locator(S.TURN_NEXT).first.click()
            await human_pause(self.page, 2500)
            await self._role_or_raise()          # «هیچ سمتی» در بخش تعیین دادورز
            return
        if not await click_text(self.page, *S.TURN_ROLE_PLACEHOLDER, timeout=15_000):
            await self._role_or_raise()      # شاید sweet-alert «هیچ سمتی» آمده باشد
            txt = await page_text(self.page)
            raise FlowError("TURN_REJECTED", "role dropdown missing",
                            "⚠️ سامانه اجازه‌ی ادامه نداد:\n" + to_fa_digits(_site_message(txt)))
        roles = [m for m in await self._menu() if S.TURN_ROLE_WORD in normalize_fa(m["text"])]
        if not roles:
            raise FlowError("PARSE_CHANGED", "no daadvarz role option")
        await self._click_menu(roles[0]["idx"])
        await self.page.keyboard.press("Escape")
        if not await click_text(self.page, *S.TURN_PERSON_PLACEHOLDER, timeout=10_000):
            raise FlowError("PARSE_CHANGED", "daadvarz person dropdown missing")
        people = await self._menu()
        if not people:
            raise FlowError("PARSE_CHANGED", "daadvarz list empty")
        chosen = await self._choose(people, "دادورز مرتبط را انتخاب کنید:", "دادورز:\n{}\nتأیید می‌کنید؟")
        await self._click_menu(chosen["idx"])
        await self.page.keyboard.press("Escape")
        await self.page.locator(S.TURN_NEXT).first.click()
        await human_pause(self.page, 2500)
        await self._role_or_raise()          # «هیچ سمتی» در بخش تعیین دادورز (دستور کارفرما)

    async def select_reason(self):
        """علت مراجعه (دستور کارفرما — آبان ۱۴۰۵): همیشه ردیف ۱۵ فهرست علت‌ها
        («درخواست جلب متهم») انتخاب می‌شود؛ فهرست علت‌ها برای کاربر ارسال نمی‌شود."""
        if not await visible(self.page.locator(S.TURN_REASON_BTN), timeout=8000):
            return
        await self.page.locator(S.TURN_REASON_BTN).first.click()
        await human_pause(self.page, 1500)
        if not await self._click_reason_15():
            raise FlowError("PARSE_CHANGED", "reason row 15 (درخواست جلب متهم) not found")
        await self._after_reason_pick()

    async def _after_reason_pick(self):
        """بعد از انتخاب علت: «متوجه شدم» ← برگشت به تقویم (ضبط steps). اگر دکمه
        نبود، مودال بسته و «مرحله ی بعدی» زده می‌شود (سازگار با حالت‌های دیگر)."""
        if await click_text(self.page, *S.TURN_UNDERSTOOD, timeout=4_000):
            await human_pause(self.page, 1500)
            return
        with contextlib.suppress(Exception):
            if await visible(self.page.locator(".modal.show, .modal.in"), timeout=1500):
                await click_text(self.page, "بستن", timeout=2_000)
                await human_pause(self.page, 800)
        with contextlib.suppress(Exception):
            nxt = self.page.locator(S.TURN_NEXT)
            if await visible(nxt, timeout=4000):
                await nxt.first.click()
                await human_pause(self.page, 2000)

    async def _click_reason_row(self, pat) -> bool:
        """کلیک روی اولین ردیفِ قابل‌مشاهده‌ی منطبق (دکمه‌ی «انتخاب» یا خود ردیف)."""
        try:
            rows = self.page.locator("tr").filter(has_text=pat)
            for i in range(await rows.count()):
                row = rows.nth(i)
                if not await row.is_visible():
                    continue
                btn = row.locator("button").first
                if await visible(btn, timeout=2_000):
                    await btn.click()
                else:
                    await row.click()
                return True
        except Exception:
            pass
        return False

    async def _click_reason_15(self) -> bool:
        """انتخاب ردیف ۱۵ فهرست علت‌ها (دستور کارفرما — همیشه همین ردیف).

        ۱) ردیفی که متنش «درخواست جلب متهم» است؛
        ۲) ردیفی که خانه‌ی شماره‌اش ۱۵ است (ترتیب فهرست ممکن است جابه‌جا شود)؛
        ۳) ردیف پانزدهم جدول علت‌ها."""
        if await self._click_reason_row(text_re(*S.TURN_REASON_15)):
            return True
        try:                                   # خانه‌ی شماره‌ی ۱۵
            rows = self.page.locator(S.TURN_REASON_ROW)
            if not await rows.count():
                rows = self.page.locator("#btnUnitReferalReasonTypeModal ~ * tr, .modal tr")
            for i in range(await rows.count()):
                row = rows.nth(i)
                if not await row.is_visible():
                    continue
                first_td = row.locator("td").first
                num = normalize_fa(await first_td.inner_text(timeout=1_000)).strip()
                if num == "15":
                    btn = row.locator("button").first
                    if await visible(btn, timeout=1_500):
                        await btn.click()
                    else:
                        await row.click()
                    return True
        except Exception:
            pass
        try:                                   # ردیف پانزدهم
            rows = self.page.locator("tr").filter(has_text=text_re("انتخاب"))
            vis_rows = [r for r in range(await rows.count()) if await rows.nth(r).is_visible()]
            if len(vis_rows) >= 15:
                row = rows.nth(vis_rows[14])
                btn = row.locator("button").first
                if await visible(btn, timeout=1_500):
                    await btn.click()
                else:
                    await row.click()
                return True
        except Exception:
            pass
        return False

    async def _click_reason_text(self, label: str) -> bool:
        """انتخاب علتِ جایگزین («ارائه دلائل» / «پیگیری پرونده»)."""
        return await self._click_reason_row(text_re(label))

    # ── خطای علت مراجعه (دستور کارفرما) ────────────────────────────────
    async def _fix_reason_error_if_any(self) -> bool:
        """خطای «نمی توان علت مراجعه را ... انتخاب نمود» (دستور کارفرما — آبان ۱۴۰۵):

        «مرحله ی قبلی» (اگر روی تقویم هستیم) ← «فهرست علت ها» ← علت جایگزین:
        اول «ارائه دلائل»، اگر باز هم همین خطا آمد «پیگیری پرونده» ← «متوجه شدم»
        و ادامه‌ی همان روند تا اخذ نوبت. هر دو هم رد شدند ← TURN_REASON_FAILED.
        """
        if not await self._reason_error():
            return False
        await self._hide_message(("علت مراجعه", "نمی توان", "انتخاب"))   # پیام کهنه
        if not self._reason_fallbacks:
            raise FlowError("TURN_REASON_REJECTED", "all reasons rejected by unit", T.TURN_REASON_FAILED)
        label = self._reason_fallbacks.pop(0)
        await self.job.say(f"🔁 سامانه علت مراجعه را نپذیرفت؛ علت را به «{label}» تغییر می‌دهم…")
        await self._close_alert()
        if not await visible(self.page.locator(S.TURN_REASON_BTN), timeout=2500):
            prev = self.page.locator(S.TURN_PREV)
            if not await visible(prev, timeout=6_000):
                raise FlowError("PARSE_CHANGED", "prev-step button not found")
            await prev.first.click()
            await human_pause(self.page, 2000)
        if not await visible(self.page.locator(S.TURN_REASON_BTN), timeout=8000):
            raise FlowError("PARSE_CHANGED", "reason-list button not found")
        await self.page.locator(S.TURN_REASON_BTN).first.click()
        await human_pause(self.page, 1500)
        if not await self._click_reason_text(label):
            raise FlowError("PARSE_CHANGED", f"reason row '{label}' not found")
        await self._after_reason_pick()
        await self._role_or_raise()
        return True

    # ── تقویم: انتخاب روزِ هدف (از فردا؛ بدون پنجشنبه/جمعه/تعطیل) ───────
    async def _click_day_cell(self, idx: str):
        """کلیک سلولِ روز با برچسبِ data-lb-day (برچسبِ خودِ ربات است؛ data-day
        متعلق به خودِ تقویم mds است و دست نمی‌خورد)."""
        await self.page.evaluate(DAYS_JS)          # تازه‌سازی برچسب data-lb-day
        await self.page.locator(f'[data-lb-day="{idx}"]').first.click()
        await human_pause(self.page, 1800)

    async def _select_day(self, target: dt.date) -> bool:
        """روز هدف در تقویم کلیک می‌شود؛ اگر ماهِ نمایش‌داده‌شده عقب‌تر بود، با فلشِ
        «ماه بعد» جلو می‌رود. خروجی False = چنین روزی قابل انتخاب نبود.

        تقویم mds (HTML ارسالی کارفرما): هر سلول data-number="YYYYMMDD" دارد و
        روزِ هدف با تطبیق دقیق همین تاریخ پیدا می‌شود — سلول‌های ماهِ مجاور
        (data-nm) و روزهای disabled از قبل در DAYS_JS حذف شده‌اند؛ بنابراین
        «26»یِ ماهِ گذشته هرگز به‌جای «26»یِ ماهِ جاری کلیک نمی‌شود. برای تقویم‌های
        قدیمی (بدون data-number) همان تطبیقِ شماره‌ی روز در ماهِ نمایش‌داده‌شده است.
        """
        tj = jalali_of(target)
        want = f"{tj.year:04d}{tj.month:02d}{tj.day:02d}"   # data-number هدف
        for _ in range(26):                      # حداکثر ۲۶ ماه جلو رفتن
            info = await self.page.evaluate(DAYS_JS)
            shown = parse_jalali_header(info.get("header") or "")
            if not shown or (shown[0], shown[1]) >= (tj.year, tj.month):
                break                            # ماهِ درست است (یا سربرگ ناخواناست)
            if not info.get("has_next"):
                break                            # فلشِ ماه بعد نبود
            with contextlib.suppress(Exception):
                await self.page.locator('[data-lb-next="1"]').first.click()
            await human_pause(self.page, 900)
        info = await self.page.evaluate(DAYS_JS)
        shown = parse_jalali_header(info.get("header") or "")
        if shown and (shown[0], shown[1]) != (tj.year, tj.month):
            return False                         # به ماهِ روزِ هدف نرسیدیم
        for c in info["cells"]:                  # ۱) تقویم mds: تطبیق دقیق data-number
            if c.get("number") == want:
                await self._click_day_cell(c["idx"])
                return True
        for c in info["cells"]:                  # ۲) تقویم قدیمی: شماره‌ی روز
            if not c.get("number") and int(c["day"]) == tj.day:
                await self._click_day_cell(c["idx"])
                return True
        return False

    async def _wait_turn_table(self):
        """صبر تا جدول ساعت‌های روز لود شود یا پیام خطای روز/ظرفیت/علت مراجعه/بازه بیاید."""
        async def _has_times() -> bool:
            return bool(await self.page.evaluate(TIMES_JS))

        await wait_first({
            "times": _has_times,
            "error": self._day_error,
            "capacity": self._capacity_error,
            "reason": self._reason_error,
            "range": self._range_error,
        }, timeout_ms=12_000)
        await human_pause(self.page, 600)

    async def _click_yes(self) -> bool:
        """دکمه‌ی تأیید «بلی» با تطبیق کاملِ متن.

        («بلی» زیررشته‌ی «قبلی» است — تطبیق بخشی می‌تواند دکمه‌ی «مرحله ی قبلی» را
        به‌جای «بلی» بزند؛ روی همین مرحله، نوبت ثبت نمی‌شد.)
        """
        for name in S.TURN_YES:
            try:
                loc = self.page.get_by_role("button", name=name, exact=True)
                if await loc.first.is_visible():
                    await loc.first.click()
                    return True
            except Exception:
                continue
        return await click_text(self.page, *S.TURN_YES, timeout=6_000)

    async def _read_create_error(self, timeout_s: float = 4.0) -> str:
        """متن هشدارِ بعد از ثبتِ ناموفق — sweet-alert ممکن است چند لحظه بعد از
        پاسخِ خطای API باز شود؛ تا چند ثانیه فرصت خواندن داده می‌شود."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_s
        while loop.time() < end:
            txt = await self._alert_text()
            if txt:
                return txt
            await asyncio.sleep(0.3)
        return ""

    async def _try_slots(self, target: dt.date, tries: int) -> tuple[str | None, int, bool]:
        """ساعت‌های آزادِ همین روز را به‌ترتیب امتحان می‌کند (دستور کارفرما:
        دونه‌دونه روزها/ساعت‌ها تا پیدا شدن نوبتِ خالی — ضبط steps 2).

        ساعت‌های «تکمیل ظرفیت» (کلاس disable / State==2) هرگز کلیک نمی‌شوند.
        خطای «ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است» ← همین روز رها
        می‌شود و مستقیم روزِ بعد می‌رویم (دستور کارفرما) — ساعتِ بعدیِ همان روز
        امتحان نمی‌شود و از سهمیه‌ی تلاش‌ها هم کم نمی‌شود (خطای روز است، نه ساعت).
        خروجی: (متن نوبتِ ثبت‌شده یا None، تعداد تلاش‌های مصرف‌شده، ظرفیتِ روز پر؟).
        """
        slots = await self.page.evaluate(TIMES_JS)
        free = [s for s in slots if not s.get("full")]
        for t in free:
            if tries >= config.TURN_MAX_SLOT_TRIES:
                return None, tries, False
            tries += 1
            await self.page.evaluate(TIMES_JS)      # تازه‌سازی برچسب data-time
            with contextlib.suppress(Exception):
                await self.page.locator(f'[data-time="{t["idx"]}"]').first.click()
            status = None
            try:
                async with self.page.expect_response(lambda r: S.TURN_CREATE_API in r.url,
                                                     timeout=25_000) as ri:
                    await self.page.locator(S.TURN_CREATE).first.click()
                    await self._click_yes()
                status = (await ri.value).status
            except Exception:
                status = None
            await human_pause(self.page, 2000)
            if status == 200 or "#/Detail" in self.page.url:
                return (f"روز {fa_date(target)} ({weekday_fa(target)}) ساعت {to_fa_digits(t['time'])}",
                        tries, False)
            # متن هشدارِ خطا قبل از بستن خوانده می‌شود (مثل خطای بازه‌ی فعال — steps 2)
            self._last_create_error = await self._read_create_error()
            await click_text(self.page, *S.TURN_CLOSE, timeout=4000)
            # «با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.»
            # ← مستقیم روزِ بعد (دستور کارفرما — HTML ارسالی)
            if _is_capacity_error(self._last_create_error):
                log.info("turn day %s capacity full at %s", target, t['time'])
                return None, tries - 1, True
        return None, tries, False

    async def book(self) -> str:
        """روز و ساعتِ اولین نوبتِ خالی (دستور کارفرما — آبان ۱۴۰۵):

        از «فردا» شروع می‌شود (روز جاری انتخاب نمی‌شود)؛ پنجشنبه/جمعه/تعطیل رسمی رد
        می‌شود؛ روزها دونه‌دونه چک می‌شوند تا «تأیید و چاپ» (ثبتِ موفق) نمایش داده
        شود؛ خطای علت مراجعه ← «ارائه دلائل» و سپس «پیگیری پرونده»؛ خطای «ظرفیت
        نوبت دهی در زمان انتخاب شده تکمیل شده» ← مستقیم روزِ بعد؛ خطای «طبق
        تنظیمات شعبه... فعال است» ← روزهای قبل از شروعِ بازه رد و داخل/بعد از بازه
        ← «ظرفیت پر؛ ساعت ۸ صبح روز بعد مجدداً اقدام نمائید» (دستور کارفرما).
        """
        await self.job.ask_choice(T.TURN_BOOK_CONFIRM, [("ok", "✅ بله، ثبت کن")])
        tries = 0
        days = turn_candidate_days(config.TURN_MAX_DAY_LOOKAHEAD)
        i = 0
        while i < len(days):
            target = days[i]
            i += 1
            self._last_create_error = ""        # هشدارِ روزِ قبلی خوانده نشود
            # بازه‌ی فعالِ شعبه معلوم شده و این روز قبل از شروعِ آن است ← رد
            ar_start = self._active_range[0]
            if ar_start and target < ar_start:
                continue
            for _round in range(3):        # دور بعدی فقط بعد از اصلاح خطای «علت مراجعه»
                if not await self._select_day(target):
                    break                  # چنین روزی در تقویم قابل انتخاب نبود ← روز بعد
                await self._wait_turn_table()
                err = await self._day_error()
                if err:
                    # پنجشنبه/تعطیل رسمی/عدم حضور دادورز ← حتماً روز بعد (دستور کارفرما)
                    log.info("turn day %s blocked: %s", target, err[:150])
                    await self._close_alert()
                    break
                cap = await self._capacity_error()
                if cap:
                    # «ظرفیت نوبت دهی ... تکمیل شده است» ← مستقیم روزِ بعد (دستور کارفرما)
                    log.info("turn day %s capacity full: %s", target, cap[:150])
                    await self._close_alert()
                    break
                rng = await self._range_error()
                if rng and await self._handle_range_error(rng, target):
                    break                  # روز قبل از شروعِ بازه‌ی فعال بود ← روزهای بعدی
                if await self._reason_error():
                    await self._fix_reason_error_if_any()
                    continue               # علت مراجعه اصلاح شد ← دوباره همین روز
                when, tries, day_full = await self._try_slots(target, tries)
                if when:
                    return when
                if day_full:
                    break                  # ظرفیت این روز تکمیل شد ← مستقیم روزِ بعد
                if tries >= config.TURN_MAX_SLOT_TRIES:
                    raise FlowError("NO_SLOT", "slot tries exhausted",
                                    "⚠️ چند نوبت پشت سر هم پذیرفته نشد؛ کمی بعد دوباره امتحان کنید.")
                if await self._role_error():
                    # «هیچ سمتی ...» حین ثبت نوبت ← ظرفیت پر (دستور کارفرما)
                    await self._close_alert()
                    raise FlowError("TURN_CAPACITY_FULL", "role error while booking",
                                    T.TURN_CAPACITY_FULL)
                if await self._reason_error():
                    await self._fix_reason_error_if_any()
                    continue               # دوباره همین روز
                rng = await self._range_error()
                if rng and await self._handle_range_error(rng, target):
                    break                  # خطای بازه بعد از ثبت ناموفق ← روزهای بعدی
                break                      # همه‌ی ساعت‌ها «تکمیل ظرفیت» بود ← روز بعد
        raise FlowError("NO_SLOT", "no free slot", "⚠️ نوبت خالی پیدا نشد. کمی بعد دوباره امتحان کنید.")

    async def go_home(self):
        """«صفحه اصلی» نوبت‌دهی (#btnHome) — بین نوبت‌های متوالی (ضبط steps:
        بعد از چاپ، #btnHome ← «اخذ نوبت بر اساس شماره پرونده» برای نوبت بعدی)."""
        with contextlib.suppress(Exception):
            if await visible(self.page.locator(S.TURN_HOME), timeout=4_000):
                await self.page.locator(S.TURN_HOME).first.click()
                await human_pause(self.page, 2000)
                return
        with contextlib.suppress(Exception):
            await self.page.goto(config.TURN_URL, wait_until="domcontentloaded", timeout=45_000)
            await human_pause(self.page, 2000)

    async def print_ticket(self) -> bytes:
        with contextlib.suppress(Exception):
            await self.page.wait_for_url(re.compile(r"#/Detail"), timeout=20_000)
        await click_text(self.page, *S.TURN_CLOSE, timeout=4000)
        for _ in range(3):
            try:
                since = len(self.br.pdfs)
                async with self.br.context.expect_page(timeout=15_000) as pi:
                    await self.page.locator(S.TURN_PRINT).first.click()
                pp = await pi.value
                try:
                    data = await self.br.popup_bytes(pp, since)
                    if data:
                        return data
                    raise RuntimeError("empty print")
                finally:
                    with contextlib.suppress(Exception):
                        await pp.close()
            except Exception:
                await asyncio.sleep(10)
        return await pdf_of(self.page)


def _site_message(txt: str) -> str:
    for line in txt.splitlines():
        if re.search(r"امکان|مجاز|خطا|یافت نشد|نمی\s*باشد", line):
            return line.strip()[:300]
    return "پیام مشخصی نمایش داده نشد."


async def work_turn(ctx, br, login, page, numbers: list[str], by: str, on_booked=None):
    """ثبت نوبت برای یک یا چند پرونده (دستور کارفرما — آبان ۱۴۰۵).

    «ثبت چند نوبت»: هر شماره عین ضبط steps — جستجو ← تأیید کاربر ← بررسی ←
    دادورز ← علت ۱۵ ← روز/ساعت ← چاپ؛ بعد از هر نوبت «صفحه اصلی» و شروع
    روند تازه برای شماره‌ی بعدی. خطای یک شماره بقیه را متوقف نمی‌کند.

    on_booked(number): بعد از هر ثبتِ موفق صدا زده می‌شود (مثلاً برای «استفاده‌شده»
    کردن فاکتور، تا با دکمه‌ی شروعِ دوباره نوبتِ ثبت‌شده تکراری ثبت نشود).
    خروجی: {"booked": [...], "failed": [...]}.
    """
    t = Turn(ctx, br, login, page)
    numbers = [n for n in numbers if n]
    booked, failed = [], []
    if len(numbers) > 1:
        await ctx.job.say(T.TURN_MULTI_START.format(n=to_fa_digits(len(numbers))))
    for i, number in enumerate(numbers):
        if i:
            await t.go_home()
        try:
            await t.select_case(number, by)
            await t.select_daadvarz()
            await t.select_reason()
            when = await t.book()
            pdf = await t.print_ticket()
        except (JobCancelled, UserTimeout):
            raise                          # لغو/مهلت کاربر ← توقف کل کار
        except FlowError as e:
            if len(numbers) == 1:
                raise
            await ctx.job.say(f"⚠️ نوبت {to_fa_digits(number)} ثبت نشد:\n{e.user_message or T.SITE_DOWN}")
            await ctx.report(e.category, f"turn {number}: {str(e)[:150]}")
            failed.append(number)
            continue
        await ctx.step("L11")
        await ctx.job.send_pdf(pdf, f"nobat_{number}.pdf",
                               f"✅ نوبت ملاقات با دادورز ثبت شد ({when}).\nپرونده/بایگانی: {to_fa_digits(number)}\n"
                               "لطفاً ۱۵ دقیقه قبل از نوبت با کارت ملی حاضر شوید.")
        ctx.new_items += 1
        booked.append(number)
        if on_booked is not None:
            with contextlib.suppress(Exception):
                await on_booked(number)
    if len(numbers) > 1:
        await ctx.job.say(T.TURN_MULTI_DONE.format(
            done="، ".join(to_fa_digits(n) for n in booked) or "—",
            failed="، ".join(to_fa_digits(n) for n in failed) or "—"))
    return {"booked": booked, "failed": failed}
