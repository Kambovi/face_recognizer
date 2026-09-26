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
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - exercised via API layer
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
