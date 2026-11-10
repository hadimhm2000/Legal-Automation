from legal_bot.handoff import make_token, verify_token


def test_roundtrip_and_rules():
    t = make_token(42, "s", ts=1000)
    assert len(t) < 64
    assert verify_token(t, "s", 42, ttl=300, now=1100)
    assert not verify_token(t, "s", 43, ttl=300, now=1100)      # uid دیگر
    assert not verify_token(t, "s", 42, ttl=300, now=1400)      # منقضی
    assert not verify_token(t, "x", 42, ttl=300, now=1100)      # راز اشتباه
    assert not verify_token(t[:-2] + "AA", "s", 42, now=1100)   # دستکاری
    assert not verify_token("", "s", 42)
