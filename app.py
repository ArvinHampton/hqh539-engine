import streamlit as st

from billing import (
    CREDIT_PACKS,
    StripeCheckoutError,
    StripeConfigurationError,
    StripeTransientError,
    apply_checkout_session_id,
    create_credit_pack_checkout,
    create_subscription_checkout,
    is_live_mode,
)
from config import app_base_url
from database import (
    bytes_per_credit,
    create_user,
    credits_for_payload,
    deduct_credits,
    get_user,
    init_db,
    verify_user,
)
from hqh539 import hqh_539, ternary_step

init_db()

st.set_page_config(page_title="HQH-539 Resonant Hash Engine", layout="wide", page_icon="🔐")

if "email" not in st.session_state:
    st.session_state.email = None

BASE_URL = app_base_url()
# Stripe fills {CHECKOUT_SESSION_ID}; billing appends session_id= if missing
CHECKOUT_SUCCESS = f"{BASE_URL}/?checkout=success"
CHECKOUT_CANCEL = f"{BASE_URL}/?checkout=cancel"

st.title("HQH-539 • Resonant Hash Engine")
st.caption("539 Labs LLC")

if is_live_mode():
    st.warning("Live billing is enabled. Real charges will be processed.")

st.info(
    "HQH-539 is a 539-step one-way hash function with exceptionally strong avalanche properties. "
    "Its design makes reversal computationally infeasible with known classical and quantum methods, "
    "pending independent peer review."
)

# ==================== AUTHENTICATION ====================
if not st.session_state.email:
    tab_login, tab_register = st.tabs(["Login", "Register"])
    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", type="primary"):
            if verify_user(email, password):
                st.session_state.email = email.strip().lower()
                st.rerun()
            else:
                st.error("Invalid credentials")
    with tab_register:
        new_email = st.text_input("New Email", key="register_email")
        new_password = st.text_input("New Password", type="password", key="register_password")
        if st.button("Create Account"):
            if create_user(new_email, new_password):
                st.success("Account created. Please log in.")
            else:
                st.error("Email already exists — log in with that email.")
    st.stop()

email = st.session_state.email

# ==================== APPLY PURCHASE ON RETURN ====================
# Primary path for crediting the logged-in user (webhook is backup / async).
qp = st.query_params
if qp.get("checkout") == "success" and qp.get("session_id"):
    session_id = str(qp.get("session_id"))
    try:
        applied, detail = apply_checkout_session_id(session_id)
        if applied:
            st.success("Payment confirmed — credits are now on your account.")
        elif detail == "already_applied":
            st.success("Payment already applied to your account.")
        elif detail == "user_missing":
            st.error(
                "Payment succeeded but no account matches the checkout email. "
                "Register/login with the **same email** used at Stripe checkout, then reopen this success link."
            )
        else:
            st.info(f"Payment received. Sync status: {detail}. Refresh in a few seconds if credits are not visible yet.")
    except (StripeConfigurationError, StripeTransientError, StripeCheckoutError) as exc:
        st.warning(f"Could not verify checkout with Stripe yet: {exc}")
elif qp.get("checkout") == "success":
    st.success(
        "Payment received. If credits do not appear within a minute, refresh this page "
        "or ensure the Stripe webhook is pointed at the webhook service."
    )

user = get_user(email)

with st.sidebar:
    st.write(f"Signed in as **{email}**")
    if user:
        if user.get("subscription_active"):
            st.success("Pro subscription active")
            if user.get("subscription_expires"):
                st.caption(f"Renews / expires: {user['subscription_expires'][:10]}")
        else:
            st.metric("Credits remaining", user.get("credits", 0))
        unit = bytes_per_credit()
        st.caption(f"Tolling: 1 credit per {unit // 1024} KiB of input (min 1)")
    if st.button("Log out"):
        st.session_state.email = None
        st.rerun()

# ==================== PAYWALL ====================
if not user or (not user.get("subscription_active") and user.get("credits", 0) <= 0):
    st.warning("Choose how you want to access HQH-539:")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Monthly Subscription")
        st.markdown("**$149 / month** — Unlimited usage")
        if st.button("Subscribe — $149/mo", type="primary", key="subscribe_btn"):
            try:
                url = create_subscription_checkout(
                    customer_email=email,
                    success_url=CHECKOUT_SUCCESS,
                    cancel_url=CHECKOUT_CANCEL,
                )
                st.link_button("Complete Subscription →", url, type="primary")
            except StripeConfigurationError as exc:
                st.error(f"Billing is not configured: {exc}")
            except (StripeTransientError, StripeCheckoutError) as exc:
                st.error(f"Could not start checkout: {exc}")

    with col2:
        st.subheader("Credit Packs (Pay-Per-Use)")
        pack = st.selectbox("Select Credit Pack", list(CREDIT_PACKS.keys()))
        if st.button("Buy Credits", key="buy_credits_btn"):
            try:
                url = create_credit_pack_checkout(
                    pack_label=pack,
                    customer_email=email,
                    success_url=CHECKOUT_SUCCESS,
                    cancel_url=CHECKOUT_CANCEL,
                )
                st.link_button("Purchase Credits →", url, type="primary")
            except StripeConfigurationError as exc:
                st.error(f"Billing is not configured: {exc}")
            except (StripeTransientError, StripeCheckoutError) as exc:
                st.error(f"Could not start checkout: {exc}")

    st.caption(
        "Checkout is locked to your account email. "
        "Credits apply when you return from Stripe (and via webhook). "
        f"Usage toll: **1 credit / {bytes_per_credit() // 1024} KiB** of data hashed (minimum 1)."
    )
    st.stop()

st.success(f"Access granted — {email}")

# ==================== MAIN TABS ====================
tab_hash, tab_avalanche, tab_viz = st.tabs(
    ["Hash Computation", "Avalanche Effect", "539-Step Visualization"]
)

with tab_hash:
    msg = st.text_area("Input Message", "The universe counts in threes.")
    cost = credits_for_payload(msg)
    nbytes = len(msg.encode("utf-8"))
    st.caption(f"Input size: {nbytes} bytes → **{cost} credit(s)** for this hash")
    if st.button("Compute HQH-539", type="primary"):
        if deduct_credits(email, cost):
            st.code(hqh_539(msg), language="text")
            user = get_user(email)
            if user and not user.get("subscription_active"):
                st.caption(f"Charged {cost} credit(s). Remaining: {user.get('credits', 0)}")
        else:
            st.warning(f"Need {cost} credit(s) for this payload (or an active Pro subscription).")

with tab_avalanche:
    st.subheader("Avalanche Demonstration")
    col1, col2 = st.columns(2)
    with col1:
        orig = st.text_input("Original Message", "The universe counts in threes.")
    with col2:
        mod = st.text_input("Modified Message", "The universe counts in threez.")
    cost_av = credits_for_payload(orig) + credits_for_payload(mod)
    st.caption(f"Two hashes → **{cost_av} credit(s)** total")
    if st.button("Compare Hashes"):
        if deduct_credits(email, cost_av):
            h1 = hqh_539(orig)
            h2 = hqh_539(mod)
            diff = bin(int(h1, 16) ^ int(h2, 16)).count("1")
            st.metric("Bit Differences", f"{diff} / 512", f"{(diff / 512) * 100:.2f}% change")
            st.code(f"Original:  {h1}\nModified: {h2}", language="text")
            user = get_user(email)
            if user and not user.get("subscription_active"):
                st.caption(f"Charged {cost_av} credit(s). Remaining: {user.get('credits', 0)}")
        else:
            st.warning(f"Need {cost_av} credit(s) for this comparison.")

with tab_viz:
    st.subheader("Real-Time 539-Step Visualization")
    st.caption("Visualization is free (no payload hash).")
    if st.button("Run 539-Step Collapse"):
        sequence = []
        n = 10**12
        for _ in range(539):
            sequence.append(float(n))
            n = ternary_step(n)
        st.line_chart(sequence)

st.caption("539 Labs LLC • HQH-539 Resonant Hash Engine")
