"""جزئیات و فهرست پرونده روی سامانه‌ی ساختگی اطلاع‌رسانی — منطق جدید (A/B/C/D/GGG):

- استعلام: اول ۴۰۹/«صف پردازش» → صبر و استعلام مجدد → نتیجه.
- «تعداد نمایش در صفحه» = ۱۰۰ + پرینت همه‌ی صفحه‌ها تا آخر.
- جزئیات: هر ردیف فرعی ← تب «روند کاری پرونده» ← «نسخه چاپی» ← تب «آخرین موضوعات» ← متن.
- پرسش «بازه‌ی زمانی بیشتر؟» + اخطار بازه‌ی تکراری + پنجره‌های یک‌ساله.
"""
import types

from legal_bot.services import resultcase
from legal_bot.services.browser import Browser
from test_case_parser import CASE_INFO

PDF = b"%PDF-1.4\n%%EOF"
SUBJECT = ("علت طرح:اجراي حکم\nمحکومیت:محكوميت مدني- حكم به پرداخت وجه نقد\n"
           "خواسته:درخواست صدور اجرائيه نسبت به چك بلامحل\n"
           "محکوم له:بازرگاني پويش صنعت كبير پارسافر\nمحکوم علیه:سيدجواد حيدري خورميزي")

CASES = [
    {"no": "140513920000890035", "sub": "1", "arch": "0500732",
     "br": "اجراي احكام شعبه 1 دادگاه عمومي حقوقي شهرستان يزد"},
    {"no": "140513920000890035", "sub": "2", "arch": "0500732",
     "br": "شعبه 14 دادگاه عمومي حقوقي شهرستان يزد"},
    {"no": "140513920000890123", "sub": "1", "arch": "0500740", "br": "شعبه 3 دادگاه عمومي حقوقي شهرستان يزد"},
    {"no": "140513920000890999", "sub": "1", "arch": "0500750", "br": "شعبه 5 دادگاه عمومي حقوقي شهرستان يزد"},
]

LIST_TMPL = """<html><head><meta charset="utf-8"></head><body>
<input id="txtHstCaseNo">
<label><input type="checkbox" id="liveCase" checked> مختومه نشده‌</label>
<label><input type="checkbox" id="archivedCase"> مختومه شده‌</label>
<input name="saveFromDate" value="1405/01/01"><input name="saveToDate" value="1405/08/16">
<button id="go">بازیابی اطلاعات</button>
<div id="warn" class="alert alert-warning" style="display:none">
  <p ng-bind-html="viewModel.warningMessage">درخواست شما در صف پردازش قرار گرفته و هنوز نوبت آن نرسیده، لطفا پس از گذشت دو دقیقه، مجددا جهت مشاهده نتیجه اقدام نمائید</p>
</div>
<div id="nf" class="alert alert-info" style="display:none">
  <p ng-bind-html="viewModel.infoMessage">پرونده ای یافت نشد</p>
</div>
<div id="res" style="display:none">
  <select id="ps"><option value="3">3</option><option value="5">5</option><option value="100">100</option></select>
  <div id="cards"></div>
  <nav><ul id="pager"></ul></nav>
</div>
<script>
const CASES = __CASES__;
const EFFECTIVE = 3;  // «سرور» ساختگی حداکثر ۳ ردیف در صفحه می‌دهد (تا صفحه‌بندی دیده شود)
let pageNo = 1;
function render() {
  const all = CASES.slice((pageNo - 1) * EFFECTIVE, pageNo * EFFECTIVE);
  document.getElementById('cards').innerHTML = all.map((c, i) => `<div class="card">
    <p>شماره پرونده: ${c.no} ردیف فرعی: ${c.sub} شماره بایگانی: ${c.arch} شعبه: ${c.br}</p>
    <span onclick="window.open('/ResultCase/CaseListWithPasswordByCaseNo?x=${c.no}${c.sub}')">مشاهده</span>
  </div>`).join('');
  const pages = Math.max(1, Math.ceil(CASES.length / EFFECTIVE));
  let lis = '';
  for (let p = 1; p <= pages; p++) lis += `<li class="${p === pageNo ? 'active' : ''}"><span>${p}</span></li>`;
  document.getElementById('pager').innerHTML = lis;
}
async function reload() {
  await fetch('/ResultCase/GetCaseListForPerson', {method: 'POST'});
  render();
}
document.getElementById('go').onclick = async () => {
  const r = await fetch('/ResultCase/GetCaseListForPerson', {method: 'POST'});
  if (r.status === 409) {
    document.getElementById('warn').style.display = 'block';
    document.getElementById('res').style.display = 'none';
    return;
  }
  const data = await r.json();
  document.getElementById('warn').style.display = 'none';
  if (!data.found) {
    document.getElementById('nf').style.display = 'block';
    document.getElementById('res').style.display = 'none';
    return;
  }
  document.getElementById('nf').style.display = 'none';
  document.getElementById('res').style.display = 'block';
  render();
};
document.getElementById('ps').onchange = () => reload();
document.getElementById('pager').addEventListener('click', async (e) => {
  const li = e.target.closest('li'); if (!li) return;
  const t = (li.innerText || '').trim(); if (!/^\\d+$/.test(t)) return;
  pageNo = parseInt(t, 10);
  await reload();
});
</script>
</body></html>"""

DETAIL = """<html><head><meta charset="utf-8"></head><body>
<div class="custom-box-tab" id="pills-profile-tab" role="tab" onclick="fill('flow')">
  <span class="text-w-700">روند کاری پرونده</span>
</div>
<div class="custom-box-tab" id="pills-disabled-tab" role="tab" onclick="fill('subj')">
  <span class="text-w-700">آخرین موضوعات</span>
</div>
<div id="box" style="display:none">
  <p ng-bind-html="viewModel.caseInfo" style="white-space:pre-line" id="ci"></p>
  <button onclick="window.open('/Reports/PrintResultCase?x=1')">نسخه چاپی</button>
</div>
<script>
const FLOW = %s;
const SUBJ = %s;
function fill(which) {
  document.getElementById('ci').textContent = which === 'flow' ? FLOW : SUBJ;
  document.getElementById('box').style.display = 'block';
}
</script>
</body></html>""" % (repr(CASE_INFO), repr(SUBJECT))


def make_handler(list_html, mode="queue_then_found"):
    """mode: queue_then_found | found | not_found"""
    state = {"n": 0}

    async def handler(route):
        u = route.request.url
        if "GetCaseListForPerson" in u or "GetCaseListForLawyer" in u:
            state["n"] += 1
            if mode == "queue_then_found" and state["n"] == 1:
                return await route.fulfill(status=409, body="{}")
            if mode == "not_found":
                return await route.fulfill(status=200, content_type="application/json", body='{"found": false}')
            return await route.fulfill(status=200, content_type="application/json", body='{"found": true}')
        if "PrintResultCase" in u:
            return await route.fulfill(body=PDF, content_type="application/pdf")
        if "CaseListWithPasswordByCaseNo" in u:
            return await route.fulfill(body=DETAIL, content_type="text/html; charset=utf-8")
        return await route.fulfill(body=list_html, content_type="text/html; charset=utf-8")

    return handler


def _list(cases):
    import json
    return LIST_TMPL.replace("__CASES__", json.dumps(cases))


class FakeJob:
    user_id = 1

    def __init__(self, answers=None):
        self.said, self.pdfs = [], []
        self.answers = list(answers or [])

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def send_pdf(self, data, name, caption=""):
        self.pdfs.append((name, data[:8], caption))

    def _pop(self):
        return self.answers.pop(0) if self.answers else None

    async def ask_choice(self, prompt, options, **kw):
        self.said.append(prompt)
        kind, v = self._pop() or ("choice", options[0][0])
        assert kind == "choice", f"expected choice answer, got {kind}"
        return v

    async def ask_text(self, prompt, validator=None, **kw):
        self.said.append(prompt)
        while True:
            kind, v = self._pop() or ("text", "1404/01/01")
            assert kind == "text", f"expected text answer, got {kind}"
            if not validator:
                return v
            val, err = validator(v)
            if val is not None:
                return val
            self.said.append(err)


def make_ctx(job):
    async def step(c):
        pass

    return types.SimpleNamespace(job=job, step=step, new_items=0)


async def _run(list_html, mode, work):
    """مرورگر + مسیریابی سایت ساختگی + اجرای `work(ctx, br, login, page)`."""
    job = FakeJob()
    ctx = make_ctx(job)

    async def ensure(p):
        return p

    async with Browser() as br:
        await br.context.route("**/*", make_handler(list_html, mode))
        await br.page.goto("https://resultcase.adliran.ir/ResultCase/CaseListForPerson")
        await work(ctx, br, types.SimpleNamespace(ensure=ensure), br.page)
    return job


async def test_detail_flow_with_queue_retry():
    """GGG+D: صف پردازش → استعلام مجدد → دو ردیف فرعی ← PDF روند کاری + متن آخرین موضوعات."""
    async def work(ctx, br, login, page):
        await resultcase.work_detail(ctx, br, login, page, "140513920000890035")
        assert await page.locator("#archivedCase").is_checked()     # هر دو حالت جستجو شد
        assert await page.locator("#txtHstCaseNo").input_value() == "140513920000890035"
        assert await page.locator("#ps").input_value() == "100"     # تعداد نمایش = ۱۰۰

    job = await _run(_list(CASES[:2]), "queue_then_found", work)
    text = "\n".join(job.said)
    assert "صف پردازش" in text and "تلاش ۱" in text          # پیام انتظار GGG
    assert "استعلام پرونده در بازه‌ی زمانی ۱۴۰۵/۰۱/۰۱ تا ۱۴۰۵/۰۸/۱۶ انجام شد" in text
    assert "ردیف فرعی ۱" in text and "ردیف فرعی ۲" in text  # هر دو ردیف فرعی
    assert "شماره بایگانی: ۰۵۰۰۷۳۲" in text
    assert "وقت رسیدگی: ۱۴۰۵/۰۹/۲۹ ساعت ۰۹:۴۵" in text
    assert "علت طرح:اجراي حکم" in text                       # متن «آخرین موضوعات»
    assert "لایحه به شماره 1405220876719741 مورخ 1405/08/13 از طرف «علي خادمي مجومرد»" in text
    assert len(job.pdfs) == 2 and all(p[1] == b"%PDF-1.4" for p in job.pdfs)
    assert all(p[0] == "case_140513920000890035_flow.pdf" for p in job.pdfs)


async def test_detail_wider_range_with_duplicate_warning():
    """بله ← بازه‌ی تکراری (اخطار) ← بازه‌ی قبلی (پنجره‌ی یک‌ساله) ← ثبت در فیلدها و استعلام مجدد."""

    async def work(ctx, br, login, page):
        job = ctx.job
        job.answers = [
            ("choice", "yes"),
            ("text", "1405/02/01"), ("text", "1405/03/01"),    # داخل بازه‌ی استعلام‌شده → اخطار
            ("text", "1403/06/01"), ("text", "1404/02/15"),     # قبل از بازه → دو سال شمسی = دو پنجره
        ]
        await resultcase.work_detail(ctx, br, login, page, "140513920000890035")
        # بازه‌ی کاربر در فیلدهای سامانه ثبت شد (پنجره‌ی آخر: ۱۴۰۴/۰۱/۰۱ تا ۱۴۰۴/۰۲/۱۵)
        assert await page.locator('input[name="saveFromDate"]').input_value() == "1404/01/01"
        assert await page.locator('input[name="saveToDate"]').input_value() == "1404/02/15"

    job = await _run(_list(CASES[:2]), "queue_then_found", work)
    text = "\n".join(job.said)
    assert "آیا مایلید بازه‌ی زمانی بیشتری بررسی شود؟" in text
    assert "همان بازه‌ای است که ابتدای کار استعلام شد" in text   # اخطار بازه‌ی تکراری
    assert "بازه‌ی ۱۴۰۳/۰۶/۰۱ تا ۱۴۰۳/۱۲/۳۰ بررسی می‌شود" in text  # پنجره‌ی اول (۱۴۰۳ کبیسه)
    assert "بازه‌ی ۱۴۰۴/۰۱/۰۱ تا ۱۴۰۴/۰۲/۱۵ بررسی می‌شود" in text  # پنجره‌ی دوم
    assert "مورد جدیدی یافت نشد" in text                      # ردیف‌های تکراری دوباره ارسال نشد


async def test_detail_not_found():
    async def work(ctx, br, login, page):
        ctx.job.answers = [("choice", "no")]
        await resultcase.work_detail(ctx, br, login, page, "140513920000890035")

    job = await _run(_list(CASES[:2]), "not_found", work)
    text = "\n".join(job.said)
    assert "در این بخش یافت نشد" in text
    assert not job.pdfs


async def test_work_list_prints_all_pages():
    """A/B/C: تعداد نمایش ۱۰۰ ← ورق زدن همه‌ی صفحه‌ها ← پرینت هر صفحه."""

    async def work(ctx, br, login, page):
        await resultcase.work_list(ctx, br, login, page, "all")
        assert await page.locator("#ps").input_value() == "100"

    job = await _run(_list(CASES), "found", work)
    names = [p[0] for p in job.pdfs]
    assert names[0] == "cases_all.pdf"                    # جدول کل پرونده‌ها
    assert names[1:] == ["cases_all_page1.pdf", "cases_all_page2.pdf"]  # پرینت همه‌ی صفحه‌ها
    assert "تعداد: ۴" in job.pdfs[0][2]                   # هر ۴ پرونده از دو صفحه جمع شد
    assert job.pdfs[1][2] == "🖨 نسخه‌ی چاپی صفحه‌ی ۱ از ۲"
    assert job.pdfs[2][2] == "🖨 نسخه‌ی چاپی صفحه‌ی ۲ از ۲"
    assert job.pdfs[0][1] == b"%PDF-1.4"
