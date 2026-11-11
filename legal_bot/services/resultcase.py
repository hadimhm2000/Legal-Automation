"""سامانه اطلاع‌رسانی پرونده (resultcase.adliran.ir) — بخش اشخاص حقیقی یا وکلا.

۱) چاپ تمام پرونده‌ها   ۲) پرونده‌های جاری («مختومه نشده»)   ۳) پرونده‌های مختومه («مختومه شده»)
۴) چاپ و مشاهده‌ی جزئیات با شماره پرونده (روند کاری + آخرین موضوعات + لوایح دارای «220»)
۵) پرونده‌های ثبت‌شده برای بررسی روزانه (فقط تغییرات جدید اعلام می‌شود)

قواعد جدید (دستور کارفرما + ضبط‌های A/B/C/D/GGG):
- «تعداد نمایش در یک صفحه» همیشه روی ۱۰۰ گذاشته می‌شود؛ سپس همه‌ی صفحه‌ها تا آخر
  پرینت گرفته می‌شود (اگر شماره‌ی صفحه‌ای نمایش داده نشد، فقط صفحه‌ی اول).
- خطاهای استعلام (GGG) در همه‌ی مراحل: «صف پردازش…» → ۱ دقیقه صبر و دوباره استعلام،
  تا جواب بیاید یا «پرونده ای یافت نشد»؛ «تاخیر در اجرای سرویس…» → همان گزینه/مسیر
  دوباره، و اگر درست نشد ریلود و تکرار از ابتدای همان کار.
- بعد از هر استعلام با شماره پرونده، بازه‌ی زمانیِ جستجو‌شده (فیلدهای تاریخ شروع/پایان)
  به کاربر اعلام می‌شود و گزینه‌ی «بازه‌ی زمانی بیشتر» (بله/خیر) داده می‌شود؛ بازه‌ی
  بیش از یک سال، سال‌به‌سال (مرز سال شمسی) جدا می‌شود و بازه‌ی استعلام‌شده تکرار نمی‌شود.
- جزئیات پرونده (D): هر ردیف فرعی/شعبه ← «روند کاری پرونده» (اگر اطلاعات پایین صفحه
  نیامد ۳۰ ثانیه صبر و دوباره همان تب) ← «نسخه چاپی» (تب جدید ← PDF) ← «آخرین موضوعات»
  ← ارسال متن به همراه PDF قبلی ← ردیف فرعی بعدی.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re

from playwright.async_api import Page

from .. import config, texts as T
from ..utils import (fa_date, normalize_fa, parse_jalali, subtract_ranges, to_fa_digits,
                     to_jalali_str, year_windows)
from . import selectors as S
from .browser import SET_INPUT_JS, click_text, human_pause, page_text, pdf_of, text_re, visible, wait_first
from .case_parser import diff_new_lines, extract_lavayeh, last_change, line_hash, next_hearing, numbered_lines, \
    parse_case_card
from .reports import resultcase_list_pdf
from .session import FlowError, JobCancelled, UserTimeout

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

# پیام‌های سامانه (GGG): هشدار (صف پردازش) / اطلاع (یافت نشد) / خطا (تاخیر در اجرای سرویس)
MSG_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const pick = sels => {
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        if (vis(el)) { const t = (el.innerText || '').trim(); if (t) return t; }
      }
    }
    return '';
  };
  return {
    warning: pick(['[ng-bind-html="viewModel.warningMessage"]', '.alert-warning']),
    info:    pick(['[ng-bind-html="viewModel.infoMessage"]', '.alert-info']),
    error:   pick(['[ng-bind-html="viewModel.errorMessage"]', '.alert-danger']),
  };
}
"""

# همه‌ی selectهایی که «تعداد نمایش در صفحه» هستند (گزینه‌ی ۱۰۰ دارند)
PAGE_SIZE_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const out = [];
  document.querySelectorAll('select').forEach((s, i) => {
    if (!vis(s)) return;
    const opts = Array.from(s.options || []).map(o => (o.value || '').trim());
    if (opts.indexOf('100') !== -1) {
      s.setAttribute('data-rc-ps', String(i));
      out.push({idx: String(i), value: (s.value || '').trim()});
    }
  });
  return out;
}
"""

# صفحه‌بندی نتیجه: nav > ul > li (شماره صفحه / فلش بعدی) — طبق ضبط‌های B و C
PAGINATION_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const toEn = s => (s || '').replace(/[۰-۹]/g, d => d.charCodeAt(0) - 0x06F0)
                             .replace(/[٠-٩]/g, d => d.charCodeAt(0) - 0x0660);
  const out = [];
  document.querySelectorAll('ul').forEach((ul, i) => {
    if (!vis(ul)) return;
    const lis = Array.from(ul.children).filter(li => li.tagName === 'LI');
    const numbers = [];
    let hasNext = false, nextDisabled = false, active = null;
    lis.forEach(li => {
      const t = toEn((li.innerText || '').trim());
      if (/^\d+$/.test(t)) {
        li.setAttribute('data-rc-page', t);
        numbers.push(parseInt(t, 10));
        if (/(^|\s)active(\s|$)/.test(li.className)) active = parseInt(t, 10);
      } else if (/^(>|»|›|بعدی|بعد|next)$/i.test(t)) {
        li.setAttribute('data-rc-next', '1');
        hasNext = true;
        if (/(^|\s)disabled(\s|$)/.test(li.className)) nextDisabled = true;
      }
    });
    const isNav = ul.closest ? !!ul.closest('nav') : false;
    if (numbers.length >= 2 || ((isNav || /(pagination|pager)/i.test(ul.className)) && numbers.length)) {
      ul.setAttribute('data-rc-nav', String(i));
      out.push({idx: String(i), numbers: numbers, active: active, hasNext: hasNext, nextDisabled: nextDisabled});
    }
  });
  return out;
}
"""


class _SvcDelay(Exception):
    """«تاخیر در اجرای سرویس» با تکرار همان کار برطرف نشد → ریلود و تکرار از ابتدا."""


def _classify(warning: str, info: str, error: str) -> str:
    """('' | 'queue' | 'not_found' | 'svc') — تشخیص پیام‌های سامانه طبق GGG."""
    w, i, e = normalize_fa(warning or ""), normalize_fa(info or ""), normalize_fa(error or "")
    if any(normalize_fa(t) in w for t in S.RC_QUEUE_TEXTS):
        return "queue"
    if any(normalize_fa(t) in e for t in S.RC_SVC_DELAY_TEXTS):
        return "svc"
    if any(normalize_fa(t) in i for t in S.RC_NOT_FOUND_TEXTS):
        return "not_found"
    return ""


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
        await human_pause(self.page, 2000)

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

    # ── استعلام (با منطق تلاش مجدد GGG) ─────────────────────────────
    async def search(self, live: bool, archived: bool, case_no: str | None = None,
                     date_from: dt.date | None = None, date_to: dt.date | None = None) -> str:
        """استعلام/«بازیابی اطلاعات».

        - «صف پردازش…» → RC_QUEUE_WAIT_SEC صبر و دوباره استعلام، تا نتیجه یا «یافت نشد».
        - «تاخیر در اجرای سرویس…» → همان استعلام دوباره؛ برطرف نشد → ریلود و تکرار کل جستجو.
        خروجی: "found" | "not_found"
        """
        for restart in range(config.RC_SVC_MAX_RESTARTS + 1):
            try:
                return await self._search_once(live, archived, case_no, date_from, date_to)
            except _SvcDelay:
                if restart >= config.RC_SVC_MAX_RESTARTS:
                    raise FlowError(
                        "SVC_DELAY", "service delay kept repeating",
                        "⚠️ سامانه‌ی عدل ایران مکرراً «تاخیر در اجرای سرویس» داد و با ریلود هم "
                        "درست نشد. لطفاً کمی بعد دوباره امتحان کنید.")
                await self.job.say("🔄 خطای «تاخیر در اجرای سرویس» برطرف نشد؛ صفحه را ریلود می‌کنم و "
                                   "استعلام را از ابتدا تکرار می‌کنم…")
                await self.reload()
        raise FlowError("SVC_DELAY", "unreachable")

    async def _search_once(self, live, archived, case_no, date_from, date_to) -> str:
        await self.ensure()
        if case_no is not None:
            box = self.page.locator(S.RC_CASE_NO).first
            await box.wait_for(state="visible", timeout=15_000)
            await box.click()
            await box.fill(case_no)
        if date_from is not None:
            await self._set_date(S.RC_DATE_FROM, date_from)
        if date_to is not None:
            await self._set_date(S.RC_DATE_TO, date_to)
        await self._set_box(S.RC_LIVE, S.RC_LIVE_LABEL, live)
        await self._set_box(S.RC_ARCHIVED, S.RC_ARCHIVED_LABEL, archived)
        queue_tries = svc_tries = 0
        while True:
            status = await self._click_search()
            state = await self._wait_state(config.SEARCH_WAIT_MS, ok_status=status)
            if state == "found":
                await human_pause(self.page)
                return "found"
            if state == "not_found":
                await human_pause(self.page, 800)
                return "not_found"
            if state == "queue":
                queue_tries += 1
                if queue_tries > config.RC_QUEUE_MAX_TRIES:
                    raise FlowError("SITE_BUSY", "case queue kept too long",
                                    "⚠️ درخواست شما مدت طولانی در «صف پردازش» سامانه ماند و نوبتش "
                                    "نرسید. لطفاً کمی بعد دوباره امتحان کنید.")
                await self.job.say(T.rc_queue_wait(to_fa_digits(queue_tries),
                                                   to_fa_digits(config.RC_QUEUE_MAX_TRIES),
                                                   to_fa_digits(max(1, round(config.RC_QUEUE_WAIT_SEC / 60)))))
                await asyncio.sleep(config.RC_QUEUE_WAIT_SEC)
                continue
            # «تاخیر در اجرای سرویس» یا هیچ واکنشی → همان استعلام دوباره؛ تداوم → ریلود
            svc_tries += 1
            if svc_tries >= config.RC_SVC_MAX_TRIES:
                raise _SvcDelay()
            await asyncio.sleep(config.RC_SVC_RETRY_SEC)

    async def _click_search(self) -> int | None:
        """کلیک «بازیابی اطلاعات» + انتظار برای پاسخ API فهرست (تا پیام کهنه خوانده نشود)."""
        try:
            async with self.page.expect_response(
                    lambda r: S.RC_GET_LIST_API in r.url and r.request.method == "POST",
                    timeout=20_000) as ri:
                if not await click_text(self.page, *S.RC_SEARCH, timeout=10_000):
                    raise FlowError("PARSE_CHANGED", "resultcase search button not found")
            resp = await ri.value
            return resp.status
        except FlowError:
            raise
        except Exception:
            return None   # دکمه کلیک شد ولی پاسخ API دیده نشد

    async def _messages(self, page) -> dict:
        try:
            return await page.evaluate(MSG_JS)
        except Exception:
            return {}

    async def _cards_visible(self) -> bool:
        try:
            return bool(await self.cards())
        except Exception:
            return False

    async def _wait_state(self, timeout_ms: int, ok_status: int | None = None) -> str:
        """حالت صفحه پس از استعلام: queue / svc / not_found / found / '' (مهلت تمام شد)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_ms / 1000
        while loop.time() < end:
            msgs = await self._messages(self.page)
            state = _classify(msgs.get("warning", ""), msgs.get("info", ""), msgs.get("error", ""))
            if ok_status == 200 and state in ("queue", "svc"):
                state = ""   # پیام کهنه (پاسخ 200 آمده) — نادیده
            if state:
                return state
            if await self._cards_visible():
                return "found"
            if await visible(self.page.get_by_text(text_re("موردی یافت نشد", "پرونده ای یافت نشد",
                                                             "موردی برای نمایش", "یافت نشد"))):
                return "not_found"
            await asyncio.sleep(0.4)
        return ""

    # ── تاریخ جستجو (GGG: اعلام بازه + استعلام در بازه‌ی بیشتر) ───────
    async def date_range(self) -> tuple[dt.date | None, dt.date | None]:
        """مقادیر فعلی فیلدهای «تاریخ شروع/پایان» جستجو (شمسی)."""
        out = []
        for sel in (S.RC_DATE_FROM, S.RC_DATE_TO):
            try:
                val = await self.page.locator(sel).first.input_value()
            except Exception:
                val = ""
            out.append(parse_jalali(val))
        return out[0], out[1]

    async def _set_date(self, sel: str, d: dt.date):
        """نوشتن تاریخ شمسی در فیلد datepicker (اگر readonly باشد با JS)."""
        val = to_jalali_str(d)
        el = self.page.locator(sel).first
        if not await visible(el, timeout=8_000):
            raise FlowError("PARSE_CHANGED", f"date input {sel} not found")
        with contextlib.suppress(Exception):
            await el.click()
            await el.fill(val)
        try:
            got = await el.input_value()
        except Exception:
            got = ""
        if got != val:
            await self.page.evaluate(SET_INPUT_JS, [sel, val])
        with contextlib.suppress(Exception):
            await self.page.keyboard.press("Escape")   # بستن datepicker باز شده

    # ── تعداد نمایش در صفحه = ۱۰۰ + صفحه‌بندی ─────────────────────────
    async def set_page_size_100(self) -> int:
        """«تعداد نمایش در یک صفحه» همیشه ۱۰۰ — روی همه‌ی selectهای فهرست."""
        for _ in range(6):
            sels = []
            with contextlib.suppress(Exception):
                sels = await self.page.evaluate(PAGE_SIZE_JS)
            todo = [s for s in sels if s["value"] != S.RC_PAGE_SIZE_VALUE]
            if not todo:
                await human_pause(self.page, 600)
                return len(sels)
            for s in todo:
                loc = self.page.locator(f'[data-rc-ps="{s["idx"]}"]').first
                try:
                    async with self.page.expect_response(
                            lambda r: S.RC_GET_LIST_API in r.url, timeout=8_000):
                        with contextlib.suppress(Exception):
                            await loc.select_option(S.RC_PAGE_SIZE_VALUE)
                except Exception:
                    pass
                await human_pause(self.page, 800)
        return 0

    async def _pagination_info(self) -> list[dict]:
        try:
            return await self.page.evaluate(PAGINATION_JS)
        except Exception:
            return []

    async def _click_li(self, attr: str, value) -> bool:
        loc = self.page.locator(f'[{attr}="{value}"]').first
        if not await visible(loc, timeout=3_000):
            return False
        with contextlib.suppress(Exception):
            await loc.click()
            return True
        return False

    async def _goto_page(self, n: int) -> bool:
        """رفتن به صفحه‌ی n (شماره‌ی صفحه، وگرنه فلش «بعدی»)؛ False = صفحه‌ی بیش نیست."""
        infos = await self._pagination_info()
        clicked = False
        for info in infos:
            if n in (info.get("numbers") or []) and info.get("active") != n:
                if await self._click_li("data-rc-page", n):
                    clicked = True
        if clicked:
            await self._settle_page()
            return True
        # شماره‌ی n دیده نمی‌شود (مثلاً با «...») → فلش بعدی؛ فقط وقتی صفحه واقعاً عوض شود
        for info in infos:
            if info.get("hasNext") and not info.get("nextDisabled"):
                before = max((i.get("active") or 0) for i in infos)
                if await self._click_li("data-rc-next", "1"):
                    await self._settle_page()
                    infos2 = await self._pagination_info()
                    after = max((i.get("active") or 0) for i in infos2) if infos2 else 0
                    return after > before
        return False

    async def _settle_page(self):
        """صبر تا فهرستِ صفحه‌ی تازه لود شود (کارت‌ها دیده شوند یا پیام خالی بودن)."""
        await wait_first({"cards": self._cards_visible}, timeout_ms=config.SEARCH_WAIT_MS)
        await human_pause(self.page, 1200)

    async def all_pages(self, print_pages: bool = False, max_pages: int | None = None):
        """همه‌ی صفحه‌های نتیجه: (کارت‌ها، PDF هر صفحه، تعداد صفحه‌ها).

        طبق دستور کارفرما: تعداد در صفحه ۱۰۰؛ هر تعداد صفحه بود همه تا آخر
        پرینت گرفته می‌شود؛ اگر صفحه‌بندی نبود فقط صفحه‌ی اول.
        """
        max_pages = max_pages or config.RC_MAX_PAGES
        await self.set_page_size_100()
        cases, prints, seen = [], [], set()
        page_no = 1
        while True:
            for c in await self.cards():
                info = parse_case_card(c["text"])
                if info and (info["case_number"], info.get("sub_no")) not in seen:
                    seen.add((info["case_number"], info.get("sub_no")))
                    cases.append(info)
            if print_pages:
                with contextlib.suppress(Exception):
                    prints.append(await pdf_of(self.page))
            if page_no >= max_pages:
                break
            if not await self._goto_page(page_no + 1):
                break
            page_no += 1
        return cases, prints, page_no

    async def cards(self):
        return await self.page.evaluate(CASE_CARDS_JS, S.RC_VIEW)

    # ── جزئیات یک پرونده (جریان D) ───────────────────────────────────
    async def open_details(self, seen_keys: set | None = None, on_detail=None) -> list[dict]:
        """برای هر ردیف فرعی/شعبه‌ی نتیجه (همه‌ی صفحه‌ها): روند کاری (PDF) + آخرین موضوعات (متن).

        seen_keys: کلید (شماره پرونده، ردیف فرعی، شعبه) که قبلاً پردازش شده و تکرار نمی‌شود.
        on_detail: callback ناهمگام برای ارسال همان لحظه‌ی هر نتیجه.
        """
        seen = set() if seen_keys is None else seen_keys
        results = []
        await self.set_page_size_100()
        page_no = 1
        while True:
            for c in await self.cards():
                card = parse_case_card(c["text"]) or {}
                key = (card.get("case_number"), card.get("sub_no"), card.get("branch"))
                if card.get("case_number") and key in seen:
                    continue
                d = await self._process_card(c, card)
                if d and (d.get("flow_ok") or d.get("subject_ok")):
                    if card.get("case_number"):
                        seen.add(key)
                    results.append(d)
                    if on_detail is not None:
                        await on_detail(d)
                elif d is not None:
                    await self.job.say("⚠️ جزئیات یکی از ردیف‌های فرعی پس از چند تلاش دریافت نشد و رد شد.")
            if not await self._goto_page(page_no + 1):
                break
            page_no += 1
        return results

    async def _process_card(self, c: dict, card: dict) -> dict | None:
        """«مشاهده» ← جزئیات؛ اگر خطای سرویس/خالی ماندن اطلاعات، یک‌بار از ابتدا (بستن و بازکردن)."""
        d = None
        for round_ in range(2):
            popup = await self._open_popup(c)
            if popup is None:
                break
            try:
                d = await self._read_detail(popup, card)
            finally:
                with contextlib.suppress(Exception):
                    await popup.close()
            if d and (d.get("flow_ok") or d.get("subject_ok")):
                return d
            await asyncio.sleep(3)
        return d

    async def _open_popup(self, c: dict) -> Page | None:
        popup = None
        for attempt in range(2):
            try:
                async with self.br.context.expect_page(timeout=15_000) as pi:
                    await self.cards()   # برچسب data-rc را تازه می‌کند
                    await self.page.locator(f'[data-rc="{c["idx"]}"]').first.click()
                popup = await pi.value
                break
            except Exception:
                if attempt == 0:
                    await self.job.say("⏳ صفحه‌ی جزئیات باز نشد؛ دوباره تلاش می‌کنم…")
                    await asyncio.sleep(5)
        if popup is not None:
            with contextlib.suppress(Exception):
                await popup.wait_for_load_state("domcontentloaded", timeout=30_000)
        return popup

    async def _read_detail(self, popup: Page, card: dict) -> dict:
        """جریان D: «روند کاری پرونده» ← اطلاعات ← «نسخه چاپی» ← «آخرین موضوعات» ← متن."""
        out = {"card": card, "flow_info": "", "subject_info": "", "pdf": None,
               "flow_ok": False, "subject_ok": False}
        prev = ""
        # ۱) تب «روند کاری پرونده» ← اطلاعات پایین صفحه ← «نسخه چاپی» (تب جدید ← PDF)
        if await self._open_tab_with_info(popup, S.RC_TAB_FLOW, before=prev):
            out["flow_ok"] = True
            out["flow_info"] = prev = await self._case_info_text(popup)
            out["pdf"] = await self._print(popup)
        # ۲) برگشت به همان صفحه ← تب «آخرین موضوعات» ← اطلاعات پایین صفحه ← ارسال متنی
        if await self._open_tab_with_info(popup, S.RC_TAB_SUBJECT, before=prev):
            out["subject_ok"] = True
            out["subject_info"] = await self._case_info_text(popup)
        return out

    async def _open_tab_with_info(self, popup: Page, words: list[str], before: str = "") -> bool:
        """تب را می‌زند و تا درج اطلاعات پایین صفحه صبر می‌کند؛ نیامد ۳۰ ثانیه بعد دوباره همان تب.

        (خطای «تاخیر در اجرای سرویس» هم همین‌جا خوانده می‌شود → همان گزینه دوباره)
        """
        for _ in range(max(1, config.RC_TAB_MAX_TRIES)):
            if not await self._click_tab(popup, words, timeout=8_000):
                return False   # تب پیدا نشد — ساختار صفحه عوض شده
            if await self._wait_case_info(popup, config.RC_TAB_INFO_WAIT_SEC, before=before):
                return True
            msgs = await self._messages(popup)
            if _classify(msgs.get("warning", ""), msgs.get("info", ""),
                         msgs.get("error", "")) == "not_found":
                return False   # «پرونده ای یافت نشد» — تکرار بی‌فایده است
        return False

    async def _click_tab(self, popup: Page, words: list[str], timeout: int = 8_000) -> bool:
        pat = text_re(*words)
        tab = popup.locator(".custom-box-tab, [role='tab']").filter(has_text=pat)
        if await visible(tab, timeout=min(timeout, 3_000)):
            with contextlib.suppress(Exception):
                await tab.first.click()
                return True
        return await click_text(popup, *words, timeout=timeout)

    async def _wait_case_info(self, popup: Page, timeout_sec: int, before: str = "") -> bool:
        """صبر تا اطلاعات پایین صفحه درج شود (و با متن تب قبلی فرق داشته باشد)."""
        loc = popup.locator(S.RC_CASE_INFO).first
        loop = asyncio.get_running_loop()
        end = loop.time() + max(1, timeout_sec)
        while loop.time() < end:
            try:
                txt = (await loc.inner_text()).strip()
            except Exception:
                txt = ""
            if txt and (not before or normalize_fa(txt) != normalize_fa(before)):
                return True
            await asyncio.sleep(1)
        try:   # مهلت تمام شد؛ متنِ غیرخالی بهتر از هیچ است
            return bool((await loc.inner_text()).strip())
        except Exception:
            return False

    async def _case_info_text(self, popup: Page) -> str:
        try:
            return await popup.locator(S.RC_CASE_INFO).first.inner_text()
        except Exception:
            return await page_text(popup)

    async def _print(self, popup: Page) -> bytes | None:
        """«نسخه چاپی» ← تب جدید ← PDF (با چند تلاش)."""
        for _ in range(3):
            try:
                since = len(self.br.pdfs)
                async with self.br.context.expect_page(timeout=15_000) as pi:
                    if not await click_text(popup, *S.RC_PRINT, timeout=6_000):
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
    """A/B/C: فهرست پرونده‌ها — اندازه‌ی صفحه ۱۰۰ + پرینت همه‌ی صفحه‌ها تا آخر."""
    rc = ResultCase(ctx, br, login, page)
    live, archived = {"all": (True, True), "live": (True, False), "archived": (False, True)}[which]
    title = {"all": "تمام پرونده‌ها (سامانه اطلاع‌رسانی پرونده)", "live": "پرونده‌های جاری (مختومه نشده)",
             "archived": "پرونده‌های مختومه شده"}[which]
    status = await rc.search(live, archived)
    if status == "not_found":
        await ctx.job.say(f"📂 {title}: پرونده‌ای یافت نشد.")
        return
    cases, prints, n_pages = await rc.all_pages(print_pages=True)
    if not cases:
        txt = await page_text(rc.page)
        if not re.search(r"پرونده|موردی|یافت", txt):
            raise FlowError("PARSE_CHANGED", "case list not recognised")
        await ctx.job.say(f"📂 {title}: پرونده‌ای یافت نشد.")
        return
    for c in cases:
        c["status"] = {"live": "جاری", "archived": "مختومه"}.get(which, "-")
    await ctx.step("L11")
    await ctx.job.send_pdf(resultcase_list_pdf(title, cases), f"cases_{which}.pdf",
                           f"📂 {title}\nتعداد: {to_fa_digits(len(cases))}")
    # نسخه‌ی چاپی خودِ صفحه‌ها: هر صفحه‌ی نتیجه تا آخر (اگر یکی بود، همان صفحه‌ی اول)
    for i, data in enumerate(prints, 1):
        await ctx.job.send_pdf(data, f"cases_{which}_page{i}.pdf",
                               f"🖨 نسخه‌ی چاپی صفحه‌ی {to_fa_digits(i)} از {to_fa_digits(n_pages)}")
    ctx.new_items = len(cases)


def _detail_caption(case_no, d) -> str:
    info = normalize_fa(d.get("flow_info") or d.get("subject_info") or "")
    card = d.get("card") or {}
    parts = [f"📂 پرونده {to_fa_digits(case_no)}"
             + (f" — ردیف فرعی {to_fa_digits(card.get('sub_no'))}" if card.get("sub_no") else "")]
    if card.get("branch"):
        parts.append(f"شعبه: {to_fa_digits(card['branch'])}")
    m = re.search(r"شماره\s*بایگانی\s*(\d+)", info)
    if m:
        parts.append(f"شماره بایگانی: {to_fa_digits(m.group(1))}")
    if not card.get("branch"):
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


async def deliver_detail(ctx, case_no: str, d: dict):
    """ارسال نتیجه‌ی یک ردیف فرعی: PDF روند کاری + متن «آخرین موضوعات»."""
    job = ctx.job
    await job.say(_detail_caption(case_no, d))
    if d.get("pdf"):
        await job.send_pdf(d["pdf"], f"case_{case_no}_flow.pdf",
                           f"🖨 روند کاری پرونده — {to_fa_digits(case_no)}")
    elif d.get("flow_info"):
        await _send_long(job, "📜 روند کاری پرونده:\n" + d["flow_info"].strip())
    if (d.get("subject_info") or "").strip():
        await _send_long(job, "📝 آخرین موضوعات:\n" + d["subject_info"].strip())
    lav = extract_lavayeh(d.get("flow_info") or "")
    if lav:
        await job.say(T.lavayeh_message(lav))


async def work_detail(ctx, br, login, page, case_no: str):
    """D: جزئیات پرونده با شماره پرونده + پرسش بازه‌ی زمانی بیشتر (GGG)."""
    rc = ResultCase(ctx, br, login, page)
    seen: set = set()
    total = 0

    async def deliver(d):
        await deliver_detail(ctx, case_no, d)

    status = await rc.search(True, True, case_no=case_no)
    if status == "found":
        total += len(await rc.open_details(seen_keys=seen, on_detail=deliver))
    await ctx.step("L11")
    total += await _maybe_wider_range(ctx, rc, case_no, seen, deliver)
    if not total:
        await ctx.job.say(f"پرونده {to_fa_digits(case_no)} در این بخش یافت نشد. "
                          "(اگر پرونده مربوط به موکل است، بخش «وکیل» را امتحان کنید.)")
        return
    ctx.new_items = total


def _jalali_validator(v):
    d = parse_jalali(v)
    return (d, None) if d else (None, T.BAD_DATE)


async def _maybe_wider_range(ctx, rc: ResultCase, case_no: str, seen: set, deliver) -> int:
    """اعلام بازه‌ی استعلام‌شده + «بازه‌ی زمانی بیشتر؟» (بله/خیر) + اجرای پنجره‌های یک‌ساله.

    - بازه‌ی ابتدایی استعلام‌شده هرگز دوباره استعلام نمی‌شود؛ اگر کاربر همانجا زمان داد،
      همان‌جا اخطار داده می‌شود.
    - بازه‌ی بیش از یک سال، سال‌به‌سال (مرز سال شمسی) جدا می‌شود.
    """
    job = ctx.job
    try:
        s0, e0 = await rc.date_range()
        if s0 and e0:
            await job.say(T.rc_searched_range(fa_date(s0), fa_date(e0)))
        else:
            await job.say(f"🔍 استعلام پرونده {to_fa_digits(case_no)} انجام شد.")
        if await job.ask_choice(T.RC_ASK_WIDER, [("yes", T.RC_WIDER_YES), ("no", T.RC_WIDER_NO)],
                                back=False) != "yes":
            return 0
        exclude = [(s0, e0)] if (s0 and e0) else []
        while True:
            start = await job.ask_text(T.RC_ASK_WIDER_FROM, _jalali_validator)
            end = await job.ask_text(T.RC_ASK_WIDER_TO, _jalali_validator)
            if end < start:
                start, end = end, start
            remaining = subtract_ranges(start, end, exclude)
            if not remaining:
                await job.say(T.RC_RANGE_DUP)   # همان بازه‌ی استعلام‌شده — اخطار
                continue
            windows = [w for a, b in remaining for w in year_windows(a, b)]
            break
    except (JobCancelled, UserTimeout):
        await job.say("⏱ پاسخی نرسید؛ بدون بررسی بازه‌ی بیشتر ادامه می‌دهم.")
        return 0
    total = 0
    for w_start, w_end in windows:
        await job.say(T.rc_range_plan(fa_date(w_start), fa_date(w_end)))
        status = await rc.search(True, True, case_no=case_no, date_from=w_start, date_to=w_end)
        if status != "found":
            await job.say(T.rc_range_empty(fa_date(w_start), fa_date(w_end)))
            continue
        total += len(await rc.open_details(seen_keys=seen, on_detail=deliver))
    await job.say(T.rc_wider_done(total))
    return total


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
            status = await rc.search(True, True, case_no)
            details = await rc.open_details() if status == "found" else []
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
            all_hashes |= {line_hash(x) for x in numbered_lines(d["flow_info"])}
            new_lines += diff_new_lines(d["flow_info"], old) if old else []
        first_time = not t["line_hashes"]
        await ctx.db.update_tracked(ctx.job.user_id, case_no, last_change(details[0]["flow_info"]), all_hashes)
        if first_time:
            await ctx.job.say(_detail_caption(case_no, details[0]) + "\n✅ وضعیت فعلی ثبت شد؛ از این به بعد فقط تغییرات اعلام می‌شود.")
            if details[0].get("pdf"):
                await ctx.job.send_pdf(details[0]["pdf"], f"case_{case_no}.pdf", "🖨 روند کاری پرونده")
            continue
        if not new_lines:
            await ctx.job.say(f"✅ پرونده {to_fa_digits(case_no)}: تغییر جدیدی نیست.")
            continue
        changed += 1
        await ctx.job.say(f"🆕 تغییرات جدید پرونده {to_fa_digits(case_no)}:\n"
                          + "\n".join(f"• {to_fa_digits(x)}" for x in new_lines[:30]))
        if details[0].get("pdf"):
            await ctx.job.send_pdf(details[0]["pdf"], f"case_{case_no}.pdf", "🖨 روند کاری پرونده")
        lav = [x for x in extract_lavayeh("\n".join(new_lines))]
        if lav:
            await ctx.job.say(T.lavayeh_message(lav))
    ctx.new_items = changed
