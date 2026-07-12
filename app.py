import streamlit as st

st.set_page_config(page_title="HQH-539 Resonant Hash Engine", layout="wide", page_icon="🔐")

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
from config import app_base_url, is_master_email, master_emails
from database import (
    activate_subscription,
    add_credits,
    bytes_per_credit,
    create_user,
    credits_for_payload,
    deduct_credits,
    get_user,
    init_db,
    list_users,
    set_password,
    user_exists,
    verify_user,
)
from crypto_hqh import (
    CryptoError,
    is_hqh539_package,
    pack_encrypted_file,
    unpack_encrypted_file,
)
from hqh539 import hqh_539, ternary_step

# Soft cap for in-browser deposits (Streamlit memory)
MAX_DEPOSIT_BYTES = 25 * 1024 * 1024

try:
    init_db()
    _db_error = None
except Exception as exc:  # noqa: BLE001
    _db_error = str(exc)

if "email" not in st.session_state:
    st.session_state.email = None

BASE_URL = app_base_url()
CHECKOUT_SUCCESS = f"{BASE_URL}/?checkout=success"
CHECKOUT_CANCEL = f"{BASE_URL}/?checkout=cancel"

st.title("HQH-539 • Resonant Hash Engine")
st.caption("539 Labs LLC")

if _db_error:
    st.error(
        "Database is unavailable — login and registration cannot run until this is fixed.\n\n"
        f"`{_db_error}`"
    )
    st.stop()

if is_live_mode():
    st.warning("Live billing is enabled. Real charges will be processed.")

st.info(
    "HQH-539 is a 539-step one-way hash function with exceptionally strong avalanche properties. "
    "Its design makes reversal computationally infeasible with known classical and quantum methods, "
    "pending independent peer review."
)

# ==================== AUTHENTICATION ====================
if not st.session_state.email:
    tab_login, tab_register, tab_reset = st.tabs(["Login", "Register", "Reset password"])

    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login", type="primary", key="login_btn"):
            em = (email or "").strip().lower()
            if not em or not password:
                st.error("Enter both email and password.")
            else:
                try:
                    if verify_user(em, password):
                        st.session_state.email = em
                        st.rerun()
                    elif user_exists(em):
                        st.error(
                            "Wrong password for this email. "
                            "Use the **Reset password** tab to set a new one, then log in."
                        )
                    else:
                        st.error("No account for that email. Use **Register** first.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Login failed (database error): {exc}")

    with tab_register:
        new_email = st.text_input("New Email", key="register_email")
        new_password = st.text_input("New Password", type="password", key="register_password")
        if st.button("Create Account", key="register_btn"):
            em = (new_email or "").strip().lower()
            if not em or "@" not in em:
                st.error("Enter a valid email.")
            elif not new_password or len(new_password) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                try:
                    if create_user(em, new_password):
                        st.success("Account created. Switch to **Login** and sign in.")
                    elif user_exists(em):
                        st.error(
                            "That email is already registered. "
                            "Log in, or use **Reset password** if you forgot it."
                        )
                    else:
                        st.error("Could not create account. Try again.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Registration failed (database error): {exc}")

    with tab_reset:
        st.caption(
            "Sets a new password for an existing account. "
            "Use this if registration says the email already exists."
        )
        reset_email = st.text_input("Email", key="reset_email")
        reset_pw = st.text_input("New password", type="password", key="reset_password")
        reset_pw2 = st.text_input("Confirm new password", type="password", key="reset_password2")
        if st.button("Set new password", key="reset_btn"):
            em = (reset_email or "").strip().lower()
            if not em or not reset_pw:
                st.error("Enter email and a new password.")
            elif reset_pw != reset_pw2:
                st.error("Passwords do not match.")
            elif len(reset_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                try:
                    if not user_exists(em):
                        st.error("No account for that email. Use **Register** instead.")
                    elif set_password(em, reset_pw):
                        st.success("Password updated. Switch to **Login** and sign in.")
                    else:
                        st.error("Could not update password.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Reset failed (database error): {exc}")

    st.stop()

email = st.session_state.email
master = is_master_email(email)

# ==================== APPLY PURCHASE ON RETURN ====================
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
            st.info(
                f"Payment received. Sync status: {detail}. "
                "Refresh in a few seconds if credits are not visible yet."
            )
    except (StripeConfigurationError, StripeTransientError, StripeCheckoutError) as exc:
        st.warning(f"Could not verify checkout with Stripe yet: {exc}")
elif qp.get("checkout") == "success":
    st.success(
        "Payment received. If credits do not appear within a minute, refresh this page."
    )

try:
    user = get_user(email)
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not load your account: {exc}")
    st.stop()

# Master always has access even with 0 credits / missing sub flags
has_access = bool(
    master
    or (user and (user.get("unlimited") or user.get("subscription_active") or user.get("credits", 0) > 0))
)

with st.sidebar:
    st.write(f"Signed in as **{email}**")
    if master:
        st.success("MASTER OPERATOR")
        st.caption("Full overrides · no toll · admin panel unlocked")
    elif user:
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

# ==================== PAYWALL (skipped for master) ====================
if not has_access:
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

if master:
    st.success(f"Master access — {email}")
else:
    st.success(f"Access granted — {email}")

tabs = [
    "Hash Computation",
    "File encrypt",
    "File decrypt",
    "Avalanche Effect",
    "539-Step Visualization",
]
if master:
    tabs.append("Master overrides")

tab_objs = st.tabs(tabs)
tab_hash = tab_objs[0]
tab_enc = tab_objs[1]
tab_dec = tab_objs[2]
tab_avalanche = tab_objs[3]
tab_viz = tab_objs[4]
tab_master = tab_objs[5] if master else None

with tab_hash:
    msg = st.text_area("Input Message", "The universe counts in threes.")
    cost = 0 if master else credits_for_payload(msg)
    nbytes = len(msg.encode("utf-8"))
    if master:
        st.caption(f"Input size: {nbytes} bytes → **master override (0 credits)**")
    else:
        st.caption(f"Input size: {nbytes} bytes → **{cost} credit(s)** for this hash")
    if st.button("Compute HQH-539", type="primary"):
        allowed = master or deduct_credits(email, cost)
        if allowed:
            st.code(hqh_539(msg), language="text")
            if not master:
                user = get_user(email)
                if user and not user.get("subscription_active"):
                    st.caption(f"Charged {cost} credit(s). Remaining: {user.get('credits', 0)}")
        else:
            st.warning(f"Need {cost} credit(s) for this payload (or an active Pro subscription).")

with tab_enc:
    st.subheader("File deposit → HQH-539 encryption")
    st.markdown(
        "Upload a file to encrypt. Key material is derived with **HQH-539** "
        "(resonant KDF); payload is sealed with **ChaCha20-Poly1305**. "
        "Download a `.hqh539enc` package you can decrypt later with the same password."
    )
    deposit = st.file_uploader(
        "Deposit file",
        type=None,
        key="encrypt_upload",
        help=f"Max {MAX_DEPOSIT_BYTES // (1024 * 1024)} MiB per deposit",
    )
    enc_password = st.text_input(
        "Encryption password",
        type="password",
        key="encrypt_password",
        help="Required to decrypt later. Store it safely — it is never stored by the server.",
    )
    enc_password2 = st.text_input(
        "Confirm password",
        type="password",
        key="encrypt_password2",
    )

    if deposit is not None:
        raw = deposit.getvalue()
        cost_enc = 0 if master else credits_for_payload(raw)
        st.caption(
            f"Deposit: **{deposit.name}** · {len(raw):,} bytes · "
            + (
                "**master override (0 credits)**"
                if master
                else f"**{cost_enc} credit(s)** to encrypt"
            )
        )
        if len(raw) > MAX_DEPOSIT_BYTES:
            st.error(
                f"File exceeds the {MAX_DEPOSIT_BYTES // (1024 * 1024)} MiB deposit limit."
            )
        elif st.button("Encrypt deposit", type="primary", key="encrypt_btn"):
            if not enc_password:
                st.error("Enter an encryption password.")
            elif enc_password != enc_password2:
                st.error("Passwords do not match.")
            else:
                allowed = master or deduct_credits(email, cost_enc)
                if not allowed:
                    st.warning(
                        f"Need {cost_enc} credit(s) for this file "
                        "(or an active Pro subscription)."
                    )
                else:
                    try:
                        package = pack_encrypted_file(raw, enc_password, deposit.name)
                        out_name = f"{deposit.name}.hqh539enc"
                        st.success(
                            f"Encrypted {len(raw):,} bytes → {len(package):,} byte package."
                        )
                        st.download_button(
                            label=f"Download {out_name}",
                            data=package,
                            file_name=out_name,
                            mime="application/octet-stream",
                            key="encrypt_download",
                        )
                        if not master:
                            user = get_user(email)
                            if user and not user.get("subscription_active"):
                                st.caption(
                                    f"Charged {cost_enc} credit(s). "
                                    f"Remaining: {user.get('credits', 0)}"
                                )
                    except CryptoError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Encryption failed: {exc}")

with tab_dec:
    st.subheader("Decrypt HQH-539 package")
    st.markdown(
        "Upload a `.hqh539enc` package produced by this engine and enter the "
        "password used at encryption time."
    )
    sealed = st.file_uploader(
        "Encrypted package",
        type=None,
        key="decrypt_upload",
        help="Typically ends with .hqh539enc",
    )
    dec_password = st.text_input(
        "Decryption password",
        type="password",
        key="decrypt_password",
    )

    if sealed is not None:
        pkg = sealed.getvalue()
        cost_dec = 0 if master else credits_for_payload(pkg)
        st.caption(
            f"Package: **{sealed.name}** · {len(pkg):,} bytes · "
            + (
                "**master override (0 credits)**"
                if master
                else f"**{cost_dec} credit(s)** to decrypt"
            )
        )
        if not is_hqh539_package(pkg):
            st.warning(
                "This file does not start with the HQH-539 package magic. "
                "Decrypt may still be attempted if the header is intact."
            )
        if len(pkg) > MAX_DEPOSIT_BYTES:
            st.error(
                f"File exceeds the {MAX_DEPOSIT_BYTES // (1024 * 1024)} MiB limit."
            )
        elif st.button("Decrypt package", type="primary", key="decrypt_btn"):
            if not dec_password:
                st.error("Enter the decryption password.")
            else:
                allowed = master or deduct_credits(email, cost_dec)
                if not allowed:
                    st.warning(
                        f"Need {cost_dec} credit(s) for this file "
                        "(or an active Pro subscription)."
                    )
                else:
                    try:
                        plaintext, orig_name = unpack_encrypted_file(pkg, dec_password)
                        st.success(
                            f"Decrypted **{orig_name}** ({len(plaintext):,} bytes)."
                        )
                        st.download_button(
                            label=f"Download {orig_name}",
                            data=plaintext,
                            file_name=orig_name,
                            mime="application/octet-stream",
                            key="decrypt_download",
                        )
                        if not master:
                            user = get_user(email)
                            if user and not user.get("subscription_active"):
                                st.caption(
                                    f"Charged {cost_dec} credit(s). "
                                    f"Remaining: {user.get('credits', 0)}"
                                )
                    except CryptoError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Decryption failed: {exc}")

with tab_avalanche:
    st.subheader("Avalanche Demonstration")
    col1, col2 = st.columns(2)
    with col1:
        orig = st.text_input("Original Message", "The universe counts in threes.")
    with col2:
        mod = st.text_input("Modified Message", "The universe counts in threez.")
    cost_av = 0 if master else credits_for_payload(orig) + credits_for_payload(mod)
    if master:
        st.caption("Two hashes → **master override (0 credits)**")
    else:
        st.caption(f"Two hashes → **{cost_av} credit(s)** total")
    if st.button("Compare Hashes"):
        charged = True if master else deduct_credits(email, cost_av)
        if charged:
            h1 = hqh_539(orig)
            h2 = hqh_539(mod)
            diff = bin(int(h1, 16) ^ int(h2, 16)).count("1")
            st.metric("Bit Differences", f"{diff} / 512", f"{(diff / 512) * 100:.2f}% change")
            st.code(f"Original:  {h1}\nModified: {h2}", language="text")
            if not master:
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

if tab_master is not None:
    with tab_master:
        st.subheader("Master operator overrides")
        st.caption(
            f"Master emails: {', '.join(sorted(master_emails()))}. "
            "These accounts bypass paywall and data-volume tolling."
        )

        st.markdown("#### Grant credits to a user")
        g_email = st.text_input("User email", key="master_grant_email")
        g_amt = st.number_input("Credits to add", min_value=1, max_value=1_000_000, value=100, step=10)
        if st.button("Grant credits", key="master_grant_btn"):
            target = (g_email or "").strip().lower()
            if not target or "@" not in target:
                st.error("Enter a valid user email.")
            elif not user_exists(target):
                st.error("That user has not registered yet.")
            elif add_credits(target, int(g_amt)):
                st.success(f"Added {int(g_amt)} credits to {target}.")
            else:
                st.error("Grant failed.")

        st.markdown("#### Activate Pro (30 days)")
        s_email = st.text_input("User email for Pro", key="master_sub_email")
        if st.button("Activate Pro subscription", key="master_sub_btn"):
            target = (s_email or "").strip().lower()
            if not target or "@" not in target:
                st.error("Enter a valid user email.")
            elif not user_exists(target):
                st.error("That user has not registered yet.")
            elif activate_subscription(target, days=30):
                st.success(f"Pro activated for 30 days: {target}")
            else:
                st.error("Activation failed.")

        st.markdown("#### Tolling override (session)")
        st.caption(
            "Master sessions never deduct credits. "
            "Optional env `MASTER_EMAILS` adds more operator emails (comma-separated)."
        )
        if st.checkbox("Show computed toll for a sample payload", key="master_toll_preview"):
            sample = st.text_area("Sample", "x" * 1000, key="master_toll_sample")
            st.write(
                {
                    "bytes": len(sample.encode("utf-8")),
                    "credits_if_customer": credits_for_payload(sample),
                    "bytes_per_credit": bytes_per_credit(),
                    "master_charge": 0,
                }
            )

        st.markdown("#### Registered users")
        try:
            rows = list_users(200)
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.info("No users registered yet.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not list users: {exc}")

st.caption("539 Labs LLC • HQH-539 Resonant Hash Engine")
