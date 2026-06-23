"""SQLite persistence for HQH-539 users and billing state."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from config import data_dir

DB_FILENAME = "hqh539.db"


def db_path() -> Path:
    root = Path(data_dir())
    root.mkdir(parents=True, exist_ok=True)
    return root / DB_FILENAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                credits INTEGER DEFAULT 0,
                subscription_active INTEGER DEFAULT 0,
                subscription_expires TEXT
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(email: str, password: str) -> bool:
    email = email.strip().lower()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (email, password_hash, credits) VALUES (?, ?, 0)",
            (email, hash_password(password)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def verify_user(email: str, password: str) -> bool:
    email = email.strip().lower()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
        row = c.fetchone()
        return bool(row and row["password_hash"] == hash_password(password))
    finally:
        conn.close()


def get_user(email: str) -> dict | None:
    email = email.strip().lower()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT credits, subscription_active, subscription_expires FROM users WHERE email = ?",
            (email,),
        )
        row = c.fetchone()
        if not row:
            return None

        expires = row["subscription_expires"]
        active = bool(row["subscription_active"])
        if active and expires:
            if datetime.fromisoformat(expires) < datetime.now():
                deactivate_subscription(email)
                active = False

        return {
            "credits": int(row["credits"]),
            "subscription_active": active,
            "subscription_expires": expires,
        }
    finally:
        conn.close()


def add_credits(email: str, amount: int) -> None:
    if amount <= 0:
        return
    email = email.strip().lower()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET credits = credits + ? WHERE email = ?",
            (amount, email),
        )
        conn.commit()
    finally:
        conn.close()


def deduct_credit(email: str) -> bool:
    email = email.strip().lower()
    user = get_user(email)
    if not user:
        return False
    if user["subscription_active"]:
        return True
    if user["credits"] <= 0:
        return False

    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET credits = credits - 1 WHERE email = ? AND credits > 0",
            (email,),
        )
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def activate_subscription(email: str, days: int = 30) -> None:
    email = email.strip().lower()
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            """UPDATE users
               SET subscription_active = 1, subscription_expires = ?
               WHERE email = ?""",
            (expires, email),
        )
        conn.commit()
    finally:
        conn.close()


def deactivate_subscription(email: str) -> None:
    email = email.strip().lower()
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE users SET subscription_active = 0 WHERE email = ?",
            (email,),
        )
        conn.commit()
    finally:
        conn.close()