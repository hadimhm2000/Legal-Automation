import datetime as dt

from legal_bot.utils import (date_windows, looks_like_secret, mask_national_code, parse_jalali,
                             subtract_ranges, to_jalali_str, valid_national_code, validate_archive_number,
                             validate_case_number, year_windows)


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


def test_year_windows_jalali_boundaries():
    """بازه‌ی بیش از یک سال → پنجره‌های یک‌ساله با مرز سال شمسی (۱۴۰۳ کبیسه است)."""
    w = year_windows(parse_jalali("1403/09/01"), parse_jalali("1405/02/10"))
    assert [to_jalali_str(a) for a, _ in w] == ["1403/09/01", "1404/01/01", "1405/01/01"]
    assert [to_jalali_str(b) for _, b in w] == ["1403/12/30", "1404/12/29", "1405/02/10"]
    # بازه‌ی داخل یک سال → همان یک پنجره
    assert year_windows(parse_jalali("1404/02/01"), parse_jalali("1404/11/20")) == [
        (parse_jalali("1404/02/01"), parse_jalali("1404/11/20"))]
    # ترتیب برعکس هم درست می‌شود
    w2 = year_windows(parse_jalali("1405/02/10"), parse_jalali("1403/09/01"))
    assert w2 == w


def test_subtract_ranges():
    initial = (parse_jalali("1405/01/01"), parse_jalali("1405/08/16"))
    # کاملاً داخل بازه‌ی استعلام‌شده → خالی (باید به کاربر اخطار داد)
    assert subtract_ranges(parse_jalali("1405/02/01"), parse_jalali("1405/03/01"), [initial]) == []
    # کاملاً قبل → دست‌نخورده
    assert subtract_ranges(parse_jalali("1403/06/01"), parse_jalali("1404/02/15"), [initial]) == [
        (parse_jalali("1403/06/01"), parse_jalali("1404/02/15"))]
    # هم‌پوشانی از دو طرف → فقط دو تکه‌ی استعلام‌نشده
    out = subtract_ranges(parse_jalali("1404/10/01"), parse_jalali("1405/09/30"), [initial])
    assert out == [(parse_jalali("1404/10/01"), parse_jalali("1404/12/29")),
                   (parse_jalali("1405/08/17"), parse_jalali("1405/09/30"))]
    # بازه‌ی exclude بیرون از بازه‌ی کاربر
    assert subtract_ranges(parse_jalali("1405/01/10"), parse_jalali("1405/01/20"), [initial]) == []
    # بدون exclude
    assert subtract_ranges(parse_jalali("1405/01/01"), parse_jalali("1405/01/31"), []) == [
        (parse_jalali("1405/01/01"), parse_jalali("1405/01/31"))]


def test_looks_like_secret():
    assert looks_like_secret("4420160616")
    assert looks_like_secret("123456")
    assert not looks_like_secret("140513920000890035")
    assert not looks_like_secret("سلام")
