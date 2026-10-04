"""Edge licences: the cloud signs, the edge box verifies.

A licence is `<base64url(json)>.<base64url(Ed25519 signature)>` with
{tenant, site, iat, exp, max_cameras, max_people}. The cloud hands a fresh
one (valid LICENCE_DAYS) to a connected, paid-up edge box every time it
syncs. The box only knows the PUBLIC key, so it can check a licence but
never make one. When the licence has run out (plus GRACE_DAYS for an
internet outage) the box stops accepting camera events: the subscription
is what keeps attendance running.

  python -m app.licence keygen      -> new key pair for the cloud .env / edge build
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

LICENCE_DAYS = 7
GRACE_DAYS = 7


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def keygen() -> tuple[str, str]:
    """(private, public) as base64 raw keys."""
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def public_from_private(private_b64: str) -> str:
    k = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def issue(private_b64: str, *, tenant: str, site: str, max_cameras: int, max_people: int,
          days: int = LICENCE_DAYS, now: float | None = None) -> str:
    now = now or time.time()
    payload = {"tenant": tenant, "site": site, "iat": int(now), "exp": int(now + days * 86400),
               "max_cameras": max_cameras, "max_people": max_people}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64)).sign(body)
    return f"{_b64e(body)}.{_b64e(sig)}"


@dataclass
class LicenceState:
    valid: bool          # events may be processed
    reason: str          # ok / grace / expired / invalid / missing
    payload: dict[str, Any]
    seconds_left: float  # until hard stop (exp + grace)


def check(token: str | None, public_b64: str, now: float | None = None) -> LicenceState:
    now = now or time.time()
    if not token or not public_b64:
        return LicenceState(False, "missing", {}, 0)
    try:
        body_s, sig_s = token.split(".", 1)
        body = _b64d(body_s)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64)).verify(_b64d(sig_s), body)
        payload = json.loads(body)
    except Exception:  # noqa: BLE001 - any tampering / garbage = invalid
        return LicenceState(False, "invalid", {}, 0)
    exp = float(payload.get("exp", 0))
    hard = exp + GRACE_DAYS * 86400
    if now <= exp:
        return LicenceState(True, "ok", payload, hard - now)
    if now <= hard:
        return LicenceState(True, "grace", payload, hard - now)
    return LicenceState(False, "expired", payload, 0)


if __name__ == "__main__":  # pragma: no cover
    import sys

    if sys.argv[1:] == ["keygen"]:
        priv, pub = keygen()
        print(f"LICENCE_PRIVATE_KEY={priv}   # cloud .env only, keep secret")
        print(f"LICENCE_PUBLIC_KEY={pub}    # edge boxes")
    else:
        print(__doc__)
