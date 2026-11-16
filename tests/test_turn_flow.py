"""جریان ثبت نوبت روی سایت ساختگی (مطابق ضبط‌های کارفرما — آبان ۱۴۰۵):

  • انتخاب روز همیشه از «فردا» شروع می‌شود (روز جاری هرگز انتخاب نمی‌شود).
  • پنجشنبه/جمعه/تعطیل رسمی در فهرست روزهای نامزد نیست؛ خطای «پنجشنبه ها» ← روز بعد.
  • نوبت‌های «btn-time disable» (State==2 / تکمیل ظرفیت) کلیک نمی‌شوند؛ اگر همه‌ی
    ساعت‌های یک روز disable بود ← روز بعد (دونه‌دونه مثل ضبط steps 2).
  • خطای «نمی توان علت مراجعه را ... انتخاب نمود» ← «فهرست علت ها» ← «ارائه دلائل»؛
    باز هم نشد ← «پیگیری پرونده» (دستور کارفرما — آبان ۱۴۰۵).
  • خطای «طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای X لغایت Y فعال
    است.» ← قبل از X: رد شدن به شروع بازه؛ بعد از Y: «کامل پر؛ ۲۴ ساعت دیگر
    ساعت ۸ صبح» (دستور کارفرما — ضبط steps 2).
  • علت مراجعه همیشه ردیف ۱۵ «درخواست جلب متهم» است و فهرست علت‌ها برای کاربر
    ارسال نمی‌شود (دستور کارفرما).
  • بعد از «بررسی اطلاعات پرونده فوق» اگر سامانه خودش دادورز را پر کرده باشد،
    مستقیم «مرحله ی بعدی» (دستور کارفرما — ضبط steps).
  • sweet-alert «هیچ سمتی ... تعریف نشده است»: حین ثبت ← «ظرفیت پر؛ ۲۴ ساعت دیگر».
  • «ثبت چند نوبت»: بعد از هر نوبت «صفحه اصلی» و روند تازه برای شماره‌ی بعدی.
  • متن کامل گزینه‌های منو (دادورزها) در پیام نمایش داده می‌شود؛ دکمه‌ها شماره‌دارند.
"""
import datetime as dt
import json
import types

import pytest

from legal_bot import config
from legal_bot.services import turn as turnmod
from legal_bot.services.browser import Browser
from legal_bot.services.session import FlowError
from legal_bot.utils import (fa_date, jalali_of, to_fa_digits, to_jalali_str, today_tehran,
                             turn_candidate_days, weekday_fa)

PAGE = """<html><head><meta charset="utf-8"><style>.hide{display:none}</style></head><body>
<table>
  <thead><tr>
    <th><button onclick="shift(-1)">«</button></th>
    <th colspan="5"><strong id="calTitle"></strong></th>
    <th><button ng-click="move(1)" onclick="shift(1)">»</button></th>
  </tr></thead>
  <tbody><tr id="row"></tr></tbody>
</table>
<h2 id="dayMsg" class="hide"></h2>
<div id="times"></div>
<p id="reasonErr" class="hide">در تنظیمات نوبت دهی برای این واحد نمی توان علت مراجعه را«معرفي وراث محكوم عليه» انتخاب نمود.</p>
<button id="btnPrevStep" class="hide" onclick="goPrev()">مرحله ی قبلی</button>
<button id="btnUnitReferalReasonTypeModal" onclick="openReasons()">فهرست علت ها</button>
<button id="btnUnderstood" class="hide" onclick="understood()">متوجه شدم</button>
<button id="btnNextStep" class="hide" onclick="goNext()">مرحله ی بعدی</button>
<div id="reasonModal" class="hide"><table><tbody>
  <tr onclick="pickReason(this)"><td>15</td><td><button>انتخاب</button></td><td>درخواست جلب متهم</td></tr>
  <tr onclick="pickReason(this)"><td>16</td><td><button>انتخاب</button></td><td>ارائه دلائل</td></tr>
  <tr onclick="pickReason(this)"><td>17</td><td><button>انتخاب</button></td><td>پیگیری پرونده</td></tr>
  <tr onclick="pickReason(this)"><td>1</td><td><button>انتخاب</button></td><td>معرفي وراث محكوم عليه</td></tr>
</tbody></table></div>
<button id="btnCreateUnitTurn" class="hide" onclick="doCreate()">ثبت و دریافت نوبت</button>
<button id="yesBtn" class="hide">بلی</button>
<button id="closeBtn" class="hide" onclick="closeAll()">بستن</button>
<div id="sweet" class="hide sweet-alert showSweetAlert visible">
  <p id="sweetText"></p>
  <button onclick="closeSweet()">بستن</button>
</div>
<script>
const DATA = __DATA__;
const GLITCH = __GLITCH__;
const SWEET_ROLE = __ROLE__;
const REJECT_MODE = __REJECT__;   // 0: همه‌ی علت‌ها پذیرفته | 1: فقط «ارائه دلائل» رد | 2: هر دو جایگزین رد
const MONTHS = __MONTHS__;
let y = __SY__, m = __SM__;
let reasonFixed = false;
window.pickedReason = '';
function show(id) { document.getElementById(id).style.display = 'block'; }
function hide(id) { document.getElementById(id).style.display = 'none'; }
function renderCal() {
  document.getElementById('calTitle').innerText = MONTHS[m - 1] + ' ' + y;
  const row = document.getElementById('row');
  row.innerHTML = '';
  for (let d = 1; d <= 31; d++) {
    const td = document.createElement('td');
    td.innerText = String(d);
    td.setAttribute('onclick', 'pick(' + d + ')');
    row.appendChild(td);
  }
}
function shift(dir) {
  m += dir;
  if (m > 12) { m = 1; y++; }
  if (m < 1) { m = 12; y--; }
  renderCal();
}
function pick(d) {
  const key = y + '-' + m + '-' + d;
  const cfg = DATA[key];
  const times = document.getElementById('times');
  const msg = document.getElementById('dayMsg');
  times.innerHTML = '';
  hide('dayMsg'); hide('btnCreateUnitTurn'); hide('yesBtn');
  if (!cfg) return;
  if (cfg.error) { msg.innerText = cfg.error; show('dayMsg'); return; }
  // خطای بازه‌ی فعالِ شعبه (ضبط steps 2):
  // «طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای X لغایت Y فعال است.»
  if (cfg.range_error) { msg.innerText = cfg.range_error; show('dayMsg'); return; }
  if (cfg.reason_error && !reasonFixed) {
    show('reasonErr'); show('btnPrevStep');
    return;
  }
  (cfg.times || []).forEach(t => {
    const wrap = document.createElement('div');
    wrap.className = 'col-md-2 col-sm-2 col-xs-4';
    const b = document.createElement('div');
    b.className = 'btn-time' + (t.full ? ' disable' : '');
    b.innerText = t.time;
    wrap.appendChild(b);
    times.appendChild(wrap);
  });
  if ((cfg.times || []).some(t => !t.full)) {
    show('btnCreateUnitTurn'); show('yesBtn');
  }
}
async function doCreate() {
  const r = await fetch('/Turn/CMSUnitTurnCreate', {method: 'POST'});
  if (r.ok) { location.hash = '#/Detail'; return; }
  show('closeBtn');
  if (GLITCH) {
    show('reasonErr'); show('btnPrevStep');
  }
  if (SWEET_ROLE) {
    document.getElementById('sweetText').innerText =
      'هیچ سمتی در «شعبه اول اجراي احكام شوراهاي حل اختلاف شهرستان يزد» تعریف نشده است، ' +
      'امکان ورود به مرحله بعد وجود ندارد .';
    show('sweet');
  }
}
function closeAll() { hide('closeBtn'); }
function closeSweet() { hide('sweet'); }
function goPrev() {
  hide('reasonErr'); hide('btnPrevStep');
  show('btnUnitReferalReasonTypeModal');
}
function openReasons() { show('reasonModal'); }
function pickReason(tr) {
  window.pickedReason = (tr.innerText || '').replace(/\\s+/g, ' ').trim();
  hide('reasonModal'); hide('btnUnitReferalReasonTypeModal');
  show('btnUnderstood');
  // حالت‌های «رد شدن علت جایگزین»: REJECT_MODE 1 ← اولین جایگزین رد؛ 2 ← هر دو رد
  if (REJECT_MODE === 0) reasonFixed = true;
  else if (REJECT_MODE === 1 && window.pickedReason.indexOf('ارائه') === -1) reasonFixed = true;
  else if (REJECT_MODE === 2 && window.pickedReason.indexOf('درخواست جلب متهم') !== -1) reasonFixed = true;
}
function understood() {
  hide('btnUnderstood'); hide('btnUnitReferalReasonTypeModal'); hide('reasonErr');
}
function goNext() {
  hide('btnNextStep'); hide('reasonErr');
}
renderCal();
</script>
</body></html>"""


def _day_key(d: dt.date) -> str:
    j = jalali_of(d)
    return f"{j.year}-{j.month}-{j.day}"


class TurnSite:
    """سایت ساختگی نوبت‌دهی. day_cfg: {کلید روز: {"times": [...]} یا {"error": "..."}
    یا {"range_error": "..."} یا {"reason_error": true}}.

    month_offset: تقویم در ابتدا چند ماه عقب‌تر از ماهِ جاری نمایش داده می‌شود
    (برای آزمایش ناوبری ماه با فلش «بعد»).
    fail_first_create: این تعداد ثبتِ اول ۵۰۰ می‌دهد (خطای علت مراجعه و...).
    reject_fallbacks: 0 = همه‌ی علت‌ها پذیرفته؛ 1 = فقط «ارائه دلائل» رد می‌شود؛
    2 = هر دو علت جایگزین («ارائه دلائل» و «پیگیری پرونده») رد می‌شوند.
    """

    def __init__(self, day_cfg: dict, *, month_offset: int = -1, glitch_reason=False,
                 role_error=False, fail_first_create: int = 0, reject_fallbacks: int = 0):
        self.day_cfg, self.glitch_reason, self.role_error = day_cfg, glitch_reason, role_error
        self.fail_first_create = fail_first_create
        self.create_count = 0
        tj = jalali_of(today_tehran())
        y, m = tj.year, tj.month
        for _ in range(-min(month_offset, 0)):
            m -= 1
            if m < 1:
                m, y = 12, y - 1
        for _ in range(max(month_offset, 0)):
            m += 1
            if m > 12:
                m, y = 1, y + 1
        months_json = json.dumps(
            ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"], ensure_ascii=False)
        self.html = (PAGE
                     .replace("__DATA__", json.dumps(day_cfg, ensure_ascii=False))
                     .replace("__GLITCH__", "true" if glitch_reason else "false")
                     .replace("__ROLE__", "true" if role_error else "false")
                     .replace("__REJECT__", str(int(reject_fallbacks)))
                     .replace("__MONTHS__", months_json)
                     .replace("__SY__", str(y))
                     .replace("__SM__", str(m)))

    async def handle(self, route):
        url = route.request.url
        if "/Turn/CMSUnitTurnCreate" in url:
            self.create_count += 1
            if self.create_count > self.fail_first_create:
                return await route.fulfill(status=200, body="{}")
            return await route.fulfill(status=500, body="{}")
        return await route.fulfill(body=self.html, content_type="text/html; charset=utf-8")


class FakeJob:
    user_id = 1
    owner = (1, "x")

    def __init__(self):
        self.said, self.choices, self.pdfs = [], [], []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def ask_choice(self, prompt, options, **kw):
        self.choices.append((prompt, options))
        return options[0][0]          # «بله، ثبت کن» / تأیید

    async def send_pdf(self, data, filename, caption=""):
        self.pdfs.append((filename, caption))


def make_turn(br, page, job=None):
    job = job or FakeJob()
    ctx = types.SimpleNamespace(job=job)
    return turnmod.Turn(ctx, br, None, page), job


async def _open(site: TurnSite, url="https://adliran.ir/Turn/Index"):
    br = Browser()
    await br.__aenter__()
    await br.context.route("**/*", site.handle)
    await br.page.goto(url)
    return br


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "HEADLESS", True)
    monkeypatch.setattr(config, "TURN_MAX_DAY_LOOKAHEAD", 6)


async def test_book_starts_tomorrow_skips_full_day_and_day_error():
    """روز جاری انتخاب نمی‌شود؛ روزِ «تکمیل ظرفیت» و روزِ خطادار رد می‌شوند و
    اولین ساعتِ آزادِ روزِ بعدی ثبت می‌شود."""
    cands = turn_candidate_days(6)
    cfg = {
        _day_key(cands[0]): {"times": [{"time": "08:30", "full": True},
                                       {"time": "08:46", "full": True},
                                       {"time": "09:02", "full": True}]},      # همه disable
        _day_key(cands[1]): {"error": "به دلیل عدم حضور دادورز اجراي احكام، "
                                      "نمی توان «پنجشنبه ها» را انتخاب نمود."},
        _day_key(cands[2]): {"times": [{"time": "08:30", "full": True},
                                       {"time": "09:02", "full": False},
                                       {"time": "09:18", "full": False}]},
    }
    site = TurnSite(cfg)
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert site.create_count == 1
    assert fa_date(cands[2]) in when
    assert to_fa_digits("09:02") in when
    assert weekday_fa(cands[2]) in when
    # روز جاری و روزهای خطادار/پر انتخاب نشد
    assert fa_date(cands[0]) not in when and fa_date(cands[1]) not in when
    assert "پنجشنبه" not in when


async def test_book_never_picks_today_or_off_days():
    """حتی اگر فقط «امروز» ساعت آزاد داشته باشد، انتخاب نمی‌شود (دستور کارفرما)."""
    today = today_tehran()
    # فقط امروزِ کاذبی که در فهرست نامزدها نیست، ساعت آزاد دارد
    cfg = {_day_key(today): {"times": [{"time": "10:00", "full": False}]}}
    site = TurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.book()
    finally:
        await br.close()
    assert ei.value.category == "NO_SLOT"      # امروز نوبت آزاد داشت ولی انتخاب نشد


async def test_reason_error_first_fallback_is_arze_delael():
    """خطای «نمی توان علت مراجعه را...» بعد از ثبت ناموفق ← «فهرست علت ها» ←
    «ارائه دلائل» ← ثبت نوبت ادامه می‌یابد (دستور کارفرما — آبان ۱۴۰۵)."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"times": [{"time": "09:02", "full": False}]}}
    site = TurnSite(cfg, glitch_reason=True, fail_first_create=1)
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert site.create_count == 2                       # اول ۵۰۰ (خطای علت) بعد ۲۰۰
    assert fa_date(cands[0]) in when
    # به کاربر اعلام شد که علت به «ارائه دلائل» تغییر کرد (اولین جایگزین)
    assert any("ارائه دلائل" in s for s in job.said)
    assert not any("درخواست جلب متهم» تغییر" in s for s in job.said)


async def test_reason_error_second_fallback_is_peygiri_proande():
    """«ارائه دلائل» هم رد شد ← «پیگیری پرونده» ← ثبت نوبت (دستور کارفرما)."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"reason_error": True,
                                "times": [{"time": "10:38", "full": False}]}}
    site = TurnSite(cfg, reject_fallbacks=1)
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert site.create_count == 1               # با «پیگیری پرونده» ثبت شد
    assert fa_date(cands[0]) in when
    assert any("ارائه دلائل" in s for s in job.said)
    assert any("پیگیری پرونده" in s for s in job.said)


async def test_reason_error_at_day_click_fixed_same_day():
    """اگر خطای علت مراجعه همان‌جا بعد از انتخاب روز ظاهر شود، روز رد نمی‌شود؛
    علت با «فهرست علت ها ← ارائه دلائل» اصلاح و همان روز ثبت می‌شود."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"reason_error": True,
                                "times": [{"time": "10:38", "full": False}]}}
    site = TurnSite(cfg)
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert fa_date(cands[0]) in when          # همان روز رزرو شد، نه روز بعد
    assert any("ارائه دلائل" in s for s in job.said)


async def test_all_reasons_rejected_stops_with_clear_message():
    """هر دو علت جایگزین هم رد شدند ← توقف با پیام روشن (دستور کارفرما)."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"reason_error": True,
                                "times": [{"time": "10:38", "full": False}]}}
    site = TurnSite(cfg, reject_fallbacks=2)      # هر دو جایگزین رد می‌شوند
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.book()
    finally:
        await br.close()
    assert ei.value.category == "TURN_REASON_REJECTED"
    assert "علت‌های مراجعه" in ei.value.user_message


async def test_select_reason_always_picks_row_15_without_asking_user():
    """دستور کارفرما: علت مراجعه همیشه ردیف ۱۵ «درخواست جلب متهم» است و فهرست
    علت‌ها برای کاربر ارسال نمی‌شود (هیچ پرسشی از کاربر نمی‌آید)."""
    site = TurnSite({})
    br = await _open(site)
    try:
        t, job = make_turn(br, br.page)
        await t.select_reason()
        picked = await br.page.evaluate("window.pickedReason")
        understood_hidden = await br.page.evaluate(
            "() => document.getElementById('btnUnderstood').style.display === 'none'")
    finally:
        await br.close()
    assert "درخواست جلب متهم" in picked
    assert understood_hidden                       # «متوجه شدم» هم زده شد
    assert job.choices == []                       # هیچ فهرستی برای کاربر ارسال نشد


async def test_range_error_after_active_window_means_full():
    """«طبق تنظیمات شعبه، اخذ نوبت برای روزهای X لغایت Y فعال است» روی روزِ بعدِ
    پایانِ بازه ← نوبت کامل پر است؛ ۲۴ ساعت دیگر ساعت ۸ صبح (steps 2)."""
    cands = turn_candidate_days(6)
    rng = (f"طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای "
           f"{to_jalali_str(cands[0])} لغایت {to_jalali_str(cands[1])} فعال است.")
    cfg = {
        _day_key(cands[0]): {"times": [{"time": "09:02", "full": False}]},
        _day_key(cands[1]): {"times": [{"time": "09:02", "full": False}]},
        _day_key(cands[2]): {"range_error": rng},       # بعد از پایانِ بازه
    }
    site = TurnSite(cfg, fail_first_create=2)           # دو روزِ بازه هم پر بودند
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.book()
    finally:
        await br.close()
    assert ei.value.category == "TURN_CAPACITY_FULL"
    assert "کامل پر" in ei.value.user_message
    assert "۲۴ ساعت" in ei.value.user_message
    assert "۸ صبح" in ei.value.user_message
    assert site.create_count == 2                      # روزهای داخل بازه امتحان شدند


async def test_range_error_before_window_skips_to_start():
    """همان خطا روی روزِ قبل از شروعِ بازه ← آن روز رد می‌شود و از روزِ شروعِ
    بازه ادامه می‌یابد (پیاده‌روی دونه‌دونه)."""
    cands = turn_candidate_days(6)
    rng = (f"طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای "
           f"{to_jalali_str(cands[2])} لغایت {to_jalali_str(cands[5])} فعال است.")
    cfg = {
        _day_key(cands[0]): {"range_error": rng},       # قبل از شروعِ بازه
        _day_key(cands[1]): {"range_error": rng},       # هنوز قبل از بازه
        _day_key(cands[2]): {"times": [{"time": "10:15", "full": False}]},
    }
    site = TurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert site.create_count == 1
    assert fa_date(cands[2]) in when                   # روزِ شروعِ بازه رزرو شد
    assert fa_date(cands[0]) not in when and fa_date(cands[1]) not in when


async def test_role_error_while_booking_says_capacity_full():
    """sweet-alert «هیچ سمتی ... تعریف نشده است» حین ثبت نوبت ← پیام «ظرفیت پر؛
    ۲۴ ساعت دیگر اقدام کنید» (دستور کارفرما)."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"times": [{"time": "09:02", "full": False}]}}
    site = TurnSite(cfg, role_error=True, fail_first_create=1)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.book()
    finally:
        await br.close()
    assert ei.value.category == "TURN_CAPACITY_FULL"
    assert "۲۴ ساعت" in ei.value.user_message
    assert "ظرفیت" in ei.value.user_message


async def test_role_error_in_case_step_says_no_turn_possible():
    """همان sweet-alert در مرحله‌ی پرونده/دادورز ← «امکان نوبت گرفتن نمی باشد»."""
    site = TurnSite({})
    site.html = site.html.replace(
        '<div id="sweet" class="hide',
        '<div id="sweet" class="sweet-alert showSweetAlert visible"')
    site.html = site.html.replace(
        '<p id="sweetText"></p>',
        '<p id="sweetText">هیچ سمتی در «شعبه اول اجراي احكام» تعریف نشده است، '
        'امکان ورود به مرحله بعد وجود ندارد .</p>')
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t._role_or_raise()
    finally:
        await br.close()
    assert ei.value.category == "TURN_NO_ROLE"
    assert "امکان نوبت گرفتن" in ei.value.user_message


async def test_times_js_flags_disable_class_as_full():
    """نوبت‌های «btn-time disable» (State==2 / تکمیل ظرفیت) full=True می‌گیرند.
    روز با _select_day انتخاب می‌شود (ناوبری ماه از یک ماه عقب‌تر هم آزمایش می‌شود)."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"times": [{"time": "08:30", "full": True},
                                          {"time": "09:02", "full": False}]}}
    site = TurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        assert await t._select_day(cands[0])       # از ماهِ عقب‌تر با فلش «بعد» می‌رسد
        slots = await br.page.evaluate(turnmod.TIMES_JS)
    finally:
        await br.close()
    by_time = {s["time"]: s for s in slots}
    assert by_time["08:30"]["full"] is True       # کلاس disable → غیرقابل انتخاب
    assert by_time["09:02"]["full"] is False


async def test_choose_shows_full_text_with_numbered_buttons():
    """متن کامل گزینه‌های منو (نام کامل دادورزها) در پیام می‌آید و دکمه‌ها
    شماره‌دارند — نه بریده‌شده به ۶۰ نویسه (دستور کارفرما)."""
    long_texts = [
        "دادورز اجراي احكام اجراي احكام شعبه 1 دادگاه عمومي حقوقي شهرستان اردكان - "
        "حامد عزيزي احمدآباد -  میز کار شماره 3",
        "دادورز اجراي احكام اجراي احكام شعبه 1 دادگاه عمومي حقوقي شهرستان اردكان - "
        "محمد پرنيان -  میز کار شماره 2",
        "دادورز اجراي احكام اجراي احكام شعبه 1 دادگاه عمومي حقوقي شهرستان اردكان - "
        "علي دهستاني اردكاني -  میز کار شماره 1",
    ]
    items = [{"idx": str(i), "text": t} for i, t in enumerate(long_texts)]

    class ChooseJob(FakeJob):
        async def ask_choice(self, prompt, options, **kw):
            self.choices.append((prompt, options))
            return options[1][0]                    # گزینه‌ی دوم

    job = ChooseJob()
    t = turnmod.Turn(types.SimpleNamespace(job=job), None, None, None)
    chosen = await t._choose(items, "دادورز مرتبط را انتخاب کنید:", "دادورز:\n{}\nتأیید می‌کنید؟")
    assert chosen["idx"] == "1"
    prompt, options = job.choices[-1]
    # متن کامل هر سه گزینه در پیام هست (بریده نمی‌شود)
    for txt in long_texts:
        assert to_fa_digits(txt) in prompt
    # دکمه‌ها فقط شماره‌اند
    assert [lbl for _, lbl in options] == ["۱", "۲", "۳"]
    assert prompt.splitlines()[0] == "دادورز مرتبط را انتخاب کنید:"


async def test_single_item_confirm_shows_full_text():
    item = {"idx": "0", "text": "دادورز اجراي احكام شعبه 1 - حميده زاهدي -  میز کار شماره 4"}
    job = FakeJob()
    t = turnmod.Turn(types.SimpleNamespace(job=job), None, None, None)
    chosen = await t._choose([item], "x", "دادورز:\n{}\nتأیید می‌کنید؟")
    assert chosen is item
    prompt, options = job.choices[-1]
    assert to_fa_digits(item["text"]) in prompt
    assert [k for k, _ in options] == ["ok"]


# ── دادورز: تکمیل خودکار توسط سامانه بعد از «بررسی اطلاعات پرونده فوق» ──────
DAADVARZ_PREFILLED_HTML = """<html><head><meta charset="utf-8"><style>.hide{display:none}</style></head><body>
<button id="btnNextStep" onclick="document.getElementById('lbl').innerText='NEXT_CLICKED'">مرحله ی بعدی</button>
<div id="lbl"></div>
</body></html>"""

DAADVARZ_ASK_HTML = """<html><head><meta charset="utf-8"><style>.hide{display:none}</style></head><body>
<button onclick="document.getElementById('roleMenu').classList.remove('hide')">انتخاب سمت جهت ملاقات</button>
<ul id="roleMenu" class="dropdown-menu hide"><li onclick="pickRole()">دادورز اجراي احكام</li></ul>
<button onclick="document.getElementById('personMenu').classList.remove('hide')">هیچ موردی انتخاب نشده</button>
<ul id="personMenu" class="dropdown-menu hide"><li onclick="pickPerson()">دادورز اجراي احكام شعبه 1 - حميده زاهدي -  میز کار شماره 4</li></ul>
<button id="btnNextStep" onclick="document.getElementById('lbl').innerText='NEXT_CLICKED'">مرحله ی بعدی</button>
<div id="lbl"></div>
<script>
function pickRole(){ document.getElementById('roleMenu').classList.add('hide'); window.rolePicked = true; }
function pickPerson(){ document.getElementById('personMenu').classList.add('hide'); window.personPicked = true; }
</script>
</body></html>"""


async def _open_html(html: str):
    async def handle(route):
        return await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    br = Browser()
    await br.__aenter__()
    await br.context.route("**/*", handle)
    await br.page.goto("https://adliran.ir/Turn/Index#/Create")
    return br


async def test_daadvarz_prefilled_by_site_goes_straight_to_next_step():
    """دستور کارفرما (ضبط steps): بعد از «بررسی اطلاعات پرونده فوق» اگر خودِ سامانه
    سمت/دادورز را پر کرده باشد (placeholderها نیستند)، مستقیم «مرحله ی بعدی»."""
    br = await _open_html(DAADVARZ_PREFILLED_HTML)
    try:
        t, job = make_turn(br, br.page)
        await t.select_daadvarz()
        lbl = await br.page.evaluate("document.getElementById('lbl').innerText")
    finally:
        await br.close()
    assert lbl == "NEXT_CLICKED"                       # مستقیم مرحله‌ی بعد
    assert any("دادورز این پرونده را تکمیل" in s for s in job.said)
    assert job.choices == []                           # از کاربر چیزی پرسیده نشد


async def test_daadvarz_not_prefilled_asks_user():
    """placeholderها روی صفحه‌اند ← مثل قبل: سمت «دادورز» + انتخاب دادورز از کاربر."""
    br = await _open_html(DAADVARZ_ASK_HTML)
    try:
        t, job = make_turn(br, br.page)
        await t.select_daadvarz()
        lbl = await br.page.evaluate("document.getElementById('lbl').innerText")
        role_picked = await br.page.evaluate("window.rolePicked === true")
        person_picked = await br.page.evaluate("window.personPicked === true")
    finally:
        await br.close()
    assert lbl == "NEXT_CLICKED"
    assert role_picked and person_picked
    # تأییدِ دادورزِ تنها از کاربر پرسیده شد و متن کاملش در پیام بود
    assert len(job.choices) == 1
    prompt, options = job.choices[0]
    assert "حميده زاهدي" in prompt
    assert [k for k, _ in options] == ["ok"]


# ── جستجوی پرونده در «فهرست پرونده های من» (ضبط steps) ─────────────────────
MY_CASES_HTML = """<html><head><meta charset="utf-8"><style>.hide{display:none}</style></head><body>
<button onclick="document.getElementById('create').classList.remove('hide')">اخذ نوبت بر اساس شماره پرونده</button>
<div id="create" class="hide">
  <input id="txtCaseNo">
  <button id="btnHstcaseList" onclick="document.getElementById('list').classList.remove('hide')">فهرست پرونده های من</button>
  <div id="list" class="hide">
    <input id="txtCaseNoSearch" placeholder="شماره پرونده">
    <input id="txtArchiveNoSearch" placeholder="شماره بایگانی شعبه">
    <button onclick="retrieve()">بازیابی پرونده</button>
    <div id="alertBox" class="hide"><p id="alertText">موردی یافت نشد</p>
      <button onclick="document.getElementById('alertBox').classList.add('hide')">بستن</button></div>
    <table><tbody id="tbody"></tbody></table>
  </div>
</div>
<button id="btnCheckUnitTurn" class="hide" onclick="document.getElementById('checked').classList.remove('hide')">بررسی اطلاعات پرونده فوق</button>
<div id="checked" class="hide">CHECKED</div>
<script>
const CASES = __CASES__;
function retrieve(){
  const t = document.getElementById('tbody'); t.innerHTML = '';
  const arch = document.getElementById('txtArchiveNoSearch').value;
  const cs = document.getElementById('txtCaseNoSearch').value;
  const found = (CASES||[]).filter(c => (!arch || String(c.arch).indexOf(arch) !== -1)
                                     && (!cs || String(c.no).indexOf(cs) !== -1));
  if (!found.length) { document.getElementById('alertBox').classList.remove('hide'); return; }
  found.forEach(c => {
    const tr = document.createElement('tr');
    const td1 = document.createElement('td'); td1.innerText = c.text;
    const td2 = document.createElement('td');
    const b = document.createElement('button'); b.innerText = 'انتخاب';
    b.onclick = function(){ window.selectedRow = c.text;
      document.getElementById('btnCheckUnitTurn').classList.remove('hide'); };
    td2.appendChild(b); tr.appendChild(td1); tr.appendChild(td2); t.appendChild(tr);
  });
}
</script>
</body></html>"""

CASE_ROW_TEXT = ("شماره پرونده 140313920001478238 - شعبه اول اجراي احكام دادگاه عمومي "
                 "حقوقي شهرستان يزد - شماره بایگانی 0501667")


async def _open_my_cases(cases: list[dict]):
    html = MY_CASES_HTML.replace("__CASES__", json.dumps(cases, ensure_ascii=False))

    async def handle(route):
        return await route.fulfill(body=html, content_type="text/html; charset=utf-8")

    br = Browser()
    await br.__aenter__()
    await br.context.route("**/*", handle)
    await br.page.goto("https://adliran.ir/Turn/Index#/Create")
    return br


async def test_select_case_by_archive_fills_field_and_asks_confirmation():
    """دستور کارفرما (ضبط steps): شماره بایگانی در فیلدِ خودش پر می‌شود، «استعلام»
    زده می‌شود و نتیجه برای تأیید کاربر فرستاده می‌شود؛ بعد ردیف و «بررسی»."""
    br = await _open_my_cases([{"no": "140313920001478238", "arch": "0501667", "text": CASE_ROW_TEXT}])
    try:
        t, job = make_turn(br, br.page)
        await t.select_case("0501667", "archive")
        arch_val = await br.page.evaluate("document.getElementById('txtArchiveNoSearch').value")
        case_val = await br.page.evaluate("document.getElementById('txtCaseNoSearch').value")
        selected = await br.page.evaluate("window.selectedRow")
        checked = await br.page.evaluate(
            "() => document.getElementById('checked').style.display !== 'none'")
    finally:
        await br.close()
    assert arch_val == "0501667"                 # در فیلدِ «شماره بایگانی شعبه»
    assert case_val == ""                        # نه در فیلدِ شماره پرونده
    assert "0501667" in (selected or "")         # ردیفِ همان بایگانی انتخاب شد
    assert checked                               # «بررسی اطلاعات پرونده فوق» زده شد
    # نتیجه‌ی استعلام برای تأیید کاربر فرستاده شد (متن کامل ردیف)
    assert len(job.choices) == 1
    prompt, options = job.choices[0]
    assert "پرونده" in prompt and to_fa_digits("0501667") in prompt
    assert [k for k, _ in options] == ["ok"]


async def test_select_case_by_archive_not_found_closes_alert_and_raises():
    br = await _open_my_cases([])
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.select_case("9999999", "archive")
        # sweet-alertِ «یافت نشد» بسته شد (کلاس hide برگشت)
        alert_hidden = await br.page.evaluate(
            "() => document.getElementById('alertBox').classList.contains('hide')")
    finally:
        await br.close()
    assert ei.value.category == "CASE_NOT_FOUND"
    assert alert_hidden


async def test_select_case_by_case_number_fills_case_field():
    br = await _open_my_cases([{"no": "140313920001478238", "arch": "0501667", "text": CASE_ROW_TEXT}])
    try:
        t, job = make_turn(br, br.page)
        await t.select_case("140313920001478238", "case")
        case_val = await br.page.evaluate("document.getElementById('txtCaseNoSearch').value")
        arch_val = await br.page.evaluate("document.getElementById('txtArchiveNoSearch').value")
    finally:
        await br.close()
    assert case_val == "140313920001478238"
    assert arch_val == ""
    # جستجو با شماره پرونده: انتخاب از بین شعبه‌های اجرای احکام (متن استخراج‌شده)
    assert len(job.choices) == 1
    prompt, _ = job.choices[0]
    assert "اجرای احکام" in prompt or "اجراي احكام" in prompt


# ── ثبت چند نوبت (دستور کارفرما — آبان ۱۴۰۵) ───────────────────────────────
async def test_work_turn_multi_books_each_number_and_goes_home(monkeypatch):
    """چند نوبت: بعد از هر نوبت «صفحه اصلی» و روند تازه برای شماره‌ی بعدی؛
    خطای یک شماره بقیه را متوقف نمی‌کند و نتیجه‌ی نهایی اعلام می‌شود."""
    calls, booked_cb = [], []

    class FakeTurn:
        def __init__(self, ctx, br, login, page):
            pass

        async def go_home(self):
            calls.append("home")

        async def select_case(self, number, by):
            calls.append(("case", number))
            if number == "222":
                raise FlowError("NO_SLOT", "no free slot", "⚠️ نوبت خالی پیدا نشد.")

        async def select_daadvarz(self):
            calls.append("daadvarz")

        async def select_reason(self):
            calls.append("reason")

        async def book(self):
            calls.append("book")
            return "روز نمونه ساعت ۱۰:۱۵"

        async def print_ticket(self):
            return b"%PDF-1.4 fake"

    monkeypatch.setattr(turnmod, "Turn", FakeTurn)
    job = FakeJob()
    steps = []

    async def step(c):
        steps.append(c)

    async def report(cat, msg=""):
        steps.append(("ERR", cat))

    ctx = types.SimpleNamespace(job=job, step=step, report=report, new_items=0, run_id=1)

    async def on_booked(number):
        booked_cb.append(number)

    res = await turnmod.work_turn(ctx, None, None, None, ["111", "222", "333"], "archive",
                                  on_booked=on_booked)
    assert res["booked"] == ["111", "333"]
    assert res["failed"] == ["222"]
    assert booked_cb == ["111", "333"]             # بعد از هر ثبتِ موفق صدا زده شد
    assert calls.count("home") == 2                # قبل از شماره‌ی دوم و سوم
    # روند کامل (پرونده ← دادورز ← علت ← رزرو) برای هر شماره‌ی موفق اجرا شد
    assert [c for c in calls if c == "daadvarz"] == ["daadvarz", "daadvarz"]
    assert calls.count("book") == 2
    # نوبت‌های موفق PDF گرفتند
    assert [f for f, _ in job.pdfs] == ["nobat_111.pdf", "nobat_333.pdf"]
    # خطای شماره‌ی وسط برای کاربر اعلام شد و نتیجه‌ی نهایی هم آمد
    assert any("۲۲۲" in s and "ثبت نشد" in s for s in job.said)
    assert any("ثبت‌شده" in s and "۱۱۱" in s and "۳۳۳" in s for s in job.said)
    assert any("ثبت‌نشده" in s and "۲۲۲" in s for s in job.said)
    assert ctx.new_items == 2


async def test_work_turn_single_failure_reraises(monkeypatch):
    """تکی: خطا همان‌جا بالا می‌آید (رفتار قبلی حفظ شده)."""
    class FakeTurn:
        def __init__(self, ctx, br, login, page):
            pass

        async def select_case(self, number, by):
            raise FlowError("NO_SLOT", "x", "⚠️ نوبت خالی پیدا نشد.")

    monkeypatch.setattr(turnmod, "Turn", FakeTurn)
    job = FakeJob()

    async def step(c):
        pass

    async def report(cat, msg=""):
        pass

    ctx = types.SimpleNamespace(job=job, step=step, report=report, new_items=0, run_id=1)
    with pytest.raises(FlowError) as ei:
        await turnmod.work_turn(ctx, None, None, None, ["111"], "archive")
    assert ei.value.category == "NO_SLOT"
    assert job.pdfs == []
