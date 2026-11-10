"""راه‌اندازی Playwright و کمک‌تابع‌های مشترک کلیک/انتظار.

حالت پیش‌فرض: مرورگر «قابل‌مشاهده» (HEADLESS=0) تا رفتار ربات را ببینید؛ پنجره در
گوشه‌ی بالا-چپ با اندازه‌ی BROWSER_WINDOW_SIZE باز می‌شود تا با پنجره‌ی ربات اصلی
قاطی نشود. اگر نمایشگر نباشد (سرور)، خودکار به headless برمی‌گردد.

قاعده: `networkidle` ممنوع است (روی این سایت ۳۰ ثانیه timeout می‌دهد)؛ به‌جایش انتظار برای
selector/آدرس یا «اولین مورد از چند حالت» + مکث‌های انسانی (ببینید: رفتار انسانی).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import random
import re

from playwright.async_api import Page, async_playwright

from .. import config
from ..utils import normalize_fa

log = logging.getLogger(__name__)
_sem: asyncio.Semaphore | None = None


def semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(config.MAX_CONCURRENT_BROWSERS)
    return _sem


class Browser:
    """async with Browser() as br:  br.context / br.page  — همیشه در خروج بسته می‌شود."""

    def __init__(self):
        self._pw = None
        self.browser = None
        self.context = None
        self.page: Page | None = None
        self.dialogs: list[str] = []
        self.pdfs: list[bytes] = []   # PDFهایی که در هر تب باز/دانلود شدند (headless نمایشگر PDF ندارد)
        self._pdf_keys: list[tuple] = []
        self._held = False

    async def __aenter__(self):
        await semaphore().acquire()
        self._held = True
        try:
            self._pw = await async_playwright().start()
            args = ["--disable-blink-features=AutomationControlled"]  # مثل ربات اصلی؛ نشانه‌های اتوماسیون کمتر
            if not config.HEADLESS:
                # پنجره‌ی قابل‌مشاهده در گوشه‌ی بالا-چپ (متمایز از ربات اصلی)
                if config.BROWSER_WINDOW_POSITION:
                    args.append(f"--window-position={config.BROWSER_WINDOW_POSITION}")
                if config.BROWSER_WINDOW_SIZE:
                    args.append(f"--window-size={config.BROWSER_WINDOW_SIZE}")
            try:
                self.browser = await self._pw.chromium.launch(headless=config.HEADLESS, args=args)
            except Exception:
                if config.HEADLESS:
                    raise
                # سرور بدون نمایشگر (X/Display نداریم) → برگشت خودکار به headless
                log.warning("launching a visible browser failed (no display?); falling back to headless")
                self.browser = await self._pw.chromium.launch(headless=True, args=args)
            self.context = await self.browser.new_context(
                locale="fa-IR", viewport=None if not config.HEADLESS else {"width": 1366, "height": 900},
                no_viewport=not config.HEADLESS,  # در حالت قابل‌مشاهده صفحه کل پنجره را می‌گیرد
                accept_downloads=True,
                ignore_https_errors=config.IGNORE_HTTPS_ERRORS)
            self.context.set_default_timeout(20_000)
            self.context.on("page", self._attach)
            self.context.on("response", self._on_response)
            self.page = await self.context.new_page()
            if not config.HEADLESS:
                log.info("👀 مرورگر قابل‌مشاهده باز شد (ربات حقوقی — پنجره‌ی بالا-چپ)")
            return self
        except Exception:
            await self.close()
            raise

    def _attach(self, page: Page):
        async def on_dialog(d):
            self.dialogs.append(normalize_fa(d.message))
            with contextlib.suppress(Exception):
                await d.dismiss()
        page.on("dialog", on_dialog)

        async def on_download(d):
            with contextlib.suppress(Exception):
                path = await d.path()
                with open(path, "rb") as f:
                    self._add_pdf(f.read(), d.url)
        page.on("download", on_download)

    def _add_pdf(self, data: bytes, url: str):
        # یک فایل هم «پاسخ» و هم «دانلود» تولید می‌کند؛ فقط آخرین آدرس تکراری حذف می‌شود
        import time

        key = (url, int(time.monotonic() // 3))  # همان آدرس در همان ۳ ثانیه = همان فایل
        if data and data[:4] == b"%PDF" and (not self._pdf_keys or self._pdf_keys[-1] != key):
            self.pdfs.append(data)
            self._pdf_keys.append(key)

    async def _on_response(self, resp):
        if "pdf" in (resp.headers.get("content-type") or "").lower():
            with contextlib.suppress(Exception):
                self._add_pdf(await resp.body(), resp.url)

    async def popup_bytes(self, popup: Page, since: int, timeout=20.0) -> bytes | None:
        """محتوای تبِ تازه‌بازشده: PDF ضبط‌شده (پاسخ/دانلود) یا PDF رندرشده‌ی صفحه‌ی HTML."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if len(self.pdfs) > since:
                return self.pdfs[since]
            url = popup.url or ""
            if url.startswith("http"):
                with contextlib.suppress(Exception):
                    await popup.wait_for_load_state("load", timeout=3_000)
                if len(self.pdfs) > since:
                    return self.pdfs[since]
                with contextlib.suppress(Exception):
                    ctype = await popup.evaluate("document.contentType")
                    if ctype and "html" in ctype:
                        await popup.wait_for_timeout(1000)
                        return await pdf_of(popup)
            await asyncio.sleep(0.4)
        return None

    async def __aexit__(self, *exc):
        await self.close()

    async def close(self):
        for obj in (self.context, self.browser):
            if obj is not None:
                with contextlib.suppress(Exception):
                    await obj.close()
        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()
        self.context = self.browser = self._pw = self.page = None
        if self._held:
            self._held = False
            semaphore().release()

    def pop_dialogs(self) -> list[str]:
        d, self.dialogs = self.dialogs, []
        return d


# ── رفتار انسانی: سرعت پایین + مکث تصادفی + انتظار برای لود کامل ────────
def human_ms(base_ms: float) -> float:
    """پایه × (۱ + جیتر تصادفی) × ضریب سرعت — هر بار کمی متفاوت، مثل انسان.

    نمونه (پیش‌فرض‌ها): تایپ هر نویسه ۱۲۰–۲۴۰ms، مکث بین مراحل ۱٫۵–۳ ثانیه.
    SPEED_FACTOR را بزرگ‌تر بگذارید تا کل ربات کندتر شود.
    """
    jitter = 1.0 + random.uniform(0, max(0.0, config.HUMAN_JITTER))
    return base_ms * jitter * max(0.0, config.SPEED_FACTOR)


async def human_pause(page: Page, base_ms: float | None = None):
    """مکث انسانی (با جیتر) روی صفحه."""
    await page.wait_for_timeout(human_ms(base_ms if base_ms is not None else config.STEP_PAUSE_MS))


async def wait_ready(page: Page, timeout_ms: int = 30_000, settle: bool = True):
    """انتظار برای لود کامل صفحه (`networkidle` ممنوع است) + مکث انسانی.

    برای اینکه مطمئن باشیم سامانه کامل لود شده و دکمه‌ها (CTA) آماده‌ی کلیک‌اند.
    """
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("load", timeout=timeout_ms)
    if settle:
        await human_pause(page, config.PAGE_SETTLE_MS)


# ── کمک‌تابع‌ها ──────────────────────────────────────────────────────────
def text_re(*words: str) -> re.Pattern:
    """الگوی متنی که «ي/ی» و «ك/ک» و نیم‌فاصله را یکسان می‌گیرد."""
    parts = []
    for w in words:
        w = re.escape(normalize_fa(w)).replace("ی", "[یيى]").replace("ک", "[کك]").replace(r"\ ", r"[\s‌]*")
        parts.append(w)
    return re.compile("|".join(parts))


async def visible(locator, timeout=0) -> bool:
    try:
        if timeout:
            await locator.first.wait_for(state="visible", timeout=timeout)
            return True
        return await locator.first.is_visible()
    except Exception:
        return False


async def click_text(page: Page, *words, timeout=10_000, exact_role=None) -> bool:
    """روی اولین عنصر قابل‌مشاهده با یکی از متن‌ها کلیک می‌کند."""
    pat = text_re(*words)
    cands = [page.get_by_role(exact_role, name=pat)] if exact_role else [
        page.get_by_role("button", name=pat), page.get_by_role("link", name=pat), page.get_by_text(pat)]
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while True:
        for loc in cands:
            try:
                n = await loc.count()
                for i in range(n):
                    el = loc.nth(i)
                    if await el.is_visible():
                        await el.click()
                        return True
            except Exception:
                continue
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.4)


async def wait_first(checks: dict, timeout_ms=20_000, poll=0.4):
    """checks: {name: async callable → bool}. نام اولین شرط برقرار یا None."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout_ms / 1000
    while loop.time() < end:
        for name, fn in checks.items():
            try:
                if await fn():
                    return name
            except Exception:
                pass
        await asyncio.sleep(poll)
    return None


async def page_text(page: Page) -> str:
    try:
        return normalize_fa(await page.inner_text("body", timeout=10_000))
    except Exception:
        return ""


async def pdf_of(page: Page) -> bytes:
    """PDF صفحه — در حالت قابل‌مشاهده page.pdf() کار نمی‌کند، پس از CDP استفاده می‌شود.

    Page.printToPDF از طریق CDP هم در headless و هم در حالت پنجره‌دار جواب می‌دهد.
    اگر CDP در دسترس نبود (مرورگر غیر کرومیوم)، به page.pdf برمی‌گردیم.
    """
    with contextlib.suppress(Exception):
        await page.emulate_media(media="print")
    try:
        cdp = await page.context.new_cdp_session(page)
        try:
            result = await cdp.send("Page.printToPDF", {
                "paperWidth": 8.27, "paperHeight": 11.69,       # A4 (اینچ)
                "printBackground": True,
                "marginTop": 0.31, "marginBottom": 0.31,       # ~۸ میلی‌متر
                "marginLeft": 0.24, "marginRight": 0.24,       # ~۶ میلی‌متر
            })
            return base64.b64decode(result["data"])
        finally:
            with contextlib.suppress(Exception):
                await cdp.detach()
    except Exception:
        pass
    return await page.pdf(format="A4", print_background=True,
                          margin={"top": "8mm", "bottom": "8mm", "left": "6mm", "right": "6mm"})
