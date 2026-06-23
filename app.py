import streamlit as st

from billing import (
    CREDIT_PACKS,
    StripeCheckoutError,
    StripeConfigurationError,
    StripeTransientError,
    create_credit_pack_checkout,
    create_subscription_checkout,
    is_live_mode,
)
from config import app_base_url
from database import create_user, deduct_credit, get_user, init_db, verify_user
from hqh539 import hqh_539, ternary_step

init_db()

st.set_page_config(page_title="HQH-539 Resonant Hash Engine", layout="wide", page_icon="🔐")

if "email" not in st.session_state:
    st.session_state.email = None

BASE_URL = app_base_url()
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
                st.error("Email already exists")
    st.stop()

email = st.session_state.email
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
    if st.button("Log out"):
        st.session_state.email = None
        st.rerun()

if st.query_params.get("checkout") == "success":
    st.success("Payment received. Access updates after Stripe webhook confirmation (usually under a minute).")

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
        "Use the same email at checkout that you registered with. "
        "Credits and subscriptions are applied by the Stripe webhook — not via the return URL."
    )
    st.stop()

st.success(f"Access granted — {email}")

# ==================== MAIN TABS ====================
tab_hash, tab_avalanche, tab_viz = st.tabs(
    ["Hash Computation", "Avalanche Effect", "539-Step Visualization"]
)

with tab_hash:
    msg = st.text_area("Input Message", "The universe counts in threes.")
    if st.button("Compute HQH-539", type="primary"):
        if deduct_credit(email):
            st.code(hqh_539(msg), language="text")
            user = get_user(email)
            if user and not user.get("subscription_active"):
                st.caption(f"Credits remaining: {user.get('credits', 0)}")
        else:
            st.warning("Insufficient credits or subscription expired.")

with tab_avalanche:
    st.subheader("Avalanche Demonstration")
    col1, col2 = st.columns(2)
    with col1:
        orig = st.text_input("Original Message", "The universe counts in threes.")
    with col2:
        mod = st.text_input("Modified Message", "The universe counts in threez.")
    if st.button("Compare Hashes"):
        h1 = hqh_539(orig)
        h2 = hqh_539(mod)
        diff = bin(int(h1, 16) ^ int(h2, 16)).count("1")
        st.metric("Bit Differences", f"{diff} / 512", f"{(diff / 512) * 100:.2f}% change")
        st.code(f"Original:  {h1}\nModified: {h2}", language="text")

with tab_viz:
    st.subheader("Real-Time 539-Step Visualization")
    if st.button("Run 539-Step Collapse"):
        sequence = []
        n = 10**12
        for _ in range(539):
            sequence.append(float(n))
            n = ternary_step(n)
        st.line_chart(sequence)

st.caption("539 Labs LLC • HQH-539 Resonant Hash Engine")