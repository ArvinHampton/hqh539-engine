"""Stripe webhook + HTTP file encrypt/decrypt service for HQH-539-512."""
from __future__ import annotations

import os

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from billing import apply_paid_checkout_session
from database import init_db
from file_service import register_file_routes

load_dotenv()

app = Flask(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Ensure DB tables exist (shared Postgres with Streamlit app)
try:
    init_db()
except Exception as exc:  # noqa: BLE001
    print(f"init_db warning: {exc}")

register_file_routes(app)


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "ok",
            "db": bool(os.getenv("DATABASE_URL")),
            "file_api": True,
        }
    ), 200


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
        if isinstance(session, dict) and session.get("status") == "complete":
            session.setdefault("payment_status", session.get("payment_status") or "paid")
        applied, msg = apply_paid_checkout_session(session)
        print(f"checkout.session.completed applied={applied} msg={msg} id={session.get('id')}")
        return jsonify({"status": "ok", "applied": applied, "detail": msg}), 200

    if event["type"] == "customer.subscription.deleted":
        print("Subscription cancelled event received")
        return jsonify({"status": "ok"}), 200

    return jsonify({"status": "ignored", "type": event["type"]}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    print(f"Service on http://0.0.0.0:{port} (webhook + /file/encrypt + /file/decrypt)")
    app.run(host="0.0.0.0", port=port, debug=False)
