import datetime as dt

from legal_bot.utils import (date_windows, looks_like_secret, mask_national_code, parse_jalali, to_jalali_str,
                             valid_national_code, validate_archive_number, validate_case_number)


def test_national_code():
    assert valid_national_code("4420160616")
    assert valid_national_code("۴۴۲۰۹۱۰۱۴۳")
    assert not valid_national_code("4420160617")
    assert not valid_national_code("1111111111")
    assert not valid_national_code("12345")
    assert mask_national_code("4420160616") == "۴۴******۱۶"


def test_case_number_rules():
    assert validate_case_number("140513920000890035") == ("140513920000890035", None)
    assert validate_case_number("۹۹۰۹۹۸۳۵۹۳۰۰۰۵۹۵")[0] == "9909983593000595"
    n, err = validate_case_number("14051392000089003")
    assert n is None and "۱۸ رقمی" in err and "۱۷" in err
    n, err = validate_case_number("99099835930005951")
    assert n is None and "۱۶ رقمی" in err
    assert validate_case_number("5505")[0] is None
    assert validate_case_number("abc")[0] is None
    assert validate_archive_number("0500732")[0] == "0500732"


def test_jalali():
    d = parse_jalali("1405.08.30")
    assert to_jalali_str(d) == "1405/08/30"
    assert parse_jalali("۱۳۹۹/۰۹/۰۹") == dt.date(2020, 11, 29)
    assert parse_jalali("1405/13/40") is None


def test_date_windows_30_days():
    s, e = dt.date(2026, 1, 1), dt.date(2026, 3, 15)
    w = date_windows(s, e, 30)
    assert w[0] == (dt.date(2026, 1, 1), dt.date(2026, 1, 30))
    assert w[-1][1] == e
    assert all((b - a).days <= 29 for a, b in w)
    for (a1, b1), (a2, b2) in zip(w, w[1:]):
        assert a2 == b1 + dt.timedelta(days=1)
    assert date_windows(e, s, 30) == w  # ترتیب برعکس


def test_looks_like_secret():
    assert looks_like_secret("4420160616")
    assert looks_like_secret("123456")
    assert not looks_like_secret("140513920000890035")
    assert not looks_like_secret("سلام")
