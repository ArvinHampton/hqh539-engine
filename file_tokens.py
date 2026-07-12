"""Short-lived HMAC tokens so the file service can trust the logged-in Streamlit user."""
from __future__ import annotations

import hashlib
import hmac
import os
import time


def _secret() -> bytes:
    raw = (
        os.getenv("FILE_TOKEN_SECRET")
        or os.getenv("STRIPE_SECRET_KEY")
        or os.getenv("STRIPE_WEBHOOK_SECRET")
        or "hqh539-dev-file-token"
    )
    return raw.encode("utf-8")


def mint_file_token(email: str, ttl_seconds: int = 3600) -> str:
    email = (email or "").strip().lower()
    exp = int(time.time()) + max(60, ttl_seconds)
    body = f"{email}|{exp}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def verify_file_token(token: str) -> str | None:
    """Return email if token is valid, else None."""
    if not token or token.count("|") != 2:
        return None
    email, exp_s, sig = token.split("|", 2)
    email = email.strip().lower()
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    body = f"{email}|{exp}"
    expect = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    if "@" not in email:
        return None
    return email
