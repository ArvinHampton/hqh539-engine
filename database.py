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

# Credit tolling: 1 credit per this many input bytes (rounded up), minimum 1.
# Override with env HQH539_BYTES_PER_CREDIT (e.g. 65536 = 64 KiB per credit).
DEFAULT_BYTES_PER_CREDIT = 64 * 1024

CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    credits INTEGER DEFAULT 0,
    subscription_active INTEGER DEFAULT 0,
    subscription_expires TEXT
)
"""

CREATE_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS credit_ledger (
    session_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    credits INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
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

        url = _database_url()
        # Render external needs SSL; internal hostnames usually work without.
        kwargs: dict[str, Any] = {"cursor_factory": RealDictCursor}
        if url and "render.com" in url and "sslmode" not in url:
            kwargs["sslmode"] = "require"
        conn = psycopg2.connect(url, **kwargs)
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
        c.execute(_q(CREATE_LEDGER_SQL))
    # One-shot: CLEAR_ACCOUNT_EMAIL=user@example.com deletes that row so they can re-register.
    # Remove the env var after deploy (does not grant credits or set passwords).
    clear_email = (os.getenv("CLEAR_ACCOUNT_EMAIL") or "").strip().lower()
    if clear_email:
        if delete_user(clear_email):
            print(f"CLEAR_ACCOUNT_EMAIL: deleted user {clear_email!r}")
        else:
            print(f"CLEAR_ACCOUNT_EMAIL: no user row for {clear_email!r}")


def user_exists(email: str) -> bool:
    email = email.strip().lower()
    if not email:
        return False
    with _connect() as conn:
        c = conn.cursor()
        c.execute(_q("SELECT 1 FROM users WHERE email = ?"), (email,))
        return c.fetchone() is not None


def delete_user(email: str) -> bool:
    """Remove a user row (and their ledger rows). Returns True if a user was deleted."""
    email = email.strip().lower()
    if not email:
        return False
    with _connect() as conn:
        c = conn.cursor()
        c.execute(_q("DELETE FROM credit_ledger WHERE email = ?"), (email,))
        c.execute(_q("DELETE FROM users WHERE email = ?"), (email,))
        return c.rowcount > 0


def set_password(email: str, password: str) -> bool:
    """Update password for an existing user. Returns False if user missing."""
    email = email.strip().lower()
    if not email or not password:
        return False
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("UPDATE users SET password_hash = ? WHERE email = ?"),
            (hash_password(password), email),
        )
        return c.rowcount > 0


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
            _q(
                "SELECT credits, subscription_active, subscription_expires FROM users WHERE email = ?"
            ),
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


def bytes_per_credit() -> int:
    raw = os.getenv("HQH539_BYTES_PER_CREDIT", "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return n
        except ValueError:
            pass
    return DEFAULT_BYTES_PER_CREDIT


def credits_for_payload(data: str | bytes) -> int:
    """Toll: ceil(payload_bytes / BYTES_PER_CREDIT), minimum 1 credit."""
    if isinstance(data, str):
        n = len(data.encode("utf-8"))
    else:
        n = len(data)
    unit = bytes_per_credit()
    return max(1, (n + unit - 1) // unit)


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
            print(
                f"add_credits: no user row for {email!r} "
                f"(register in the Hash Engine with this email first)"
            )
        return updated


def deduct_credits(email: str, amount: int) -> bool:
    """Deduct `amount` credits (or allow free if Pro). Returns False if insufficient."""
    if amount <= 0:
        return True
    email = email.strip().lower()
    user = get_user(email)
    if not user:
        return False
    if user["subscription_active"]:
        return True
    if user["credits"] < amount:
        return False

    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q(
                "UPDATE users SET credits = credits - ? "
                "WHERE email = ? AND credits >= ?"
            ),
            (amount, email, amount),
        )
        return c.rowcount > 0


def deduct_credit(email: str) -> bool:
    """Back-compat: deduct one credit."""
    return deduct_credits(email, 1)


def grant_checkout_once(
    session_id: str,
    email: str,
    credits: int,
    kind: str = "credits",
) -> tuple[bool, str]:
    """
    Idempotently grant credits (or mark subscription) for a Stripe checkout session.
    Returns (applied_now, message).
    """
    if not session_id or not email:
        return False, "missing session_id or email"
    email = email.strip().lower()
    session_id = session_id.strip()

    with _connect() as conn:
        c = conn.cursor()
        c.execute(_q("SELECT session_id FROM credit_ledger WHERE session_id = ?"), (session_id,))
        if c.fetchone():
            return False, "already_applied"

        # Ensure ledger insert happens first for idempotency under concurrency
        try:
            c.execute(
                _q(
                    "INSERT INTO credit_ledger (session_id, email, credits, kind, created_at) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (session_id, email, int(credits), kind, datetime.utcnow().isoformat()),
            )
        except Exception as exc:
            if _using_postgres():
                import psycopg2

                if isinstance(exc, psycopg2.IntegrityError):
                    return False, "already_applied"
            elif isinstance(exc, sqlite3.IntegrityError):
                return False, "already_applied"
            raise

        if kind == "subscription":
            expires = (datetime.now() + timedelta(days=30)).isoformat()
            c.execute(
                _q(
                    """UPDATE users
                       SET subscription_active = 1, subscription_expires = ?
                       WHERE email = ?"""
                ),
                (expires, email),
            )
            if c.rowcount == 0:
                print(f"grant_checkout_once: no user for subscription {email!r}")
                c.execute(_q("DELETE FROM credit_ledger WHERE session_id = ?"), (session_id,))
                return False, "user_missing"
            return True, "subscription_activated"

        c.execute(
            _q("UPDATE users SET credits = credits + ? WHERE email = ?"),
            (int(credits), email),
        )
        if c.rowcount == 0:
            print(f"grant_checkout_once: no user for credits {email!r}")
            # Roll back ledger row so a later retry (after register) can succeed
            c.execute(_q("DELETE FROM credit_ledger WHERE session_id = ?"), (session_id,))
            return False, "user_missing"
        return True, f"credited_{credits}"


def activate_subscription(email: str, days: int = 30) -> bool:
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
        return c.rowcount > 0


def deactivate_subscription(email: str) -> None:
    email = email.strip().lower()
    with _connect() as conn:
        c = conn.cursor()
        c.execute(
            _q("UPDATE users SET subscription_active = 0 WHERE email = ?"),
            (email,),
        )
