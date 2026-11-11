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

try:  # برای سنجش رم آزاد سرور (اختیاری؛ اگر نصب نبود فقط سقف هم‌زمانی اعمال می‌شود)
    import psutil
except Exception:  # pragma: no cover
    psutil = None

# آدرس‌های آمار/تبلیغ که برای کار ربات لازم نیستند و فقط رم و پهنای باند می‌گیرند
_TRACKER_RE = re.compile(r"google-analytics|googletagmanager|doubleclick|yandex\.(ru|com)/metrika|mc\.yandex|"
                         r"hotjar|clarity\.ms|facebook\.net|connect\.facebook", re.I)

# فلگ‌های سبک‌سازی Chromium (بی‌خطر؛ روی رفتار سایت اثری ندارند)
_LEAN_ARGS = [
    "--disable-extensions", "--disable-background-networking", "--disable-component-update",
    "--disable-sync", "--disable-default-apps", "--no-first-run", "--mute-audio",
    "--disable-features=Translate,MediaRouter,OptimizationHints,AutofillServerCommunication",
    "--disable-background-timer-throttling",
]


def free_ram_mb() -> float | None:
    if psutil is None:
        return None
    try:
        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:  # pragma: no cover
        return None


# ── صف ورود: سقف هم‌زمانی + محافظ رم ─────────────────────────────────
class Admission:
    """هر کار مرورگری قبل از شروع یک «نوبت» می‌گیرد.

    - حداکثر MAX_CONCURRENT_BROWSERS کار هم‌زمان؛
    - اگر رم آزاد سرور کمتر از MIN_FREE_RAM_MB شد، کار جدید منتظر می‌ماند (تا پروژه‌های دیگرِ
      همین سرور گیر نکنند) — مگر هیچ کاری در حال اجرا نباشد؛
    - صف «اول‌آمده، اول‌رفته» است و جایگاه هر نفر از طریق on_queue(pos) به او اعلام می‌شود.
    """

    def __init__(self):
        self.active = 0
        self._queue: list[object] = []
        self._cond = asyncio.Condition()

    @property
    def waiting(self) -> int:
        return len(self._queue)

    def _can_admit(self) -> bool:
        if self.active >= max(1, config.MAX_CONCURRENT_BROWSERS):
            return False
        if self.active == 0:
            return True
        free = free_ram_mb()
        return free is None or free >= config.MIN_FREE_RAM_MB

    async def acquire(self, on_queue=None):
        ticket = object()
        last_pos = None
        async with self._cond:
            self._queue.append(ticket)
            try:
                while True:
                    if self._queue[0] is ticket and self._can_admit():
                        self._queue.pop(0)
                        self.active += 1
                        self._cond.notify_all()
                        return
                    pos = self._queue.index(ticket) + 1
                    if on_queue is not None and pos != last_pos:
                        last_pos = pos
                        _fire(on_queue(pos))
                    # رم ممکن است بدون آزاد شدن نوبت هم خالی شود → هر چند ثانیه دوباره بررسی
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._cond.wait(), config.QUEUE_POLL_SEC)
            except BaseException:
                with contextlib.suppress(ValueError):
                    self._queue.remove(ticket)
                self._cond.notify_all()
                raise

    async def release(self):
        async with self._cond:
            self.active = max(0, self.active - 1)
            self._cond.notify_all()


_bg: set = set()


def _fire(coro):
    """اجرای پیام صف در پس‌زمینه (خطای ارسال نباید صف را خراب کند)."""
    async def safe():
        with contextlib.suppress(Exception):
            await coro
    t = asyncio.get_running_loop().create_task(safe())
    _bg.add(t)
    t.add_done_callback(_bg.discard)


# ── یک مرورگر مشترک؛ برای هر کار فقط یک context جدا ───────────────────
class _Gen:
    """یک نسل مرورگر. بعد از BROWSER_RECYCLE_AFTER کار «بازنشسته» می‌شود و وقتی آخرین
    کارش تمام شد بسته می‌شود (جلوی نشت تدریجی رم Chromium را می‌گیرد)."""

    def __init__(self, browser):
        self.browser = browser
        self.active = 0
        self.served = 0
        self.retired = False
        self.dead = False
        browser.on("disconnected", lambda *_: setattr(self, "dead", True))


class BrowserPool:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.admission = Admission()
        self._pw = None
        self._gen: _Gen | None = None
        self._old: list[_Gen] = []
        self._lock = asyncio.Lock()

    async def _launch(self):
        if self._pw is None:
            self._pw = await async_playwright().start()
        args = ["--disable-blink-features=AutomationControlled", *_LEAN_ARGS]  # نشانه‌های اتوماسیون کمتر
        if not config.HEADLESS:
            # پنجره‌ی قابل‌مشاهده در گوشه‌ی بالا-چپ (متمایز از ربات اصلی)
            if config.BROWSER_WINDOW_POSITION:
                args.append(f"--window-position={config.BROWSER_WINDOW_POSITION}")
            if config.BROWSER_WINDOW_SIZE:
                args.append(f"--window-size={config.BROWSER_WINDOW_SIZE}")
        try:
            b = await self._pw.chromium.launch(headless=config.HEADLESS, args=args)
        except Exception:
            if config.HEADLESS:
                raise
            # سرور بدون نمایشگر → برگشت خودکار به headless
            log.warning("launching a visible browser failed (no display?); falling back to headless")
            b = await self._pw.chromium.launch(headless=True, args=args)
        log.info("🌐 مرورگر مشترک راه‌اندازی شد (%s)", "headless" if config.HEADLESS else "visible")
        return _Gen(b)

    async def new_context(self, **kw):
        """(gen, context) — context کوکی/نشست کاملاً جدا دارد."""
        async with self._lock:
            g = self._gen
            if g is not None and (g.dead or not g.browser.is_connected() or g.retired):
                self._gen = None
                if g.active == 0:     # کاری روی نسل قبلی نمانده → همین حالا بسته شود
                    with contextlib.suppress(Exception):
                        await g.browser.close()
                else:                 # با پایان آخرین کارش در done() بسته می‌شود
                    self._old.append(g)
                g = None
            if g is None:
                g = self._gen = await self._launch()
            g.active += 1
            g.served += 1
            if g.served >= max(1, config.BROWSER_RECYCLE_AFTER):
                g.retired = True
        try:
            ctx = await g.browser.new_context(**kw)
        except Exception:
            await self.done(g)
            raise
        return g, ctx

    async def done(self, g: _Gen):
        g.active = max(0, g.active - 1)
        if g.active == 0 and (g.retired or g.dead) and g is not self._gen:
            with contextlib.suppress(Exception):
                await g.browser.close()
            with contextlib.suppress(ValueError):
                self._old.remove(g)

    def stats(self) -> dict:
        return {"active": self.admission.active, "waiting": self.admission.waiting,
                "free_ram_mb": round(free_ram_mb() or 0)}

    async def close(self):
        for g in [*self._old, self._gen]:
            if g is not None:
                with contextlib.suppress(Exception):
                    await g.browser.close()
        self._old, self._gen = [], None
        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()
        self._pw = None


_pool: BrowserPool | None = None


def pool() -> BrowserPool:
    global _pool
    loop = asyncio.get_running_loop()
    if _pool is None or _pool.loop is not loop:   # هر event loop (مثلاً هر تست) مخزن خودش را دارد
        _pool = BrowserPool()
    return _pool


async def shutdown_pool():
    global _pool
    if _pool is not None and _pool.loop is asyncio.get_running_loop():
        await _pool.close()
    _pool = None


async def _route_filter(route):
    req = route.request
    rtype = req.resource_type
    if rtype != "document" and (rtype in config.BLOCK_RESOURCE_TYPES
                                or (config.BLOCK_TRACKERS and _TRACKER_RE.search(req.url))):
        with contextlib.suppress(Exception):
            await route.abort()
        return
    with contextlib.suppress(Exception):
        await route.continue_()


class Browser:
    """async with Browser(on_queue=...) as br:  br.context / br.page — همیشه در خروج بسته می‌شود.

    همه‌ی کارها یک Chromium مشترک دارند و هر کار فقط یک context جدا (کوکی/نشست جدا) می‌گیرد؛
    این کار مصرف رم هر کاربر را از چند صد مگابایت به حدود ۱۰۰ مگابایت می‌رساند.
    """

    def __init__(self, on_queue=None):
        self.on_queue = on_queue
        self.browser = None
        self.context = None
        self.page: Page | None = None
        self.dialogs: list[str] = []
        self.pdfs: list[bytes] = []   # PDFهایی که در هر تب باز/دانلود شدند (headless نمایشگر PDF ندارد)
        self._pdf_keys: list[tuple] = []
        self._held = False
        self._pool: BrowserPool | None = None
        self._gen: _Gen | None = None

    async def __aenter__(self):
        self._pool = pool()
        await self._pool.admission.acquire(self.on_queue)
        self._held = True
        try:
            self._gen, self.context = await self._pool.new_context(
                locale="fa-IR", viewport=None if not config.HEADLESS else {"width": 1366, "height": 900},
                no_viewport=not config.HEADLESS,  # در حالت قابل‌مشاهده صفحه کل پنجره را می‌گیرد
                accept_downloads=True,
                ignore_https_errors=config.IGNORE_HTTPS_ERRORS)
            self.browser = self._gen.browser
            self.context.set_default_timeout(20_000)
            if config.BLOCK_RESOURCE_TYPES or config.BLOCK_TRACKERS:
                await self.context.route("**/*", _route_filter)
            self.context.on("page", self._attach)
            self.context.on("response", self._on_response)
            self.page = await self.context.new_page()
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
        if self.context is not None:
            with contextlib.suppress(Exception):
                await self.context.close()
        if self._gen is not None and self._pool is not None:
            with contextlib.suppress(Exception):
                await self._pool.done(self._gen)
        self.context = self.browser = self.page = self._gen = None
        if self._held:
            self._held = False
            await self._pool.admission.release()

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


# نوشتن مقدار در input فقط‌خواندنی (مثل datepickerهای شمسی) + رویدادهای AngularJS
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
