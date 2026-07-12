"""User persistence for HQH-539 — SQLite locally or PostgreSQL when DATABASE_URL is set."""
from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from config import data_dir, get as config_get

DB_FILENAME = "hqh539.db"

CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    credits INTEGER DEFAULT 0,
    subscription_active INTEGER DEFAULT 0,
    subscription_expires TEXT
)
"""


def _database_url() -> str | None:
    return config_get("DATABASE_URL") or os.getenv("DATABASE_URL")


def _using_postgres() -> bool:
    url = _database_url()
    return bool(url and url.startswith(("postgres://", "postgresql://")))


def db_path() -> Path:
    root = Path(data_dir())
    root.mkdir(parents=True, exist_ok=True)
    return root / DB_FILENAME


@contextmanager
def _connect() -> Iterator[Any]:
    if _using_postgres():
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(_database_url(), cursor_factory=RealDictCursor)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(db_path(), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _q(sql: str) -> str:
    return sql.replace("?", "%s") if _using_postgres() else sql


def init_db() -> None:
    with _connect() as conn:
        c = conn.cursor()
        c.execute(_q(CREATE_USERS_SQL))


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_user(email: str, password: str) -> bool:
    email = email.strip().lower()
    try:
        with _connect() as conn:
            c = conn.cursor()
            c.execute(
                _q("INSERT INTO users (email, password_hash, credits) VALUES (?, ?, 0)"),
                (email, hash_password(password)),
            )
        return True
    except Exception as exc:
        if _using_postgres():
            import psycopg2

            if isinstance(exc, psycopg2.IntegrityError):
                return False
        elif isinstance(exc, sqlite3.IntegrityError):
            return False
        raise


def verify_user(email: str, password: str) -> bool:
    email = email.strip().lower()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(_q("SELECT password_hash FROM users WHERE email = ?"), (email,))
        row = c.fetchone()
        if not row:
            return False
        return row["password_hash"] == hash_password(password)


def get_user(email: str) -> dict | None:
    email = email.strip().lower()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("SELECT credits, subscription_active, subscription_expires FROM users WHERE email = ?"),
            (email,),
        )
        row = c.fetchone()
        if not row:
            return None

        credits = int(row["credits"])
        active = bool(row["subscription_active"])
        expires = row["subscription_expires"]

        if active and expires:
            if datetime.fromisoformat(expires) < datetime.now():
                deactivate_subscription(email)
                active = False

        return {
            "credits": credits,
            "subscription_active": active,
            "subscription_expires": expires,
        }


def add_credits(email: str, amount: int) -> bool:
    """Add credits for an existing user. Returns True if a row was updated."""
    if amount <= 0:
        return False
    email = email.strip().lower()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("UPDATE users SET credits = credits + ? WHERE email = ?"),
            (amount, email),
        )
        updated = c.rowcount > 0
        if not updated:
            # Webhook and Streamlit must share DATABASE_URL; user must already exist.
            print(
                f"add_credits: no user row for {email!r} "
                f"(credits not applied — register on the app first, or check email match)"
            )
        return updated


def deduct_credit(email: str) -> bool:
    email = email.strip().lower()
    user = get_user(email)
    if not user:
        return False
    if user["subscription_active"]:
        return True
    if user["credits"] <= 0:
        return False

    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("UPDATE users SET credits = credits - 1 WHERE email = ? AND credits > 0"),
            (email,),
        )
        return c.rowcount > 0


def activate_subscription(email: str, days: int = 30) -> None:
    email = email.strip().lower()
    expires = (datetime.now() + timedelta(days=days)).isoformat()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q(
                """UPDATE users
                   SET subscription_active = 1, subscription_expires = ?
                   WHERE email = ?"""
            ),
            (expires, email),
        )


def deactivate_subscription(email: str) -> None:
    email = email.strip().lower()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("UPDATE users SET subscription_active = 0 WHERE email = ?"),
            (email,),
        )