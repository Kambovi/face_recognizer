"""Edge licences: signed by the cloud, checked by the box."""
from __future__ import annotations

import time

from app.licence import GRACE_DAYS, check, issue, keygen


def test_licence_lifecycle():
    priv, pub = keygen()
    now = time.time()
    tok = issue(priv, tenant="acme", site="s1", max_cameras=2, max_people=200, days=7, now=now)
    ok = check(tok, pub, now=now + 3600)
    assert ok.valid and ok.reason == "ok" and ok.payload["tenant"] == "acme"
    grace = check(tok, pub, now=now + 8 * 86400)
    assert grace.valid and grace.reason == "grace"
    dead = check(tok, pub, now=now + (7 + GRACE_DAYS + 1) * 86400)
    assert not dead.valid and dead.reason == "expired"


def test_tampered_or_foreign_licence_is_rejected():
    priv, pub = keygen()
    _, other_pub = keygen()
    tok = issue(priv, tenant="acme", site="s1", max_cameras=2, max_people=200)
    body, sig = tok.split(".")
    import base64
    import json

    data = json.loads(base64.urlsafe_b64decode(body + "=="))
    data["max_cameras"] = 99
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=") + "." + sig
    assert check(forged, pub).reason == "invalid"
    assert check(tok, other_pub).reason == "invalid"
    assert check(None, pub).reason == "missing"
