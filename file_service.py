"""
HTTP file encrypt/decrypt (Flask) for HQH-539-512.

Large deposits never touch Streamlit (avoids Render 502 + forced logout).
Browser uses a full-page portal + multipart POST to these routes.
"""
from __future__ import annotations

import html
import io
import os
from typing import Any
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file

from config import is_master_email
from crypto_hqh import CryptoError, pack_encrypted_file, unpack_encrypted_file
from database import credits_for_nbytes, deduct_credits, get_user, user_exists
from file_tokens import verify_file_token


def _max_deposit_bytes() -> int:
    raw = (os.getenv("HQH539_MAX_DEPOSIT_MB") or "2048").strip()
    try:
        mb = int(raw)
    except ValueError:
        mb = 2048
    return max(1, mb) * 1024 * 1024


def _fmt(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _page(title: str, body: str, status: int = 200) -> Response:
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>
    :root {{ font-family: system-ui, Segoe UI, sans-serif; color: #111; }}
    body {{ max-width: 640px; margin: 40px auto; padding: 0 16px; line-height: 1.45; }}
    h1 {{ font-size: 1.35rem; margin-bottom: 0.25rem; }}
    .sub {{ color: #555; margin-bottom: 1.25rem; }}
    label {{ display: block; font-weight: 600; margin: 14px 0 6px; }}
    input[type=file], input[type=password] {{
      width: 100%; padding: 10px; box-sizing: border-box; font-size: 1rem;
    }}
    button, .btn {{
      display: inline-block; margin-top: 18px; padding: 12px 20px; font-size: 1rem;
      font-weight: 600; background: #c62828; color: #fff; border: 0; border-radius: 8px;
      cursor: pointer; text-decoration: none;
    }}
    button:hover, .btn:hover {{ background: #a61f1f; }}
    .box {{ border: 1px solid #ddd; border-radius: 10px; padding: 18px; background: #fafafa; }}
    .ok {{ color: #1b5e20; }}
    .err {{ color: #b71c1c; background: #ffebee; padding: 12px; border-radius: 8px; }}
    .hint {{ color: #555; font-size: 0.92rem; margin-top: 10px; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""
    return Response(doc, status=status, mimetype="text/html; charset=utf-8")


def _auth_email_from_request() -> tuple[str | None, Response | None]:
    token = (
        request.form.get("token")
        or request.args.get("token")
        or request.headers.get("X-HQH-Token")
        or ""
    ).strip()
    email = verify_file_token(token)
    if not email:
        return None, _page(
            "Session expired",
            """
            <h1>Session expired</h1>
            <p class="err">Your encrypt/decrypt link is invalid or expired.</p>
            <p>Return to the Hash Engine, log in again, and open <strong>File encrypt</strong> for a new link.</p>
            """,
            401,
        )
    return email, None


def _require_access(email: str, nbytes: int) -> tuple[bool, Response | None]:
    if is_master_email(email):
        return True, None
    if not user_exists(email):
        return False, _page(
            "Account required",
            f"<h1>Account required</h1><p class='err'>No account for {html.escape(email)}.</p>",
            403,
        )
    user = get_user(email)
    if user and (user.get("subscription_active") or user.get("unlimited")):
        return True, None
    cost = credits_for_nbytes(nbytes)
    if not deduct_credits(email, cost):
        return False, _page(
            "Insufficient credits",
            f"""
            <h1>Insufficient credits</h1>
            <p class="err">Need <strong>{cost}</strong> credits for {_fmt(nbytes)}.</p>
            <p>Buy credits on the Hash Engine, then retry with a fresh portal link.</p>
            """,
            402,
        )
    return True, None


def register_file_routes(app: Flask) -> None:
    app.config["MAX_CONTENT_LENGTH"] = _max_deposit_bytes() + 2 * 1024 * 1024

    @app.route("/file/health", methods=["GET"])
    def file_health():
        return jsonify(
            {
                "status": "ok",
                "service": "hqh539-file",
                "max_mb": _max_deposit_bytes() // (1024 * 1024),
            }
        )

    @app.route("/file/portal", methods=["GET"])
    def file_portal():
        email, err = _auth_email_from_request()
        if err:
            return err
        mode = (request.args.get("mode") or "encrypt").strip().lower()
        token = (request.args.get("token") or "").strip()
        token_h = html.escape(token)
        email_h = html.escape(email)
        max_mb = _max_deposit_bytes() // (1024 * 1024)

        if mode == "decrypt":
            return _page(
                "HQH-539-512 Decrypt",
                f"""
                <h1>HQH-539-512 · Decrypt</h1>
                <p class="sub">Signed in as <strong>{email_h}</strong> · max {max_mb} MiB</p>
                <div class="box">
                  <form action="/file/decrypt" method="post" enctype="multipart/form-data">
                    <input type="hidden" name="token" value="{token_h}"/>
                    <label for="file">Encrypted package (.hqh539enc)</label>
                    <input id="file" type="file" name="file" required/>
                    <label for="password">Password</label>
                    <input id="password" type="password" name="password" required autocomplete="current-password"/>
                    <button type="submit">Decrypt &amp; download</button>
                    <p class="hint">Stay on this page until the download starts. Large files can take several minutes.</p>
                  </form>
                </div>
                """,
            )

        # default encrypt
        return _page(
            "HQH-539-512 Encrypt",
            f"""
            <h1>HQH-539-512 · Encrypt deposit</h1>
            <p class="sub">Signed in as <strong>{email_h}</strong> · max {max_mb} MiB<br/>
            Hampton Qutrit Hash (HQH) · 539 steps (18+521) · SHA3-512 wrap · ChaCha20-Poly1305</p>
            <div class="box">
              <form action="/file/encrypt" method="post" enctype="multipart/form-data">
                <input type="hidden" name="token" value="{token_h}"/>
                <label for="file">1 · File to encrypt</label>
                <input id="file" type="file" name="file" required/>
                <label for="password">2 · Encryption password</label>
                <input id="password" type="password" name="password" required minlength="4" autocomplete="new-password"/>
                <label for="password2">3 · Confirm password</label>
                <input id="password2" type="password" name="password2" required minlength="4" autocomplete="new-password"/>
                <button type="submit">Encrypt &amp; download</button>
                <p class="hint">
                  There is no “Continue” step — pick the file, enter both passwords, then press
                  <strong>Encrypt &amp; download</strong> once. Keep this tab open until the file downloads.
                </p>
              </form>
            </div>
            """,
        )

    @app.route("/file/encrypt", methods=["POST"])
    def file_encrypt():
        return _handle_encrypt()

    @app.route("/file/decrypt", methods=["POST"])
    def file_decrypt():
        return _handle_decrypt()


def _handle_encrypt() -> Any:
    email, err = _auth_email_from_request()
    if err:
        return err

    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    if len(password) < 4:
        return _page("Error", "<h1>Error</h1><p class='err'>Password must be at least 4 characters.</p>", 400)
    if password != password2:
        return _page("Error", "<h1>Error</h1><p class='err'>Passwords do not match.</p>", 400)

    f = request.files.get("file")
    if f is None or not f.filename:
        return _page("Error", "<h1>Error</h1><p class='err'>No file uploaded.</p>", 400)

    data = f.read()
    if not data:
        return _page("Error", "<h1>Error</h1><p class='err'>Empty file.</p>", 400)
    if len(data) > _max_deposit_bytes():
        return _page(
            "Error",
            f"<h1>Error</h1><p class='err'>File exceeds max size ({_max_deposit_bytes() // (1024*1024)} MiB).</p>",
            413,
        )

    ok, err = _require_access(email, len(data))
    if not ok:
        return err

    try:
        package = pack_encrypted_file(data, password, f.filename)
    except CryptoError as exc:
        return _page("Error", f"<h1>Error</h1><p class='err'>{html.escape(str(exc))}</p>", 400)
    except Exception as exc:  # noqa: BLE001
        return _page("Error", f"<h1>Error</h1><p class='err'>Encryption failed: {html.escape(str(exc))}</p>", 500)

    out_name = f"{os.path.basename(f.filename)}.hqh539enc"
    return send_file(
        io.BytesIO(package),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=out_name,
        max_age=0,
    )


def _handle_decrypt() -> Any:
    email, err = _auth_email_from_request()
    if err:
        return err

    password = request.form.get("password") or ""
    if not password:
        return _page("Error", "<h1>Error</h1><p class='err'>Password required.</p>", 400)

    f = request.files.get("file")
    if f is None or not f.filename:
        return _page("Error", "<h1>Error</h1><p class='err'>No package uploaded.</p>", 400)

    data = f.read()
    if not data:
        return _page("Error", "<h1>Error</h1><p class='err'>Empty file.</p>", 400)
    if len(data) > _max_deposit_bytes():
        return _page(
            "Error",
            f"<h1>Error</h1><p class='err'>File exceeds max size ({_max_deposit_bytes() // (1024*1024)} MiB).</p>",
            413,
        )

    ok, err = _require_access(email, len(data))
    if not ok:
        return err

    try:
        plaintext, orig_name = unpack_encrypted_file(data, password)
    except CryptoError as exc:
        return _page("Error", f"<h1>Error</h1><p class='err'>{html.escape(str(exc))}</p>", 400)
    except Exception as exc:  # noqa: BLE001
        return _page("Error", f"<h1>Error</h1><p class='err'>Decryption failed: {html.escape(str(exc))}</p>", 500)

    return send_file(
        io.BytesIO(plaintext),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=orig_name or "recovered.bin",
        max_age=0,
    )
