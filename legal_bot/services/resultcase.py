"""سامانه اطلاع‌رسانی پرونده (resultcase.adliran.ir) — بخش اشخاص حقیقی یا وکلا.

۱) چاپ تمام پرونده‌ها   ۲) پرونده‌های جاری («مختومه نشده»)   ۳) پرونده‌های مختومه («مختومه شده»)
۴) چاپ و مشاهده‌ی جزئیات با شماره پرونده (روند کار + آخرین موضوعات + لوایح دارای «220»)
۵) پرونده‌های ثبت‌شده برای بررسی روزانه (فقط تغییرات جدید اعلام می‌شود)
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re

from playwright.async_api import Page

from .. import texts as T
from ..utils import normalize_fa, to_fa_digits
from . import selectors as S
from .browser import click_text, page_text, pdf_of, visible
from .case_parser import diff_new_lines, extract_lavayeh, last_change, line_hash, next_hearing, numbered_lines, \
    parse_case_card
from .reports import resultcase_list_pdf
from .session import FlowError

log = logging.getLogger(__name__)

CASE_CARDS_JS = r"""
(words) => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0);
  const out = [];
  const btns = Array.from(document.querySelectorAll('button, a, span')).filter(
      b => vis(b) && words.some(w => (b.innerText || '').trim() === w) && !b.querySelector('button,a,span'));
  btns.forEach((b, i) => {
    let el = b, txt = '';
    for (let k = 0; k < 10 && el; k++) {
      el = el.parentElement; if (!el) break;
      txt = norm(el.innerText || '');
      if (/شماره\s*پرونده/.test(txt) && /\d{14,20}/.test(txt)) break;
    }
    if (!/\d{14,20}/.test(txt)) return;
    b.setAttribute('data-rc', String(i));
    out.push({idx: String(i), text: txt.slice(0, 600)});
  });
  return out;
}
"""


class ResultCase:
    def __init__(self, ctx, br, login, page: Page):
        self.ctx, self.br, self.login, self.page = ctx, br, login, page
        self.job = ctx.job
        self.home_url = page.url

    async def ensure(self):
        self.page = await self.login.ensure(self.page)

    async def reload(self):
        with contextlib.suppress(Exception):
            await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=45_000)
        await self.ensure()
        await self.page.wait_for_timeout(2000)

    async def _set_box(self, sel, labels, want: bool):
        el = self.page.locator(sel).first
        try:
            if await el.is_checked() == want:
                return
        except Exception:
            pass
        with contextlib.suppress(Exception):
            await (el.check(force=True, timeout=4000) if want else el.uncheck(force=True, timeout=4000))
            return
        await click_text(self.page, *labels, timeout=4000)

    async def search(self, live: bool, archived: bool, case_no: str | None = None):
        await self.ensure()
        if case_no is not None:
            box = self.page.locator(S.RC_CASE_NO).first
            await box.wait_for(state="visible", timeout=15_000)
            await box.click()
            await box.fill(case_no)
        await self._set_box(S.RC_LIVE, S.RC_LIVE_LABEL, live)
        await self._set_box(S.RC_ARCHIVED, S.RC_ARCHIVED_LABEL, archived)
        if not await click_text(self.page, *S.RC_SEARCH, timeout=10_000):
            raise FlowError("PARSE_CHANGED", "resultcase search button not found")
        await self.page.wait_for_timeout(3500)

    async def cards(self):
        return await self.page.evaluate(CASE_CARDS_JS, S.RC_VIEW)

    async def _next_page(self, n: int) -> bool:
        loc = self.page.locator(".pagination").get_by_text(re.compile(rf"^\s*{n}\s*$"))
        if not await visible(loc):
            loc = self.page.locator("ul li span, ul li a").get_by_text(re.compile(rf"^\s*{n}\s*$"))
        if await visible(loc):
            await loc.first.click()
            await self.page.wait_for_timeout(2500)
            return True
        return False

    async def all_cases(self, max_pages=30) -> list[dict]:
        out, seen = [], set()
        for p in range(1, max_pages + 1):
            if p > 1 and not await self._next_page(p):
                break
            for c in await self.cards():
                info = parse_case_card(c["text"])
                if info and (info["case_number"], info.get("sub_no")) not in seen:
                    seen.add((info["case_number"], info.get("sub_no")))
                    out.append(info)
        return out

    # ── جزئیات یک پرونده ──
    async def open_details(self) -> list[dict]:
        """برای هر ردیف فرعیِ نتیجه‌ی جستجو: متن روند کار + PDFها."""
        results = []
        cards = await self.cards()
        for c in cards:
            card = parse_case_card(c["text"]) or {}
            popup = None
            try:
                async with self.br.context.expect_page(timeout=15_000) as pi:
                    await self.cards()
                    await self.page.locator(f'[data-rc="{c["idx"]}"]').first.click()
                popup = await pi.value
            except Exception:
                await self.job.say("⏳ صفحه‌ی جزئیات باز نشد؛ دوباره تلاش می‌کنم…")
                await asyncio.sleep(5)
                with contextlib.suppress(Exception):
                    async with self.br.context.expect_page(timeout=15_000) as pi:
                        await self.cards()
                        await self.page.locator(f'[data-rc="{c["idx"]}"]').first.click()
                    popup = await pi.value
            if popup is None:
                continue
            try:
                results.append(await self._read_detail(popup, card))
            finally:
                with contextlib.suppress(Exception):
                    await popup.close()
        return results

    async def _read_detail(self, popup: Page, card: dict) -> dict:
        info_loc = popup.locator(S.RC_CASE_INFO).first
        try:
            await info_loc.wait_for(state="visible", timeout=30_000)
            for _ in range(20):  # تا وقتی loading تمام شود
                if (await info_loc.inner_text()).strip():
                    break
                await asyncio.sleep(0.5)
            case_info = await info_loc.inner_text()
        except Exception:
            case_info = await page_text(popup)
        pdfs = []
        for title in S.RC_TABS:
            with contextlib.suppress(Exception):
                await click_text(popup, title, timeout=3000)
                await popup.wait_for_timeout(2000)
            data = await self._print(popup)
            if data:
                pdfs.append((title, data))
        return {"card": card, "case_info": case_info, "pdfs": pdfs}

    async def _print(self, popup: Page) -> bytes | None:
        for _ in range(3):
            try:
                since = len(self.br.pdfs)
                async with self.br.context.expect_page(timeout=15_000) as pi:
                    if not await click_text(popup, *S.RC_PRINT, timeout=6000):
                        raise RuntimeError("no print button")
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
                await asyncio.sleep(5)
        with contextlib.suppress(Exception):
            return await pdf_of(popup)
        return None


# ── کارها ────────────────────────────────────────────────────────────
async def work_list(ctx, br, login, page, which: str):
    rc = ResultCase(ctx, br, login, page)
    live, archived = {"all": (True, True), "live": (True, False), "archived": (False, True)}[which]
    await rc.search(live, archived)
    cases = await rc.all_cases()
    title = {"all": "تمام پرونده‌ها (سامانه اطلاع‌رسانی پرونده)", "live": "پرونده‌های جاری (مختومه نشده)",
             "archived": "پرونده‌های مختومه شده"}[which]
    for c in cases:
        c["status"] = {"live": "جاری", "archived": "مختومه"}.get(which, "-")
    if not cases:
        txt = await page_text(rc.page)
        if not re.search(r"پرونده|موردی|یافت", txt):
            raise FlowError("PARSE_CHANGED", "case list not recognised")
        await ctx.job.say(f"📂 {title}: پرونده‌ای یافت نشد.")
        return
    await ctx.step("L11")
    await ctx.job.send_pdf(resultcase_list_pdf(title, cases), f"cases_{which}.pdf",
                           f"📂 {title}\nتعداد: {to_fa_digits(len(cases))}")
    # نسخه‌ی چاپی خود صفحه هم (برای اطمینان از کامل بودن)
    with contextlib.suppress(Exception):
        await ctx.job.send_pdf(await pdf_of(rc.page), f"cases_{which}_page.pdf", "🖨 نسخه‌ی چاپی صفحه‌ی سامانه")
    ctx.new_items = len(cases)


def _detail_caption(case_no, d) -> str:
    info = normalize_fa(d["case_info"])
    parts = [f"📂 پرونده {to_fa_digits(case_no)}"
             + (f" — ردیف فرعی {to_fa_digits(d['card'].get('sub_no'))}" if d["card"].get("sub_no") else "")]
    m = re.search(r"شماره\s*بایگانی\s*(\d+)", info)
    if m:
        parts.append(f"شماره بایگانی: {to_fa_digits(m.group(1))}")
    m = re.search(r"به\s*(شعبه\s*[^\n]+?)\s*ارجاع", info)
    if m:
        parts.append(f"شعبه: {to_fa_digits(m.group(1))}")
    h = next_hearing(info)
    if h:
        parts.append(f"📅 وقت رسیدگی: {to_fa_digits(h[0])} ساعت {to_fa_digits(h[1])}")
    lc = last_change(info)
    if lc:
        parts.append(f"🕒 آخرین تغییر: {to_fa_digits(lc)}")
    return "\n".join(parts)


async def _send_long(job, text):
    for i in range(0, len(text), 3500):
        await job.say(text[i:i + 3500])


async def work_detail(ctx, br, login, page, case_no: str):
    rc = ResultCase(ctx, br, login, page)
    await rc.search(True, True, case_no)
    details = await rc.open_details()
    if not details:
        await ctx.job.say(f"پرونده {to_fa_digits(case_no)} در این بخش یافت نشد. "
                          "(اگر پرونده مربوط به موکل است، بخش «وکیل» را امتحان کنید.)")
        return
    await ctx.step("L11")
    for d in details:
        await ctx.job.say(_detail_caption(case_no, d))
        await _send_long(ctx.job, "📜 روند کار پرونده:\n" + d["case_info"].strip())
        for title, data in d["pdfs"]:
            await ctx.job.send_pdf(data, f"case_{case_no}_{len(title)}.pdf", f"🖨 {title} — {to_fa_digits(case_no)}")
        lav = extract_lavayeh(d["case_info"])
        if lav:
            await ctx.job.say(T.lavayeh_message(lav))
    ctx.new_items = len(details)


async def work_track(ctx, br, login, page, tracked: list[dict]):
    """برای هر پرونده‌ی ثبت‌شده فقط تغییرات جدید را اعلام می‌کند."""
    rc = ResultCase(ctx, br, login, page)
    import json

    changed = 0
    for i, t in enumerate(tracked):
        case_no = t["case_number"]
        if i:
            await rc.reload()
        try:
            await rc.search(True, True, case_no)
            details = await rc.open_details()
        except FlowError:
            raise
        except Exception as e:
            await ctx.report("PARSE_CHANGED", f"track {case_no}: {type(e).__name__}")
            continue
        if not details:
            await ctx.job.say(f"⚠️ پرونده {to_fa_digits(case_no)} یافت نشد.")
            continue
        old = set(json.loads(t["line_hashes"] or "[]"))
        all_hashes = set()
        new_lines = []
        for d in details:
            all_hashes |= {line_hash(x) for x in numbered_lines(d["case_info"])}
            new_lines += diff_new_lines(d["case_info"], old) if old else []
        first_time = not t["line_hashes"]
        await ctx.db.update_tracked(ctx.job.user_id, case_no, last_change(details[0]["case_info"]), all_hashes)
        if first_time:
            await ctx.job.say(_detail_caption(case_no, details[0]) + "\n✅ وضعیت فعلی ثبت شد؛ از این به بعد فقط تغییرات اعلام می‌شود.")
            for title, data in details[0]["pdfs"][:1]:
                await ctx.job.send_pdf(data, f"case_{case_no}.pdf", f"🖨 {title}")
            continue
        if not new_lines:
            await ctx.job.say(f"✅ پرونده {to_fa_digits(case_no)}: تغییر جدیدی نیست.")
            continue
        changed += 1
        await ctx.job.say(f"🆕 تغییرات جدید پرونده {to_fa_digits(case_no)}:\n"
                          + "\n".join(f"• {to_fa_digits(x)}" for x in new_lines[:30]))
        for title, data in details[0]["pdfs"][:1]:
            await ctx.job.send_pdf(data, f"case_{case_no}.pdf", f"🖨 {title}")
        lav = [x for x in extract_lavayeh("\n".join(new_lines))]
        if lav:
            await ctx.job.say(T.lavayeh_message(lav))
    ctx.new_items = changed
