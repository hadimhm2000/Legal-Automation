"""هر رقم فارسی/عربی که کاربر می‌فرستد باید قبل از ورود به سامانه لاتین شود."""
import asyncio

import pytest

from legal_bot.services.session import SecretVault, Job
from legal_bot.utils import to_en_digits


def test_to_en_digits_all_variants():
    assert to_en_digits("۰۱۲۳۴۵۶۷۸۹ ٠١٢٣٤٥٦٧٨٩ abc ۱۴۰۵/۰۹/۰۴") == "0123456789 0123456789 abc 1405/09/04"


def test_vault_normalizes():
    v = SecretVault()
    v.put((1, "x"), "nc", "۰۰۱۲۳۴۵۶۷۸")
    assert v.get((1, "x"), "nc") == "0012345678"


async def test_deliver_text_normalizes():
    class E:
        accept_text = True
        future = asyncio.get_event_loop().create_future()

    j = Job.__new__(Job)
    j._expect = E()
    assert j.deliver_text("پرونده ۹۸۰۰۱۲۳") is True
    assert E.future.result() == ("text", "پرونده 9800123")
