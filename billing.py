"""Stripe Checkout integration with retry logic for HQH-539."""
from __future__ import annotations

import functools
import time
from typing import Any

import stripe

from config import get, get_config

CREDIT_PACKS: dict[str, dict[str, Any]] = {
    "100 Credits — $29": {"credits": 100, "price_env": "STRIPE_PRICE_ID_100"},
    "500 Credits — $99": {"credits": 500, "price_env": "STRIPE_PRICE_ID_500"},
    "2000 Credits — $299": {"credits": 2000, "price_env": "STRIPE_PRICE_ID_2000"},
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
    key = get("STRIPE_SECRET_KEY", "")
    return key.startswith("sk_live_")


@retry_with_exponential_backoff()
def create_subscription_checkout(
    customer_email: str,
    success_url: str,
    cancel_url: str,
) -> str:
    price_id = _validate_subscription_config()
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=customer_email.strip().lower(),
        client_reference_id=customer_email.strip().lower(),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_email": customer_email.strip().lower(), "product": "hqh539_pro"},
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
    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=customer_email.strip().lower(),
        client_reference_id=customer_email.strip().lower(),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url + "?checkout=success",
        cancel_url=cancel_url,
        metadata={
            "user_email": customer_email.strip().lower(),
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