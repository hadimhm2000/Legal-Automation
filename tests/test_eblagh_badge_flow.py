"""روند «بررسی ابلاغیه‌های جدید» روی UI جدید سامانه‌ی ابلاغ (دستور کارفرما — آبان ۱۴۰۵):

  کارت «ابلاغیه بازنشده» (عدد ۰ → پیام + اسکرین‌شات بدون کلیک / عدد ۲ → کلیک)
  ← جدول ابلاغیه‌ها ← «مشاهده» (مودال #modalXXL) ← «نسخه چاپی» (تب جدید PDF)
  ← بستن مودال با × ← جدول خالی شد → «۳ ماه قبل» (بازیابی) ← ابلاغیه‌ی بعدی.
  عدد کارت بعد از صبر+ریلود هم نیامد → «سامانه ابلاغ قطع است».
"""
import asyncio
import types
from pathlib import Path

import pytest

from legal_bot import config
from legal_bot.services import eblagh
from legal_bot.services.browser import Browser
from legal_bot.services.session import FlowError

FX = Path(__file__).parent / "fixtures"

IDS = ["9910103593005227", "9910103593004809"]


def new_ui_page(badge: str) -> str:
    """سایت ساختگی با UI جدید. badge: '0' یا '2' یا 'loading'."""
    return f"""<html><head><meta charset="utf-8"><style>
      .modal {{ display: none; position: fixed; inset: 0; background: #fff; }}
      .modal.show {{ display: block; }}
    }}</style></head><body>
<div id="home">
  <div class="card"><div class="card-body p-3" id="badgeCard">
    <div class="d-flex flex-column pb-md-3 pb-2">
      <div class="d-flex align-items-center justify-content-center" id="badgeBox">
        <span id="badgeNum" class="text-red"></span>
        <strong>ابلاغیه<br>بازنشده</strong>
      </div>
    </div>
  </div></div>
</div>
<div id="listView" style="display:none">
  <div class="col-lg-3 col-md-2">
    <button class="btn btn-primary w-100" ng-click="actions.changeDateWithMonth(-3,1)" id="m3">3 ماه قبل</button>
  </div>
  <div id="rows"></div>
  <div class="VerticalGap" id="gap" style="display:none"></div>
</div>
<div id="modalXXL" class="modal">
  <div class="modal-body p-4 pt-3">
    <ul class="nav nav-tabs justify-content-center" id="myTab" role="tablist">
      <li class="nav-item" role="presentation">
        <button class="nav-link active" id="eblagh-detail-tab" type="button" role="tab"><span>جزئیات</span></button>
      </li>
    </ul>
    <div class="tab-content p-4">
      <p>شماره ابلاغیه: <span id="mNum"></span></p>
    </div>
    <button type="button" class="btn btn-primary" ng-click="actions.getENoticeDocumentPrint()" id="prbtn">نسخه چاپی</button>
  </div>
  <button type="button" class="btn-close mx-0" data-bs-dismiss="modal" aria-label="Close" title="بستن"
          ng-click="actions.clearMessage()" id="xbtn"></button>
</div>
<script>
const BADGE = '{badge}';
const NOTICES = {IDS};
let viewed = [], cur = null, glitched = false, listOpen = false, hidden = false;
const badgeNum = document.getElementById('badgeNum');
if (BADGE === 'loading') {{
  badgeNum.style.display = 'none';              // عدد هنوز لود نشده
}} else {{
  badgeNum.innerText = BADGE;                   // 0 یا 2
}}
function renderRows() {{
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  NOTICES.filter(n => !viewed.includes(n)).forEach(n => {{
    rows.insertAdjacentHTML('beforeend', `
      <div class="card card-table-row mb-1"><div class="card-body py-4 px-4">
        <div class="d-flex align-items-center justify-content-between">
          <div class="d-flex align-items-center">
            <p class="mb-1 text-muted me-5">شماره ابلاغیه: <span class="ng-binding">${{n}}</span></p>
            <p class="mb-1 text-muted me-5">تاریخ صدور: <span>1405/06/29</span></p>
          </div>
          <button type="button" class="btn btn-outline-secondary" data-bs-toggle="modal"
                  data-bs-target="#modalXXL" ng-click="actions.openNotice(item,false)"
                  onclick="openModal('${{n}}')">مشاهده</button>
        </div>
      </div></div>`);
  }});
}}
function openModal(n) {{
  cur = n; document.getElementById('mNum').innerText = n;
  document.getElementById('modalXXL').classList.add('show');
}}
document.getElementById('badgeCard').addEventListener('click', () => {{
  listOpen = true;
  document.getElementById('home').style.display = 'none';
  document.getElementById('listView').style.display = 'block';
  renderRows();
}});
document.getElementById('prbtn').addEventListener('click', () => {{
  window.open('/Report/ENoticePrint.aspx?n=' + cur);
}});
document.getElementById('xbtn').addEventListener('click', () => {{
  document.getElementById('modalXXL').classList.remove('show');
  viewed.push(cur);
  renderRows();
  if (viewed.length === 1) {{   // باگ سایت: بعد از بستن اولین مودال جدول خالی می‌ماند
    glitched = true; hidden = true;
    document.getElementById('rows').style.display = 'none';
    document.getElementById('gap').style.display = 'block';
  }}
}});
document.getElementById('m3').addEventListener('click', () => {{
  if (hidden) {{
    hidden = false;
    document.getElementById('rows').style.display = 'block';
    document.getElementById('gap').style.display = 'none';
    renderRows();
  }}
}});
</script></body></html>"""


def print_page(n):
    name = "notice_3333.txt" if n.endswith("5227") else "notice_2323.txt"
    body = (FX / name).read_text(encoding="utf-8")
    rows = body.splitlines()
    html = "".join(f"<div>{r}</div>" for r in rows)
    if n.endswith("5227"):
        html += ("<table><tr><td>تاریخ حضور</td><td>ساعت حضور</td><td>محل حضور</td></tr>"
                 "<tr><td>۱۳۹۹/۰۹/۰۹</td><td>۱۰:۰۰</td><td>یزد</td></tr></table>")
    return f"<html><body>{html}</body></html>"


def make_handler(badge):
    async def handler(route):
        url = route.request.url
        if "ENoticePrint.aspx" in url:
            return await route.fulfill(body=print_page(url.split("n=")[1].split("&")[0]),
                                       content_type="text/html; charset=utf-8")
        return await route.fulfill(body=new_ui_page(badge), content_type="text/html; charset=utf-8")
    return handler


class FakeJob:
    user_id = 1
    owner = (1, "x")

    def __init__(self):
        self.said, self.pdfs, self.photos = [], [], []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def send_pdf(self, data, name, caption=""):
        self.pdfs.append((name, data[:4], caption))

    async def send_photo(self, data, caption=""):
        self.photos.append((caption, len(data)))


def make_ctx(db, job):
    async def step(c):
        pass

    async def report(cat, msg=""):
        job.said.append(("ERR", cat, msg))

    return types.SimpleNamespace(job=job, db=db, step=step, report=report, run_id=1, new_items=0)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "BADGE_WAIT_SEC", 1)
    monkeypatch.setattr(config, "EMPTY_LIST_RETRY_SEC", 1)
    monkeypatch.setattr(config, "SEARCH_WAIT_MS", 4000)


async def _run_work_new(db, badge):
    job = FakeJob()
    ctx = make_ctx(db, job)

    async def ensure(page):
        return page

    login = types.SimpleNamespace(ensure=ensure)
    async with Browser() as br:
        await br.context.route("**/*", make_handler(badge))
        await br.page.goto("https://eblagh1.adliran.ir/Notice/Home/Index")
        await eblagh.work_new(ctx, br, login, br.page)
    return job


async def test_badge_zero_screenshot_no_click(db):
    """عدد کارت ۰ است → پیام «ابلاغیه جدیدی ندارید» + اسکرین‌شات؛ هیچ کلیک/چاپی انجام نمی‌شود."""
    await db.upsert_user(1, 1)
    job = await _run_work_new(db, "0")
    assert any("ابلاغیه‌ی جدیدی ندارید" in s for s in job.said)
    assert len(job.photos) == 1 and job.photos[0][1] > 100     # اسکرین‌شات غیرخالی
    assert not job.pdfs                                        # هیچ چاپی انجام نشد


async def test_badge_two_full_modal_flow_with_recovery(db):
    """عدد ۲ → کارت کلیک می‌شود ← دو ابلاغیه از مودال چاپ می‌شوند؛ جدول بعد از
    بستن اولین مودال خالی می‌ماند و «۳ ماه قبل» ردیف دوم را برمی‌گرداند."""
    await db.upsert_user(1, 1)
    job = await _run_work_new(db, "2")
    # هر دو ابلاغیه چاپ و ارسال شد
    names = [p[0] for p in job.pdfs]
    assert names == [f"eblagh_{IDS[0]}.pdf", f"eblagh_{IDS[1]}.pdf"]
    assert all(p[1] == b"%PDF" for p in job.pdfs)
    # بازیابی جدول خالی اعلام شد
    assert any("۳ ماه قبل" in s for s in job.said)
    assert any("۲ ابلاغیه چاپ و ارسال شد" in s for s in job.said)
    # اطلاع تاریخ/ساعت جلسه از PDF برای کاربر اعلام شد (استخراج از قبل موجود بود)
    assert any("تاریخ حضور" in p[2] for p in job.pdfs)
    notices = await db.all("SELECT external_id FROM notices ORDER BY id")
    assert [n["external_id"] for n in notices] == IDS


async def test_badge_loading_forever_reports_down(db):
    """عدد هیچ‌وقت لود نمی‌شود → ریلود → باز نشد → «سامانه ابلاغ قطع است»."""
    await db.upsert_user(1, 1)
    with pytest.raises(FlowError) as ei:
        await _run_work_new(db, "loading")
    assert ei.value.category == "EBLAGH_DOWN"
    assert "قطع" in (ei.value.user_message or "")
