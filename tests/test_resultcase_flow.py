"""جزئیات پرونده روی سامانه‌ی ساختگی اطلاع‌رسانی: جستجو ← مشاهده (تب جدید) ← روند کار ← نسخه چاپی ← لوایح."""
import types

from legal_bot.services import resultcase
from legal_bot.services.browser import Browser
from test_case_parser import CASE_INFO

PDF = b"%PDF-1.4\n%%EOF"
LIST = """<html><body>
<input id=txtHstCaseNo>
<label><input type=checkbox id=liveCase checked> مختومه نشده‌</label>
<label><input type=checkbox id=archivedCase> مختومه شده‌</label>
<button onclick="document.getElementById('res').style.display='block'">بازیابی اطلاعات</button>
<div id=res style="display:none"><div class=card>
  <p>شماره پرونده: 140513920000890035 ردیف فرعی: 2 شماره بایگانی: 0500732</p>
  <span onclick="window.open('/ResultCase/CaseListWithPasswordByCaseNo?caseNo=1')">مشاهده</span></div></div>
</body></html>"""
DETAIL = """<html><body><a>روند کار پرونده</a><a>آخرین موضوعات پرونده</a>
<div><p ng-bind-html="viewModel.caseInfo" style="white-space:pre-line">%s</p>
<button onclick="window.open('/Reports/PrintResultCase?x=1')">نسخه چاپی</button></div></body></html>""" % CASE_INFO


async def handler(route):
    u = route.request.url
    if "PrintResultCase" in u:
        return await route.fulfill(body=PDF, content_type="application/pdf")
    if "CaseListWithPasswordByCaseNo" in u:
        return await route.fulfill(body=DETAIL, content_type="text/html; charset=utf-8")
    return await route.fulfill(body=LIST, content_type="text/html; charset=utf-8")


class FakeJob:
    user_id = 1

    def __init__(self):
        self.said, self.pdfs = [], []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def send_pdf(self, data, name, caption=""):
        self.pdfs.append((name, data[:4]))


async def test_detail_and_lavayeh():
    job = FakeJob()

    async def step(c):
        pass

    async def ensure(p):
        return p

    ctx = types.SimpleNamespace(job=job, step=step, new_items=0)
    async with Browser() as br:
        await br.context.route("**/*", handler)
        await br.page.goto("https://resultcase.adliran.ir/ResultCase/CaseListForPerson")
        await resultcase.work_detail(ctx, br, types.SimpleNamespace(ensure=ensure), br.page, "140513920000890035")
        assert await br.page.locator("#archivedCase").is_checked()     # هر دو حالت جستجو شد
        assert await br.page.locator("#txtHstCaseNo").input_value() == "140513920000890035"
    text = "\n".join(job.said)
    assert "شماره بایگانی: ۰۵۰۰۷۳۲" in text and "شعبه ۱۰۸" in text
    assert "وقت رسیدگی: ۱۴۰۵/۰۹/۲۹ ساعت ۰۹:۴۵" in text
    assert "لایحه به شماره 1405220876719741 مورخ 1405/08/13 از طرف «علي خادمي مجومرد»" in text
    assert "1405130632226925" not in job.said[-1]
    assert len(job.pdfs) == 2 and all(p[1] == b"%PDF" for p in job.pdfs)
