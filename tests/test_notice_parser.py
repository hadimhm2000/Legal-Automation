import datetime as dt
from pathlib import Path

from legal_bot.services.notice_parser import parse_notice_text

FX = Path(__file__).parent / "fixtures"


def test_3333_hearing_date_and_time():
    i = parse_notice_text((FX / "notice_3333.txt").read_text(encoding="utf-8"))
    assert i["notice_number"] == "9910103593005227"
    assert i["case_number"] == "9909983593000595"
    assert i["archive_number"] == "9900630"
    assert i["branch"].startswith("شعبه 10 شورای حل اختلاف")
    assert i["hearing_date"] == dt.date(2020, 11, 29)   # 1399/09/09
    assert i["hearing_time"] == "10:00"
    assert i["deadline_days"] is None
    assert i["sent_date"] == dt.date(2020, 11, 22)


def test_2323_deadline_days_without_date():
    i = parse_notice_text((FX / "notice_2323.txt").read_text(encoding="utf-8"))
    assert i["notice_number"] == "9910103593004809"
    assert i["hearing_date"] is None
    assert i["deadline_days"] == 10
    assert i["sent_date"] == dt.date(2020, 11, 1)


def test_table_wins_and_word_numbers():
    i = parse_notice_text("شماره ابلاغیه: 140510000000000001\nظرف مهلت ده روز اقدام نمایید",
                          {"date": "", "time": "", "place": ""})
    assert i["deadline_days"] == 10
    i = parse_notice_text("x", {"date": "1405/09/29", "time": "09:45", "place": "یزد"})
    assert i["hearing_date"] and i["hearing_time"] == "09:45"
