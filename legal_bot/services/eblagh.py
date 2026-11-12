"""سامانه ابلاغ الکترونیک قضایی (سامانه‌ی اصلی eblagh1.adliran.ir — نه پشتیبان).

روند «بررسی ابلاغیه‌های جدید» (مطابق فایل دستور کارفرما — HTMLهای آبان ۱۴۰۵):
  بعد از ورود، کارت «ابلاغیه بازنشده» صفحه‌ی اصلی چک می‌شود:
    • عدد ۰ → بدون کلیک، «ابلاغیه جدیدی ندارید» + اسکرین‌شات صفحه برای کاربر.
    • عدد نیامده (در حال لود) → تا ۳۰ ثانیه صبر؛ نیامد → ریلود سایت و ۳۰ ثانیه دیگر؛
      باز نیامد → «سامانه ابلاغ قطع است؛ یک ساعت دیگر درخواست دهید».
    • عدد > ۰ → کلیک روی همان کارت ← جدول ابلاغیه‌های جدید.
  برای هر ابلاغیه: «مشاهده» (مودال #modalXXL) ← تب «جزئیات» (اگر تب دیگری هم بود،
  اول همین روند انجام می‌شود) ← «نسخه چاپی» (تب جدید ENoticePrint.aspx ← PDF؛
  اگر باز نشد ۳۰ ثانیه صبر و دوباره) ← «پیوست‌ها» ← بستن مودال با دکمه‌ی ×.
  بعد از بستن مودال اگر جدول خالی بود (فقط VerticalGap): دکمه‌ی «۳ ماه قبل» و
  صبر برای لود کامل؛ اگر ردیفی نیامد هر ۱۰ ثانیه دوباره — به تعداد ابلاغیه‌های بازنشده.
  اگر ابلاغیه دیگر در فهرست نبود (چون مشاهده شد) ← «بازگشت» ← «ابلاغیه‌های
  مشاهده شده» و پیدا کردن با همان شماره.
  «چاپ گروهی» استفاده نمی‌شود (به برنامه‌ی محلی سمپ‌یار روی localhost:8010 نیاز دارد).

جستجوی ابلاغیه‌های صادره براساس شماره پرونده / شماره ابلاغیه (دستور کارفرما):
  بعد از لاگین روی کارت «ابلاغیه‌های مشاهده شده» کلیک می‌شود ← «جستجوی ابلاغیه»
  (collapse با href=#SeenEblaghSearchBox) ← شماره در فیلد مربوطه
  (ENotifySearchCriteria.NoticedDocCaseNo / NoticedDocNo) ← «بازیابی ابلاغیه»
  (actions.getAllENotice). خالی ماندن → یک بار دیگر «بازیابی ابلاغیه»؛ اگر خطای
  قرمز «با شرایط وارد شده ابلاغیه‌ای یافت نشد.» آمد، متن آن برای کاربر فرستاده
  می‌شود. قبل از چاپ، همه‌ی ردیف‌ها (صادرکننده + موضوع + تاریخ) برای کاربر
  فرستاده می‌شود و فقط مواردی که کاربر انتخاب کند چاپ می‌شوند.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import re

from playwright.async_api import Page

from .. import config, keyboards as K
from .. import texts as T
from ..utils import fa_date, normalize_fa, to_fa_digits, to_jalali_str, today_tehran
from . import selectors as S
from .browser import SET_INPUT_JS, click_text, human_pause, page_text, pdf_of, text_re, visible, wait_first
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

# خواندن کارت «ابلاغیه بازنشده» صفحه‌ی اصلی (HTML ارسالی کارفرما):
#   <div class="d-flex align-items-center justify-content-center">
#     <span class="text-red text-xxl ...">2</span>          ← عدد (وقتی > 0)
#     <span class="text-main bg-grey-light ...">0</span>    ← عدد (وقتی == 0)
#     <strong>ابلاغیه<br>بازنشده</strong>
#   </div>
# عدد داخل والدِ strong است؛ اگر هیچ عددی نبود یعنی هنوز در حال لود شدن است.
BADGE_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const toEn = s => (s || '')
      .replace(/[۰-۹]/g, d => String(d.charCodeAt(0) - 0x06F0))
      .replace(/[٠-٩]/g, d => String(d.charCodeAt(0) - 0x0660));
  const labels = Array.from(document.querySelectorAll('strong, b, h5, h6'))
      .filter(e => vis(e) && /ابلاغیه/.test(e.innerText || ''));
  for (const s of labels) {
    const t = (s.innerText || '').replace(/[\n\r\t ]+/g, ' ');
    if (!/باز[\s\u200c]*نشده/.test(t)) continue;   // فقط کارت «ابلاغیه بازنشده»
    const box = s.parentElement;                     // فقط عدد + برچسب را دارد
    if (!box) continue;
    const m = toEn(box.innerText || '').match(/(\d+)/);
    let card = s;
    for (let k = 0; k < 6 && card.parentElement; k++) {
      card = card.parentElement;
      if (String(card.className || '').indexOf('card') >= 0) break;
    }
    (card || s).setAttribute('data-lb-badge', 'new');
    return m ? {state: 'count', count: parseInt(m[1], 10)} : {state: 'loading'};
  }
  return {state: 'absent'};
}
"""

# کارت «ابلاغیه‌های مشاهده شده» صفحه‌ی اصلی (HTML ارسالی کارفرما):
#   <div class="card-body p-3"> … <strong class="text-w-500 …">ابلاغیه‌های<br>مشاهده شده</strong>
# این کارت دروازه‌ی ورود به بخش جستجوی ابلاغیه است (دستور کارفرما)؛
# برای کلیک مطمئن، کارت تگ data-lb-viewed می‌گیرد.
VIEWED_CARD_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const labels = Array.from(document.querySelectorAll('strong, b, h5, h6'))
      .filter(e => vis(e) && /ابلاغیه/.test(e.innerText || ''));
  for (const s of labels) {
    const t = (s.innerText || '').replace(/[\n\r\t ]+/g, ' ');
    if (!/مشاهده[\s\u200c]*شده/.test(t)) continue;   // فقط کارت «ابلاغیه‌های مشاهده شده»
    let card = s;
    for (let k = 0; k < 6 && card.parentElement; k++) {
      card = card.parentElement;
      if (String(card.className || '').indexOf('card') >= 0) break;
    }
    (card || s).setAttribute('data-lb-viewed', '1');
    return true;
  }
  return false;
}
"""

# ردیف‌های نتیجه‌ی جستجو (tempAllENoticeList): هر ردیف «مشاهده» دارد و متن کارت
# شامل شماره ابلاغیه / تاریخ صدور / صادر کننده / موضوع ابلاغیه است (HTML کارفرما).
# دکمه‌ی «مشاهده» هر ردیف هم مثل CARDS_JS تگ data-lb می‌گیرد تا کلیک‌پذیر شود.
SEARCH_ROWS_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const norm = s => (s || '').replace(/[۰-۹]/g, d => String(d.charCodeAt(0) - 0x06F0))
                              .replace(/[٠-٩]/g, d => String(d.charCodeAt(0) - 0x0660));
  const out = [];
  const btns = Array.from(document.querySelectorAll('button, a')).filter(
      b => vis(b) && (b.innerText || '').trim() === 'مشاهده');
  btns.forEach(b => {
    let el = b, txt = '';
    for (let k = 0; k < 8 && el; k++) {
      el = el.parentElement; if (!el) break;
      txt = norm(el.innerText || '');
      if (/شماره\s*ابلاغیه/.test(txt)) break;
    }
    const grab = re => {
      const m = txt.match(re);
      return m ? m[1].replace(/[\n\r\t ]+/g, ' ').trim() : '';
    };
    const id = grab(/شماره\s*ابلاغیه\s*[:：]?\s*(\d{12,20})/);
    if (!id) return;
    b.setAttribute('data-lb', id);
    out.push({
      id: id,
      issue_date: grab(/تاریخ\s*صدور\s*[:：]?\s*([\d\/\-.]+)/),
      issuer: grab(/صادر[\s\u200c]*کننده\s*[:：]?\s*([^\n]+)/),
      subject: grab(/موضوع\s*ابلاغیه\s*[:：]?\s*([^\n]+)/),
    });
  });
  const seen = new Set();
  return out.filter(o => !seen.has(o.id) && seen.add(o.id));
}
"""


class Eblagh:
    def __init__(self, ctx, br, login, page: Page):
        self.ctx, self.br, self.login, self.page = ctx, br, login, page
        self.job = ctx.job
        self.home_url = page.url
        # سقف فشار دکمه‌ی «۳ ماه قبل» وقتی جدول بعد از بستن مودال خالی ماند
        # (به تعداد ابلاغیه‌های بازنشده — دستور کارفرما)
        self.recover_presses = 0

    # ── ناوبری ──
    async def ensure(self):
        self.page = await self.login.ensure(self.page)

    async def reload_home(self):
        with contextlib.suppress(Exception):
            await self.page.goto(self.home_url, wait_until="domcontentloaded", timeout=45_000)
        await self.ensure()
        await human_pause(self.page, 2500)

    async def _wait_list_ready(self):
        """صبر تا فهرست ابلاغیه‌ها واقعاً لود شود (کارت‌ها یا پیام خالی بودن) — نه زمان ثابت."""
        async def ready() -> bool:
            if await self.cards():
                return True
            # فقط پیام‌های روشنِ «خالی بودن»؛ واژه‌ی کلی «ابلاغیه» در سرصفحه هست و علامت لود نیست
            txt = await page_text(self.page)
            return any(w in txt for w in ("یافت نشد", "موردی به نمایش", "رکوردی", "موجود نیست"))
        await wait_first({"list": ready}, timeout_ms=config.SEARCH_WAIT_MS)
        await human_pause(self.page)

    async def open_new_list(self):
        """باز کردن جدول ابلاغیه‌های جدید: کلیک روی کارت «ابلاغیه بازنشده» (UI جدید)
        یا منوی قبلی «ابلاغیه‌های جدید» (UI قدیمی)."""
        await self.ensure()
        clicked = False
        loc = self.page.locator(S.BADGE_CARD_SEL)
        if await visible(loc, timeout=4_000):
            with contextlib.suppress(Exception):
                await loc.first.click()
                clicked = True
        if not clicked:
            clicked = await click_text(self.page, *S.NEW_BADGE_CARD, timeout=6_000)
        if not clicked and await visible(self.page.locator(S.NEW_NOTICES_ID)):
            with contextlib.suppress(Exception):
                await self.page.locator(S.NEW_NOTICES_ID).first.click()
                clicked = True
        if not clicked:
            clicked = await click_text(self.page, *S.NEW_NOTICES, timeout=10_000)
        if not clicked:
            raise FlowError("PARSE_CHANGED", "new-notices card/button not found")
        await self._wait_list_ready()

    async def open_viewed_list(self):
        """ورود به «ابلاغیه‌های مشاهده شده» (دستور کارفرما — کلید ورود جستجو):

        بعد از لاگین باید روی کارت «ابلاغیه‌های مشاهده شده» صفحه‌ی اصلی کلیک شود؛
        کارت با VIEWED_CARD_JS تگ می‌خورد و کلیک می‌شود (جایگزین: متن/دکمه‌ی UI قدیم).
        اگر از قبل داخل همین بخش هستیم، ناوبری انجام نمی‌شود.
        """
        await self.ensure()
        if await self._on_viewed_list():
            return
        if not await self._on_home():
            # از صفحه‌ی جزئیات/فهرست جدید اول «بازگشت» (اگر وجود دارد)
            with contextlib.suppress(Exception):
                await click_text(self.page, *S.BACK_BTN, timeout=2_500)
        clicked = False
        with contextlib.suppress(Exception):
            if await self.page.evaluate(VIEWED_CARD_JS):
                loc = self.page.locator(S.VIEWED_CARD_SEL)
                if await visible(loc, timeout=3_000):
                    with contextlib.suppress(Exception):
                        await loc.first.click()
                        clicked = True
        if not clicked:
            clicked = await click_text(self.page, *S.VIEWED_NOTICES, timeout=10_000)
        if not clicked:
            raise FlowError("PARSE_CHANGED", "viewed-notices card/button not found")
        await self._wait_list_ready()

    async def _on_viewed_list(self) -> bool:
        """نشانه‌های بودن در صفحه‌ی «ابلاغیه‌های مشاهده شده» (فرم جستجوی ابلاغیه)."""
        if await visible(self.page.locator(S.SEARCH_BOX_BTN), timeout=1_000):
            return True
        return await visible(self.page.locator(S.SEARCH_CASE_INPUT), timeout=1_000)

    async def _on_home(self) -> bool:
        """صفحه‌ی اصلی سامانه ابلاغ (کارت‌های خدمات روی آن است)."""
        st = await self._badge_state()
        if st.get("state") in ("count", "loading"):
            return True
        return await self._old_menu_visible()

    # ── کارت «ابلاغیه بازنشده» (صفحه‌ی اصلی — دستور کارفرما) ──
    async def _badge_state(self) -> dict:
        with contextlib.suppress(Exception):
            r = await self.page.evaluate(BADGE_JS)
            if isinstance(r, dict):
                return r
        return {"state": "absent"}

    async def _old_menu_visible(self) -> bool:
        """نشانه‌های UI قدیمی (منوی «ابلاغیه‌های جدید») — برای ادامه‌ی روند قدیمی."""
        if await visible(self.page.locator(S.NEW_NOTICES_ID), timeout=1_500):
            return True
        with contextlib.suppress(Exception):
            return await visible(self.page.get_by_text(text_re(*S.NEW_NOTICES)), timeout=1_500)
        return False

    async def _wait_badge(self, timeout_sec: float):
        """صبر تا عدد کارت بیاید. خروجی: ("count", N) / ("loading", None) / ("absent", None)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_sec
        while loop.time() < end:
            r = await self._badge_state()
            if r.get("state") == "count":
                return ("count", int(r.get("count") or 0))
            if r.get("state") == "absent" and await self._old_menu_visible():
                return ("absent", None)   # UI قدیمی است؛ کارت اصلاً وجود ندارد
            await asyncio.sleep(1.0)       # در حال لود / تاخیر سامانه
        r = await self._badge_state()
        if r.get("state") == "count":
            return ("count", int(r.get("count") or 0))
        if r.get("state") == "absent" and await self._old_menu_visible():
            return ("absent", None)
        return ("loading", None)

    async def read_badge(self):
        """عدد کارت «ابلاغیه بازنشده» را می‌خواند (مطابق دستور کارفرما):

        • عدد ۰ یا بیشتر → ("count", N)
        • کارت نبود (UI قدیمی) → ("absent", None)
        • عدد بعد از ۳۰ ثانیه صبر + ریلود سایت + ۳۰ ثانیه دیگر هم نیامد → ("down", None)
        """
        await self.ensure()
        st = await self._wait_badge(config.BADGE_WAIT_SEC)
        if st[0] == "loading":
            await self.job.say(T.BADGE_RELOADING)
            await self.reload_home()
            st = await self._wait_badge(config.BADGE_WAIT_SEC)
        return ("down", None) if st[0] == "loading" else st

    async def home_screenshot(self) -> bytes | None:
        """اسکرین‌شات صفحه‌ی اصلی (برای اعلام «ابلاغیه جدیدی ندارید» به کاربر)."""
        try:
            with contextlib.suppress(Exception):
                await self.page.locator(S.BADGE_CARD_SEL).first.scroll_into_view_if_needed(timeout=3_000)
            await human_pause(self.page, 400)
            return await self.page.screenshot(timeout=15_000)
        except Exception:
            return None

    # ── بازیابی جدول خالی با «۳ ماه قبل» ──
    async def _has_cards(self) -> bool:
        return bool(await self.cards())

    async def _press_months3(self, timeout=8_000) -> bool:
        """دکمه‌ی «۳ ماه قبل» — صبر برای فعال بودن (disabled حین لود) و کلیک."""
        loc = self.page.locator(S.MONTHS3_BTN).first
        try:
            await loc.wait_for(state="visible", timeout=timeout)
            for _ in range(10):
                if await loc.is_enabled():
                    await loc.click()
                    return True
                await asyncio.sleep(1)
        except Exception:
            pass
        return await click_text(self.page, *S.MONTHS3_BACK, timeout=4_000)

    async def recover_empty_list(self, max_presses: int) -> bool:
        """بعد از بستن مودال، جدول ابلاغیه‌های بازنشده خالی شد (فقط VerticalGap):

        دکمه‌ی «۳ ماه قبل» را می‌زنیم و صبر می‌کنیم تا لود کامل شود؛ اگر ردیفی
        نیامد، هر ۱۰ ثانیه دوباره — حداکثر به تعداد ابلاغیه‌های بازنشده.
        """
        presses = max(1, int(max_presses or 1))
        await self.job.say(T.EMPTY_LIST_RECOVERING)
        for i in range(presses):
            if not await self._press_months3():
                log.warning("«۳ ماه قبل» button not found/clickable")
                return False
            got = await wait_first({"row": self._has_cards},
                                   timeout_ms=config.EMPTY_LIST_RETRY_SEC * 1000)
            if got == "row":
                await human_pause(self.page, 800)
                return True
        return await self._has_cards()

    async def cards(self) -> list[dict]:
        return await self.page.evaluate(CARDS_JS, S.VIEW_BTN)

    async def _next_page(self) -> bool:
        nxt = self.page.locator(".pagination li:not(.disabled):not(.active) >> text=/^(›|»|بعدی|>)$/")
        if await visible(nxt):
            await nxt.first.click()
            await human_pause(self.page, 2000)   # فرصت لود صفحه‌ی بعد
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

    # ── فرم «جستجوی ابلاغیه» (داخل بخش «مشاهده شده» — HTML ارسالی کارفرما) ──
    async def search_rows(self) -> list[dict]:
        """ردیف‌های فعلی نتیجه: شماره ابلاغیه + تاریخ صدور + صادرکننده + موضوع."""
        with contextlib.suppress(Exception):
            r = await self.page.evaluate(SEARCH_ROWS_JS)
            if isinstance(r, list):
                return r
        return []

    async def all_search_rows(self, max_pages=20) -> list[dict]:
        seen, out = set(), []
        for _ in range(max_pages):
            for c in await self.search_rows():
                if c["id"] not in seen:
                    seen.add(c["id"])
                    out.append(c)
            if not await self._next_page():
                break
        return out

    async def _search_error_text(self) -> str:
        """متن خطای قرمز جستجو (مثل «با شرایط وارد شده ابلاغیه‌ای یافت نشد.»)."""
        try:
            loc = self.page.locator(S.SEARCH_ERR_SEL)
            if await visible(loc, timeout=1_500):
                txt = normalize_fa(await loc.first.inner_text(timeout=2_000))
                return txt.strip()
        except Exception:
            pass
        return ""

    async def _open_search_form(self):
        """باز کردن فرم «جستجوی ابلاغیه» (دکمه‌ی collapse با href=#SeenEblaghSearchBox)."""
        loc = self.page.locator(S.SEARCH_BOX_BTN)
        if await visible(loc, timeout=8_000):
            try:
                aria = (await loc.first.get_attribute("aria-expanded") or "").lower()
            except Exception:
                aria = ""
            if aria != "true":        # بسته است → باز کن
                with contextlib.suppress(Exception):
                    await loc.first.click()
                    await human_pause(self.page, 1_200)
        else:
            if not await click_text(self.page, *S.SEARCH_NOTICE, timeout=8_000):
                raise FlowError("PARSE_CHANGED", "search-notice toggle not found")
            await human_pause(self.page, 1_200)

    async def _fill_search_value(self, css: str, label_words: tuple, value: str):
        """پرکردن فیلد جستجو — اول با selector دقیق (ng-model)، بعد با label فرم."""
        loc = self.page.locator(css)
        if not await visible(loc, timeout=8_000):
            pat = text_re(*label_words)
            loc = (self.page.locator("label").filter(has_text=pat)
                   .locator("xpath=following::input[1]"))
            if not await visible(loc, timeout=4_000):
                raise FlowError("PARSE_CHANGED", f"search input not found ({css})")
        el = loc.first
        await el.click()
        await el.fill(value)
        await human_pause(self.page, 400)

    async def _click_search_go(self) -> bool:
        """دکمه‌ی «بازیابی ابلاغیه» (actions.getAllENotice — نه «بازیابی اطلاعات» بازه)."""
        try:
            await self.page.locator(S.SEARCH_GO_NG).first.click(timeout=8_000)
            return True
        except Exception:
            return await click_text(self.page, *S.SEARCH_NOTICE_GO, timeout=6_000)

    async def _wait_search_done(self, ids_before: set):
        """صبر تا نتیجه‌ی «بازیابی ابلاغیه» بیاید.

        نشانه‌ها: چرخه‌ی لود دکمه (ng-disabled=viewModel.loading)، یا عوض شدن فهرست
        کارت‌ها نسبت به قبل، یا پیام خطا/خالی‌بودن. اگر لود دیده نشد، حداکثر ۶ ثانیه
        صبر می‌کنیم (نتایج برخی جستجوها با فهرست قبل یکی است).
        """
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        deadline = t0 + config.SEARCH_WAIT_MS / 1000
        saw_loading = False
        while loop.time() < deadline:
            try:
                enabled = await self.page.locator(S.SEARCH_GO_NG).first.is_enabled()
            except Exception:
                enabled = True
            if not enabled:
                saw_loading = True
            elif saw_loading:
                break                                    # لود تمام شد → نتیجه آماده است
            else:
                if await self._search_error_text():
                    break
                cur = {c["id"] for c in await self.cards()}
                if cur and cur != ids_before:
                    break
                txt = await page_text(self.page)
                if not cur and any(w in txt for w in ("یافت نشد", "موردی به نمایش", "رکوردی", "موجود نیست")):
                    break
                if loop.time() - t0 > 6:
                    break
            await asyncio.sleep(0.4)
        await human_pause(self.page, 1_000)

    async def run_search(self, field: str, value: str) -> list[dict]:
        """کل جستجو: «ابلاغیه‌های مشاهده شده» ← «جستجوی ابلاغیه» ← مقدار در فیلد
        مربوطه ← «بازیابی ابلاغیه» ← ردیف‌های نتیجه.

        field: "case" (شماره پرونده) یا "notice" (شماره ابلاغیه).
        """
        css, label = ((S.SEARCH_CASE_INPUT, ("شماره پرونده",)) if field == "case"
                      else (S.SEARCH_NO_INPUT, ("شماره ابلاغیه",)))
        await self.open_viewed_list()
        ids_before = {c["id"] for c in await self.cards()}
        await self._open_search_form()
        await self._fill_search_value(css, label, value)
        if not await self._click_search_go():
            raise FlowError("PARSE_CHANGED", "search go button not found")
        await self._wait_search_done(ids_before)
        return await self.all_search_rows()

    # ── یک ابلاغیه ──
    async def _wait_detail(self):
        """صبر برای باز شدن جزئیات: مودال #modalXXL (UI جدید) یا صفحه‌ی جزئیات (قدیم)."""
        await wait_first({
            "modal": lambda: visible(self.page.locator(S.MODAL_OPEN)),
            "detail": lambda: visible(self.page.locator(S.DETAIL_TAB)),
        }, timeout_ms=20_000)

    async def _open_print(self) -> Page | None:
        """«نسخه چاپی» ← تب جدید. اگر تب باز نشد/خطا آمد: ۳۰ ثانیه صبر و دوباره
        (تا PRINT_MAX_TRIES بار — دستور کارفرما)."""
        for attempt in range(config.PRINT_MAX_TRIES):
            with contextlib.suppress(Exception):
                if await visible(self.page.locator(S.DETAIL_TAB)):
                    await self.page.locator(S.DETAIL_TAB).first.click()
            try:
                async with self.br.context.expect_page(timeout=10_000) as pi:
                    clicked = False
                    loc = self.page.locator(S.PRINT_BTN_NG)
                    with contextlib.suppress(Exception):
                        if await visible(loc, timeout=2_000):
                            await loc.first.click()
                            clicked = True
                    if not clicked and not await click_text(self.page, *S.PRINT_BTN, timeout=8_000):
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
        await human_pause(popup, 1500)
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
        await human_pause(self.page, 1500)
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

    async def _close_detail(self) -> bool:
        """بستن پنجره‌ی جزئیات ابلاغیه: در UI جدید دکمه‌ی × بالای مودال
        (btn-close / ng-click="actions.clearMessage()")؛ در UI قدیمی «بازگشت»."""
        loc = self.page.locator(S.MODAL_CLOSE)
        if await visible(loc, timeout=2_500):
            with contextlib.suppress(Exception):
                await loc.first.click()
            with contextlib.suppress(Exception):   # صبر تا مودال کاملاً بسته شود
                await self.page.locator(S.MODAL_OPEN).first.wait_for(state="hidden", timeout=10_000)
            await human_pause(self.page, 1_200)
            return True
        return await click_text(self.page, *S.BACK_BTN, timeout=5_000)

    async def process(self, ext_id: str, *, is_new: bool, prefer="current") -> dict | None:
        """یک ابلاغیه را باز (مودال جزئیات)، چاپ و (با پیوست‌ها) برای کاربر ارسال می‌کند. خروجی: اطلاعات استخراج‌شده."""
        for round_ in range(2):  # دور دوم = بعد از ریلود سایت
            if not await self.find_and_open(ext_id, prefer=prefer if round_ == 0 else "viewed"):
                if round_ == 0:
                    await self.reload_home()
                    continue
                return None
            await self._wait_detail()
            await human_pause(self.page, 2_000)
            popup = await self._open_print()
            if popup is None:
                await self.job.say("🔄 صفحه‌ی چاپ پس از ۳ تلاش باز نشد؛ سایت را ریلود می‌کنم…")
                await self.reload_home()
                continue
            text, table, pdf = await self._read_print(popup)
            info = parse_notice_text(text, table)
            info["notice_number"] = info.get("notice_number") or ext_id
            atts = await self._attachments(ext_id)
            await self._close_detail()
            await human_pause(self.page, 1_500)
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
    """بررسی ابلاغیه‌های جدید — مطابق دستور کارفرما (فایل آبان ۱۴۰۵):

    ۱) کارت «ابلاغیه بازنشده» صفحه‌ی اصلی چک می‌شود؛
    ۲) عدد ۰ → پیام + اسکرین‌شات (بدون کلیک)؛
    ۳) عدد > ۰ → کلیک روی کارت ← جدول ← چاپ تک‌تک؛
    ۴) جدول بعد از بستن مودال خالی ماند → «۳ ماه قبل» (هر ۱۰ ثانیه، به تعداد بازنشده‌ها).
    """
    e = Eblagh(ctx, br, login, page)
    state, count = await e.read_badge()
    if state == "down":
        # عدد بعد از ۳۰ ثانیه + ریلود + ۳۰ ثانیه دیگر هم نیامد
        raise FlowError("EBLAGH_DOWN", "new-notice badge did not load", T.EBLAGH_DOWN)
    if state == "count" and count == 0:
        await ctx.job.say(T.NO_NEW_NOTICES.format(time=to_fa_digits(dt.datetime.now().strftime("%H:%M"))))
        shot = await e.home_screenshot()
        if shot:
            with contextlib.suppress(Exception):
                await ctx.job.send_photo(shot, "📸 صفحه‌ی اصلی سامانه ابلاغ — بدون ابلاغیه‌ی جدید")
        return
    if state == "count":
        e.recover_presses = count
    await e.open_new_list()
    cards = await e.all_cards()
    ids = [c["id"] for c in cards]
    if state == "count" and not ids:
        # بَج عدد داد ولی جدول خالی/لود نشد → «۳ ماه قبل»
        if await e.recover_empty_list(count):
            ids = [c["id"] for c in await e.all_cards()]
    if not ids:
        if state == "count" and count > 0:
            # بَج عدد داده بود ولی جدول نیامد ← ساختار صفحه عوض شده یا کلیک کارت کار نکرد
            raise FlowError("PARSE_CHANGED", f"badge count={count} but new-notices list is empty")
        txt = await page_text(e.page)
        if not re.search(r"ابلاغیه|موردی|یافت", txt):
            raise FlowError("PARSE_CHANGED", "new-notices page not recognised")
        await ctx.job.say(T.NO_NEW_NOTICES.format(time=to_fa_digits(dt.datetime.now().strftime("%H:%M"))))
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
        # قبل از ابلاغیه‌ی بعدی: اگر بعد از بستن مودال جدول خالی شده بود (فقط VerticalGap)،
        # با «۳ ماه قبل» ردیف‌ها را برمی‌گردانیم — هر ۱۰ ثانیه، به تعداد ابلاغیه‌های بازنشده
        if is_new and i + 1 < len(ids) and not await e.cards():
            if not await e.recover_empty_list(e.recover_presses or len(ids)):
                with contextlib.suppress(Exception):
                    await e.open_new_list()
    if failed:
        await ctx.job.say("⚠️ این ابلاغیه‌ها چاپ نشدند و به مدیر گزارش شد: " + "، ".join(to_fa_digits(x) for x in failed)
                          + "\nمی‌توانید بعداً با «جستجو براساس شماره پرونده» دوباره بگیرید.")
    else:
        await ctx.job.say(f"✅ {to_fa_digits(len(ids))} ابلاغیه چاپ و ارسال شد.")


def _text_chunks(text: str, size: int = 3500) -> list[str]:
    """شکستن متن بلند به تکه‌های زیر سقف پیام بله/تلگرام — بدون بریدن یک خط."""
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


async def _ask_which_to_print(ctx, rows: list[dict], *, what: str) -> list[str]:
    """فهرست ردیف‌های پیدا‌شده را با صادرکننده/موضوع/تاریخ برای کاربر می‌فرستد و
    می‌پرسد کدام‌ها چاپ شوند (دستور کارفرما: «بگو که کدام از موارد بالا را نیاز
    دارید تا چاپ بگیریم»). خروجی: شناسه‌های انتخابی (خالی = هیچ‌کدام)."""
    job = ctx.job
    lines = [T.SEARCH_FOUND_ROWS.format(what=what, n=to_fa_digits(len(rows)))]
    for i, r in enumerate(rows, 1):
        lines.append(T.SEARCH_ROW_ITEM.format(
            n=to_fa_digits(i), id=to_fa_digits(r["id"]),
            date=to_fa_digits(r.get("issue_date") or "-"),
            issuer=(r.get("issuer") or "-")[:100],
            subject=(r.get("subject") or "-")[:150]))
    for chunk in _text_chunks("\n".join(lines)):
        await job.say(chunk)
    n = len(rows)
    options = [(str(i), to_fa_digits(i)) for i in range(1, n + 1)]
    options += [("all", T.SEARCH_PRINT_ALL), ("none", T.SEARCH_PRINT_NONE)]
    prompt = T.SEARCH_WHICH_TO_PRINT
    for _ in range(3):  # پاسخ نامفهوم → دوباره بپرس
        kind, v = await job.ask(prompt, options, accept_text=True, grid=4)
        if kind == "choice":
            if v == "none":
                return []
            if v == "all":
                return [r["id"] for r in rows]
            return [rows[int(v) - 1]["id"]]
        t = normalize_fa(v)
        if "همه" in t:
            return [r["id"] for r in rows]
        nums = sorted({int(x) for x in re.findall(r"\d+", t) if 1 <= int(x) <= n})
        if nums:
            return [rows[i - 1]["id"] for i in nums]
        prompt = T.SEARCH_BAD_CHOICE
    return []


async def _print_search_results(ctx, e: Eblagh, ids: list[str], redo):
    """چاپ ابلاغیه‌های انتخاب‌شده — همان روند مشاهده تا چاپ ابلاغیه‌های بازنشده.

    اگر بعد از بستن مودال فهرست نتیجه خالی/گم شده بود، جستجو دوباره انجام می‌شود
    (`redo`) و بعد ردیف موردنظر باز و چاپ می‌شود.
    """
    failed = []
    for ext in ids:
        info = None
        for round_ in range(2):
            # دور اول: جستجوی دوباره فقط اگر ردیف گم شده باشد؛ دور دوم: همیشه (بازسازی صفحه)
            if round_ or ext not in [c["id"] for c in await e.cards()]:
                await redo()
            if not await e._click_card(ext):
                continue
            await e._wait_detail()
            await human_pause(e.page, 2_000)
            popup = await e._open_print()
            if popup is None:
                await e.reload_home()
                continue
            text, table, pdf = await e._read_print(popup)
            info = parse_notice_text(text, table)
            info["notice_number"] = info.get("notice_number") or ext
            info["_attachments"] = await e._attachments(ext)
            info["_pdf"], info["_is_new"] = pdf, False
            await e._close_detail()
            await human_pause(e.page, 1_500)
            break
        if info:
            await deliver_notice(ctx, info)
            await ctx.db.set_run_item(ctx.run_id, ext, "done")
            ctx.new_items += 1
        else:
            failed.append(ext)
            await ctx.db.set_run_item(ctx.run_id, ext, "failed")
            await ctx.report("PRINT_FAILED", f"notice {ext} (search) could not be printed")
    if failed:
        await ctx.job.say("⚠️ این ابلاغیه‌ها چاپ نشدند و به مدیر گزارش شد: "
                          + "، ".join(to_fa_digits(x) for x in failed))
    else:
        await ctx.job.say(f"✅ {to_fa_digits(len(ids))} ابلاغیه چاپ و ارسال شد.")


async def _search_and_print(ctx, br, login, page, *, field: str, value: str, what: str):
    """جستجوی ابلاغیه‌های صادره براساس شماره پرونده/شماره ابلاغیه (دستور کارفرما):

    ۱) ورود به «ابلاغیه‌های مشاهده شده» (کلیک روی کارت صفحه‌ی اصلی)؛
    ۲) «جستجوی ابلاغیه» ← مقدار در فیلد مربوطه ← «بازیابی ابلاغیه»؛
    ۳) خالی بودن → یک بار دیگر «بازیابی ابلاغیه»؛ خطای سامانه → متن خطا برای کاربر؛
    ۴) همه‌ی ردیف‌ها (صادرکننده + موضوع + تاریخ) برای کاربر ← انتخاب کاربر؛
    ۵) چاپ موارد انتخابی، مثل روند مشاهده تا چاپ ابلاغیه‌های بازنشده.
    """
    e = Eblagh(ctx, br, login, page)

    async def redo() -> list[dict]:
        return await e.run_search(field, value)

    rows = await redo()
    if not rows:
        # دستور کارفرما: یک بار دیگر «بازیابی ابلاغیه»؛ اگر خطای قرمز آمد، متنش برای کاربر
        await ctx.job.say(T.SEARCH_ONCE_MORE)
        await e._click_search_go()
        await e._wait_search_done(set())
        rows = await e.all_search_rows()
        if not rows:
            err = await e._search_error_text()
            await ctx.job.say(err or T.SEARCH_NOT_FOUND.format(what=what))
            return
    await ctx.db.add_run_items(ctx.run_id, [r["id"] for r in rows])
    chosen = await _ask_which_to_print(ctx, rows, what=what)
    if not chosen:
        await ctx.job.say(T.SEARCH_NOTHING_SELECTED)
        return
    await ctx.job.say(T.SEARCH_PRINTING_SELECTED.format(n=to_fa_digits(len(chosen))))
    await _print_search_results(ctx, e, chosen, redo=redo)


async def work_by_case(ctx, br, login, page, case_number: str):
    await _search_and_print(ctx, br, login, page, field="case", value=case_number,
                            what=f"پرونده {to_fa_digits(case_number)}")


async def work_by_notice(ctx, br, login, page, notice_number: str):
    """جستجوی ابلاغیه‌های صادره براساس شماره ابلاغیه — درست مثل شماره پرونده،
    فقط مقدار در فیلد «شماره ابلاغیه» (ENotifySearchCriteria.NoticedDocNo) می‌رود."""
    await _search_and_print(ctx, br, login, page, field="notice", value=notice_number,
                            what=f"شماره ابلاغیه {to_fa_digits(notice_number)}")


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
    await e._wait_list_ready()


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
                await e._wait_detail()
                await human_pause(e.page, 2000)
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
                await e._close_detail()
                await human_pause(e.page, 1500)
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
