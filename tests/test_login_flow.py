"""جریان واقعی SanaLogin روی یک سایت ساختگی (Playwright route) — بدون اینترنت.

سناریو‌ها: رمز شخصی اشتباه ← کپچا ← رمز درست ← «ارسال رمز موقت» ← رمز موقت اشتباه
← رمز درست ← ورود. و: رمز شخصی اشتباه تا سقف ← توقف.

دستور کارفرما (آبان ۱۴۰۵ — ضبط steps 3): دکمه‌ی «ارسال رمز موقت» فقط وقتی نمایش
داده می‌شود که پیامِ «رمز موقت جدید ... ارسال شد» خودِ سامانه روی صفحه نباشد؛
و صفحه‌ی خطای Login/ErrorPage (آبان ۱۴۰۵): تب بسته و دوباره از گزینه‌ی قبلی.
"""
import asyncio
import base64
import json
import types

import pytest

from legal_bot import config, texts as T
from legal_bot.services import sana_login
from legal_bot.services.browser import Browser
from legal_bot.services.session import FlowError, Job, vault

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

HOME = """<html><body>
<div id=pop><p>اطلاعیه</p><button onclick="document.getElementById('pop').remove()">بستن</button></div>
<div class=card onclick="document.getElementById('m').style.display='block'">ابلاغ الکترونیک قضایی</div>
<div id=m style="display:none"><a href="http://eblagh1.adliran.ir" target="_blank">سامانه ابلاغ الکترونیک قضایی</a>
<a href="http://eblagh.adliran.ir/Dashboard/NoticeIndex" target="_blank">سامانه پشتیبان 1</a></div>
</body></html>"""

LOGIN = """<html><body><form onsubmit="return false">
<input id=personNationalCode><input id=personUserPassword type=password>
<div id=cap style="display:none"><img src="/Login/GetCaptchaImage" width=100 height=30><input id=captcha></div>
<div id=otpbox style="display:none"><input id=otpPassowrd>
<p id=otpauto style="display:none">رمز موقت جدید برای شماره همراه شما ارسال شد. پس از دریافت، جهت ورود از رمز موقت جدید استفاده نمایید.</p>
 <span id=resend onclick="fetch('/Login/SendOtpPasswordForPerson',{method:'POST'});document.getElementById('otpauto').style.display='block'">ارسال مجدد رمز موقت</span></div>
<div id=err></div></form>
<script>
const $ = s => document.querySelector(s);
const AUTO = __AUTO__;
$('#personUserPassword').addEventListener('keydown', async e => {
  if (e.key !== 'Enter') return;
  const r = await fetch('/Login/CheckPersonLogin', {method: 'POST', body: JSON.stringify({
     nc: $('#personNationalCode').value, pw: $('#personUserPassword').value, cap: $('#captcha').value})});
  if (r.status === 200) { $('#otpbox').style.display = 'block'; if (AUTO) $('#otpauto').style.display = 'block'; }
  else { $('#err').innerText = 'خطا'; $('#cap').style.display = 'block'; $('#personUserPassword').value=''; }
});
$('#otpPassowrd').addEventListener('keydown', async e => {
  if (e.key !== 'Enter') return;
  const r = await fetch('/Login/CheckPersonOtpLogin', {method: 'POST', body: JSON.stringify({otp: $('#otpPassowrd').value})});
  if (r.status === 200) location.href = 'https://eblagh1.adliran.ir/ENotice/Index';
  else $('#err').innerText = 'رمز یکبار مصرف شما نادرست است';
});
</script></body></html>"""

ERROR_PAGE = "<html><body><h1>خطای سامانه</h1></body></html>"


class Site:
    def __init__(self, good_pw="goodpw", otp_auto_sent=False, error_page_first=False):
        self.good_pw = good_pw
        self.captcha_required = False
        self.resends = 0
        self.login_bodies = []
        self.otp_auto_sent = otp_auto_sent
        self.error_page_first = error_page_first
        self.error_pages = 0
        self.login_html = LOGIN.replace("__AUTO__", "true" if otp_auto_sent else "false")

    async def handle(self, route):
        req = route.request
        url = req.url
        if url.startswith("https://adliran.ir/"):
            return await route.fulfill(body=HOME, content_type="text/html; charset=utf-8")
        if "eblagh1.adliran.ir/Login/ErrorPage" in url:
            return await route.fulfill(body=ERROR_PAGE, content_type="text/html; charset=utf-8")
        if url.rstrip("/") in ("http://eblagh1.adliran.ir", "https://eblagh1.adliran.ir"):
            if self.error_page_first:
                # دستور کارفرما (آبان ۱۴۰۵): ورود بخش به صفحه‌ی خطا افتاد
                # (سایت واقعی 302 می‌دهد؛ اینجا با JS هدایت می‌شود چون route+302
                # رویداد باز شدن تب را گیر می‌اندازد)
                self.error_page_first = False
                self.error_pages += 1
                return await route.fulfill(content_type="text/html", body=(
                    "<script>location.replace('https://eblagh1.adliran.ir/Login/ErrorPage')</script>"))
            # سایت واقعی 302 می‌دهد؛ در محیط تست با JS هدایت می‌شود
            return await route.fulfill(content_type="text/html", body=(
                "<script>location.replace('https://iehraz.adliran.ir/Login/Authenticate"
                "?ReturnUrl=http://eblagh1.adliran.ir/ENotice/Index')</script>"))
        if "iehraz.adliran.ir/Login/Authenticate" in url:
            return await route.fulfill(body=self.login_html, content_type="text/html; charset=utf-8")
        if "GetCaptchaImage" in url:
            return await route.fulfill(body=PNG, content_type="image/png")
        if "CheckPersonLogin" in url:
            b = json.loads(req.post_data)
            self.login_bodies.append({k: bool(v) for k, v in b.items()})
            ok = b["nc"] == "4420160616" and b["pw"] == self.good_pw and (not self.captcha_required or b["cap"] == "52877")
            if not ok:
                self.captcha_required = True
            return await route.fulfill(status=200 if ok else 409, body='{"message":"رمز شخصی اشتباه است"}')
        if "SendOtpPasswordForPerson" in url:
            self.resends += 1
            return await route.fulfill(status=200, body="{}")
        if "CheckPersonOtpLogin" in url:
            ok = json.loads(req.post_data)["otp"] == "123456"
            return await route.fulfill(status=200 if ok else 409, body="{}")
        if "eblagh1.adliran.ir/ENotice/Index" in url:
            return await route.fulfill(body="<html><body>ابلاغیه‌های جدید</body></html>", content_type="text/html; charset=utf-8")
        return await route.fulfill(status=404, body="")


class FakeBot:
    def __init__(self):
        self.texts = []
        self.photos = 0

    def _msg(self, text, kb):
        self.texts.append(text)
        return types.SimpleNamespace(message_id=len(self.texts), reply_markup=kb)

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        return self._msg(text, reply_markup)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.photos += 1
        return self._msg(caption, reply_markup)

    async def edit_message_reply_markup(self, **kw):
        pass


async def drive(job: Job, bot: FakeBot, answers: list, log: list | None = None):
    """answers: [(بخشی از متن پرسش, ("text", v) یا ("choice", key))] به ترتیب.
    log: ثبت (متن پرسش، کلیدهای گزینه‌ها) برای بررسی دکمه‌ها."""
    i = 0
    while True:  # تا وقتی لغو شود (تأییدهای «مقدار دریافتی» بعد از آخرین پاسخ هم باید زده شوند)
        await asyncio.sleep(0.05)
        e = job._expect
        if not e or e.future.done():
            continue
        prompt = bot.texts[-1] or ""
        if log is not None:
            log.append((prompt, [k for k, _ in e.options]))
        if prompt.startswith("مقدار دریافتی"):
            job.deliver_callback(e.seq, [k for k, _ in e.options].index("ok"))
            continue
        if i >= len(answers):
            continue
        frag, (kind, v) = answers[i]
        assert frag in prompt, (frag, prompt)
        if kind == "text":
            job.deliver_text(v)
        else:
            job.deliver_callback(e.seq, [k for k, _ in e.options].index(v))
        i += 1


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "TYPE_DELAY_MS", 1)
    monkeypatch.setattr(config, "STEP_PAUSE_MS", 30)
    monkeypatch.setattr(config, "HEADLESS", True)


async def _run(site, answers, log: list | None = None):
    bot = FakeBot()
    job = Job(bot=bot, user_id=1, chat_id=1, kind="t")
    steps = []

    async def step(c):
        steps.append(c)

    ctx = types.SimpleNamespace(job=job, step=step)
    async with Browser() as br:
        await br.context.route("**/*", site.handle)
        login = sana_login.SanaLogin(ctx, br, "eblagh")
        driver = asyncio.create_task(drive(job, bot, answers, log))
        try:
            page = await asyncio.wait_for(login.run(), 90)
            ok = login.is_target(page)
        except BaseException:
            print("BOT TEXTS:", bot.texts, "URLS:", [p.url for p in br.context.pages], "DRIVER:", driver)
            raise
        finally:
            driver.cancel()
    return bot, job, steps, ok


async def test_full_login_with_wrong_password_captcha_and_wrong_otp():
    site = Site()
    answers = [
        (T.ASK_NATIONAL_CODE, ("text", "۴۴۲۰۱۶۰۶۱۶")),
        (T.ASK_PASSWORD, ("text", "badpw")),
        ("رمز شخصی شما اشتباه است", ("text", "goodpw")),
        ("کد امنیتی", ("text", "52877")),
        # پرسش اول رمز موقت: پیام «رمز موقت جدید ... ارسال شد» روی صفحه نیست ←
        # دکمه‌ی «ارسال رمز موقت» هست (دستور کارفرما — ضبط steps 3)؛ اینجا اشتباه می‌شود.
        (T.ASK_OTP[:16], ("text", "111111")),
        # رمز اشتباه ← دوباره پرسیده می‌شود؛ هنوز پیامِ ارسالِ خودکار روی صفحه نیست ←
        # دکمه‌ی ارسال هست ← یک‌بار ارسال می‌شود.
        ("رمز موقت واردشده صحیح نبود", ("choice", "resend")),
        # ارسال دستی ← پیام «رمز موقت جدید ... ارسال شد» روی صفحه ظاهر شد ←
        # پرسش بعدی بدون دکمه‌ی ارسال است.
        ("رمز موقت دوباره برای شما ارسال شد", ("text", "123456")),
    ]
    log = []
    bot, job, steps, ok = await _run(site, answers, log=log)
    assert ok
    assert site.resends == 1                     # فقط ارسالِ دستی؛ ارسال مجدد خودکار حذف شد
    assert bot.photos == 1                       # فقط تصویر کپچا
    assert steps[:4] == ["L04", "L05", "L06", "L07"]
    # پیام پرسش اول: «ارسال شد؛ وارد کنید» + توصیه‌ی ۳۰ دقیقه
    otp_prompt = next(t for t in bot.texts if t and "رمز موقت برای شما پیامک شد" in t)
    assert "۳۰ دقیقه" in otp_prompt
    # پرسش اول دکمه‌ی «ارسال رمز موقت» دارد (پیامِ خودکار نبود — دستور کارفرما)
    first_opts = next(o for p, o in log if p == otp_prompt)
    assert "resend" in first_opts
    # پرسشِ بعد از ارسال دستی: پیام خودکار روی صفحه است ← بدون دکمه‌ی ارسال
    after = next(o for p, o in log if "دوباره برای شما ارسال شد" in (p or ""))
    assert "resend" not in after
    assert vault.get(job.owner, "nc") == "4420160616"  # تا پایان Job در RAM (برای ورود مجدد)
    vault.wipe(job.owner)
    assert vault.is_empty(job.owner)
    assert all("goodpw" not in (t or "") and "4420160616" not in (t or "") for t in bot.texts)


async def test_otp_resend_button_present_when_no_auto_sent_message():
    """دستور کارفرما (ضبط steps 3): پیام «رمز موقت جدید ... ارسال شد» روی صفحه
    نبود ← دکمه‌ی «ارسال رمز موقت» در هر پرسش رمز موقت حتماً هست."""
    site = Site()                                 # بدون پیامِ ارسالِ خودکار
    answers = [
        (T.ASK_NATIONAL_CODE, ("text", "4420160616")),
        (T.ASK_PASSWORD, ("text", "goodpw")),
        (T.ASK_OTP[:16], ("text", "123456")),
    ]
    log = []
    bot, job, steps, ok = await _run(site, answers, log=log)
    assert ok
    otp_prompts = [(p, o) for p, o in log if "رمز موقت" in (p or "") and "مقدار دریافتی" not in p]
    assert otp_prompts
    for _p, opts in otp_prompts:
        assert "resend" in opts


async def test_otp_resend_button_hidden_when_site_auto_sent_message():
    """همان دستور، حالت دوم: پیام «رمز موقت جدید ... ارسال شد» روی صفحه هست ←
    دکمه‌ی «ارسال رمز موقت» برای کاربر نمایش داده نمی‌شود."""
    site = Site(otp_auto_sent=True)
    answers = [
        (T.ASK_NATIONAL_CODE, ("text", "4420160616")),
        (T.ASK_PASSWORD, ("text", "goodpw")),
        ("رمز موقت جدید", ("text", "123456")),
    ]
    log = []
    bot, job, steps, ok = await _run(site, answers, log=log)
    assert ok
    assert site.resends == 0                      # هیچ ارسال دستی‌ای لازم نشد
    otp_prompts = [(p, o) for p, o in log if "رمز موقت" in (p or "") and "مقدار دریافتی" not in p]
    assert otp_prompts
    for _p, opts in otp_prompts:
        assert "resend" not in opts               # دکمه‌ی ارسال هرگز نمایش داده نشد
    # پیام پرسش همان «رمز موقت جدید سامانه» است (نه پیام عمومی)
    assert any("سامانه خودش" in (p or "") for p, _o in otp_prompts)


async def test_error_page_on_entry_closes_tab_and_reenters():
    """دستور کارفرما (آبان ۱۴۰۵): اگر ورود به بخش به Login/ErrorPage افتاد،
    تب بسته می‌شود و دوباره از «گزینه‌ی قبلی» (کارت همان سامانه) وارد می‌شویم."""
    site = Site(error_page_first=True)
    answers = [
        (T.ASK_NATIONAL_CODE, ("text", "4420160616")),
        (T.ASK_PASSWORD, ("text", "goodpw")),
        (T.ASK_OTP[:16], ("text", "123456")),
    ]
    bot, job, steps, ok = await _run(site, answers)
    assert ok
    assert site.error_pages == 1                  # فقط بار اول خطا داد؛ دفعه‌ی بعد درست شد
    assert any("صفحه‌ی خطا" in (t or "") for t in bot.texts)   # پیام تلاش دوباره برای کاربر


async def test_wrong_otp_limit_stops():
    site = Site()
    answers = [
        (T.ASK_NATIONAL_CODE, ("text", "4420160616")),
        (T.ASK_PASSWORD, ("text", "goodpw")),
        (T.ASK_OTP[:16], ("text", "111111")),                       # اشتباه ۱
        ("رمز موقت واردشده صحیح نبود", ("text", "111111")),        # اشتباه ۲
        ("رمز موقت واردشده صحیح نبود", ("text", "111111")),        # اشتباه ۳ ← توقف
    ]
    with pytest.raises(FlowError) as ei:
        await _run(site, answers)
    assert ei.value.category == "OTP_RESEND_LIMIT"
    assert site.resends == 0                       # هیچ ارسال دستی‌ای انجام نشد


async def test_wrong_password_limit_stops():
    site = Site(good_pw="never")
    answers = [(T.ASK_NATIONAL_CODE, ("text", "4420160616")), (T.ASK_PASSWORD, ("text", "a1"))]
    for _ in range(config.MAX_PASSWORD_ATTEMPTS - 1):
        answers.append(("رمز شخصی شما اشتباه است", ("text", "a2")))
        answers.append(("کد امنیتی", ("text", "52877")))
    with pytest.raises(FlowError) as ei:
        await _run(site, answers)
    assert ei.value.category == "LOGIN_BAD_CREDENTIALS"
    assert len(site.login_bodies) == config.MAX_PASSWORD_ATTEMPTS
    assert "09306186888" in ei.value.user_message
