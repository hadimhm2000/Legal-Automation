"""سامانه ابلاغ الکترونیک قضایی (سامانه‌ی اصلی eblagh1.adliran.ir — نه پشتیبان).

روند (مطابق ضبط کارفرما):
  ابلاغیه‌های جدید ← شماره‌ی همه را پیش از شروع یادداشت کن (run_items) ←
  برای هر کدام: «مشاهده» ← «جزئیات» ← «نسخه چاپی» (تب جدید ENoticePrint.aspx ← PDF)
  ← «پیوست‌ها» ← هر «مشاهده» (اگر alert «در حال استخراج… دو دقیقه» آمد، صبر و تلاش مجدد)
  ← «بازگشت».
  اگر ابلاغیه دیگر در «جدید» نبود (چون مشاهده شد یا صفحه ریلود شد) ← «بازگشت» ←
  «ابلاغیه‌های مشاهده شده» و پیدا کردن با همان شماره.
  اگر صفحه‌ی چاپ باز نشد: ۱۰ ثانیه صبر و تلاش دوباره؛ بعد از ۳ تلاش، ریلود سایت.
  «چاپ گروهی» استفاده نمی‌شود (به برنامه‌ی محلی سمپ‌یار روی localhost:8010 نیاز دارد).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re

from playwright.async_api import Page

from .. import config, keyboards as K
from ..utils import fa_date, normalize_fa, to_fa_digits, to_jalali_str, today_tehran
from . import selectors as S
from .browser import click_text, page_text, pdf_of, visible
from .notice_parser import TABLE_JS, parse_notice_text
from .session import FlowError

log = logging.getLogger(__name__)

# ── خواندن کارت‌های ابلاغیه در فهرست ─────────────────────────────────────
CARDS_JS = r"""
(words) => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                              .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660);
  const out = [];
  const btns = Array.from(document.querySelectorAll('button, a, span')).filter(
      b => vis(b) && words.some(w => (b.innerText || '').trim() === w));
  btns.forEach((b, i) => {
    let el = b, txt = '';
    for (let k = 0; k < 8 && el; k++) {
      el = el.parentElement; if (!el) break;
      txt = norm(el.innerText || '');
      if (/\d{12,20}/.test(txt)) break;
    }
    const m = txt.match(/شماره\s*ابلاغیه\s*[:：]?\s*(\d{12,20})/) || txt.match(/(\d{16,20})/);
    if (!m) return;
    b.setAttribute('data-lb', m[1]);
    out.push({id: m[1], text: txt.slice(0, 400)});
  });
  const seen = new Set();
  return out.filter(o => !seen.has(o.id) && seen.add(o.id));
}
"""

ATTACH_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const tab = document.querySelector('#eblagh-attachment-tab');
  let pane = null;
  if (tab) {
    const id = tab.getAttribute('aria-controls') || (tab.getAttribute('href') || '').replace('#', '')
               || (tab.getAttribute('data-bs-target') || tab.getAttribute('data-target') || '').replace('#', '');
    if (id) pane = document.getElementById(id);
  }
  const root = pane || document;
  const links = Array.from(root.querySelectorAll('a, button')).filter(
      a => vis(a) && (a.innerText || '').trim() === 'مشاهده');
  links.forEach((a, i) => a.setAttribute('data-lb-att', String(i)));
  return links.length;
}
"""

SET_INPUT_JS = r"""
([sel, value]) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  el.removeAttribute('readonly');
  el.value = value;
  for (const t of ['input', 'change', 'blur']) el.dispatchEvent(new Event(t, {bubbles: true}));
  try { if (window.angular) window.angular.element(el).triggerHandler('input'); } catch (e) {}
  return true;
}
"""


class Eblagh:
    def __init__(self, ctx, br, login, page: Page):
        self.ctx, self.br, self.login, self.page = ctx, br, login, page
        self.job = ctx.job
        self.home_url = page.url

    # ── ناوبری ──
    async def ensure(self):
        self.page = await self.login.ensure(self.page)

    async def reload_home(self):
        with contextlib.suppress(Exception):
            await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=45_000)
        await self.ensure()
        await self.page.wait_for_timeout(2500)

    async def open_new_list(self):
        await self.ensure()
        if await visible(self.page.locator(S.NEW_NOTICES_ID)):
            await self.page.locator(S.NEW_NOTICES_ID).first.click()
        else:
            await click_text(self.page, *S.NEW_NOTICES, timeout=10_000)
        await self.page.wait_for_timeout(2500)

    async def open_viewed_list(self):
        await self.ensure()
        await click_text(self.page, *S.BACK_BTN, timeout=3_000)
        if not await click_text(self.page, *S.VIEWED_NOTICES, timeout=10_000):
            raise FlowError("PARSE_CHANGED", "viewed-notices button not found")
        await self.page.wait_for_timeout(2500)

    async def cards(self) -> list[dict]:
        return await self.page.evaluate(CARDS_JS, S.VIEW_BTN)

    async def _next_page(self) -> bool:
        nxt = self.page.locator(".pagination li:not(.disabled):not(.active) >> text=/^(›|»|بعدی|>)$/")
        if await visible(nxt):
            await nxt.first.click()
            await self.page.wait_for_timeout(2000)
            return True
        return False

    async def all_cards(self, max_pages=20) -> list[dict]:
        seen, out = set(), []
        for _ in range(max_pages):
            for c in await self.cards():
                if c["id"] not in seen:
                    seen.add(c["id"])
                    out.append(c)
            if not await self._next_page():
                break
        return out

    async def _click_card(self, ext_id) -> bool:
        await self.cards()  # برچسب data-lb را تازه می‌کند
        loc = self.page.locator(f'[data-lb="{ext_id}"]')
        if await visible(loc):
            await loc.first.click()
            return True
        return False

    async def find_and_open(self, ext_id, prefer="current") -> bool:
        """اول در فهرست فعلی، بعد در «ابلاغیه‌های مشاهده شده» (با ورق زدن) دنبال شماره می‌گردد."""
        if prefer == "current" and await self._click_card(ext_id):
            return True
        await self.open_viewed_list()
        for _ in range(20):
            if await self._click_card(ext_id):
                return True
            if not await self._next_page():
                break
        return False

    # ── یک ابلاغیه ──
    async def _open_print(self) -> Page | None:
        for attempt in range(config.PRINT_MAX_TRIES):
            with contextlib.suppress(Exception):
                if await visible(self.page.locator(S.DETAIL_TAB)):
                    await self.page.locator(S.DETAIL_TAB).first.click()
            try:
                async with self.br.context.expect_page(timeout=10_000) as pi:
                    if not await click_text(self.page, *S.PRINT_BTN, timeout=8_000):
                        raise RuntimeError("print button not visible")
                popup = await pi.value
                return popup
            except Exception:
                await self.job.say(f"⏳ صفحه‌ی چاپ باز نشد؛ {to_fa_digits(config.PRINT_RETRY_WAIT_SEC)} "
                                   f"ثانیه دیگر دوباره تلاش می‌کنم ({to_fa_digits(attempt + 1)}/"
                                   f"{to_fa_digits(config.PRINT_MAX_TRIES)})…")
                await asyncio.sleep(config.PRINT_RETRY_WAIT_SEC)
        return None

    async def _read_print(self, popup: Page):
        with contextlib.suppress(Exception):
            await popup.wait_for_load_state("load", timeout=40_000)
        await popup.wait_for_timeout(1500)
        text = await page_text(popup)
        table = None
        with contextlib.suppress(Exception):
            table = await popup.evaluate(TABLE_JS)
        data = await pdf_of(popup)
        with contextlib.suppress(Exception):
            await popup.close()
        return text, table, data

    async def _attachments(self, ext_id) -> list[bytes]:
        out = []
        if not await visible(self.page.locator(S.ATTACH_TAB)):
            return out
        await self.page.locator(S.ATTACH_TAB).first.click()
        await self.page.wait_for_timeout(1500)
        n = await self.page.evaluate(ATTACH_JS)
        for i in range(n):
            warned = False
            for attempt in range(config.ATTACHMENT_MAX_TRIES):
                self.br.pop_dialogs()
                popup = None
                since = len(self.br.pdfs)
                try:
                    async with self.br.context.expect_page(timeout=12_000) as pi:
                        await self.page.evaluate(ATTACH_JS)
                        await self.page.locator(f'[data-lb-att="{i}"]').first.click()
                    popup = await pi.value
                except Exception:
                    popup = None
                await asyncio.sleep(2)
                dialogs = " ".join(self.br.pop_dialogs())
                if any(normalize_fa(w) in dialogs for w in S.ATTACH_BUSY_TEXT):
                    if popup:
                        with contextlib.suppress(Exception):
                            await popup.close()
                    if not warned:
                        await self.job.say(f"⏳ پیوست {to_fa_digits(i + 1)} ابلاغیه {to_fa_digits(ext_id)} در سامانه "
                                           "در حال آماده‌سازی است؛ حدود ۲ دقیقه صبر می‌کنم و دوباره تلاش می‌کنم…")
                        warned = True
                    await asyncio.sleep(config.ATTACHMENT_WAIT_SEC)
                    continue
                if popup is None:
                    continue
                try:
                    data = await self.br.popup_bytes(popup, since)
                    if data:
                        out.append(data)
                finally:
                    with contextlib.suppress(Exception):
                        await popup.close()
                break
            else:
                await self.job.say(f"⚠️ پیوست {to_fa_digits(i + 1)} ابلاغیه {to_fa_digits(ext_id)} پس از چند تلاش "
                                   "دریافت نشد؛ بعداً از بخش جستجو دوباره امتحان کنید.")
        return out

    async def process(self, ext_id: str, *, is_new: bool, prefer="current") -> dict | None:
        """یک ابلاغیه را باز، چاپ و (با پیوست‌ها) برای کاربر ارسال می‌کند. خروجی: اطلاعات استخراج‌شده."""
        for round_ in range(2):  # دور دوم = بعد از ریلود سایت
            if not await self.find_and_open(ext_id, prefer=prefer if round_ == 0 else "viewed"):
                if round_ == 0:
                    await self.reload_home()
                    continue
                return None
            await self.page.wait_for_timeout(2000)
            popup = await self._open_print()
            if popup is None:
                await self.job.say("🔄 صفحه‌ی چاپ پس از ۳ تلاش باز نشد؛ سایت را ریلود می‌کنم…")
                await self.reload_home()
                continue
            text, table, pdf = await self._read_print(popup)
            info = parse_notice_text(text, table)
            info["notice_number"] = info.get("notice_number") or ext_id
            atts = await self._attachments(ext_id)
            await click_text(self.page, *S.BACK_BTN, timeout=5_000)
            await self.page.wait_for_timeout(1500)
            info["_pdf"], info["_attachments"], info["_is_new"] = pdf, atts, is_new
            return info
        return None


# ── ثبت و ارسال نتیجه ──────────────────────────────────────────────────
def summary_caption(info: dict, reminders: list[str]) -> str:
    lines = [f"📩 ابلاغیه {to_fa_digits(info.get('notice_number') or '-')}"]
    if info.get("case_number"):
        lines.append(f"پرونده: {to_fa_digits(info['case_number'])}")
    if info.get("archive_number"):
        lines.append(f"شماره بایگانی: {to_fa_digits(info['archive_number'])}")
    if info.get("branch"):
        lines.append(f"شعبه: {to_fa_digits(info['branch'])}")
    if info.get("notice_type"):
        lines.append(f"نوع: {info['notice_type'][:120]}")
    if info.get("hearing_date"):
        lines.append(f"📅 تاریخ حضور: {fa_date(info['hearing_date'])} ساعت {to_fa_digits(info.get('hearing_time') or '-')}")
    if info.get("deadline_days"):
        lines.append(f"⏳ مهلت: {to_fa_digits(info['deadline_days'])} روز")
    lines += reminders
    lines.append("⚠️ ابلاغ رسمی فقط در سامانه‌ی ثنا معتبر است.")
    return "\n".join(lines)


async def deliver_notice(ctx, info: dict) -> int:
    """PDF و پیوست‌ها را می‌فرستد، اطلاعات مهم را ذخیره و یادآوری‌ها را تنظیم می‌کند."""
    db, job = ctx.db, ctx.job
    await ctx.step("L10")
    nid = await db.save_notice(job.user_id, info)
    rem_lines = []
    common = dict(notice_id=nid, case_number=info.get("case_number"), archive_number=info.get("archive_number"),
                  branch=info.get("branch"), external_id=info.get("notice_number"))
    today = today_tehran()
    if info.get("hearing_date") and info["hearing_date"] >= today:
        await db.add_reminder(job.user_id, "hearing", info["hearing_date"], due_time=info.get("hearing_time"), **common)
        rem_lines.append("⏰ یادآوری جلسه: ۲ روز و ۱ روز قبل (و صبح همان روز) برایتان ارسال می‌شود.")
    elif info.get("deadline_days"):
        # ابلاغیه‌ی جدید همین الان مشاهده (ابلاغ) شد؛ برای ابلاغیه‌های قبلاً مشاهده‌شده، محافظه‌کارانه
        # از تاریخ ارسال به سامانه حساب می‌شود.
        base = today if info.get("_is_new") else (info.get("sent_date") or info.get("issue_date") or today)
        due = base + dt.timedelta(days=int(info["deadline_days"]))
        if due >= today:
            await db.add_reminder(job.user_id, "deadline", due, start_date=base, **common)
            rem_lines.append(f"⏰ آخرین مهلت (تخمینی): {fa_date(due)} — هر ۳ روز یک‌بار و روز قبل از آن یادآوری می‌شود. "
                             "(مبدأ مهلت را با قانون آیین دادرسی تطبیق دهید.)")
    await ctx.step("L11")
    name = f"eblagh_{info.get('notice_number') or 'x'}.pdf"
    try:
        await job.send_pdf(info["_pdf"], name, summary_caption(info, rem_lines))
        for i, a in enumerate(info.get("_attachments") or [], 1):
            await job.send_pdf(a, f"peyvast_{info.get('notice_number')}_{i}.pdf",
                               f"📎 پیوست {to_fa_digits(i)} ابلاغیه {to_fa_digits(info.get('notice_number') or '')}")
    except Exception as e:
        await ctx.report("SEND_FAILED", type(e).__name__)
    if not rem_lines:
        await job.say(f"ابلاغیه {to_fa_digits(info.get('notice_number') or '')}: آیا تمایل دارید زمان یادآوری یا "
                      "توضیحی به این پرونده اضافه کنید؟",
                      K.inline([[("✅ بله", f"rem:add:{nid}"), ("❌ خیر", "rem:no")]]))
    return nid


# ── سه کار اصلی ───────────────────────────────────────────────────────
async def work_new(ctx, br, login, page):
    e = Eblagh(ctx, br, login, page)
    await e.open_new_list()
    cards = await e.all_cards()
    ids = [c["id"] for c in cards]
    if not ids:
        txt = await page_text(e.page)
        if not re.search(r"ابلاغیه|موردی|یافت", txt):
            raise FlowError("PARSE_CHANGED", "new-notices page not recognised")
        await ctx.job.say(f"✅ بررسی شد؛ ابلاغیه‌ی جدیدی نیست (ساعت {to_fa_digits(dt.datetime.now().strftime('%H:%M'))}).")
        return
    await ctx.db.add_run_items(ctx.run_id, ids)
    await ctx.job.say(f"📩 {to_fa_digits(len(ids))} ابلاغیه‌ی جدید پیدا شد: "
                      + "، ".join(to_fa_digits(i) for i in ids) + "\nدر حال چاپ و ارسال…")
    await _process_ids(ctx, e, ids, is_new=True)


async def _process_ids(ctx, e: Eblagh, ids, *, is_new, prefer="current"):
    failed = []
    for i, ext in enumerate(ids):
        try:
            info = await e.process(ext, is_new=is_new, prefer=prefer if i == 0 else "current")
        except FlowError:
            raise
        except Exception as ex:
            log.warning("notice %s failed: %s", ext, type(ex).__name__)
            info = None
        if not info:
            failed.append(ext)
            await ctx.db.set_run_item(ctx.run_id, ext, "failed")
            await ctx.report("PRINT_FAILED", f"notice {ext} could not be printed")
            await e.reload_home()
            continue
        await deliver_notice(ctx, info)
        await ctx.db.set_run_item(ctx.run_id, ext, "done")
        ctx.new_items += 1
        # برگشت به فهرستی که شماره‌ها از آن آمده‌اند
        if is_new:
            with contextlib.suppress(Exception):
                await e.open_new_list()
    if failed:
        await ctx.job.say("⚠️ این ابلاغیه‌ها چاپ نشدند و به مدیر گزارش شد: " + "، ".join(to_fa_digits(x) for x in failed)
                          + "\nمی‌توانید بعداً با «جستجو براساس شماره پرونده» دوباره بگیرید.")
    else:
        await ctx.job.say(f"✅ {to_fa_digits(len(ids))} ابلاغیه چاپ و ارسال شد.")


async def work_by_case(ctx, br, login, page, case_number: str):
    e = Eblagh(ctx, br, login, page)
    await e.ensure()
    if not await click_text(e.page, *S.SEARCH_NOTICE, timeout=10_000):
        raise FlowError("PARSE_CHANGED", "search-notice button not found")
    await e.page.wait_for_timeout(1200)
    inp = e.page.locator("input[type=text]:visible, input:not([type]):visible").filter(
        has_not=e.page.locator(f"{S.RANGE_FROM}, {S.RANGE_TO}"))
    target = None
    for i in range(await inp.count()):
        el = inp.nth(i)
        name = normalize_fa((await el.get_attribute("placeholder") or "") + (await el.get_attribute("name") or "")
                            + (await el.get_attribute("ng-model") or ""))
        if re.search(r"پرونده|case", name, re.I):
            target = el
            break
    target = target or (inp.first if await inp.count() else None)
    if target is None:
        raise FlowError("PARSE_CHANGED", "case-number input not found")
    await target.click()
    await target.fill(case_number)
    await click_text(e.page, *S.SEARCH_NOTICE_GO, timeout=8_000)
    await e.page.wait_for_timeout(3000)
    ids = [c["id"] for c in await e.all_cards()]
    if not ids:
        await ctx.job.say(f"برای پرونده {to_fa_digits(case_number)} ابلاغیه‌ای صادر نشده است (یا یافت نشد).")
        return
    await ctx.db.add_run_items(ctx.run_id, ids)
    await ctx.job.say(f"🔢 {to_fa_digits(len(ids))} ابلاغیه برای پرونده {to_fa_digits(case_number)} پیدا شد؛ در حال چاپ…")
    # پس از هر چاپ، جستجو باید دوباره انجام شود؛ ساده‌تر: هر شماره را در «مشاهده شده» پیدا کن
    await _process_ids(ctx, e, ids, is_new=False, prefer="current")


async def _set_range(e: Eblagh, start: dt.date, end: dt.date):
    for sel, d in ((S.RANGE_FROM, start), (S.RANGE_TO, end)):
        val = to_jalali_str(d)
        el = e.page.locator(sel).first
        if not await visible(el, timeout=8_000):
            raise FlowError("PARSE_CHANGED", f"date input {sel} not found")
        with contextlib.suppress(Exception):
            await el.click()
            await el.fill(val)
        if (await el.input_value()) != val:
            await e.page.evaluate(SET_INPUT_JS, [sel, val])
        await e.page.keyboard.press("Escape")
    if not await click_text(e.page, *S.RANGE_GO, timeout=8_000):
        raise FlowError("PARSE_CHANGED", "range search button not found")
    await e.page.wait_for_timeout(3500)


async def work_by_range(ctx, br, login, page, start: dt.date, end: dt.date):
    """بازه‌ی بیش از یک ماه به تکه‌های ۳۰ روزه شکسته و تا پایان بازه‌ی کاربر ادامه داده می‌شود."""
    from ..utils import date_windows

    e = Eblagh(ctx, br, login, page)
    windows = date_windows(start, end, config.DATE_WINDOW_DAYS)
    total = 0
    for w_start, w_end in windows:
        await e.open_viewed_list()
        await _set_range(e, w_start, w_end)
        ids = [c["id"] for c in await e.all_cards()]
        label = f"{fa_date(w_start)} تا {fa_date(w_end)}"
        if not ids:
            await ctx.job.say(f"📅 بازه‌ی {label}: ابلاغیه‌ای نبود؛ ادامه با بازه‌ی بعد…")
            continue
        await ctx.db.add_run_items(ctx.run_id, ids)
        await ctx.job.say(f"📅 بازه‌ی {label}: {to_fa_digits(len(ids))} ابلاغیه؛ در حال چاپ…")
        for ext in ids:
            info = None
            # بعد از «بازگشت» ممکن است فیلتر بازه پاک شده باشد
            if ext not in [c["id"] for c in await e.cards()]:
                await e.open_viewed_list()
                await _set_range(e, w_start, w_end)
            for _ in range(2):
                if not await e._click_card(ext):
                    await e.open_viewed_list()
                    await _set_range(e, w_start, w_end)
                    continue
                await e.page.wait_for_timeout(2000)
                popup = await e._open_print()
                if popup is None:
                    await e.reload_home()
                    await e.open_viewed_list()
                    await _set_range(e, w_start, w_end)
                    continue
                text, table, pdf = await e._read_print(popup)
                info = parse_notice_text(text, table)
                info["notice_number"] = info.get("notice_number") or ext
                info["_attachments"] = await e._attachments(ext)
                info["_pdf"], info["_is_new"] = pdf, False
                await click_text(e.page, *S.BACK_BTN, timeout=5_000)
                await e.page.wait_for_timeout(1500)
                break
            if info:
                await deliver_notice(ctx, info)
                await ctx.db.set_run_item(ctx.run_id, ext, "done")
                total += 1
                ctx.new_items += 1
            else:
                await ctx.db.set_run_item(ctx.run_id, ext, "failed")
                await ctx.report("PRINT_FAILED", f"notice {ext} (range) could not be printed")
    await ctx.job.say(f"✅ جستجوی بازه‌ی {fa_date(start)} تا {fa_date(end)} تمام شد؛ "
                      f"{to_fa_digits(total)} ابلاغیه ارسال شد.")
