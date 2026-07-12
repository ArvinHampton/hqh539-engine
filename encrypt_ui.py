"""
Streamlit side of encrypt/decrypt: only opens a full-page file portal.

No file upload, no password widgets, no Continue button inside Streamlit.
That work happens on FILE_SERVICE_URL (Flask), which does not drop the login session.
"""
from __future__ import annotations

import os
from urllib.parse import quote

import streamlit as st

from file_tokens import mint_file_token


def _file_service_url() -> str:
    return (
        os.getenv("FILE_SERVICE_URL")
        or os.getenv("WEBHOOK_URL")
        or "https://hqh539-webhook.onrender.com"
    ).rstrip("/")


def _max_mb() -> int:
    raw = (os.getenv("HQH539_MAX_DEPOSIT_MB") or "2048").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2048


def _portal_url(email: str, mode: str) -> str:
    token = mint_file_token(email, ttl_seconds=7200)
    base = _file_service_url()
    return f"{base}/file/portal?mode={quote(mode)}&token={quote(token, safe='')}"


def render_encrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Encrypt deposit")
    st.caption(
        f"Hampton Qutrit Hash (HQH-539) · SHA3-512 wrap · ChaCha20-Poly1305 · limit {_max_mb()} MiB"
    )
    st.warning(
        "Encrypt runs in a **separate browser page** on the file server. "
        "That avoids Streamlit connection 502 errors and keeps you logged in here."
    )
    if is_master:
        st.success("Master operator — no credit charge on encrypt.")

    url = _portal_url(email, "encrypt")
    st.link_button("Open Encrypt Portal →", url, type="primary")
    st.markdown(f"Or open this link: [{url.split('?')[0]}?mode=encrypt&token=…]({url})")

    st.markdown(
        """
**On the portal page**
1. Choose the file  
2. Enter password  
3. Confirm password  
4. Click **Encrypt & download** once  
5. Keep that tab open until the `.hqh539enc` file downloads  

There is **no Continue button** on the portal — only **Encrypt & download**.
"""
    )
    st.caption(f"Signed in as `{email}` · service `{_file_service_url()}`")


def render_decrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Decrypt package")
    st.caption("Recover a file from a `.hqh539enc` package.")
    st.warning(
        "Decrypt also opens on the **file server** in a separate page so large packages "
        "do not drop this Streamlit session."
    )
    if is_master:
        st.success("Master operator — no credit charge on decrypt.")

    url = _portal_url(email, "decrypt")
    st.link_button("Open Decrypt Portal →", url, type="primary")
    st.markdown(
        """
**On the portal page**
1. Choose the `.hqh539enc` package  
2. Enter password  
3. Click **Decrypt & download**  
"""
    )
    st.caption(f"Signed in as `{email}` · service `{_file_service_url()}`")
