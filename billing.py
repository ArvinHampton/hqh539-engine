"""Stripe Checkout integration with retry logic for HQH-539."""
from __future__ import annotations

import functools
import time
from typing import Any

import stripe

from config import get, get_config
from database import grant_checkout_once

CREDIT_PACKS: dict[str, dict[str, Any]] = {
    "100 Credits — $29": {"credits": 100, "price_env": "STRIPE_PRICE_ID_100"},
    "500 Credits — $99": {"credits": 500, "price_env": "STRIPE_PRICE_ID_500"},
    "2000 Credits — $299": {"credits": 2000, "price_env": "STRIPE_PRICE_ID_2000"},
}

PRICE_ENV_TO_CREDITS = {
    "STRIPE_PRICE_ID_100": 100,
    "STRIPE_PRICE_ID_500": 500,
    "STRIPE_PRICE_ID_2000": 2000,
}


class StripeConfigurationError(Exception):
    pass


class StripeTransientError(Exception):
    pass


class StripeCheckoutError(Exception):
    pass


def _configure_stripe() -> None:
    stripe.api_key = get("STRIPE_SECRET_KEY")


def retry_with_exponential_backoff(max_retries: int = 4, base_delay: float = 1.0, max_delay: float = 10.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except stripe.error.StripeError as e:
                    last_exception = e
                    transient = isinstance(
                        e,
                        (
                            stripe.error.APIConnectionError,
                            stripe.error.RateLimitError,
                            stripe.error.ServiceUnavailableError,
                        ),
                    )
                    if transient and attempt < max_retries - 1:
                        time.sleep(min(base_delay * (2**attempt), max_delay))
                        continue
                    raise StripeTransientError(f"Stripe error: {e}") from e
                except Exception as e:
                    raise StripeCheckoutError(f"Unexpected error: {e}") from e
            raise StripeTransientError(f"Max retries exceeded: {last_exception}")
        return wrapper
    return decorator


def _validate_subscription_config() -> str:
    _configure_stripe()
    price_id = get("STRIPE_PRICE_ID_PRO")
    if not stripe.api_key:
        raise StripeConfigurationError("STRIPE_SECRET_KEY is missing")
    if not price_id:
        raise StripeConfigurationError("STRIPE_PRICE_ID_PRO is missing")
    return price_id


def _validate_credit_pack_config(pack_label: str) -> tuple[int, str]:
    _configure_stripe()
    if not stripe.api_key:
        raise StripeConfigurationError("STRIPE_SECRET_KEY is missing")

    pack = CREDIT_PACKS.get(pack_label)
    if not pack:
        raise ValueError(f"Unknown credit pack: {pack_label}")

    price_id = get(pack["price_env"])
    if not price_id:
        raise StripeConfigurationError(f"{pack['price_env']} is missing")
    return int(pack["credits"]), price_id


def is_live_mode() -> bool:
    key = get("STRIPE_SECRET_KEY", "") or ""
    return key.startswith("sk_live_") or key.startswith("rk_live_")


def _price_to_credits_map() -> dict[str, int]:
    mapping: dict[str, int] = {}
    for env_key, credits in PRICE_ENV_TO_CREDITS.items():
        price_id = get(env_key)
        if price_id:
            mapping[price_id] = credits
    return mapping


def resolve_email_from_session(session: dict[str, Any] | Any) -> str | None:
    meta = getattr(session, "metadata", None) or (session.get("metadata") if isinstance(session, dict) else None) or {}
    email = meta.get("user_email") if isinstance(meta, dict) else None
    if email:
        return str(email).strip().lower()

    if isinstance(session, dict):
        details = session.get("customer_details") or {}
        email = details.get("email") or session.get("customer_email")
        if email:
            return str(email).strip().lower()
        client_ref = session.get("client_reference_id")
    else:
        details = getattr(session, "customer_details", None)
        email = None
        if details is not None:
            email = getattr(details, "email", None) or (details.get("email") if isinstance(details, dict) else None)
        email = email or getattr(session, "customer_email", None)
        if email:
            return str(email).strip().lower()
        client_ref = getattr(session, "client_reference_id", None)

    if client_ref and "@" in str(client_ref):
        return str(client_ref).strip().lower()
    return None


def resolve_credits_from_session(session: dict[str, Any] | Any) -> int | None:
    meta = getattr(session, "metadata", None) or (session.get("metadata") if isinstance(session, dict) else None) or {}
    if isinstance(meta, dict) and meta.get("credits"):
        try:
            return int(meta["credits"])
        except (TypeError, ValueError):
            pass

    session_id = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
    if not session_id:
        return None

    _configure_stripe()
    price_map = _price_to_credits_map()
    try:
        line_items = stripe.checkout.Session.list_line_items(session_id, limit=10)
        total = 0
        for item in line_items.data:
            price = item.price
            price_id = price.id if price else ""
            qty = int(item.quantity or 1)
            if price_id in price_map:
                total += price_map[price_id] * qty
        return total or None
    except stripe.error.StripeError as exc:
        print(f"resolve_credits_from_session: line_items failed: {exc}")
        return None


def apply_paid_checkout_session(session: dict[str, Any] | Any) -> tuple[bool, str]:
    """
    Apply a paid/complete Checkout Session to the user ledger (idempotent).
    Safe to call from webhook and from the app return URL.
    """
    if isinstance(session, dict):
        session_id = session.get("id") or ""
        mode = session.get("mode")
        payment_status = session.get("payment_status")
        status = session.get("status")
    else:
        session_id = getattr(session, "id", "") or ""
        mode = getattr(session, "mode", None)
        payment_status = getattr(session, "payment_status", None)
        status = getattr(session, "status", None)

    if payment_status and payment_status not in ("paid", "no_payment_required"):
        return False, f"not_paid:{payment_status}"
    if status and status not in ("complete",):
        return False, f"not_complete:{status}"

    email = resolve_email_from_session(session)
    if not email:
        return False, "no_email"

    if mode == "subscription":
        return grant_checkout_once(session_id, email, 0, kind="subscription")

    if mode == "payment":
        credits = resolve_credits_from_session(session)
        if not credits:
            return False, "credits_unresolved"
        return grant_checkout_once(session_id, email, credits, kind="credits")

    return False, f"unknown_mode:{mode}"


@retry_with_exponential_backoff()
def retrieve_checkout_session(session_id: str) -> Any:
    _configure_stripe()
    return stripe.checkout.Session.retrieve(session_id)


def apply_checkout_session_id(session_id: str) -> tuple[bool, str]:
    """Fetch session from Stripe and grant credits if paid."""
    if not session_id:
        return False, "missing_session_id"
    session = retrieve_checkout_session(session_id)
    # Require complete + paid for return-URL path
    status = getattr(session, "status", None)
    payment_status = getattr(session, "payment_status", None)
    if status != "complete" or payment_status != "paid":
        return False, f"session_not_ready status={status} payment={payment_status}"
    return apply_paid_checkout_session(session)


@retry_with_exponential_backoff()
def create_subscription_checkout(
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    price_id = _validate_subscription_config()
    email = customer_email.strip().lower()
    # Stripe replaces {CHECKOUT_SESSION_ID} on redirect
    if "{CHECKOUT_SESSION_ID}" not in success_url:
        joiner = "&" if "?" in success_url else "?"
        success_url = f"{success_url}{joiner}session_id={{CHECKOUT_SESSION_ID}}"

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        client_reference_id=email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_email": email, "product": "hqh539_pro"},
    )
    if not session.url:
        raise StripeCheckoutError("Stripe did not return a checkout URL")
    return session.url


@retry_with_exponential_backoff()
def create_credit_pack_checkout(
    pack_label: str,
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    credits, price_id = _validate_credit_pack_config(pack_label)
    email = customer_email.strip().lower()
    if "{CHECKOUT_SESSION_ID}" not in success_url:
        joiner = "&" if "?" in success_url else "?"
        success_url = f"{success_url}{joiner}session_id={{CHECKOUT_SESSION_ID}}"

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=email,
        client_reference_id=email,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_email": email,
            "credits": str(credits),
            "product": "hqh539_credits",
        },
    )
    if not session.url:
        raise StripeCheckoutError("Stripe did not return a checkout URL")
    return session.url


def configured_price_ids() -> dict[str, str | None]:
    cfg = get_config()
    return {
        "pro": cfg.get("STRIPE_PRICE_ID_PRO"),
        "pack_100": cfg.get("STRIPE_PRICE_ID_100"),
        "pack_500": cfg.get("STRIPE_PRICE_ID_500"),
        "pack_2000": cfg.get("STRIPE_PRICE_ID_2000"),
    }
