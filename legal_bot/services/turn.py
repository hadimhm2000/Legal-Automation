"""ثبت نوبت قضائی (adliran.ir/Turn) — ملاقات با دادورز اجرای احکام.

روند (مطابق فایل ضبط کارفرما):
  «اخذ نوبت بر اساس شماره پرونده» ← «فهرست پرونده های من» ← جستجوی شماره پرونده/بایگانی
  ← فقط شعبه‌هایی که «اجرای احکام / اجرا احکام» دارند (یکی ← تأیید کاربر؛ چندتا ← انتخاب کاربر)
  ← «بررسی اطلاعات پرونده فوق» ← «انتخاب سمت جهت ملاقات» = همیشه «دادورز»
  ← فهرست دوم (زیر دادورز) برای کاربر ← «مرحله ی بعدی» ← «فهرست علت ها» ← روز و ساعت
  ← «ثبت و دریافت نوبت» ← «بلی» (اگر نوبت پر بود «بستن» و ساعت/روز بعدی) ← «چاپ».

قواعد روز و ساعت (دستور کارفرما — آبان ۱۴۰۵):
  • متن کامل هر گزینه‌ی منو (شعبه/دادورز/علت) برای کاربر نمایش داده می‌شود؛ دکمه‌ها شماره‌دارند.
  • روزِ جاری انتخاب نمی‌شود؛ همیشه از «فردا» شروع می‌شود.
  • پنجشنبه، جمعه و تعطیلات رسمی هرگز انتخاب نمی‌شوند؛ خطای «پنجشنبه ها / تعطیل» ← روز بعد.
  • نوبت‌های «btn-time disable» (State==2، تکمیل ظرفیت) قابل انتخاب نیستند؛ فقط ساعت‌های
    آزاد (State!=2) انتخاب می‌شوند.
  • اگر همه‌ی ساعت‌های یک روز تکمیل ظرفیت بود ← روز بعد و ادامه‌ی همین روند تا رزرو نوبت.
  • خطای «نمی توان علت مراجعه را ... انتخاب نمود» ← «مرحله ی قبلی» ← «فهرست علت ها» ←
    ردیف ۱۵ «درخواست جلب متهم» ← ادامه‌ی روند تا اخذ نوبت.
  • sweet-alert «هیچ سمتی ... تعریف نشده است»: در مرحله‌ی شماره پرونده/تعیین دادورز ←
    «امکان نوبت گرفتن نمی باشد»؛ حین ثبت نوبت ← «ظرفیت پر است؛ ۲۴ ساعت دیگر اقدام کنید».
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
from ..utils import (fa_date, jalali_of, normalize_fa, parse_jalali_header, to_fa_digits,
                     turn_candidate_days, weekday_fa)
from . import selectors as S
from .browser import click_text, human_pause, page_text, pdf_of, text_re, visible, wait_first
from .session import FlowError

log = logging.getLogger(__name__)

# ردیف‌های «فهرست پرونده های من» که شماره را دارند + دکمه‌ی انتخاب‌شان
ROWS_JS = r"""
(num) => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                              .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660);
  const rows = Array.from(document.querySelectorAll('tr, .card, .list-group-item')).filter(vis);
  const out = [];
  rows.forEach((r, i) => {
    const t = norm(r.innerText || '').replace(/\s+/g, ' ');
    if (!num || !t.includes(num)) return;
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
    const cls = (el.className + ' ' + (el.parentElement ? el.parentElement.className : '')).toLowerCase();
    if (/disabled|old|off|past|holiday|unavailable|text-muted/.test(cls)) return;
    if (el.getAttribute('aria-disabled') === 'true') return;
    el.setAttribute('data-day', String(i));
    out.cells.push({idx: String(i), day: t});
  });
  for (const el of document.querySelectorAll('th, strong, b, .datepicker-switch, .switch, .uib-title, [role=columnheader]')) {
    if (!vis(el)) continue;
    const t = norm(el.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && /1[34]\d{2}/.test(t) && t.length <= 40) { out.header = t; break; }
  }
  const nextSel = ['th button[ng-click="move(1)"]', '.next', 'th.next',
                   'button.next', 'a.next', '.glyphicon-chevron-right', '.glyphicon-chevron-left'];
  for (const sel of nextSel) {
    try {
      for (const el of document.querySelectorAll(sel)) {
        if (vis(el)) { el.setAttribute('data-lb-next', '1'); out.has_next = true; return out; }
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


def is_execution_branch(text: str) -> bool:
    t = normalize_fa(text)
    return any(normalize_fa(w) in t for w in S.EXECUTION_WORDS)


def branch_of(text: str) -> str:
    t = normalize_fa(text)
    m = re.search(r"((?:اجرای?\s*احکام\s*)?شعبه\s*\d+[^|\n]{0,80})", t)
    return (m.group(1) if m else t[:120]).strip()


class Turn:
    def __init__(self, ctx, br, login, page: Page):
        self.ctx, self.br, self.login, self.page = ctx, br, login, page
        self.job = ctx.job

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

    # ── منوها ──
    async def _menu(self) -> list[dict]:
        await self.page.wait_for_timeout(900)
        return await self.page.evaluate(MENU_JS)

    async def _click_menu(self, idx):
        await self.page.locator(f'[data-mi="{idx}"]').first.click()
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
        await human_pause(self.page, 2000)
        if not await click_text(self.page, *S.TURN_BY_CASE, timeout=15_000):
            raise FlowError("PARSE_CHANGED", "turn: 'by case number' card not found")
        await human_pause(self.page, 2000)
        rows = []
        if await visible(self.page.locator(S.TURN_MY_CASES), timeout=8000):
            await self.page.locator(S.TURN_MY_CASES).first.click()
            await human_pause(self.page, 1500)
            box = self.page.locator(S.TURN_MY_CASES_SEARCH).first
            if by == "case" and await visible(box, timeout=5000):
                await box.fill(number)
            await click_text(self.page, *S.TURN_MY_CASES_GO, timeout=6000)
            await human_pause(self.page, 3000)
            rows = await self.page.evaluate(ROWS_JS, number)
        if rows:
            ex = [r for r in rows if is_execution_branch(r["text"])]
            if not ex:
                raise FlowError("NO_EXECUTION_BRANCH", "no execution branch",
                                "⚠️ برای این پرونده شعبه‌ی «اجرای احکام» پیدا نشد؛ نوبت دادورز فقط برای پرونده‌های "
                                "اجرای احکام ثبت می‌شود. مبلغ پرداختی توسط مدیر بررسی و پیگیری می‌شود.")
            items = [{"idx": r["idx"], "text": branch_of(r["text"])} for r in ex]
            chosen = await self._choose(items, "شعبه‌ی اجرای احکام مورد نظر را انتخاب کنید:",
                                        "شعبه‌ی استخراج‌شده:\n{}\nتأیید می‌کنید؟")
            await self.page.locator(f'[data-tr="{chosen["idx"]}"]').first.click()
            await human_pause(self.page, 1500)
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

    async def select_daadvarz(self):
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
        await self._fix_reason_error_if_any()

    async def select_reason(self):
        if not await visible(self.page.locator(S.TURN_REASON_BTN), timeout=8000):
            return
        await self.page.locator(S.TURN_REASON_BTN).first.click()
        reasons = await self._menu()
        if reasons:
            chosen = await self._choose(reasons, "علت مراجعه را انتخاب کنید:", "علت مراجعه:\n{}\nتأیید می‌کنید؟")
            await self._click_menu(chosen["idx"])
        await click_text(self.page, *S.TURN_UNDERSTOOD, timeout=5000)
        await human_pause(self.page, 1500)

    # ── خطای علت مراجعه (دستور کارفرما) ────────────────────────────────
    async def _click_reason_15(self) -> bool:
        """انتخاب ردیف «درخواست جلب متهم» (ردیف ۱۵ فهرست علت ها)."""
        pat = text_re(*S.TURN_REASON_15)
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
        return await click_text(self.page, *S.TURN_REASON_15, timeout=6_000)

    async def _fix_reason_error_if_any(self) -> bool:
        """خطای «نمی توان علت مراجعه را ... انتخاب نمود» (دستور کارفرما):

        «مرحله ی قبلی» ← دکمه‌ی «فهرست علت ها» ← ردیف ۱۵ «درخواست جلب متهم» ←
        «مرحله ی بعدی» ← ادامه‌ی همان روند تا اخذ نوبت.
        """
        if not await self._reason_error():
            return False
        await self.job.say("🔁 سامانه علت مراجعه را نپذیرفت؛ علت را به «درخواست جلب متهم» "
                           "(ردیف ۱۵) تغییر می‌دهم…")
        await self._close_alert()
        prev = self.page.locator(S.TURN_PREV)
        if not await visible(prev, timeout=6_000):
            raise FlowError("PARSE_CHANGED", "prev-step button not found")
        await prev.first.click()
        await human_pause(self.page, 2000)
        if not await visible(self.page.locator(S.TURN_REASON_BTN), timeout=8_000):
            raise FlowError("PARSE_CHANGED", "reason-list button not found")
        await self.page.locator(S.TURN_REASON_BTN).first.click()
        await human_pause(self.page, 1500)
        if not await self._click_reason_15():
            raise FlowError("PARSE_CHANGED", "reason row 15 (درخواست جلب متهم) not found")
        await human_pause(self.page, 1500)
        # اگر مودال علت‌ها باز ماند بسته می‌شود؛ سپس «مرحله ی بعدی» برای برگشتن به تقویم
        with contextlib.suppress(Exception):
            if await visible(self.page.locator(".modal.show, .modal.in"), timeout=1500):
                await click_text(self.page, "بستن", timeout=2_000)
                await human_pause(self.page, 800)
        with contextlib.suppress(Exception):
            nxt = self.page.locator(S.TURN_NEXT)
            if await visible(nxt, timeout=4_000):
                await nxt.first.click()
                await human_pause(self.page, 2000)
        await self._role_or_raise()
        return True

    # ── تقویم: انتخاب روزِ هدف (از فردا؛ بدون پنجشنبه/جمعه/تعطیل) ───────
    async def _select_day(self, target: dt.date) -> bool:
        """روز هدف در تقویم کلیک می‌شود؛ اگر ماهِ نمایش‌داده‌شده عقب‌تر بود، با فلشِ
        «ماه بعد» جلو می‌رود. خروجی False = چنین روزی قابل انتخاب نبود."""
        tj = jalali_of(target)
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
        for c in info["cells"]:
            if int(c["day"]) == tj.day:
                await self.page.evaluate(DAYS_JS)   # تازه‌سازی data-day
                await self.page.locator(f'[data-day="{c["idx"]}"]').first.click()
                await human_pause(self.page, 1800)
                return True
        return False

    async def _wait_turn_table(self):
        """صبر تا جدول ساعت‌های روز لود شود یا پیام خطای روز/علت مراجعه بیاید."""
        async def _has_times() -> bool:
            return bool(await self.page.evaluate(TIMES_JS))

        await wait_first({
            "times": _has_times,
            "error": self._day_error,
            "reason": self._reason_error,
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

    async def _try_slots(self, target: dt.date, tries: int) -> tuple[str | None, int]:
        """ساعت‌های آزادِ همین روز را به‌ترتیب امتحان می‌کند.

        ساعت‌های «تکمیل ظرفیت» (کلاس disable / State==2) هرگز کلیک نمی‌شوند.
        خروجی: (متن نوبتِ ثبت‌شده یا None، تعداد تلاش‌های مصرف‌شده).
        """
        slots = await self.page.evaluate(TIMES_JS)
        free = [s for s in slots if not s.get("full")]
        for t in free:
            if tries >= config.TURN_MAX_SLOT_TRIES:
                return None, tries
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
                        tries)
            await click_text(self.page, *S.TURN_CLOSE, timeout=4000)
        return None, tries

    async def book(self) -> str:
        """روز و ساعتِ اولین نوبتِ خالی (دستور کارفرما — آبان ۱۴۰۵):

        از «فردا» شروع می‌شود (روز جاری انتخاب نمی‌شود)؛ پنجشنبه/جمعه/تعطیل رسمی رد
        می‌شود؛ اگر همه‌ی ساعت‌های یک روز «تکمیل ظرفیت» بود، روز بعدی امتحان می‌شود.
        """
        await self.job.ask_choice(T.TURN_BOOK_CONFIRM, [("ok", "✅ بله، ثبت کن")])
        tries = 0
        for target in turn_candidate_days(config.TURN_MAX_DAY_LOOKAHEAD):
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
                if await self._reason_error():
                    await self._fix_reason_error_if_any()
                    continue               # علت مراجعه اصلاح شد ← دوباره همین روز
                when, tries = await self._try_slots(target, tries)
                if when:
                    return when
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
                break                      # همه‌ی ساعت‌ها «تکمیل ظرفیت» بود ← روز بعد
        raise FlowError("NO_SLOT", "no free slot", "⚠️ نوبت خالی پیدا نشد. کمی بعد دوباره امتحان کنید.")

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


async def work_turn(ctx, br, login, page, number: str, by: str):
    t = Turn(ctx, br, login, page)
    await t.select_case(number, by)
    await t.select_daadvarz()
    await t.select_reason()
    when = await t.book()
    pdf = await t.print_ticket()
    await ctx.step("L11")
    await ctx.job.send_pdf(pdf, f"nobat_{number}.pdf",
                           f"✅ نوبت ملاقات با دادورز ثبت شد ({when}).\nپرونده/بایگانی: {to_fa_digits(number)}\n"
                           "لطفاً ۱۵ دقیقه قبل از نوبت با کارت ملی حاضر شوید.")
    ctx.new_items = 1
