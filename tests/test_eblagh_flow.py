"""روند ابلاغیه روی سامانه‌ی ساختگی: فهرست ← مشاهده ← نسخه چاپی (تب جدید) ← پیوست (اول alert «در حال
استخراج»، بعد PDF) ← بازگشت؛ استخراج اطلاعات و ثبت یادآوری."""
import asyncio
import types
from pathlib import Path

import pytest

from legal_bot import config
from legal_bot.services import eblagh
from legal_bot.services.browser import Browser

FX = Path(__file__).parent / "fixtures"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

LIST = """<html><body>
<div id=list>
  <button onclick="alert('x')">ابلاغیه‌های جدید</button>
  <div class=card><p>شماره ابلاغیه: ۹۹۱۰۱۰۳۵۹۳۰۰۵۲۲۷</p><p>پرونده ۹۹۰۹۹۸۳۵۹۳۰۰۰۵۹۵</p>
     <button onclick="show('9910103593005227')">مشاهده</button></div>
  <div class=card><p>شماره ابلاغیه: ۹۹۱۰۱۰۳۵۹۳۰۰۴۸۰۹</p><p>پرونده ۹۹۰۹۹۸۳۵۹۳۰۰۰۵۹۵</p>
     <button onclick="show('9910103593004809')">مشاهده</button></div>
</div>
<div id=detail style="display:none">
  <span onclick="back()">بازگشت</span>
  <a id=eblagh-detail-tab href="#d">جزئیات</a>
  <a id=eblagh-attachment-tab href="#att" aria-controls="att">پیوست‌ها</a>
  <div id=d><button id=pr>نسخه چاپی</button></div>
  <div id=att><a href="#" id=attlink>مشاهده</a></div>
</div>
<script>
let cur = null, tries = 0;
function show(id) { cur = id; document.getElementById('list').style.display='none';
                    document.getElementById('detail').style.display='block'; }
function back() { document.getElementById('list').style.display='block';
                  document.getElementById('detail').style.display='none'; }
document.getElementById('pr').onclick = () => window.open('/Report/ENoticePrint.aspx?n=' + cur);
document.getElementById('attlink').onclick = (e) => { e.preventDefault();
  tries++;
  if (tries === 1) { alert('سیستم در حال استخراج اطلاعات پیوست ابلاغیه است. لطفا پس از دو دقیقه مجددا اقدام کنید.'); return; }
  window.open('/Report/HstDocumentPrint.aspx?attachmentId=1'); };
</script></body></html>"""


def print_page(n):
    name = "notice_3333.txt" if n.endswith("5227") else "notice_2323.txt"
    body = (FX / name).read_text(encoding="utf-8")
    rows = body.splitlines()
    html = "".join(f"<div>{r}</div>" for r in rows)
    # جدول حضور مثل نسخه‌ی واقعی
    if n.endswith("5227"):
        html += ("<table><tr><td>تاریخ حضور</td><td>ساعت حضور</td><td>محل حضور</td></tr>"
                 "<tr><td>۱۳۹۹/۰۹/۰۹</td><td>۱۰:۰۰</td><td>یزد</td></tr></table>")
    return f"<html><body>{html}</body></html>"


async def handler(route):
    url = route.request.url
    if "ENoticePrint.aspx" in url:
        return await route.fulfill(body=print_page(url.split("n=")[1]), content_type="text/html; charset=utf-8")
    if "HstDocumentPrint" in url:
        return await route.fulfill(body=PDF, content_type="application/pdf")
    return await route.fulfill(body=LIST, content_type="text/html; charset=utf-8")


class FakeJob:
    user_id = 1
    owner = (1, "x")

    def __init__(self):
        self.said, self.pdfs = [], []

    async def say(self, text, kb=None, **kw):
        self.said.append(text)

    async def send_pdf(self, data, name, caption=""):
        self.pdfs.append((name, data[:4], caption))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "ATTACHMENT_WAIT_SEC", 1)
    monkeypatch.setattr(config, "PRINT_RETRY_WAIT_SEC", 1)


async def test_process_two_notices(db):
    await db.upsert_user(1, 1)
    job = FakeJob()
    steps = []

    async def step(c):
        steps.append(c)

    async def report(cat, msg=""):
        steps.append(("ERR", cat, msg))

    ctx = types.SimpleNamespace(job=job, db=db, step=step, report=report, run_id=1, new_items=0)

    async def ensure(page):
        return page

    login = types.SimpleNamespace(ensure=ensure)
    async with Browser() as br:
        await br.context.route("**/*", handler)
        await br.page.goto("https://eblagh1.adliran.ir/Notice/Home/Index")
        e = eblagh.Eblagh(ctx, br, login, br.page)
        ids = [c["id"] for c in await e.cards()]
        assert ids == ["9910103593005227", "9910103593004809"]
        for ext in ids:
            info = await asyncio.wait_for(e.process(ext, is_new=True), 60)
            assert info, ext
            await eblagh.deliver_notice(ctx, info)
    names = [p[0] for p in job.pdfs]
    assert names[0] == "eblagh_9910103593005227.pdf" and job.pdfs[0][1] == b"%PDF"
    assert any(n.startswith("peyvast_") for n in names)            # پیوست بعد از alert «در حال استخراج»
    assert any("در حال آماده‌سازی" in s for s in job.said)
    cap = job.pdfs[0][2]
    assert "۹۹۰۹۹۸۳۵۹۳۰۰۰۵۹۵" in cap and "۹۹۰۰۶۳۰" in cap and "شعبه" in cap
    rems = await db.all("SELECT kind, due_date FROM reminders ORDER BY id")
    # 1399/09/09 گذشته است → یادآوری جلسه ساخته نمی‌شود؛ ابلاغیه‌ی دوم مهلت ۱۰ روزه از امروز دارد
    assert [r["kind"] for r in rems] == ["deadline"]
    notices = await db.all("SELECT external_id, archive_number FROM notices ORDER BY id")
    assert [n["external_id"] for n in notices] == ids and notices[0]["archive_number"] == "9900630"
