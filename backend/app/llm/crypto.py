"""AES-256-GCM at-rest encryption for provider API keys (S4/D18).

S3's ``auth.api_keys.key_hash`` is a one-way SHA-256 digest (verify-only). The
llm_router must instead *recover* the plaintext to call a third-party provider, so
``llm_providers.api_key_encrypted`` uses reversible AES-256-GCM: the stored blob is
``nonce:ciphertext`` (12-byte nonce hex + ":" + hex) and the master key never
touches the database. Decryption happens in-memory only, for the duration of a
call/test. Decrypt failure marks the provider failed — the router advances the
chain (never a 500). ``api_key_encrypted`` stays nullable; a row without a key is
valid.
"""

from __future__ import annotations

import os
from binascii import hexlify, unhexlify

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_ENV = "LLM_PROVIDER_MASTER_KEY"
_NONCE_BYTES = 12


class MasterKeyError(Exception):
    """LLM_PROVIDER_MASTER_KEY is unset or not a 32-byte value."""


class DecryptionError(Exception):
    """The stored blob could not be decrypted (wrong key or tampered blob)."""


def master_key() -> bytes:
    """Return the 32-byte AES-GCM master key from the environment."""
    raw = os.environ.get(MASTER_KEY_ENV)
    if raw is None:
        raise MasterKeyError(f"{MASTER_KEY_ENV} is not set")
    key = raw.encode("utf-8")
    if len(key) != 32:
        raise MasterKeyError(f"{MASTER_KEY_ENV} must be exactly 32 bytes, got {len(key)}")
    return key


def encrypt_provider_key(plaintext: str) -> str:
    """Encrypt a provider API key; returns the ``nonce:ciphertext`` blob (hex)."""
    if not plaintext:
        raise ValueError("cannot encrypt an empty key")
    key = master_key()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{hexlify(nonce).decode('ascii')}:{hexlify(ciphertext).decode('ascii')}"


def decrypt_provider_key(blob: str) -> str:
    """Decrypt an ``nonce:ciphertext`` blob back to the plaintext key."""
    key = master_key()
    nonce_hex, sep, ct_hex = blob.partition(":")
    if not sep or not nonce_hex or not ct_hex:
        raise DecryptionError("malformed api_key_encrypted blob")
    try:
        plaintext = AESGCM(key).decrypt(unhexlify(nonce_hex), unhexlify(ct_hex), None)
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("decryption failed (wrong master key or tampered blob)") from exc
    return plaintext.decode("utf-8")
