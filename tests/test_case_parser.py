from legal_bot import texts as T
from legal_bot.services.case_parser import (diff_new_lines, extract_lavayeh, last_change, line_hash, next_hearing,
                                            numbered_lines, parse_case_card)

CASE_INFO = """آخرین تغییر ثبت شده برای این پرونده مربوط به تاریخ 1405/08/17 ساعت 09:51 می باشد
رمز وارد شده مربوط به علي بهمني نيا می باشد
1-پرونده مقید به وقت رسیدگی به تاریخ 1405/09/29 راس ساعت 09:45 می باشد
2-پرونده کلاسه 140513920000890035 ردیف فرعی 2 با علت طرح رسيدگي بدوي نسبت به اتهام توهين به اشخاص عادي در دادگاه عمومي و انقلاب شهرستان يزد به تاریخ 1405/08/11 ثبت گردید و با شماره بایگانی 0500732 به شعبه 108 دادگاه كيفري دو شهر يزد (108 جزايي يزد سابق) ارجاع شد
3-ابلاغیه شماره 140513100013886674 مورخ 1405/08/12 مربوط به دادسراي عمومي و انقلاب شهرستان يزد - دادستان  در تاریخ 1405/08/12 ابلاغ و به دفتر شعبه اعاده شد
10-لایحه به شماره 1405220876719741  مورخ 1405/08/13  از طرف «علي خادمي مجومرد» با موضوع ارايه دلائل و مدارك در تاریخ 1405/08/13 واصل و به شماره 140513990009439243 ثبت گردید
11-لایحه به شماره 1405220632226925  مورخ 1405/08/16  از طرف «علي بهمني نيا» با موضوع لايحه دفاعيه  در تاریخ 1405/08/16 واصل و به شماره 140513990009519051 ثبت گردید
12-لایحه به شماره 1405130632226925  مورخ 1405/08/16  از طرف «شخص دیگر» با موضوع تست"""


def test_lavayeh_220_rule_and_format():
    lav = extract_lavayeh(CASE_INFO)
    assert [x["number"] for x in lav] == ["1405220876719741", "1405220632226925"]
    msg = T.lavayeh_message(lav)
    assert "لایحه به شماره 1405220876719741 مورخ 1405/08/13 از طرف «علي خادمي مجومرد»" in msg
    assert "@onlinejudicialservices_bot" in msg
    assert "1405130632226925" not in msg


def test_last_change_and_hearing():
    assert last_change(CASE_INFO) == "1405/08/17 09:51"
    assert next_hearing(CASE_INFO) == ("1405/09/29", "09:45")


def test_diff_only_new_lines():
    old = {line_hash(x) for x in numbered_lines(CASE_INFO)}
    new_info = CASE_INFO + "\n13-در تاریخ 1405/08/20 رای صادر شد"
    assert diff_new_lines(new_info, old) == ["در تاریخ 1405/08/20 رای صادر شد"]
    renumbered = CASE_INFO.replace("10-لایحه", "9-لایحه")
    assert diff_new_lines(renumbered, old) == []


def test_case_card():
    c = parse_case_card("شماره پرونده: 140513920000611609 ردیف فرعی: 1 شماره بایگانی: 0500732 شعبه 4 دادگاه عمومی")
    assert c["case_number"] == "140513920000611609" and c["sub_no"] == "1" and c["archive_number"] == "0500732"
