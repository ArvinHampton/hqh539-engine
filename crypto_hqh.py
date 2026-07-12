"""
HQH-539-512 keyed encryption for file deposits.

Key material is derived with Hampton Qutrit Hash (HQH): SHA3-512 wrap around
539 T3 steps (18+521), used as a KDF, then ChaCha20-Poly1305 AEAD.
"""
from __future__ import annotations

import os
import struct
from typing import Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from hqh539 import hqh_539

# Binary package magic / version
MAGIC = b"HQH539E1"
VERSION = 1
SALT_LEN = 32
NONCE_LEN = 12
KEY_LEN = 32
KDF_INFO = b"HQH539-FILE-ENC-v1"
MAX_NAME_LEN = 512


class CryptoError(Exception):
    """User-facing crypto failure."""


def _as_bytes(value: Union[str, bytes]) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def hqh539_kdf(
    secret: Union[str, bytes],
    salt: bytes,
    info: bytes = KDF_INFO,
    length: int = KEY_LEN + NONCE_LEN,
) -> bytes:
    """
    Expand password + salt into `length` bytes via iterated HQH-539 digests.

    counter || secret || salt || info  →  hqh_539 hex  →  bytes, concatenated.
    """
    secret_b = _as_bytes(secret)
    if not secret_b:
        raise CryptoError("Password/secret must not be empty")
    if not salt:
        raise CryptoError("Salt must not be empty")

    out = bytearray()
    counter = 0
    while len(out) < length:
        block_in = (
            counter.to_bytes(4, "big")
            + secret_b
            + salt
            + info
        )
        digest_hex = hqh_539(block_in, salt=salt)
        out.extend(bytes.fromhex(digest_hex))
        counter += 1
        if counter > 64:
            raise CryptoError("KDF expansion failed")
    return bytes(out[:length])


def encrypt_bytes(
    plaintext: bytes,
    password: Union[str, bytes],
    *,
    associated_data: bytes | None = None,
    salt: bytes | None = None,
) -> tuple[bytes, bytes, bytes]:
    """
    Encrypt plaintext. Returns (salt, ciphertext_with_tag, nonce_used_for_debug).

    Nonce is derived from the KDF (not stored separately); salt is required to decrypt.
    """
    if salt is None:
        salt = os.urandom(SALT_LEN)
    if len(salt) != SALT_LEN:
        raise CryptoError(f"Salt must be {SALT_LEN} bytes")

    km = hqh539_kdf(password, salt, length=KEY_LEN + NONCE_LEN)
    key, nonce = km[:KEY_LEN], km[KEY_LEN : KEY_LEN + NONCE_LEN]
    aad = associated_data or b""
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)
    return salt, ct, nonce


def decrypt_bytes(
    ciphertext: bytes,
    password: Union[str, bytes],
    salt: bytes,
    *,
    associated_data: bytes | None = None,
) -> bytes:
    """Decrypt ciphertext produced by encrypt_bytes."""
    if len(salt) != SALT_LEN:
        raise CryptoError(f"Salt must be {SALT_LEN} bytes")
    km = hqh539_kdf(password, salt, length=KEY_LEN + NONCE_LEN)
    key, nonce = km[:KEY_LEN], km[KEY_LEN : KEY_LEN + NONCE_LEN]
    aad = associated_data or b""
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise CryptoError("Decryption failed — wrong password or corrupted file") from exc


def pack_encrypted_file(
    plaintext: bytes,
    password: Union[str, bytes],
    original_name: str,
) -> bytes:
    """
    Build a self-contained .hqh539enc package:

        MAGIC (8) | VERSION (1) | salt (32) | name_len u16be | name utf-8 | ciphertext
    """
    name = (original_name or "deposit.bin").replace("\\", "/").split("/")[-1]
    name_b = name.encode("utf-8")
    if len(name_b) > MAX_NAME_LEN:
        name_b = name_b[:MAX_NAME_LEN]
        name = name_b.decode("utf-8", errors="ignore")

    # AAD binds ciphertext to original filename (detected on decrypt)
    salt, ct, _nonce = encrypt_bytes(plaintext, password, associated_data=name_b)
    return MAGIC + bytes([VERSION]) + salt + struct.pack(">H", len(name_b)) + name_b + ct


def unpack_encrypted_file(
    package: bytes,
    password: Union[str, bytes],
) -> tuple[bytes, str]:
    """
    Parse .hqh539enc package and decrypt.
    Returns (plaintext, original_filename).
    """
    min_len = 8 + 1 + SALT_LEN + 2
    if len(package) < min_len + 16:
        raise CryptoError("File is too small to be a valid HQH-539 package")

    if package[:8] != MAGIC:
        raise CryptoError("Not an HQH-539 encrypted package (bad magic)")

    version = package[8]
    if version != VERSION:
        raise CryptoError(f"Unsupported package version: {version}")

    salt = package[9 : 9 + SALT_LEN]
    name_len = struct.unpack(">H", package[9 + SALT_LEN : 9 + SALT_LEN + 2])[0]
    name_start = 9 + SALT_LEN + 2
    name_end = name_start + name_len
    if name_len > MAX_NAME_LEN or name_end > len(package):
        raise CryptoError("Corrupt package header (filename)")

    name_b = package[name_start:name_end]
    ct = package[name_end:]
    if not ct:
        raise CryptoError("Package has empty ciphertext")

    plaintext = decrypt_bytes(ct, password, salt, associated_data=name_b)
    original_name = name_b.decode("utf-8", errors="replace") or "recovered.bin"
    return plaintext, original_name


def is_hqh539_package(data: bytes) -> bool:
    return len(data) >= 8 and data[:8] == MAGIC
