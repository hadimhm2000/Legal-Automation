"""قواعد امنیتی سند (بخش ۲، ۱۲ و ۱۴)."""
import re
from pathlib import Path

from legal_bot.db import SCHEMA
from legal_bot.services.session import SecretVault

ROOT = Path(__file__).resolve().parent.parent / "legal_bot"


def test_no_credential_columns_in_db():
    cols = re.findall(r"^\s+(\w+)\s+(?:INTEGER|TEXT)", SCHEMA, re.M)
    assert cols
    for c in cols:
        assert not re.search(r"pass|otp|national|cookie|session|token|secret|captcha", c, re.I), c


def test_secrets_typed_only_in_sana_login():
    for f in ROOT.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        if "press_sequentially" in src or "vault.get(" in src:
            assert f.name in ("sana_login.py", "session.py"), f
        # هیچ کدی storage_state / trace / video / user_data_dir نمی‌سازد
        assert "storage_state" not in src and "record_video" not in src and "tracing.start" not in src, f
        assert "launch_persistent_context" not in src, f
        assert "networkidle" not in src.replace("`networkidle` ممنوع", ""), f


def test_readonly_modules_dont_click_mutating_buttons():
    forbidden = re.compile(r"(ثبت|حذف|ارسال لایحه|تأیید نهایی)")
    for name in ("eblagh.py", "resultcase.py"):
        src = (ROOT / "services" / name).read_text(encoding="utf-8")
        for m in re.finditer(r"click_text\([^)]*\)", src):
            assert not forbidden.search(m.group(0)), m.group(0)
    sel = (ROOT / "services" / "selectors.py").read_text(encoding="utf-8")
    assert "چاپ گروهی" not in sel.split("# ── اطلاع‌رسانی")[0]


def test_vault_wipe():
    v = SecretVault()
    v.put((1, "a"), "pw", "x")
    v.put((1, "a"), "nc", "y")
    assert not v.is_empty((1, "a"))
    v.wipe((1, "a"))
    assert v.is_empty((1, "a")) and v.get((1, "a"), "pw") is None
    v.put((2, "b"), "otp", "1")
    v.wipe_all()
    assert v.is_empty()
