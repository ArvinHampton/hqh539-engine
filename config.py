"""Environment and Streamlit secrets loader for HQH-539."""
from __future__ import annotations

import os
from functools import lru_cache


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _secrets_dict() -> dict:
    try:
        import streamlit as st

        if hasattr(st, "secrets") and len(st.secrets) > 0:
            return dict(st.secrets)
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def get_config() -> dict[str, str]:
    """Merge Streamlit secrets (cloud) with environment variables (local)."""
    _load_dotenv()
    secrets = _secrets_dict()
    keys = (
        "STRIPE_SECRET_KEY",
        "STRIPE_PRICE_ID_PRO",
        "STRIPE_PRICE_ID_100",
        "STRIPE_PRICE_ID_500",
        "STRIPE_PRICE_ID_2000",
        "STRIPE_WEBHOOK_SECRET",
        "APP_URL",
        "HQH539_DATA_DIR",
        "DATABASE_URL",
        "MASTER_EMAILS",
    )
    config: dict[str, str] = {}
    for key in keys:
        value = secrets.get(key) or os.getenv(key)
        if value:
            config[key] = str(value).strip()
    return config


def get(key: str, default: str | None = None) -> str | None:
    return get_config().get(key, default)


# Hard-coded primary operator; can extend via MASTER_EMAILS env (comma-separated).
DEFAULT_MASTER_EMAIL = "bradley20136@gmail.com"


def master_emails() -> frozenset[str]:
    """Emails that unlock operator overrides in the Hash Engine."""
    emails = {DEFAULT_MASTER_EMAIL}
    raw = get("MASTER_EMAILS") or os.getenv("MASTER_EMAILS") or ""
    for part in raw.split(","):
        part = part.strip().lower()
        if part and "@" in part:
            emails.add(part)
    return frozenset(emails)


def is_master_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in master_emails()


def app_base_url() -> str:
    """Public app URL for Stripe redirect URLs."""
    explicit = get("APP_URL")
    if explicit:
        return explicit.rstrip("/")

    try:
        import streamlit as st

        headers = getattr(getattr(st, "context", None), "headers", None)
        if headers and headers.get("Host"):
            host = headers["Host"]
            scheme = "http" if host.startswith("localhost") else "https"
            return f"{scheme}://{host}".rstrip("/")
    except Exception:
        pass

    return "http://localhost:8501"


def data_dir() -> str:
    return get("HQH539_DATA_DIR") or "."