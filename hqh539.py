"""HQH-539 Resonant Hash Engine — canonical reference implementation."""
from __future__ import annotations

import hashlib
from typing import Union

STEPS = 539
DOMAIN_SEP = b""


def T3(n: int) -> int:
    """Single step of the balanced ternary Syracuse map."""
    r = n % 3
    if r == 0:
        return n // 3
    if r == 1:
        return (4 * n + 2) // 3
    return (2 * n + 1) // 3


def ternary_step(n: int) -> int:
    """Alias for visualization and legacy callers."""
    return T3(n)


def iterate_n_steps(n: int, steps: int = STEPS) -> int:
    """Apply T3 exactly `steps` times."""
    state = n
    for _ in range(steps):
        state = T3(state)
    return state


def _coerce_salt(salt: Union[str, bytes]) -> bytes:
    if isinstance(salt, str):
        return salt.encode("utf-8")
    return salt


def hqh_539(message: Union[str, bytes], salt: Union[str, bytes] = b"", rounds: int = 18) -> str:
    """
    HQH-539 reference implementation.

    SHA3-512 seed → 539 T3 steps (18 user prefix + 521 fixed suffix) → SHA3-512 finalization.
    """
    if isinstance(message, str):
        message = message.encode("utf-8")
    salt_bytes = _coerce_salt(salt)
    data = message + salt_bytes

    m = int.from_bytes(hashlib.sha3_512(data).digest(), "big")

    for _ in range(rounds):
        m = T3(m)

    remaining = STEPS - rounds
    for _ in range(remaining):
        m = T3(m)

    fingerprint = m
    digest = hashlib.sha3_512(
        fingerprint.to_bytes((fingerprint.bit_length() + 7) // 8, "big") + salt_bytes + DOMAIN_SEP
    ).hexdigest()
    return digest


def hqh_539_512(message: Union[str, bytes], salt: Union[str, bytes] = b"") -> str:
    return hqh_539(message, salt, rounds=18)


def hqh_539_256(message: Union[str, bytes], salt: Union[str, bytes] = b"") -> str:
    return hqh_539_512(message, salt)[:64]


hqh539 = hqh_539

__all__ = [
    "STEPS",
    "DOMAIN_SEP",
    "T3",
    "ternary_step",
    "iterate_n_steps",
    "hqh_539",
    "hqh_539_512",
    "hqh_539_256",
    "hqh539",
]