"""
HQH-539-512 file encrypt / decrypt UI.

Step machine (no st.form). File is written to disk as soon as Streamlit
delivers it — Continue never depends on the uploader still holding the file
on the same click (that race is why Continue always failed).
"""
from __future__ import annotations

import os
import traceback

import streamlit as st

from crypto_hqh import CryptoError, is_hqh539_package, pack_encrypted_file, unpack_encrypted_file
from database import credits_for_nbytes, deduct_credits, get_user
from deposit_store import blob_meta, clear_blob, load_blob, read_prefix, save_blob


def _max_deposit_bytes() -> int:
    raw = (os.getenv("HQH539_MAX_DEPOSIT_MB") or "2048").strip()
    try:
        mb = int(raw)
    except ValueError:
        mb = 2048
    return max(1, mb) * 1024 * 1024


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 ** 3):.2f} GiB"
    if n >= 1024 * 1024:
        return f"{n / (1024 ** 2):.2f} MiB"
    if n >= 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n} B"


def _reset_encrypt_flow() -> None:
    clear_blob(st.session_state, "enc_in")
    clear_blob(st.session_state, "enc_out")
    for k in (
        "enc_flow_step",
        "enc_pass_hold",
        "enc_package_msg",
        "enc_package_toll",
        "enc_pw_widget_nonce",
        "enc_upload_error",
        "enc_last_upload_id",
    ):
        st.session_state.pop(k, None)


def _reset_decrypt_flow() -> None:
    clear_blob(st.session_state, "dec_in")
    clear_blob(st.session_state, "dec_out")
    for k in (
        "dec_flow_step",
        "dec_pass_hold",
        "dec_toll",
        "dec_pw_widget_nonce",
        "dec_upload_error",
        "dec_last_upload_id",
    ):
        st.session_state.pop(k, None)


def _stage_upload(uploaded, kind: str, max_bytes: int) -> str | None:
    """
    Write uploaded file to disk. Returns None on success, or an error string.
    kind: 'enc_in' or 'dec_in'
    """
    try:
        data = uploaded.getvalue()
    except Exception as exc:  # noqa: BLE001
        return f"Could not read upload: {exc}"

    if not data:
        return "File is empty."
    if len(data) > max_bytes:
        return f"File is too large ({_fmt_size(len(data))}). Max is {_fmt_size(max_bytes)}."

    name = (getattr(uploaded, "name", None) or "deposit.bin").strip() or "deposit.bin"
    try:
        save_blob(st.session_state, kind, data, name)
    except Exception as exc:  # noqa: BLE001
        return f"Could not save file on server: {exc}\n{traceback.format_exc()[-400:]}"
    finally:
        del data
    return None


def _upload_fingerprint(uploaded) -> str:
    """Stable-ish id so we only re-stage when a new file is chosen."""
    name = getattr(uploaded, "name", "") or ""
    size = getattr(uploaded, "size", None)
    file_id = getattr(uploaded, "file_id", None)
    if file_id is not None:
        return f"id:{file_id}"
    return f"name:{name}|size:{size}"


def render_encrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Encrypt deposit")
    st.caption(
        "Hampton Qutrit Hash (HQH-539) KDF · SHA3-512 wrap · ChaCha20-Poly1305 · "
        f"limit {_fmt_size(_max_deposit_bytes())}"
    )

    step = st.session_state.get("enc_flow_step") or "upload"
    max_bytes = _max_deposit_bytes()

    # ─── STEP: upload ─────────────────────────────────────────────
    if step == "upload":
        st.markdown("### Step 1 of 3 — Choose file")
        st.write(
            "Pick a file. It is saved to the server **as soon as it appears** below. "
            "Then click **Continue** (Continue only checks that the save finished)."
        )

        if st.session_state.get("enc_upload_error"):
            st.error(st.session_state["enc_upload_error"])

        uploaded = st.file_uploader(
            "Deposit file",
            type=None,
            key="enc_flow_uploader_v4",
        )

        # CRITICAL FIX: stage on upload delivery, NOT on Continue click.
        # Streamlit often clears the uploader value on the same run as a button press.
        if uploaded is not None:
            fp = _upload_fingerprint(uploaded)
            if st.session_state.get("enc_last_upload_id") != fp or blob_meta(st.session_state, "enc_in") is None:
                err = _stage_upload(uploaded, "enc_in", max_bytes)
                if err:
                    st.session_state["enc_upload_error"] = err
                    clear_blob(st.session_state, "enc_in")
                    st.session_state.pop("enc_last_upload_id", None)
                else:
                    st.session_state.pop("enc_upload_error", None)
                    st.session_state["enc_last_upload_id"] = fp
                    clear_blob(st.session_state, "enc_out")
                    st.session_state.pop("enc_package_msg", None)
                    st.session_state.pop("enc_package_toll", None)

        staged = blob_meta(st.session_state, "enc_in")
        if staged:
            st.success(
                f"Saved on server: **{staged.get('name')}** · {_fmt_size(int(staged.get('size') or 0))}"
            )
        else:
            st.caption("No file staged yet — choose a file above.")

        c1, c2 = st.columns(2)
        with c1:
            # Enabled only when disk staging succeeded
            cont = st.button(
                "Continue →",
                type="primary",
                key="enc_flow_upload_go_v4",
                disabled=staged is None,
            )
        with c2:
            if st.button("Reset", key="enc_flow_upload_reset_v4"):
                _reset_encrypt_flow()
                st.rerun()

        if cont:
            if blob_meta(st.session_state, "enc_in") is None:
                st.error(
                    "No file on the server yet. Wait until you see "
                    "“Saved on server”, then click Continue again."
                )
            else:
                st.session_state["enc_flow_step"] = "passphrase"
                st.session_state["enc_pw_widget_nonce"] = 0
                st.session_state.pop("enc_upload_error", None)
                st.rerun()
        return

    meta = blob_meta(st.session_state, "enc_in")
    if meta is None:
        st.warning("No staged file — returning to upload.")
        st.session_state["enc_flow_step"] = "upload"
        st.rerun()
        return

    name = meta.get("name") or "deposit.bin"
    size = int(meta.get("size") or 0)
    cost = 0 if is_master else credits_for_nbytes(size)
    st.success(
        f"Staged: **{name}** ({_fmt_size(size)})"
        + ("" if is_master else f" · {cost} credit(s)")
    )

    # ─── STEP: passphrase ─────────────────────────────────────────
    if step == "passphrase":
        st.markdown("### Step 2 of 3 — Create encryption password")
        st.write("Type a password, then click **Save password**.")
        nonce = int(st.session_state.get("enc_pw_widget_nonce") or 0)
        pw = st.text_input(
            "Encryption password",
            type="password",
            key=f"enc_flow_pw1_{nonce}",
        )
        c1, c2 = st.columns(2)
        with c1:
            save = st.button("Save password →", type="primary", key="enc_flow_pw_save_v4")
        with c2:
            if st.button("← Different file", key="enc_flow_pw_back_v4"):
                _reset_encrypt_flow()
                st.rerun()

        if save:
            if not pw or len(pw) < 4:
                st.error("Password must be at least 4 characters.")
            else:
                st.session_state["enc_pass_hold"] = pw
                st.session_state["enc_flow_step"] = "confirm"
                st.session_state["enc_pw_widget_nonce"] = nonce + 1
                st.rerun()
        return

    # ─── STEP: confirm + encrypt ──────────────────────────────────
    if step == "confirm":
        st.markdown("### Step 3 of 3 — Confirm password & encrypt")
        st.write("Re-enter the same password, then click **Encrypt now**.")
        nonce = int(st.session_state.get("enc_pw_widget_nonce") or 0)
        pw2 = st.text_input(
            "Confirm encryption password",
            type="password",
            key=f"enc_flow_pw2_{nonce}",
        )
        c1, c2 = st.columns(2)
        with c1:
            do_enc = st.button("Encrypt now", type="primary", key="enc_flow_do_encrypt_v4")
        with c2:
            if st.button("← Re-enter password", key="enc_flow_confirm_back_v4"):
                st.session_state.pop("enc_pass_hold", None)
                st.session_state["enc_flow_step"] = "passphrase"
                st.session_state["enc_pw_widget_nonce"] = nonce + 1
                st.rerun()

        if do_enc:
            held = st.session_state.get("enc_pass_hold") or ""
            if not pw2:
                st.error("Enter the confirmation password.")
            elif pw2 != held:
                st.error("Passwords do not match. Go back and set the password again.")
            elif not is_master and not deduct_credits(email, cost):
                st.warning(f"Need {cost} credit(s) (or Pro / master access).")
            else:
                loaded = load_blob(st.session_state, "enc_in")
                if not loaded:
                    st.error("Staged file missing on server. Start over.")
                    _reset_encrypt_flow()
                else:
                    raw, dep_name = loaded
                    try:
                        package = pack_encrypted_file(raw, held, dep_name)
                        out_name = f"{dep_name}.hqh539enc"
                        save_blob(st.session_state, "enc_out", package, out_name)
                        st.session_state["enc_package_msg"] = (
                            f"Encrypted {_fmt_size(len(raw))} → {_fmt_size(len(package))} package."
                        )
                        if not is_master:
                            u2 = get_user(email)
                            if u2 and not u2.get("subscription_active"):
                                st.session_state["enc_package_toll"] = (
                                    f"Charged {cost} credit(s). Remaining: {u2.get('credits', 0)}"
                                )
                        st.session_state.pop("enc_pass_hold", None)
                        st.session_state["enc_flow_step"] = "done"
                        del raw, package
                        st.rerun()
                    except CryptoError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Encryption failed: {exc}")
        return

    # ─── STEP: done ───────────────────────────────────────────────
    if step == "done":
        st.markdown("### Encryption complete")
        st.success(st.session_state.get("enc_package_msg", "Package ready."))
        if st.session_state.get("enc_package_toll"):
            st.caption(st.session_state["enc_package_toll"])

        out = load_blob(st.session_state, "enc_out")
        if out is None:
            st.error("Output package missing. Start over.")
        else:
            package, out_name = out
            st.download_button(
                label=f"Download {out_name}",
                data=package,
                file_name=out_name,
                mime="application/octet-stream",
                type="primary",
                key="enc_flow_download_v4",
            )

        if st.button("Encrypt another file", key="enc_flow_again_v4"):
            _reset_encrypt_flow()
            st.rerun()
        return

    st.session_state["enc_flow_step"] = "upload"
    st.rerun()


def render_decrypt_portal(email: str, *, is_master: bool) -> None:
    st.subheader("Decrypt package")
    st.caption("Upload a `.hqh539enc` package and recover the original file.")

    step = st.session_state.get("dec_flow_step") or "upload"
    max_bytes = _max_deposit_bytes()

    if step == "upload":
        st.markdown("### Step 1 of 2 — Choose package")
        if st.session_state.get("dec_upload_error"):
            st.error(st.session_state["dec_upload_error"])

        uploaded = st.file_uploader(
            "Encrypted package",
            type=None,
            key="dec_flow_uploader_v4",
        )

        if uploaded is not None:
            fp = _upload_fingerprint(uploaded)
            if st.session_state.get("dec_last_upload_id") != fp or blob_meta(st.session_state, "dec_in") is None:
                err = _stage_upload(uploaded, "dec_in", max_bytes)
                if err:
                    st.session_state["dec_upload_error"] = err
                    clear_blob(st.session_state, "dec_in")
                    st.session_state.pop("dec_last_upload_id", None)
                else:
                    st.session_state.pop("dec_upload_error", None)
                    st.session_state["dec_last_upload_id"] = fp
                    clear_blob(st.session_state, "dec_out")
                    st.session_state.pop("dec_toll", None)

        staged = blob_meta(st.session_state, "dec_in")
        if staged:
            st.success(
                f"Saved on server: **{staged.get('name')}** · {_fmt_size(int(staged.get('size') or 0))}"
            )
        else:
            st.caption("No package staged yet.")

        c1, c2 = st.columns(2)
        with c1:
            cont = st.button(
                "Continue →",
                type="primary",
                key="dec_flow_upload_go_v4",
                disabled=staged is None,
            )
        with c2:
            if st.button("Reset", key="dec_flow_upload_reset_v4"):
                _reset_decrypt_flow()
                st.rerun()

        if cont:
            if blob_meta(st.session_state, "dec_in") is None:
                st.error("No package on the server yet. Wait for “Saved on server”, then Continue.")
            else:
                st.session_state["dec_flow_step"] = "password"
                st.session_state["dec_pw_widget_nonce"] = 0
                st.rerun()
        return

    meta = blob_meta(st.session_state, "dec_in")
    if meta is None:
        st.session_state["dec_flow_step"] = "upload"
        st.rerun()
        return

    name = meta.get("name") or "package.hqh539enc"
    size = int(meta.get("size") or 0)
    cost = 0 if is_master else credits_for_nbytes(size)
    st.success(
        f"Staged: **{name}** ({_fmt_size(size)})"
        + ("" if is_master else f" · {cost} credit(s)")
    )

    prefix = read_prefix(st.session_state, "dec_in", 8)
    if prefix is not None and not is_hqh539_package(prefix):
        st.warning("File does not show HQH-539-512 magic header — decrypt may still work if intact.")

    if step == "password":
        st.markdown("### Step 2 of 2 — Password & decrypt")
        nonce = int(st.session_state.get("dec_pw_widget_nonce") or 0)
        pw = st.text_input(
            "Decryption password",
            type="password",
            key=f"dec_flow_pw_{nonce}",
        )
        c1, c2 = st.columns(2)
        with c1:
            do_dec = st.button("Decrypt now", type="primary", key="dec_flow_do_v4")
        with c2:
            if st.button("← Different package", key="dec_flow_back_v4"):
                _reset_decrypt_flow()
                st.rerun()

        if do_dec:
            if not pw:
                st.error("Enter the password.")
            elif not is_master and not deduct_credits(email, cost):
                st.warning(f"Need {cost} credit(s).")
            else:
                loaded = load_blob(st.session_state, "dec_in")
                if not loaded:
                    st.error("Staged package missing.")
                    _reset_decrypt_flow()
                else:
                    pkg, _ = loaded
                    try:
                        plaintext, orig = unpack_encrypted_file(pkg, pw)
                        save_blob(st.session_state, "dec_out", plaintext, orig)
                        if not is_master:
                            u2 = get_user(email)
                            if u2 and not u2.get("subscription_active"):
                                st.session_state["dec_toll"] = (
                                    f"Charged {cost} credit(s). Remaining: {u2.get('credits', 0)}"
                                )
                        st.session_state["dec_flow_step"] = "done"
                        del pkg, plaintext
                        st.rerun()
                    except CryptoError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Decryption failed: {exc}")
        return

    if step == "done":
        st.markdown("### Decryption complete")
        out = load_blob(st.session_state, "dec_out")
        if out is None:
            st.error("Output missing.")
        else:
            pt, orig = out
            st.success(f"Recovered **{orig}** ({_fmt_size(len(pt))}).")
            if st.session_state.get("dec_toll"):
                st.caption(st.session_state["dec_toll"])
            st.download_button(
                label=f"Download {orig}",
                data=pt,
                file_name=orig,
                mime="application/octet-stream",
                type="primary",
                key="dec_flow_download_v4",
            )
        if st.button("Decrypt another package", key="dec_flow_again_v4"):
            _reset_decrypt_flow()
            st.rerun()
        return

    st.session_state["dec_flow_step"] = "upload"
    st.rerun()
