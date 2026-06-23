"""Usage tracking and tier enforcement for HQH-539 Engine."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

TIER_FREE = "free"
TIER_PRO = "pro"

FREE_DAILY_LIMIT = 10

DEFAULT_STATE: dict[str, Any] = {
    "tier": TIER_FREE,
    "daily_count": 0,
    "last_date": "",
    "stripe_customer_id": None,
    "stripe_subscription_id": None,
}


def today_iso(today: date | None = None) -> str:
    return (today or date.today()).isoformat()


def normalize_state(state: dict[str, Any], today: str) -> dict[str, Any]:
    """Reset daily counter when the calendar day changes."""
    merged = {**DEFAULT_STATE, **state}
    if merged.get("last_date") != today:
        merged["daily_count"] = 0
        merged["last_date"] = today
    return merged


def daily_limit_for_tier(tier: str) -> int | None:
    """Return daily limit for tier, or None for unlimited (Pro)."""
    if tier == TIER_PRO:
        return None
    return FREE_DAILY_LIMIT


def can_use(tier: str, daily_count: int, limit: int | None = None) -> bool:
    """True if the user may perform a gated operation."""
    effective_limit = limit if limit is not None else daily_limit_for_tier(tier)
    if effective_limit is None:
        return True
    return daily_count < effective_limit


def record_use(state: dict[str, Any], today: str) -> dict[str, Any]:
    """Increment daily usage after a successful gated operation."""
    normalized = normalize_state(state, today)
    normalized["daily_count"] = int(normalized.get("daily_count", 0)) + 1
    normalized["last_date"] = today
    return normalized


def grant_pro(state: dict[str, Any], stripe_session_id: str | None = None) -> dict[str, Any]:
    """Upgrade user to Pro tier after verified payment."""
    upgraded = {**DEFAULT_STATE, **state}
    upgraded["tier"] = TIER_PRO
    if stripe_session_id:
        upgraded["stripe_checkout_session_id"] = stripe_session_id
    return upgraded


def usage_summary(tier: str, daily_count: int, today: str) -> dict[str, Any]:
    """Human-readable usage snapshot for UI."""
    limit = daily_limit_for_tier(tier)
    remaining = None if limit is None else max(0, limit - daily_count)
    return {
        "tier": tier,
        "daily_count": daily_count,
        "daily_limit": limit,
        "remaining": remaining,
        "date": today,
        "unlimited": limit is None,
    }


def tier_features() -> list[dict[str, str]]:
    """Feature comparison rows for Free vs Pro display."""
    return [
        {"feature": "Daily hash / avalanche / encrypt operations", "free": "10", "pro": "Unlimited"},
        {"feature": "Wrapped & Pure resonant modes", "free": "Yes", "pro": "Yes"},
        {"feature": "AES-GCM encrypt / decrypt (KDF)", "free": "Yes", "pro": "Yes"},
        {"feature": "Benchmarks & metrics", "free": "Yes", "pro": "Yes"},
        {"feature": "Priority support", "free": "—", "pro": "Yes"},
    ]


def _default_store_path() -> Path:
    return Path(os.environ.get("HQH539_DATA_DIR", ".")) / "usage_data.json"


def load_store(path: Path | str | None = None) -> dict[str, Any]:
    """Load the full usage store from disk."""
    store_path = Path(path) if path else _default_store_path()
    if not store_path.exists():
        return {"users": {}}
    with open(store_path, encoding="utf-8") as f:
        return json.load(f)


def save_store(store: dict[str, Any], path: Path | str | None = None) -> None:
    """Persist the full usage store to disk."""
    store_path = Path(path) if path else _default_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def get_user_state(
    user_id: str,
    path: Path | str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Load and normalize a single user's state."""
    store = load_store(path)
    users = store.setdefault("users", {})
    raw = users.get(user_id, {})
    return normalize_state(raw, today or today_iso())


def set_user_state(
    user_id: str,
    state: dict[str, Any],
    path: Path | str | None = None,
) -> None:
    """Persist a single user's state."""
    store = load_store(path)
    store.setdefault("users", {})[user_id] = state
    save_store(store, path)


def check_and_record(
    user_id: str,
    path: Path | str | None = None,
    today: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Check if user can operate; if yes, record usage and persist.
    Returns (allowed, updated_state).
    """
    today_str = today or today_iso()
    state = get_user_state(user_id, path, today_str)
    allowed = can_use(state["tier"], state["daily_count"])
    if allowed:
        state = record_use(state, today_str)
        set_user_state(user_id, state, path)
    return allowed, state