"""Stripe webhook service — deploy separately from Streamlit Cloud (Render, Railway, etc.)."""
from __future__ import annotations

import os

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from database import activate_subscription, add_credits, init_db

load_dotenv()

app = Flask(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

PRICE_TO_CREDITS = {
    os.getenv("STRIPE_PRICE_ID_100", ""): 100,
    os.getenv("STRIPE_PRICE_ID_500", ""): 500,
    os.getenv("STRIPE_PRICE_ID_2000", ""): 2000,
}

init_db()


def _resolve_email(session: dict) -> str | None:
    metadata = session.get("metadata") or {}
    email = metadata.get("user_email")
    if email:
        return email.strip().lower()

    customer_details = session.get("customer_details") or {}
    email = customer_details.get("email")
    if email:
        return email.strip().lower()

    client_ref = session.get("client_reference_id")
    if client_ref and "@" in client_ref:
        return client_ref.strip().lower()

    return None


def _credits_from_session(session: dict) -> int | None:
    metadata = session.get("metadata") or {}
    raw = metadata.get("credits")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass

    session_id = session.get("id")
    if not session_id:
        return None

    line_items = stripe.checkout.Session.list_line_items(session_id, limit=10)
    for item in line_items.data:
        price_id = item.price.id if item.price else ""
        if price_id in PRICE_TO_CREDITS:
            return PRICE_TO_CREDITS[price_id] * int(item.quantity or 1)
    return None


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    if not endpoint_secret:
        return jsonify({"error": "STRIPE_WEBHOOK_SECRET not configured"}), 500

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = _resolve_email(session)
        if not email:
            return jsonify({"status": "ignored - no email"}), 200

        if session.get("mode") == "subscription":
            activate_subscription(email, days=30)
            print(f"Subscription activated for: {email}")

        elif session.get("mode") == "payment":
            credits = _credits_from_session(session)
            if credits:
                ok = add_credits(email, credits)
                if ok:
                    print(f"Added {credits} credits for: {email}")
                else:
                    print(
                        f"WARN: could not add {credits} credits for {email} "
                        f"(user missing in shared DB — ensure DATABASE_URL is set "
                        f"and the same email is registered in the Streamlit app)"
                    )
            else:
                print(f"Payment completed but credits unresolved for: {email}")

    elif event["type"] == "customer.subscription.deleted":
        print("Subscription cancelled event received — extend database.py if you need auto-revoke.")

    return jsonify({"status": "success"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"Webhook handler running on http://0.0.0.0:{port}/webhook")
    app.run(host="0.0.0.0", port=port, debug=False)