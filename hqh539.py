"""
Hampton Qutrit Hash (HQH) — canonical reference implementation.

HQH-539-512: SHA3-512 seed → 539 T3 (qutrit/ternary) steps as 18 + 521 → SHA3-512 finalize.
Produces a 512-bit (128 hex char) digest.
"""
from __future__ import annotations

import hashlib
from typing import Union

STEPS = 539
# Structure: 18 variable/user rounds + 521 fixed suffix = 539 total T3 applications
PREFIX_ROUNDS = 18
SUFFIX_ROUNDS = STEPS - PREFIX_ROUNDS  # 521
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


def hqh_539(
    message: Union[str, bytes],
    salt: Union[str, bytes] = b"",
    rounds: int = PREFIX_ROUNDS,
) -> str:
    """
    Hampton Qutrit Hash (HQH-539-512).

    1. Seed: SHA3-512(message || salt) → integer state  
    2. Collapse: exactly 539 T3 steps, structured as `rounds` (default 18) + remaining 521  
    3. Finalize: SHA3-512(fingerprint_bytes || salt) → 128 hex chars (512-bit)
    """
    if isinstance(message, str):
        message = message.encode("utf-8")
    salt_bytes = _coerce_salt(salt)
    data = message + salt_bytes

    # SHA3-512 wrap (seed)
    m = int.from_bytes(hashlib.sha3_512(data).digest(), "big")

    # 539-step qutrit map: 18 + 521 (when rounds=18)
    for _ in range(rounds):
        m = T3(m)

    remaining = STEPS - rounds
    for _ in range(remaining):
        m = T3(m)

    fingerprint = m
    # SHA3-512 wrap (finalize) → 512-bit digest
    digest = hashlib.sha3_512(
        fingerprint.to_bytes((fingerprint.bit_length() + 7) // 8, "big") + salt_bytes + DOMAIN_SEP
    ).hexdigest()
    return digest


def hqh_539_512(message: Union[str, bytes], salt: Union[str, bytes] = b"") -> str:
    """Alias: full HQH-539 with SHA3-512 wrap (18 + 521 structure)."""
    return hqh_539(message, salt, rounds=PREFIX_ROUNDS)


def hqh_539_256(message: Union[str, bytes], salt: Union[str, bytes] = b"") -> str:
    return hqh_539_512(message, salt)[:64]


hqh539 = hqh_539

__all__ = [
    "STEPS",
    "PREFIX_ROUNDS",
    "SUFFIX_ROUNDS",
    "DOMAIN_SEP",
    "T3",
    "ternary_step",
    "iterate_n_steps",
    "hqh_539",
    "hqh_539_512",
    "hqh_539_256",
    "hqh539",
]