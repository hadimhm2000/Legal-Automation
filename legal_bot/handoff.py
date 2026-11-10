"""توکن start امضاشده بین ربات اصلی و ربات دوم (بخش ۴.۲ سند).

قالب: base64url( uid | ts | HMAC_SHA256(secret, "uid|ts")[:16] ) — کمتر از ۶۴ نویسه.
همین فایل (بدون تغییر) در ربات اصلی هم کپی شده است: legal_handoff.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def _sig(secret: str, uid: int, ts: int) -> str:
    return hmac.new(secret.encode(), f"{uid}|{ts}".encode(), hashlib.sha256).hexdigest()[:16]


def make_token(uid: int, secret: str, ts: int | None = None) -> str:
    ts = int(ts if ts is not None else time.time())
    raw = f"{uid}|{ts}|{_sig(secret, uid, ts)}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_token(token: str, secret: str, from_user_id: int, ttl: int = 300,
                 now: int | None = None) -> bool:
    if not token or not secret:
        return False
    try:
        pad = "=" * (-len(token) % 4)
        uid_s, ts_s, sig = base64.urlsafe_b64decode(token + pad).decode().split("|")
        uid, ts = int(uid_s), int(ts_s)
    except Exception:
        return False
    now = int(now if now is not None else time.time())
    if uid != from_user_id or ts > now + 30 or now - ts > ttl:
        return False
    return hmac.compare_digest(sig, _sig(secret, uid, ts))
