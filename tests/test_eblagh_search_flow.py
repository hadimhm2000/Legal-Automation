"""روند «جستجوی ابلاغیه‌های صادره» (شماره پرونده / شماره ابلاغیه) روی سایت ساختگی —
دستور کارفرما (فایل آبان ۱۴۰۵):

  بعد از لاگین روی کارت «ابلاغیه‌های مشاهده شده» کلیک می‌شود ← «جستجوی ابلاغیه»
  (collapse #SeenEblaghSearchBox) ← شماره در فیلد ng-model مربوطه ← «بازیابی
  ابلاغیه» ← ردیف‌ها با صادرکننده/موضوع/تاریخ برای کاربر ← انتخاب کاربر ←
  چاپ موارد انتخابی (مودال ← نسخه چاپی ← بستن).
  خالی بودن → یک بار دیگر «بازیابی ابلاغیه» → خطای قرمز → متن خطا برای کاربر.
"""
import asyncio
import types
from pathlib import Path

import pytest

from legal_bot import config
from legal_bot.services import eblagh
from legal_bot.services.browser import Browser

FX = Path(__file__).parent / "fixtures"

ID1, ID2 = "9910103593005227", "9910103593004809"          # پرونده‌ی CASE1
ID3 = "9910103593000999"                                    # پرونده‌ی CASE2
CASE1, CASE2 = "9909983593000595", "9909983593000707"

# سایت ساختگی با همان selectorهای واقعی سامانه (ng-model / ng-click / collapse)
PAGE = """<html><head><meta charset="utf-8"><style>
  .modal { display: none; position: fixed; inset: 0; background: #fff; }
  .modal.show { display: block; }
  #SeenEblaghSearchBox { display: none; }
  #SeenEblaghSearchBox.show { display: block; }
</style></head><body>
<div id="home">
  <div class="card"><div class="card-body p-3" id="badgeCard">
    <div class="d-flex align-items-center justify-content-center">
      <span id="badgeNum">0</span><strong>ابلاغیه<br>بازنشده</strong>
    </div>
  </div></div>
  <div class="card"><div class="card-body p-3" id="viewedCard">
    <div class="d-flex flex-column pb-md-3 pb-2">
      <div class="d-flex justify-content-center align-items-center mt-md-3 mt-2">
        <span class="ServiceSVGbox p-3"></span>
      </div>
      <div class="d-flex flex-column">
        <strong class="text-w-500 mt-3">ابلاغیه‌های<br>مشاهده شده</strong>
      </div>
    </div>
  </div></div>
</div>
<div id="viewedView" style="display:none">
  <button type="button" class="btn btn-alink me-3" data-bs-toggle="collapse"
          href="#SeenEblaghSearchBox" role="button" aria-expanded="false" id="searchToggle">جستجوی ابلاغیه</button>
  <div class="card-body p-4"><div class="row">
    <div class="col-lg-3"><label>از تاریخ</label><input name="fromDate"></div>
    <div class="col-lg-3"><label>تا تاریخ</label><input name="toDate"></div>
    <div class="col-12"><button class="btn btn-success" id="rangeGo">بازیابی اطلاعات</button></div>
  </div></div>
  <div class="collapse" id="SeenEblaghSearchBox"><div class="card-body p-4"><div class="row">
    <div class="col-lg-4"><label>شماره ابلاغیه</label>
      <input type="text" class="form-control text-end" ng-model="ENotifySearchCriteria.NoticedDocNo" id="noInput"></div>
    <div class="col-lg-4"><label>شماره پرونده</label>
      <input type="text" class="form-control text-end" ng-model="ENotifySearchCriteria.NoticedDocCaseNo" id="caseInput"></div>
    <div class="col-lg-4"><label>صادر کننده</label>
      <input type="text" class="form-control" ng-model="ENotifySearchCriteria.IssuerUnitName"></div>
    <div class="col-lg-4"><label>موضوع ابلاغیه</label>
      <input type="text" class="form-control" ng-model="ENotifySearchCriteria.SubjectType"></div>
  </div>
  <button type="button" class="btn btn-success mt-3" ng-disabled="viewModel.loading"
          ng-click="actions.getAllENotice(viewModel.pageSize, 1)" id="goBtn">بازیابی ابلاغیه</button></div></div>
  <div id="rows"></div>
  <div class="VerticalGap"></div>
  <div id="verr" class="alert alert-danger alert-dismissible fade show" role="alert" style="display:none">
    <p class="mb-0" id="verrText">با شرایط وارد شده ابلاغیه‌ای یافت نشد.</p>
    <button type="button" class="btn-close p-3"></button>
  </div>
</div>
<div id="modalXXL" class="modal">
  <div class="modal-body p-4 pt-3">
    <ul class="nav nav-tabs justify-content-center" id="myTab" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="eblagh-detail-tab" type="button" role="tab"><span>جزئیات</span></button>
      </li>
    </ul>
    <p>شماره ابلاغیه: <span id="mNum"></span></p>
    <button type="button" class="btn btn-primary" ng-click="actions.getENoticeDocumentPrint()" id="prbtn">نسخه چاپی</button>
  </div>
  <button type="button" class="btn-close mx-0" data-bs-dismiss="modal" aria-label="Close" title="بستن" id="xbtn"></button>
</div>
<script>
const NOTICES = [
  {id: '__ID1__', case: '__CASE1__', date: '1405/06/29',
   issuer: 'شعبه پنجم دادگاه تجدیدنظر استان یزد',
   subject: 'ابلاغ اخطاریه/احضاریه حضور در جلسه رسیدگی برای شخص ذی سمت و مرتبطين'},
  {id: '__ID2__', case: '__CASE1__', date: '1405/05/14',
   issuer: 'شعبه 2 دادگاه عمومی حقوقی دادگستری شهرستان تفت',
   subject: 'ابلاغ اخطاریه تبادل لوايح'},
  {id: '__ID3__', case: '__CASE2__', date: '1405/03/31',
   issuer: 'شعبه 2 دادگاه عمومی حقوقی دادگستری شهرستان تفت',
   subject: 'ابلاغ دادنامه/قرارنهايي/تصميم نهايي'},
];
let cur = null;
function renderRows(list) {
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  (list || []).forEach(n => {
    rows.insertAdjacentHTML('beforeend', `
      <div class="card card-table-row mb-1"><div class="card-body py-4 px-4">
        <span class="ColorShapeCard mx-1"></span>
        <div class="d-flex align-items-center justify-content-between">
          <div class="d-flex align-items-center">
            <div class="d-flex flex-column">
              <div class="d-flex flex-lg-row flex-column">
                <div class="d-flex">
                  <p class="mb-1 text-muted me-4">شماره ابلاغیه: <span class="ng-binding">${n.id}</span></p>
                  <p class="mb-1 text-muted me-4">تاریخ صدور: <span class="ng-binding">${n.date}</span></p>
                </div>
              </div>
              <p class="mb-1 text-muted me-5">صادر کننده: <span class="ng-binding">${n.issuer}</span></p>
              <p class="mb-0 text-muted me-5">موضوع ابلاغیه: <span class="ng-binding">${n.subject}</span></p>
            </div>
          </div>
          <button class="btn btn-outline-secondary text-md text-w-500"
                  ng-click="actions.openNotice(item,true)" onclick="openModal('${n.id}')">مشاهده</button>
        </div>
      </div></div>`);
  });
}
document.getElementById('viewedCard').addEventListener('click', () => {
  document.getElementById('home').style.display = 'none';
  document.getElementById('viewedView').style.display = 'block';
  renderRows(NOTICES);          // فهرست پیش‌فرض «ابلاغیه‌های مشاهده شده»
});
document.getElementById('searchToggle').addEventListener('click', (e) => {
  e.preventDefault();
  const box = document.getElementById('SeenEblaghSearchBox');
  box.classList.toggle('show');
  document.getElementById('searchToggle').setAttribute('aria-expanded', String(box.classList.contains('show')));
});
document.getElementById('goBtn').addEventListener('click', () => {
  const btn = document.getElementById('goBtn');
  btn.disabled = true;          // چرخه‌ی لود (ng-disabled="viewModel.loading")
  setTimeout(() => {
    const no = document.getElementById('noInput').value.trim();
    const cs = document.getElementById('caseInput').value.trim();
    let res = NOTICES;
    if (cs) res = res.filter(n => n.case === cs);
    if (no) res = res.filter(n => n.id === no);
    renderRows(res);
    document.getElementById('verr').style.display = res.length ? 'none' : 'block';
    btn.disabled = false;
  }, 250);
});
function openModal(n) {
  cur = n;
  document.getElementById('mNum').innerText = n;
  document.getElementById('modalXXL').classList.add('show');
}
document.getElementById('prbtn').addEventListener('click', () => window.open('/Report/ENoticePrint.aspx?n=' + cur));
document.getElementById('xbtn').addEventListener('click', () =>
  document.getElementById('modalXXL').classList.remove('show'));
</script></body></html>""".replace("__ID1__", ID1).replace("__ID2__", ID2).replace("__ID3__", ID3) \
     .replace("__CASE1__", CASE1).replace("__CASE2__", CASE2)


def print_page(n):
    name = "notice_3333.txt" if n.endswith("5227") else "notice_2323.txt"
    body = (FX / name).read_text(encoding="utf-8")
    html = "".join(f"<div>{r}</div>" for r in body.splitlines())
    return f"<html><body>{html}</body></html>"


async def handler(route):
    url = route.request.url
    if "ENoticePrint.aspx" in url:
        return await route.fulfill(body=print_page(url.split("n=")[1].split("&")[0]),
                                   content_type="text/html; charset=utf-8")
    return await route.fulfill(body=PAGE, content_type="text/html; charset=utf-8")


class FakeJob:
    """Job ساختگی با پاسخ‌های اسکریپت‌شده برای ask (انتخاب کاربر)."""
    user_id = 1
    owner = (1, "x")

    def __init__(self, answers=()):
        self.said, self.pdfs, self.photos = [], [], []
        self.answers = list(answers)
        self.prompts = []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def send_pdf(self, data, name, caption=""):
        self.pdfs.append((name, data[:4], caption))

    async def send_photo(self, data, caption=""):
        self.photos.append((caption, len(data)))

    async def ask(self, prompt, options=None, **kw):
        self.prompts.append(prompt)
        self.said.append(prompt)
        return self.answers.pop(0)


def make_ctx(db, job):
    async def step(c):
        pass

    async def report(cat, msg=""):
        job.said.append(("ERR", cat, msg))

    return types.SimpleNamespace(job=job, db=db, step=step, report=report, run_id=1, new_items=0)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_WAIT_MS", 8000)


async def _run(db, work, answers, *args):
    job = FakeJob(answers)
    ctx = make_ctx(db, job)

    async def ensure(page):
        return page

    login = types.SimpleNamespace(ensure=ensure)
    async with Browser() as br:
        await br.context.route("**/*", handler)
        await br.page.goto("https://eblagh1.adliran.ir/Notice/Home/Index")
        await work(ctx, br, login, br.page, *args)
    return job


async def test_by_case_lists_rows_then_prints_selected(db):
    """شماره پرونده ← ردیف‌ها با صادرکننده/موضوع/تاریخ برای کاربر ← انتخاب «۱ و ۲» ← چاپ همان دو."""
    await db.upsert_user(1, 1)
    job = await _run(db, eblagh.work_by_case, [("text", "۱ و ۲")], CASE1)
    # فهرست ردیف‌ها (صادرکننده + موضوع + تاریخ) برای کاربر فرستاده شد
    rows_msg = [s for s in job.said if "پیدا شد" in s]
    assert rows_msg and "۲" in rows_msg[0]
    assert any("شعبه پنجم دادگاه تجدیدنظر استان یزد" in s for s in job.said)
    assert any("ابلاغ اخطاریه/احضاریه" in s for s in job.said)
    assert any("۱۴۰۵/۰۶/۲۹" in s for s in job.said)
    # سؤال انتخاب آمد و فقط موارد انتخابی چاپ شدند
    assert job.prompts and "کدام مورد" in job.prompts[0]
    assert [p[0] for p in job.pdfs] == [f"eblagh_{ID1}.pdf", f"eblagh_{ID2}.pdf"]
    assert all(p[1] == b"%PDF" for p in job.pdfs)
    assert any("۲ ابلاغیه انتخاب شد" in s for s in job.said)
    assert any("۲ ابلاغیه چاپ و ارسال شد" in s for s in job.said)
    notices = await db.all("SELECT external_id FROM notices ORDER BY id")
    assert [n["external_id"] for n in notices] == [ID1, ID2]


async def test_by_notice_button_choice_prints_one(db):
    """شماره ابلاغیه ← یک ردیف ← کاربر دکمه‌ی «۱» را می‌زند ← همان یک ابلاغیه چاپ می‌شود.
    (ID2 استفاده شده چون متن صفحه‌ی چاپ ساختگی همان شماره را دارد.)"""
    await db.upsert_user(1, 1)
    job = await _run(db, eblagh.work_by_notice, [("choice", "1")], ID2)
    assert any("۹۹۱۰۱۰۳۵۹۳۰۰۴۸۰۹" in s for s in job.said)         # شماره در فهرست ردیف‌ها
    assert [p[0] for p in job.pdfs] == [f"eblagh_{ID2}.pdf"]
    assert all(p[1] == b"%PDF" for p in job.pdfs)
    assert any("۱ ابلاغیه چاپ و ارسال شد" in s for s in job.said)


async def test_by_case_none_selected_prints_nothing(db):
    await db.upsert_user(1, 1)
    job = await _run(db, eblagh.work_by_case, [("choice", "none")], CASE1)
    assert not job.pdfs
    assert any("هیچ موردی چاپ نشد" in s for s in job.said)


async def test_by_case_not_found_sends_site_error(db):
    """نتیجه‌ی خالی ← یک بار دیگر «بازیابی ابلاغیه» ← خطای قرمز ← متن خطا برای کاربر."""
    await db.upsert_user(1, 1)
    job = await _run(db, eblagh.work_by_case, [], "9909983593000708")
    assert any("یک بار دیگر" in s for s in job.said)               # تلاش دوباره اعلام شد
    assert any("یافت نشد" in s for s in job.said)                   # متن خطای سامانه
    assert not job.pdfs and not job.prompts                          # چاپ/انتخابی در کار نبود


async def test_by_case_all_word_selects_everything(db):
    """پاسخ متنی «همه» ← همه‌ی ردیف‌های آن پرونده چاپ می‌شوند."""
    await db.upsert_user(1, 1)
    job = await _run(db, eblagh.work_by_case, [("text", "همه")], CASE1)
    assert [p[0] for p in job.pdfs] == [f"eblagh_{ID1}.pdf", f"eblagh_{ID2}.pdf"]


async def test_search_rows_parser(db):
    """SEARCH_ROWS_JS شماره ابلاغیه/تاریخ/صادرکننده/موضوع را از کارت‌ها می‌خواند."""
    job = FakeJob()
    ctx = make_ctx(db, job)

    async def ensure(page):
        return page

    login = types.SimpleNamespace(ensure=ensure)
    async with Browser() as br:
        await br.context.route("**/*", handler)
        await br.page.goto("https://eblagh1.adliran.ir/Notice/Home/Index")
        e = eblagh.Eblagh(ctx, br, login, br.page)
        rows = await asyncio.wait_for(e.run_search("case", CASE1), 60)
    assert [r["id"] for r in rows] == [ID1, ID2]
    assert rows[0]["issue_date"] == "1405/06/29"
    assert "تجدیدنظر" in rows[0]["issuer"]
    assert "احضاریه" in rows[0]["subject"]
