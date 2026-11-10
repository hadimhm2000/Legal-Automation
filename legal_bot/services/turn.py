"""ثبت نوبت قضائی (adliran.ir/Turn) — ملاقات با دادورز اجرای احکام.

روند (مطابق فایل ضبط کارفرما):
  «اخذ نوبت بر اساس شماره پرونده» ← «فهرست پرونده های من» ← جستجوی شماره پرونده/بایگانی
  ← فقط شعبه‌هایی که «اجرای احکام / اجرا احکام» دارند (یکی ← تأیید کاربر؛ چندتا ← انتخاب کاربر)
  ← «بررسی اطلاعات پرونده فوق» ← «انتخاب سمت جهت ملاقات» = همیشه «دادورز»
  ← فهرست دوم (زیر دادورز) برای کاربر ← «مرحله ی بعدی» ← «فهرست علت ها» ← روز و ساعت
  ← «ثبت و دریافت نوبت» ← «بلی» (اگر نوبت پر بود «بستن» و ساعت/روز بعدی) ← «چاپ».
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re

from playwright.async_api import Page

from .. import config
from ..utils import normalize_fa, to_fa_digits
from . import selectors as S
from .browser import click_text, human_pause, page_text, pdf_of, visible
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
      out.push({idx: String(n++), text: t.slice(0, 200)});
    }
  }
  return out;
}
"""

DAYS_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0).trim();
  const out = [];
  document.querySelectorAll('td').forEach((td, i) => {
    const t = norm(td.innerText);
    if (!/^\d{1,2}$/.test(t) || !vis(td)) return;
    const cls = (td.className + ' ' + (td.parentElement ? td.parentElement.className : '')).toLowerCase();
    if (/disabled|old|off|past|holiday|unavailable|text-muted/.test(cls)) return;
    if (td.getAttribute('aria-disabled') === 'true') return;
    td.setAttribute('data-day', String(i));
    out.push({idx: String(i), day: t});
  });
  return out;
}
"""

TIMES_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0).trim();
  const out = [];
  document.querySelectorAll('div, span, button, a, label').forEach((el, i) => {
    if (!vis(el) || el.children.length) return;
    const t = norm(el.innerText);
    const m = t.match(/^([01]?\d|2[0-3]):([0-5]\d)$/);   // «11:-51» نامعتبر رد می‌شود
    if (!m) return;
    const cls = (el.className || '').toLowerCase();
    if (/disabled|reserved|full|taken/.test(cls)) return;
    el.setAttribute('data-time', String(i));
    out.push({idx: String(i), time: t});
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

    async def _menu(self) -> list[dict]:
        await self.page.wait_for_timeout(900)
        return await self.page.evaluate(MENU_JS)

    async def _click_menu(self, idx):
        await self.page.locator(f'[data-mi="{idx}"]').first.click()
        await human_pause(self.page, 1200)

    async def _choose(self, items: list[dict], prompt: str, confirm_single: str) -> dict:
        if len(items) == 1:
            await self.job.ask_choice(confirm_single.format(to_fa_digits(items[0]["text"])),
                                          [("ok", "✅ تأیید")])
            return items[0]
        opts = [(it["idx"], to_fa_digits(it["text"])[:60]) for it in items[:20]]
        idx = await self.job.ask_choice(prompt, opts)
        return next(it for it in items if it["idx"] == idx)

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

    async def select_daadvarz(self):
        if not await click_text(self.page, *S.TURN_ROLE_PLACEHOLDER, timeout=15_000):
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

    async def book(self) -> str:
        await self.job.ask_choice("نوبت در اولین روز و ساعت خالی ثبت شود؟", [("ok", "✅ بله، ثبت کن")])
        tries = 0
        days = await self.page.evaluate(DAYS_JS)
        if not days:
            raise FlowError("NO_SLOT", "no days", "⚠️ در حال حاضر روز خالی برای نوبت وجود ندارد. کمی بعد دوباره امتحان کنید.")
        for d in days:
            await self.page.evaluate(DAYS_JS)
            await self.page.locator(f'[data-day="{d["idx"]}"]').first.click()
            await human_pause(self.page, 1500)
            for t in await self.page.evaluate(TIMES_JS):
                if tries >= config.TURN_MAX_SLOT_TRIES:
                    raise FlowError("NO_SLOT", "slot tries exhausted",
                                    "⚠️ چند نوبت پشت سر هم پذیرفته نشد؛ کمی بعد دوباره امتحان کنید.")
                tries += 1
                await self.page.evaluate(TIMES_JS)
                with contextlib.suppress(Exception):
                    await self.page.locator(f'[data-time="{t["idx"]}"]').first.click()
                status = None
                try:
                    async with self.page.expect_response(lambda r: S.TURN_CREATE_API in r.url, timeout=25_000) as ri:
                        await self.page.locator(S.TURN_CREATE).first.click()
                        await click_text(self.page, *S.TURN_YES, timeout=6000)
                    status = (await ri.value).status
                except Exception:
                    status = None
                await human_pause(self.page, 2000)
                if status == 200 or "#/Detail" in self.page.url:
                    return f"روز {to_fa_digits(d['day'])} ساعت {to_fa_digits(t['time'])}"
                await click_text(self.page, *S.TURN_CLOSE, timeout=4000)
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
