"""Password hashing, JWT issuance/verification, and envelope encryption for
biometric embeddings.

Envelope encryption pattern (NON-NEGOTIABLE #2): every embedding is encrypted
with a fresh, random per-record Data Encryption Key (DEK). The DEK itself is
then encrypted ("wrapped") with a long-lived master key read from
EMBEDDING_ENCRYPTION_KEY. Both the wrapped DEK and the encrypted payload are
stored. This means rotating the master key only requires re-wrapping DEKs,
never re-encrypting embeddings, and a leaked master key alone (without the
per-record wrapped DEK) discloses nothing.

See docs/DECISIONS.md for why the plaintext `embedding` pgvector column
still exists alongside `embedding_encrypted`: pgvector's `<=>` cosine
operator has to run in SQL, so the server needs plaintext floats to search.
The encrypted column is the durable, at-rest biometric artifact; the plaintext
column is treated as a derived search index that must live on an
encrypted-at-rest volume in production (see docs/RUNBOOK.md).
"""
from __future__ import annotations

import base64
import os
import struct
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from cryptography.fernet import Fernet
import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()

# bcrypt only looks at the first 72 bytes; longer passwords are rejected by
# the password policy (services/passwords.py) instead of silently truncated.
_BCRYPT_MAX = 72
# A real-looking hash to verify against when the user does not exist, so a
# wrong email and a wrong password take the same time (no user enumeration).
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12)).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:_BCRYPT_MAX], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time: always runs one bcrypt check, even for unknown users.
    Works with hashes made by the old passlib code ($2b$ format)."""
    target = password_hash or _DUMMY_HASH
    try:
        ok = bcrypt.checkpw(password.encode()[:_BCRYPT_MAX], target.encode())
    except ValueError:
        return False
    return ok and password_hash is not None


ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


def _alg() -> str:
    alg = settings.jwt_algorithm.upper()
    if alg not in ALLOWED_JWT_ALGORITHMS:  # never "none", never asymmetric confusion
        raise RuntimeError(f"Unsupported JWT_ALGORITHM {settings.jwt_algorithm!r}")
    return alg


def create_access_token(
    subject: str, role: str, expires_minutes: int | None = None, token_version: int = 0,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_minutes or settings.jwt_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire, "iat": now, "tv": token_version}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=_alg())


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[_alg()], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError as exc:  # pragma: no cover - exercised via API layer
        raise ValueError("invalid or expired token") from exc


class _MasterKey:
    """Lazily-loaded Fernet wrapper around EMBEDDING_ENCRYPTION_KEY."""

    _fernet: Fernet | None = None

    @classmethod
    def get(cls) -> Fernet:
        if cls._fernet is None:
            key = settings.embedding_encryption_key.encode()
            cls._fernet = Fernet(key)
        return cls._fernet


def encrypt_embedding(vector: list[float]) -> bytes:
    """Envelope-encrypt a 512-d embedding.

    Layout: b"FE1" | 4-byte big-endian wrapped-DEK length | wrapped DEK |
    Fernet(DEK).encrypt(raw float32 bytes)
    """
    dek = Fernet.generate_key()
    data_fernet = Fernet(dek)
    raw = np.asarray(vector, dtype=np.float32).tobytes()
    ciphertext = data_fernet.encrypt(raw)
    wrapped_dek = _MasterKey.get().encrypt(dek)
    header = b"FE1" + struct.pack(">I", len(wrapped_dek))
    return header + wrapped_dek + ciphertext


def decrypt_embedding(blob: bytes) -> list[float]:
    if blob[:3] != b"FE1":
        raise ValueError("unrecognized embedding envelope format")
    (wrapped_len,) = struct.unpack(">I", blob[3:7])
    wrapped_dek = blob[7 : 7 + wrapped_len]
    ciphertext = blob[7 + wrapped_len :]
    dek = _MasterKey.get().decrypt(wrapped_dek)
    raw = Fernet(dek).decrypt(ciphertext)
    return np.frombuffer(raw, dtype=np.float32).tolist()


def generate_master_key() -> str:  # pragma: no cover - operator convenience
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


# --- small secrets stored in the database (API keys, WhatsApp tokens) ----------
_SECRET_PREFIX = "enc1:"


def encrypt_text(value: str) -> str:
    """Encrypt a short secret with the master key before it goes into the DB.
    Empty stays empty. Already-encrypted values are returned unchanged."""
    if not value or value.startswith(_SECRET_PREFIX):
        return value
    return _SECRET_PREFIX + _MasterKey.get().encrypt(value.encode()).decode()


def decrypt_text(value: str | None) -> str:
    """Inverse of encrypt_text. Plain (legacy, pre-encryption) values pass
    through so old installs keep working until the value is saved again."""
    if not value:
        return ""
    if not value.startswith(_SECRET_PREFIX):
        return value
    try:
        return _MasterKey.get().decrypt(value[len(_SECRET_PREFIX):].encode()).decode()
    except Exception:  # noqa: BLE001 - wrong key: behave as "not set", never crash
        return ""


def rewrap_embedding(blob: bytes, old_key: str, new_key: str) -> bytes:
    """Master-key rotation: re-encrypt only the per-record DEK (envelope)."""
    if blob[:3] != b"FE1":
        raise ValueError("unrecognized embedding envelope format")
    (wrapped_len,) = struct.unpack(">I", blob[3:7])
    wrapped_dek = blob[7 : 7 + wrapped_len]
    ciphertext = blob[7 + wrapped_len :]
    dek = Fernet(old_key.encode()).decrypt(wrapped_dek)
    new_wrapped = Fernet(new_key.encode()).encrypt(dek)
    return b"FE1" + struct.pack(">I", len(new_wrapped)) + new_wrapped + ciphertext
