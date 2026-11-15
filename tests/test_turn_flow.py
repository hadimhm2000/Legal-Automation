"""جریان ثبت نوبت روی سایت ساختگی (مطابق HTMLهای ارسالی کارفرما — آبان ۱۴۰۵):

  • انتخاب روز همیشه از «فردا» شروع می‌شود (روز جاری هرگز انتخاب نمی‌شود).
  • پنجشنبه/جمعه/تعطیل رسمی در فهرست روزهای نامزد نیست؛ خطای «پنجشنبه ها» ← روز بعد.
  • نوبت‌های «btn-time disable» (State==2 / تکمیل ظرفیت) کلیک نمی‌شوند؛ اگر همه‌ی
    ساعت‌های یک روز disable بود ← روز بعد.
  • خطای «نمی توان علت مراجعه را ... انتخاب نمود» ← «مرحله ی قبلی» ← «فهرست علت ها» ←
    ردیف ۱۵ «درخواست جلب متهم» ← ادامه تا ثبت نوبت.
  • sweet-alert «هیچ سمتی ... تعریف نشده است»: حین ثبت ← «ظرفیت پر؛ ۲۴ ساعت دیگر».
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
from legal_bot.utils import (fa_date, jalali_of, to_fa_digits, today_tehran, turn_candidate_days,
                             weekday_fa)

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
<button id="btnUnitReferalReasonTypeModal" class="hide" onclick="openReasons()">فهرست علت ها</button>
<button id="btnNextStep" class="hide" onclick="goNext()">مرحله ی بعدی</button>
<div id="reasonModal" class="hide"><table><tbody>
  <tr onclick="pickReason(this)"><td>15</td><td><button>انتخاب</button></td><td>درخواست جلب متهم</td></tr>
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
const MONTHS = __MONTHS__;
let y = __SY__, m = __SM__;
let reasonFixed = false;

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
  msg.classList.add('hide');
  document.getElementById('btnCreateUnitTurn').classList.add('hide');
  document.getElementById('yesBtn').classList.add('hide');
  if (!cfg) return;
  if (cfg.error) { msg.innerText = cfg.error; msg.classList.remove('hide'); return; }
  if (cfg.reason_error && !reasonFixed) {
    document.getElementById('reasonErr').classList.remove('hide');
    document.getElementById('btnPrevStep').classList.remove('hide');
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
    document.getElementById('btnCreateUnitTurn').classList.remove('hide');
    document.getElementById('yesBtn').classList.remove('hide');
  }
}
async function doCreate() {
  const r = await fetch('/Turn/CMSUnitTurnCreate', {method: 'POST'});
  if (r.ok) { location.hash = '#/Detail'; return; }
  document.getElementById('closeBtn').classList.remove('hide');
  if (GLITCH) {
    document.getElementById('reasonErr').classList.remove('hide');
    document.getElementById('btnPrevStep').classList.remove('hide');
  }
  if (SWEET_ROLE) {
    document.getElementById('sweetText').innerText =
      'هیچ سمتی در «شعبه اول اجراي احكام شوراهاي حل اختلاف شهرستان يزد» تعریف نشده است، ' +
      'امکان ورود به مرحله بعد وجود ندارد .';
    document.getElementById('sweet').classList.remove('hide');
  }
}
function closeAll() { document.getElementById('closeBtn').classList.add('hide'); }
function closeSweet() { document.getElementById('sweet').classList.add('hide'); }
function goPrev() {
  document.getElementById('reasonErr').classList.add('hide');
  document.getElementById('btnPrevStep').classList.add('hide');
  document.getElementById('btnUnitReferalReasonTypeModal').classList.remove('hide');
}
function openReasons() { document.getElementById('reasonModal').classList.remove('hide'); }
function pickReason(tr) {
  document.getElementById('reasonModal').classList.add('hide');
  document.getElementById('btnUnitReferalReasonTypeModal').classList.add('hide');
  document.getElementById('btnNextStep').classList.remove('hide');
  reasonFixed = true;
}
function goNext() {
  document.getElementById('btnNextStep').classList.add('hide');
  document.getElementById('reasonErr').classList.add('hide');
}
renderCal();
</script>
</body></html>"""


def _day_key(d: dt.date) -> str:
    j = jalali_of(d)
    return f"{j.year}-{j.month}-{j.day}"


class TurnSite:
    """سایت ساختگی نوبت‌دهی. day_cfg: {کلید روز: {"times": [...]} یا {"error": "..."}}.

    month_offset: تقویم در ابتدا چند ماه عقب‌تر از ماهِ جاری نمایش داده می‌شود
    (برای آزمایش ناوبری ماه با فلش «بعد»).
    fail_first_create: این تعداد ثبتِ اول ۵۰۰ می‌دهد (خطای علت مراجعه و...).
    """

    def __init__(self, day_cfg: dict, *, month_offset: int = -1, glitch_reason=False,
                 role_error=False, fail_first_create: int = 0):
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
        self.said, self.choices = [], []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def ask_choice(self, prompt, options, **kw):
        self.choices.append((prompt, options))
        return options[0][0]          # «بله، ثبت کن» / تأیید


def make_turn(br, page, job=None):
    job = job or FakeJob()
    ctx = types.SimpleNamespace(job=job)
    return turnmod.Turn(ctx, br, None, page), job


async def _open(site: TurnSite):
    br = Browser()
    await br.__aenter__()
    await br.context.route("**/*", site.handle)
    await br.page.goto("https://adliran.ir/Turn/Index")
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
    # روز جاری و روزهای خطادار/پر انتخاب نشدند
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


async def test_reason_error_fixed_with_prev_step_and_reason_15():
    """خطای «نمی توان علت مراجعه را...» ← «مرحله ی قبلی» ← «فهرست علت ها» ←
    ردیف ۱۵ «درخواست جلب متهم» ← ثبت نوبت ادامه می‌یابد (دستور کارفرما)."""
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
    # به کاربر اعلام شد که علت به «درخواست جلب متهم» تغییر کرد
    assert any("درخواست جلب متهم" in s for s in job.said)


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


async def test_reason_error_at_day_click_fixed_same_day():
    """اگر خطای علت مراجعه همان‌جا بعد از انتخاب روز ظاهر شود، روز رد نمی‌شود؛
    علت با «مرحله ی قبلی ← فهرست علت ها ← ردیف ۱۵» اصلاح و همان روز ثبت می‌شود."""
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
    assert any("درخواست جلب متهم" in s for s in job.said)


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
