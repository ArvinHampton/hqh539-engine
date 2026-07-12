"""
Disk-backed file deposits for Streamlit.

Keeping multi-MB blobs in st.session_state forces Streamlit to re-serialize them
on every websocket interaction, which drops the session (login kick) on Render.
We store only a small path/token in session_state and the bytes on local disk.
"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from config import data_dir


def _root() -> Path:
    base = Path(os.getenv("HQH539_DATA_DIR") or data_dir() or "/tmp")
    root = base / "hqh_deposits"
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_session_id(session_state) -> str:
    sid = session_state.get("_deposit_sid")
    if not sid:
        sid = uuid.uuid4().hex
        session_state["_deposit_sid"] = sid
    return sid


def session_dir(session_state) -> Path:
    d = _root() / ensure_session_id(session_state)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_blob(session_state, kind: str, data: bytes, name: str) -> dict:
    """
    Write bytes to disk. Returns metadata (no payload) for session_state.
    kind: 'enc_in' | 'enc_out' | 'dec_in' | 'dec_out'
    """
    d = session_dir(session_state)
    safe_kind = "".join(c if c.isalnum() or c in "-_" else "_" for c in kind)[:32]
    path = d / f"{safe_kind}.bin"
    path.write_bytes(data)
    meta = {
        "path": str(path),
        "name": name,
        "size": len(data),
    }
    session_state[f"blob_meta_{kind}"] = meta
    return meta


def load_blob(session_state, kind: str) -> tuple[bytes, str] | None:
    meta = session_state.get(f"blob_meta_{kind}")
    if not meta:
        return None
    path = Path(meta["path"])
    if not path.is_file():
        session_state.pop(f"blob_meta_{kind}", None)
        return None
    return path.read_bytes(), meta.get("name") or "file.bin"


def clear_blob(session_state, kind: str) -> None:
    meta = session_state.pop(f"blob_meta_{kind}", None)
    if meta and meta.get("path"):
        try:
            Path(meta["path"]).unlink(missing_ok=True)
        except OSError:
            pass


def clear_session_deposits(session_state) -> None:
    sid = session_state.get("_deposit_sid")
    for key in list(session_state.keys()):
        if str(key).startswith("blob_meta_"):
            clear_blob(session_state, str(key).replace("blob_meta_", "", 1))
    if sid:
        try:
            shutil.rmtree(_root() / sid, ignore_errors=True)
        except OSError:
            pass
