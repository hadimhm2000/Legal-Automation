"""جریان ثبت نوبت روی سایت ساختگی (مطابق ضبط‌های کارفرما — آبان ۱۴۰۵):

  • انتخاب روز همیشه از «فردا» شروع می‌شود (روز جاری هرگز انتخاب نمی‌شود).
  • پنجشنبه/جمعه/تعطیل رسمی در فهرست روزهای نامزد نیست؛ خطای «پنجشنبه ها» ← روز بعد.
  • نوبت‌های «btn-time disable» (State==2 / تکمیل ظرفیت) کلیک نمی‌شوند؛ اگر همه‌ی
    ساعت‌های یک روز disable بود ← روز بعد (دونه‌دونه مثل ضبط steps 2).
  • خطای «نمی توان علت مراجعه را ... انتخاب نمود» ← «فهرست علت ها» ← «ارائه دلائل»؛
    باز هم نشد ← «پیگیری پرونده» (دستور کارفرما — آبان ۱۴۰۵).
  • خطای «طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای X لغایت Y فعال
    است.» ← قبل از X: رد شدن به شروع بازه؛ داخل/بعد از بازه: «کامل پر؛ ساعت ۸ صبح
    روز بعد مجدداً اقدام نمائید» (دستور کارفرما — ضبط steps 2 + HTML جدید).
  • خطای «با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.» ←
    ساعتِ بعدیِ همان روز امتحان نمی‌شود؛ مستقیم روزِ بعد (دستور کارفرما — HTML جدید).
  • تقویم جدید mds.bootstrap.calendar (HTML ارسالی کارفرما): روز هدف با تطبیق دقیق
    data-number کلیک می‌شود؛ سلول‌های ماهِ مجاور (data-nm) و روزهای disabled هرگز
    کلیک نمی‌شوند («26»یِ مهر به‌جای «26»یِ آبان کلیک می‌شد — باگ رفع شد)؛ ماهِ
    نمایش‌داده‌شده از دکمه‌ی انتخاب ماه خوانده می‌شود و جلو رفتن با «ماه بعد» است.
  • علت مراجعه همیشه ردیف ۱۵ «درخواست جلب متهم» است و فهرست علت‌ها برای کاربر
    ارسال نمی‌شود (دستور کارفرما).
  • بعد از «بررسی اطلاعات پرونده فوق» اگر سامانه خودش دادورز را پر کرده باشد،
    مستقیم «مرحله ی بعدی» (دستور کارفرما — ضبط steps).
  • sweet-alert «هیچ سمتی ... تعریف نشده است»: حین ثبت ← «ظرفیت پر؛ ساعت ۸ صبح روز بعد».
  • «ثبت چند نوبت»: بعد از هر نوبت «صفحه اصلی» و روند تازه برای شماره‌ی بعدی.
  • متن کامل گزینه‌های منو (دادورزها) در پیام نمایش داده می‌شود؛ دکمه‌ها شماره‌دارند.
"""
import datetime as dt
import json
import types

import jdatetime
import pytest

from legal_bot import config
from legal_bot.services import turn as turnmod
from legal_bot.services.browser import Browser
from legal_bot.services.session import FlowError
from legal_bot.utils import (JALALI_MONTHS_FA, WEEKDAYS_FA, fa_date, jalali_of, to_fa_digits,
                            to_jalali_str, today_tehran, turn_candidate_days, weekday_fa)

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
    assert "۸ صبح" in ei.value.user_message
    assert "روز بعد" in ei.value.user_message
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


# ── تقویم جدید mds.bootstrap.calendar (HTML ارسالی کارفرما — آبان ۱۴۰۵) ──────
# «امروز» همیشه ۱۴۰۵/۰۸/۲۵ (دوشنبه) ثابت است — عین HTML ارسالی کارفرما؛
# بنابراین تقویم آبان همیشه روزهای ۲۵ تا ۳۰ مهرِ ماهِ قبل را در ابتدای خود دارد
# و «26»یِ مهر در DOM پیش از «26»یِ آبان است (عین سناریوی باگ).
FAKE_TODAY_J = jdatetime.date(1405, 8, 25)
FAKE_TODAY = FAKE_TODAY_J.togregorian()
FAKE_SELDATE = f"{WEEKDAYS_FA[FAKE_TODAY.weekday()]}، {FAKE_TODAY_J.day} {JALALI_MONTHS_FA[FAKE_TODAY_J.month - 1]} {FAKE_TODAY_J.year}"


@pytest.fixture
def fake_today(monkeypatch):
    """«امروز» روی ۱۴۰۵/۰۸/۲۵ قفل می‌شود تا تست‌های تقویم mds قطعی باشند."""
    from legal_bot import utils
    monkeypatch.setattr(utils, "today_tehran", lambda: FAKE_TODAY)


def _jmonth_len(y: int, m: int) -> int:
    if m <= 6:
        return 31
    if m <= 11:
        return 30
    try:
        jdatetime.date(y, 12, 30)
        return 30
    except ValueError:
        return 29


def _mds_month_rows(y: int, m: int) -> str:
    """ردیف‌های ماهِ (y,m) به سبک mds: سربرگ روزهای هفته + روزهای ماهِ قبل/جاری/
    بعد؛ روزهای ماهِ مجاور data-nm، روزهای گذشته/جمعه disabled، امروز data-today."""
    wd = ("شنبه", "یکشنبه", "دوشنبه", "سه شنبه", "چهارشنبه", "پنج شنبه", "جمعه")
    rows = ["<tr>" + "".join(
        f'<td class="{"text-danger" if w == "جمعه" else ""}">{w}</td>' for w in wd) + "</tr>"]
    first_wd = jdatetime.date(y, m, 1).weekday()            # شنبه=۰ … جمعه=۶
    prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
    next_y, next_m = (y, m + 1) if m < 12 else (y + 1, 1)
    cells = [("nm", prev_y, prev_m, d) for d in
             range(_jmonth_len(prev_y, prev_m) - first_wd + 1, _jmonth_len(prev_y, prev_m) + 1)]
    cells += [("day", y, m, d) for d in range(1, _jmonth_len(y, m) + 1)]
    nd = 1
    while len(cells) % 7:
        cells.append(("nm", next_y, next_m, nd))
        nd += 1
    today_g = FAKE_TODAY
    for r in range(0, len(cells), 7):
        tds = []
        for kind, cy, cm, cd in cells[r:r + 7]:
            num = f"{cy:04d}{cm:02d}{cd:02d}"
            g = jdatetime.date(cy, cm, cd).togregorian()
            attrs = f' data-number="{num}"'
            cls = ""
            if kind == "nm":
                attrs += ' data-nm=""'
            else:
                attrs += ' data-day=""'
                if g < today_g:
                    attrs += ' disabled="disabled"'
                elif g == today_g:
                    attrs += ' data-today=""'
                if g.weekday() == 4:                     # جمعه
                    cls, attrs = ' class="text-danger"', attrs + ' disabled="disabled"'
            tds.append(f"<td{cls}{attrs}>{cd}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return "".join(rows)


# عین ساختار HTML ارسالی کارفرما: جدول تو در تو + دکمه‌های data-changedatebutton
# (سال قبل/ماه قبل/ماه بعد/سال بعد) + دکمه‌ی انتخاب ماه (#…MonthSelectorButon)
# + سربرگِ تاریخِ انتخاب‌شده (th.background-skyblue) + ساعت/دقیقه/ثانیه‌ی مخفی.
MDS_PAGE = """<html><head><meta charset="utf-8"><style>.hide{display:none}</style></head><body>
<table class="table table-sm text-center p-0 m-0 font-yekan">
<thead><tr>
<th colspan="100" class="background-skyblue" data-selecteddatestring="">__SELDATE__</th>
</tr></thead>
<tbody><tr>
<td class="border-0" data-td-month="">
  <table class="table table-sm table-striped table-borderless">
    <thead>
      <tr hidden=""><th colspan="100" class="border-0">
        <table class="table table-sm table-borderless"><thead><tr>
          <th><button type="button" class="btn btn-light" id="oldHdr"></button></th>
        </tr></thead></table>
      </th></tr>
      <tr><td colspan="100" class="border-0 no-padding">
      <table class="table table-sm table-borderless"><tbody><tr>
        <th><div class="element-back blue pull-right width-full"><button type="button" tooltip-placement="top" tooltip="سال قبل" class="btn btn-primary btn-sm" title="سال قبل" data-changedatebutton="" id="btnPrevYear"> &lt;&lt; </button></div></th>
        <th><div class="element-back blue pull-right width-full"><button type="button" tooltip-placement="top" tooltip="ماه قبل" class="btn btn-info btn-sm" title="ماه قبل" data-changedatebutton="" id="btnPrevMonth"> &lt; </button></div></th>
        <th><div class="dropdown"><div class="element-back blue pull-right width-full"><button type="button" class="btn btn-light btn-sm dropdown-toggle" id="mdsBootstrapPersianDatetimePickerMonthSelectorButon" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"><i class="glyphicon glyphicon-chevron-down margin-left-10"></i><span id="mdsMonthLabel"></span></button></div></div></th>
        <th><div class="element-back blue pull-right width-full"><button type="button" tooltip-placement="top" tooltip="ماه بعد" class="btn btn-info btn-sm" title="ماه بعد" data-changedatebutton="" id="btnNextMonth"> &gt; </button></div></th>
        <th><div class="element-back blue pull-right width-full"><button type="button" tooltip-placement="top" tooltip="سال بعد" class="btn btn-primary btn-sm" title="سال بعد" data-changedatebutton="" id="btnNextYear"> &gt;&gt; </button></div></th>
      </tr></tbody></table>
      </td></tr>
    </thead>
    <tbody class="days" id="mdsDays"></tbody>
  </table>
</td></tr></tbody>
<tfoot><tr hidden=""><td colspan="100" class="border-0">
  <table class="table table-sm table-borderless"><tbody><tr>
    <td><input type="text" title="ساعت" value="20" maxlength="2" data-clock="hour"></td><td>:</td>
    <td><input type="text" title="دقیقه" value="57" maxlength="2" data-clock="minute"></td><td>:</td>
    <td><input type="text" title="ثانیه" value="30" maxlength="2" data-clock="second"></td>
  </tr></tbody></table>
</td></tr></tfoot>
</table>
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
</tbody></table></div>
<button id="btnCreateUnitTurn" class="hide" onclick="doCreate()">ثبت و دریافت نوبت</button>
<button id="yesBtn" class="hide" onclick="yesClick()">بلی</button>
<button id="closeBtn" class="hide" onclick="closeAll()">بستن</button>
<div id="sweet" class="hide sweet-alert showSweetAlert visible">
  <h2 id="sweetH2"></h2><p id="sweetText"></p>
  <button class="confirm" onclick="closeSweet()">بستن</button>
</div>
<script>
const DATA = __DATA__;
const MONTHS = __MONTHS__;
const CAP_ON_CREATE = __CAP__;
let reasonFixed = false;
window.pickedNumbers = [];
window.pickedNm = [];
window.navNext = 0;
window.pickedReason = '';
let curKey = '__START__';
function show(id){document.getElementById(id).style.display='block';}
function hide(id){document.getElementById(id).style.display='none';}
function renderMonth(){
  const m = MONTHS[curKey];
  document.getElementById('mdsMonthLabel').innerText = ' ' + m.label + ' ';
  document.getElementById('mdsDays').innerHTML = m.rows;
}
function nav(dir){
  if (dir > 0) window.navNext++;
  const p = curKey.split('-').map(Number);
  let y = p[0], mo = p[1] + dir;
  if (mo > 12){mo = 1; y++;} if (mo < 1){mo = 12; y--;}
  const k = y + '-' + mo;
  if (!MONTHS[k]) return;
  curKey = k; renderMonth();
}
function sweetH2(t){ document.getElementById('sweetH2').innerText = t;
  document.getElementById('sweetText').innerText = ''; show('sweet'); }
function sweetP(t){ document.getElementById('sweetText').innerText = t;
  document.getElementById('sweetH2').innerText = ''; show('sweet'); }
function closeSweet(){ hide('sweet'); }
function pickDay(td){
  const num = td.getAttribute('data-number');
  if (td.hasAttribute('data-nm')) { window.pickedNm.push(num); return; }
  window.pickedNumbers.push(num);
  const m = num.match(/^(\\d{4})(\\d{2})(\\d{2})$/);
  const key = m ? (+m[1]) + '-' + (+m[2]) + '-' + (+m[3]) : '';
  const cfg = DATA[key];
  const times = document.getElementById('times');
  times.innerHTML = '';
  hide('btnCreateUnitTurn'); hide('yesBtn');
  if (!cfg) return;
  if (cfg.error) { sweetH2(cfg.error); return; }
  if (cfg.range_error) { sweetP(cfg.range_error); return; }
  if (cfg.day_capacity) {
    sweetH2('با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.');
    return;
  }
  if (cfg.reason_error && !reasonFixed) { show('reasonErr'); show('btnPrevStep'); return; }
  (cfg.times || []).forEach(t => {
    const wrap = document.createElement('div');
    wrap.className = 'col-md-2 col-sm-2 col-xs-4';
    const b = document.createElement('div');
    b.className = 'btn-time' + (t.full ? ' disable' : '');
    b.innerText = t.time;
    wrap.appendChild(b); times.appendChild(wrap);
  });
  if ((cfg.times || []).some(t => !t.full)) { show('btnCreateUnitTurn'); show('yesBtn'); }
}
async function doCreate(){
  const r = await fetch('/Turn/CMSUnitTurnCreate', {method: 'POST'});
  if (r.ok) { location.hash = '#/Detail'; return; }
  if (CAP_ON_CREATE) sweetH2('با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است.');
  else show('closeBtn');
}
function yesClick(){ hide('yesBtn'); }
function closeAll(){ hide('closeBtn'); hide('sweet'); }
function goPrev(){ hide('reasonErr'); hide('btnPrevStep'); show('btnUnitReferalReasonTypeModal'); }
function openReasons(){ show('reasonModal'); }
function pickReason(tr){
  window.pickedReason = (tr.innerText || '').replace(/\\s+/g, ' ').trim();
  hide('reasonModal'); hide('btnUnitReferalReasonTypeModal'); show('btnUnderstood');
  reasonFixed = true;
}
function understood(){ hide('btnUnderstood'); hide('btnUnitReferalReasonTypeModal'); hide('reasonErr'); }
function goNext(){ hide('btnNextStep'); hide('reasonErr'); }
document.getElementById('mdsDays').addEventListener('click', e => {
  const td = e.target.closest('td');
  if (td && td.hasAttribute('data-number')) pickDay(td);
});
document.getElementById('btnPrevMonth').addEventListener('click', () => nav(-1));
document.getElementById('btnNextMonth').addEventListener('click', () => nav(1));
renderMonth();
</script>
</body></html>"""


class MdsTurnSite:
    """سایت ساختگی با تقویم mds.bootstrap.calendar (عین HTML ارسالی کارفرما).

    - هر سلولِ روز data-number="YYYYMMDD" دارد؛ روزهای ماهِ مجاور data-nm و
      روزهای گذشته/جمعه disabled و «امروز» data-today هستند.
    - ماهِ نمایش‌داده‌شده در دکمه‌ی انتخاب ماه است و سربرگِ بزرگ، تاریخِ انتخاب‌شده
      است که با جلو رفتن ماه عوض نمی‌شود (عین سایت).
    - month_offset: تقویم در ابتدا چند ماه جلوتر/عقب‌تر از ماهِ «امروز» باشد.
    - fail_first_create + capacity_on_create: ثبتِ اول به خطای ۵۰۰ و sweet-alertِ
      «ظرفیت نوبت دهی ... تکمیل شده است» منجر شود (عین HTML ارسالی کارفرما).
    """

    def __init__(self, day_cfg: dict, *, month_offset: int = 0,
                 fail_first_create: int = 0, capacity_on_create: bool = False):
        self.day_cfg = day_cfg
        self.fail_first_create = fail_first_create
        self.capacity_on_create = capacity_on_create
        self.create_count = 0
        jy, jm = FAKE_TODAY_J.year, FAKE_TODAY_J.month
        for _ in range(-min(month_offset, 0)):
            jm -= 1
            if jm < 1:
                jm, jy = 12, jy - 1
        for _ in range(max(month_offset, 0)):
            jm += 1
            if jm > 12:
                jm, jy = 1, jy + 1
        months = {}
        y, m = jy, jm
        for _ in range(2):                      # دو ماه عقب‌تر از ماهِ شروع
            m -= 1
            if m < 1:
                m, y = 12, y - 1
        for _ in range(6):                      # شش ماه از آنجا به بعد
            months[f"{y}-{m}"] = {"label": f"{JALALI_MONTHS_FA[m - 1]} - {y}",
                                  "rows": _mds_month_rows(y, m)}
            m += 1
            if m > 12:
                m, y = 1, y + 1
        self.html = (MDS_PAGE
                     .replace("__SELDATE__", FAKE_SELDATE)
                     .replace("__DATA__", json.dumps(day_cfg, ensure_ascii=False))
                     .replace("__MONTHS__", json.dumps(months, ensure_ascii=False))
                     .replace("__CAP__", "true" if capacity_on_create else "false")
                     .replace("__START__", f"{jy}-{jm}"))

    async def handle(self, route):
        url = route.request.url
        if "/Turn/CMSUnitTurnCreate" in url:
            self.create_count += 1
            if self.create_count > self.fail_first_create:
                return await route.fulfill(status=200, body="{}")
            return await route.fulfill(status=500, body="{}")
        return await route.fulfill(body=self.html, content_type="text/html; charset=utf-8")


async def test_mds_selects_tomorrow_not_today_nor_prev_month(fake_today):
    """روز جاری (۱۴۰۵/۰۸/۲۵) انتخاب نمی‌شود و «26»یِ ماهِ قبل (مهر — data-nm) هم
    هرگز کلیک نمی‌شود؛ فردا (۱۴۰۵/۰۸/۲۶) با تطبیق دقیق data-number انتخاب می‌شود
    (سناریوی عین HTML ارسالی کارفرما — باگِ انتخاب روزِ غلط)."""
    cands = turn_candidate_days(6)
    assert to_jalali_str(cands[0]) == "1405/08/26"       # فردا از «امروزِ» قفل‌شده
    cfg = {
        _day_key(FAKE_TODAY): {"times": [{"time": "10:00", "full": False}]},   # امروز — انتخاب نمی‌شود
        _day_key(cands[0]): {"times": [{"time": "09:02", "full": False}]},
    }
    site = MdsTurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
        picked, picked_nm = await br.page.evaluate("[window.pickedNumbers, window.pickedNm]")
    finally:
        await br.close()
    assert picked == ["14050826"]                # فقط فردا — نه مهرِ ۲۶ و نه امروزِ ۲۵
    assert picked_nm == []                       # سلولِ ماهِ مجاور کلیک نشد
    assert fa_date(cands[0]) in when
    assert to_fa_digits("09:02") in when


async def test_mds_capacity_error_after_create_goes_straight_to_next_day(fake_today):
    """«با عرض پوزش، ظرفیت نوبت دهی در زمان انتخاب شده تکمیل شده است» بعد از
    ثبتِ ناموفق ← ساعتِ بعدیِ همان روز امتحان نمی‌شود؛ مستقیم روزِ بعد
    (دستور کارفرما — عین sweet-alert ارسالی با <h2>)."""
    cands = turn_candidate_days(6)
    cfg = {
        _day_key(cands[0]): {"times": [{"time": "08:30", "full": False},
                                       {"time": "09:02", "full": False}]},
        _day_key(cands[1]): {"times": [{"time": "10:15", "full": False}]},
    }
    site = MdsTurnSite(cfg, fail_first_create=1, capacity_on_create=True)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
        picked = await br.page.evaluate("window.pickedNumbers")
    finally:
        await br.close()
    assert site.create_count == 2                # روز اول فقط یک ثبت (نه هر دو ساعت)
    assert picked == ["14050826", "14050827"]    # بعدِ خطای ظرفیت، مستقیم روزِ بعد
    assert fa_date(cands[1]) in when
    assert fa_date(cands[0]) not in when


async def test_mds_capacity_alert_on_day_click_goes_to_next_day(fake_today):
    """همان خطا همان‌جا بعد از انتخاب روز ظاهر شد ← بسته می‌شود و مستقیم روزِ بعد."""
    cands = turn_candidate_days(6)
    cfg = {
        _day_key(cands[0]): {"day_capacity": True},
        _day_key(cands[1]): {"times": [{"time": "10:15", "full": False}]},
    }
    site = MdsTurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
        picked = await br.page.evaluate("window.pickedNumbers")
    finally:
        await br.close()
    assert site.create_count == 1                # روز اول اصلاً ثبت نشد
    assert picked == ["14050826", "14050827"]
    assert fa_date(cands[1]) in when


async def test_mds_day_error_on_sweet_alert_h2_goes_to_next_day(fake_today):
    """خطای روز (عدم حضور دادورز) در <h2>یِ sweet-alert ← بسته و روزِ بعد."""
    cands = turn_candidate_days(6)
    cfg = {
        _day_key(cands[0]): {"error": "به دلیل عدم حضور دادورز اجراي احكام، نمی توان این روز را انتخاب نمود."},
        _day_key(cands[1]): {"times": [{"time": "10:15", "full": False}]},
    }
    site = MdsTurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
    finally:
        await br.close()
    assert fa_date(cands[1]) in when
    assert fa_date(cands[0]) not in when


async def test_mds_month_button_header_and_next_month_navigation(fake_today):
    """ماهِ نمایش‌داده‌شده از دکمه‌ی انتخاب ماه خوانده می‌شود (نه سربرگِ تاریخِ
    انتخاب‌شده) و با فلش «ماه بعد» جلو می‌رویم؛ در نمای ماهِ قبل، روزِ ماهِ بعدِ
    data-nm هست و کلیک نمی‌شود — باید اول ماه جلو رود."""
    cands = turn_candidate_days(6)
    cfg = {_day_key(cands[0]): {"times": [{"time": "09:02", "full": False}]}}
    site = MdsTurnSite(cfg, month_offset=-1)     # تقویم از مهر ۱۴۰۵ شروع می‌شود
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        when = await t.book()
        nav_next, picked, picked_nm = await br.page.evaluate(
            "[window.navNext, window.pickedNumbers, window.pickedNm]")
    finally:
        await br.close()
    assert nav_next >= 1                         # با «ماه بعد» به آبان رفت
    assert picked == ["14050826"]                # روزِ ماهِ بعد (data-nm) کلیک نشد
    assert picked_nm == []
    assert fa_date(cands[0]) in when


async def test_mds_range_error_announces_capacity_full_8am_next_day(fake_today):
    """«طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای X لغایت Y فعال است.»
    (عین sweet-alert ارسالی کارفرما با <p>) ← به کاربر اعلام می‌شود: ظرفیت نوبت‌دهی
    پر می باشد؛ ساعت ۸ صبح روز بعد مجدداً اقدام نمائید (دستور کارفرما)."""
    cands = turn_candidate_days(6)
    rng = (f"طبق تنظیمات انجام شده توسط شعبه، اخذ نوبت برای روزهای "
           f"{to_jalali_str(cands[0])} لغایت {to_jalali_str(cands[2])} فعال است.")
    cfg = {_day_key(cands[0]): {"range_error": rng}}
    site = MdsTurnSite(cfg)
    br = await _open(site)
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.book()
    finally:
        await br.close()
    assert ei.value.category == "TURN_CAPACITY_FULL"
    assert "کامل پر" in ei.value.user_message
    assert "۸ صبح" in ei.value.user_message
    assert "روز بعد" in ei.value.user_message
    assert site.create_count == 0                # اصلاً ثبت نشد


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
    assert "ظرفیت" in ei.value.user_message
    assert "۸ صبح" in ei.value.user_message
    assert "روز بعد" in ei.value.user_message


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
    <div id="alertBox" class="hide sweet-alert showSweetAlert visible">
      <h2 id="alertText">هیچ پرونده ای با شماره «140213920001085354» یافت نشد .</h2>
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
    """دستور کارفرما: sweet-alertِ «هیچ پرونده ای با شماره «...» یافت نشد» بعد از
    استعلام ← هشدار بسته می‌شود و روند متوقف می‌گردد."""
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
    assert ei.value.category == "TURN_CASE_NOT_FOUND"
    assert alert_hidden


async def test_select_case_by_case_number_not_found_stops_with_clear_message():
    """دستور کارفرما (HTML ارسالی): بعد از استعلام، sweet-alert «هیچ پرونده ای با شماره
    «...» یافت نشد .» ← روند متوقف می‌شود و به کاربر گفته می‌شود اسمش در پرونده نیست
    یا شماره پرونده اشتباه است (ادامه‌ی خودکار با همان شماره‌ی غلط ممنوع)."""
    br = await _open_my_cases([])
    try:
        t, _ = make_turn(br, br.page)
        with pytest.raises(FlowError) as ei:
            await t.select_case("140213920001085354", "case")
        alert_hidden = await br.page.evaluate(
            "() => document.getElementById('alertBox').classList.contains('hide')")
        # مسیر جایگزین (پرکردن مستقیم #txtCaseNo با همان شماره‌ی غلط) اجرا نشد
        case_input = await br.page.evaluate("() => document.getElementById('txtCaseNo').value")
    finally:
        await br.close()
    assert ei.value.category == "TURN_CASE_NOT_FOUND"
    assert "اسم شما در پرونده نیست" in ei.value.user_message
    assert "شماره پرونده اشتباه" in ei.value.user_message
    assert alert_hidden                    # هشدار سامانه بسته شد
    assert case_input == ""                # شماره‌ی غلط دوباره پر نشد


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
