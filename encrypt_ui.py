"""
Encrypt/decrypt UI for Streamlit — HTTP form posts to the file service.

Large files never enter the Streamlit websocket (avoids Render 502 + forced logout).
The browser POSTs multipart form data straight to FILE_SERVICE_URL.
"""
from __future__ import annotations

import html
import os

import streamlit as st
import streamlit.components.v1 as components

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


def render_encrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Encrypt deposit")
    st.caption(
        "Hampton Qutrit Hash (HQH-539) KDF · SHA3-512 wrap · ChaCha20-Poly1305 · "
        f"limit {_max_mb()} MiB"
    )
    st.info(
        "This form uploads **directly to the file server** (not through Streamlit). "
        "That prevents connection 502 errors and login kicks on large files. "
        "Your download starts when encryption finishes."
    )
    if is_master:
        st.success("Master operator — no credit charge.")

    token = mint_file_token(email, ttl_seconds=7200)
    action = html.escape(f"{_file_service_url()}/file/encrypt")
    token_esc = html.escape(token)

    components.html(
        f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 8px; color: #111; }}
    label {{ display: block; font-weight: 600; margin: 12px 0 4px; }}
    input[type=file], input[type=password] {{
      width: 100%; max-width: 520px; padding: 8px; box-sizing: border-box;
    }}
    button {{
      margin-top: 16px; padding: 10px 18px; font-size: 15px; font-weight: 600;
      background: #ff4b4b; color: #fff; border: 0; border-radius: 6px; cursor: pointer;
    }}
    button:hover {{ background: #e03e3e; }}
    .hint {{ color: #444; font-size: 13px; margin-top: 8px; }}
    .box {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; max-width: 560px; }}
  </style>
</head>
<body>
  <div class="box">
    <form action="{action}" method="post" enctype="multipart/form-data">
      <input type="hidden" name="token" value="{token_esc}"/>
      <label for="file">1 · File to encrypt</label>
      <input id="file" type="file" name="file" required/>

      <label for="password">2 · Encryption password</label>
      <input id="password" type="password" name="password" required minlength="4"
             autocomplete="new-password"/>

      <label for="password2">3 · Confirm password</label>
      <input id="password2" type="password" name="password2" required minlength="4"
             autocomplete="new-password"/>

      <button type="submit">Encrypt &amp; download</button>
      <p class="hint">Stay on this page while the upload runs. Large files can take several minutes.</p>
    </form>
  </div>
</body>
</html>
        """,
        height=420,
        scrolling=False,
    )
    st.caption(f"File service: `{_file_service_url()}/file/encrypt` · signed in as `{email}`")


def render_decrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Decrypt package")
    st.caption("Upload a `.hqh539enc` package and recover the original file.")
    st.info(
        "Decrypt also uses a direct browser upload to the file server "
        "(not Streamlit) so large packages do not drop your session."
    )
    if is_master:
        st.success("Master operator — no credit charge.")

    token = mint_file_token(email, ttl_seconds=7200)
    action = html.escape(f"{_file_service_url()}/file/decrypt")
    token_esc = html.escape(token)

    components.html(
        f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 8px; color: #111; }}
    label {{ display: block; font-weight: 600; margin: 12px 0 4px; }}
    input[type=file], input[type=password] {{
      width: 100%; max-width: 520px; padding: 8px; box-sizing: border-box;
    }}
    button {{
      margin-top: 16px; padding: 10px 18px; font-size: 15px; font-weight: 600;
      background: #ff4b4b; color: #fff; border: 0; border-radius: 6px; cursor: pointer;
    }}
    button:hover {{ background: #e03e3e; }}
    .hint {{ color: #444; font-size: 13px; margin-top: 8px; }}
    .box {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; max-width: 560px; }}
  </style>
</head>
<body>
  <div class="box">
    <form action="{action}" method="post" enctype="multipart/form-data">
      <input type="hidden" name="token" value="{token_esc}"/>
      <label for="file">1 · Encrypted package (.hqh539enc)</label>
      <input id="file" type="file" name="file" required/>

      <label for="password">2 · Decryption password</label>
      <input id="password" type="password" name="password" required
             autocomplete="current-password"/>

      <button type="submit">Decrypt &amp; download</button>
      <p class="hint">Wrong password returns an error page — use the browser Back button to retry.</p>
    </form>
  </div>
</body>
</html>
        """,
        height=360,
        scrolling=False,
    )
    st.caption(f"File service: `{_file_service_url()}/file/decrypt` · signed in as `{email}`")
