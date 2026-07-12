"""
HTTP file encrypt/decrypt (Flask).

Used by HQH-539-512-webhook so large deposits never touch the Streamlit websocket
(which was causing 502 + forced logout on Render).
"""
from __future__ import annotations

import io
import os
from typing import Any

from flask import Flask, Response, jsonify, request, send_file

from config import is_master_email
from crypto_hqh import CryptoError, pack_encrypted_file, unpack_encrypted_file
from database import credits_for_nbytes, deduct_credits, get_user, init_db, user_exists
from file_tokens import verify_file_token


def _max_deposit_bytes() -> int:
    raw = (os.getenv("HQH539_MAX_DEPOSIT_MB") or "2048").strip()
    try:
        mb = int(raw)
    except ValueError:
        mb = 2048
    return max(1, mb) * 1024 * 1024


def register_file_routes(app: Flask) -> None:
    """Attach /file/* routes to an existing Flask app."""

    app.config["MAX_CONTENT_LENGTH"] = _max_deposit_bytes() + 2 * 1024 * 1024

    @app.route("/file/health", methods=["GET"])
    def file_health():
        return jsonify({"status": "ok", "service": "hqh539-file", "max_mb": _max_deposit_bytes() // (1024 * 1024)})

    @app.route("/file/encrypt", methods=["POST"])
    def file_encrypt():
        return _handle_encrypt()

    @app.route("/file/decrypt", methods=["POST"])
    def file_decrypt():
        return _handle_decrypt()


def _auth_email() -> tuple[str | None, Response | None]:
    token = (request.form.get("token") or request.headers.get("X-HQH-Token") or "").strip()
    email = verify_file_token(token)
    if not email:
        return None, (jsonify({"error": "invalid or expired session token — log in again on the app"}), 401)
    return email, None


def _require_access(email: str, nbytes: int) -> tuple[bool, Response | None]:
    if is_master_email(email):
        return True, None
    if not user_exists(email):
        return False, (jsonify({"error": "account not found — register on the Hash Engine first"}), 403)
    user = get_user(email)
    if user and (user.get("subscription_active") or user.get("unlimited")):
        return True, None
    cost = credits_for_nbytes(nbytes)
    if not deduct_credits(email, cost):
        return False, (
            jsonify(
                {
                    "error": f"insufficient credits (need {cost} for {_fmt(nbytes)})",
                    "credits_needed": cost,
                }
            ),
            402,
        )
    return True, None


def _fmt(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _handle_encrypt() -> Any:
    email, err = _auth_email()
    if err:
        return err

    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    if len(password) < 4:
        return jsonify({"error": "password must be at least 4 characters"}), 400
    if password != password2:
        return jsonify({"error": "passwords do not match"}), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "no file uploaded"}), 400

    data = f.read()
    if not data:
        return jsonify({"error": "empty file"}), 400
    if len(data) > _max_deposit_bytes():
        return jsonify({"error": f"file exceeds max size ({_max_deposit_bytes() // (1024*1024)} MiB)"}), 413

    ok, err = _require_access(email, len(data))
    if not ok:
        return err

    try:
        package = pack_encrypted_file(data, password, f.filename)
    except CryptoError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"encryption failed: {exc}"}), 500

    out_name = f"{os.path.basename(f.filename)}.hqh539enc"
    return send_file(
        io.BytesIO(package),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=out_name,
        max_age=0,
    )


def _handle_decrypt() -> Any:
    email, err = _auth_email()
    if err:
        return err

    password = request.form.get("password") or ""
    if not password:
        return jsonify({"error": "password required"}), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "no package uploaded"}), 400

    data = f.read()
    if not data:
        return jsonify({"error": "empty file"}), 400
    if len(data) > _max_deposit_bytes():
        return jsonify({"error": f"file exceeds max size ({_max_deposit_bytes() // (1024*1024)} MiB)"}), 413

    ok, err = _require_access(email, len(data))
    if not ok:
        return err

    try:
        plaintext, orig_name = unpack_encrypted_file(data, password)
    except CryptoError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"decryption failed: {exc}"}), 500

    return send_file(
        io.BytesIO(plaintext),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=orig_name or "recovered.bin",
        max_age=0,
    )
