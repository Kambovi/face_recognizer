"""Security hardening (audit 2026-10-04): secrets, login, sessions, roles,
per-camera tokens, kiosk input checks, CSV + media safety."""
from __future__ import annotations

import base64
import csv
import io
from datetime import datetime, timedelta, timezone

import jwt
import numpy as np
import pytest

from app.config import Settings, insecure_settings, validate_for_production
from app.models.enums import UserRole
from app.models.users import User
from app.security import create_access_token, decrypt_text, encrypt_text, hash_password
from app.services.csvsafe import safe_cell
from app.services.passwords import password_problem

GOOD_PW = "Str0ngPassw0rd!"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def _emb() -> list[float]:
    v = np.random.rand(512)
    return (v / np.linalg.norm(v)).tolist()


def now_iso(minutes: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


# ------------------------------------------------------------------ secrets
def test_production_refuses_published_defaults():
    s = Settings(app_env="production")
    assert {"JWT_SECRET", "EMBEDDING_ENCRYPTION_KEY", "KIOSK_SERVICE_TOKEN"} <= set(insecure_settings(s))
    with pytest.raises(RuntimeError):
        validate_for_production(s)
    ok = Settings(app_env="production", jwt_secret="x" * 48, kiosk_service_token="",
                  embedding_encryption_key="ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleTEyMzQ=")
    validate_for_production(ok)  # no raise
    validate_for_production(Settings(app_env="development"))  # dev only warns


def test_db_secrets_are_encrypted_at_rest():
    enc = encrypt_text("sk-live-123")
    assert enc.startswith("enc1:") and "sk-live" not in enc
    assert decrypt_text(enc) == "sk-live-123"
    assert decrypt_text("legacy-plain") == "legacy-plain"


# ------------------------------------------------------------------ tokens
async def test_token_signed_with_another_secret_is_rejected(client, admin_user):
    forged = jwt.encode({"sub": admin_user.id, "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(days=1)},
                        "dev_only_change_me_to_a_long_random_string", algorithm="HS256")
    r = await client.get("/api/v1/employees", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_alg_none_token_is_rejected(client, admin_user):
    forged = jwt.encode({"sub": admin_user.id, "exp": datetime.now(timezone.utc) + timedelta(days=1)}, None, algorithm="none")
    r = await client.get("/api/v1/employees", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_logout_everywhere_kills_old_tokens(client, admin_user, admin_headers):
    assert (await client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=admin_headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 401


# ------------------------------------------------------------------ login
async def _user(db, email="hr@example.org", role=UserRole.HR, pw=GOOD_PW, must_change=False) -> User:
    u = User(email=email, password_hash=hash_password(pw), role=role, must_change_password=must_change)
    db.add(u)
    await db.flush()
    return u


async def test_account_locks_after_five_wrong_passwords(client, db_session):
    await _user(db_session)
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"email": "hr@example.org", "password": "wrong-pass-1"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": "hr@example.org", "password": GOOD_PW})
    assert r.status_code == 423  # locked even with the right password


async def test_ip_throttle_stops_password_spraying(client, db_session):
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": f"u{i}@example.org", "password": "x"})).status_code
        for i in range(25)
    ]
    assert 429 in codes


async def test_temporary_password_must_be_changed_first(client, db_session):
    await _user(db_session, must_change=True)
    r = await client.post("/api/v1/auth/login", json={"email": "hr@example.org", "password": GOOD_PW})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    blocked = await client.get("/api/v1/employees", headers=h)
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    weak = await client.post("/api/v1/auth/change-password", headers=h,
                             json={"current_password": GOOD_PW, "new_password": "password123"})
    assert weak.status_code == 422
    ok = await client.post("/api/v1/auth/change-password", headers=h,
                           json={"current_password": GOOD_PW, "new_password": "N3wSecure-Pass"})
    assert ok.status_code == 200
    # the old token died, the new one works everywhere
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 401
    h2 = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await client.get("/api/v1/employees", headers=h2)).status_code == 200


def test_password_policy():
    assert password_problem("short1") is not None
    assert password_problem("onlyletterslong") is not None
    assert password_problem("ChangeMe123!") is not None
    assert password_problem("ravi.kumar2026x", "ravi.kumar@acme.in") is not None
    assert password_problem("Blue-Train-4821") is None


# ------------------------------------------------------------------ roles + users
async def test_hr_can_manage_people_but_not_settings_or_users(client, db_session):
    u = await _user(db_session)
    h = {"Authorization": f"Bearer {create_access_token(u.id, 'hr')}"}
    assert (await client.post("/api/v1/employees", headers=h, json={"emp_code": "E1", "name": "A"})).status_code == 201
    assert (await client.patch("/api/v1/settings", headers=h, json={"values": {"ot_min_minutes": 10}})).status_code == 403
    assert (await client.get("/api/v1/users", headers=h)).status_code == 403


async def test_viewer_cannot_change_anything(client, viewer_user):
    h = {"Authorization": f"Bearer {create_access_token(viewer_user.id, 'viewer')}"}
    assert (await client.post("/api/v1/employees", headers=h, json={"emp_code": "E1", "name": "A"})).status_code == 403
    assert (await client.post("/api/v1/leaves", headers=h, json={"employee_id": "x", "date_from": "2026-10-01",
                                                                 "date_to": "2026-10-01"})).status_code == 403


async def test_admin_user_management_and_last_admin_guard(client, admin_user, admin_headers):
    r = await client.post("/api/v1/users", headers=admin_headers, json={"email": "new.hr@example.org", "role": "hr"})
    assert r.status_code == 201
    tmp = r.json()["temporary_password"]
    login = await client.post("/api/v1/auth/login", json={"email": "new.hr@example.org", "password": tmp})
    assert login.status_code == 200 and login.json()["must_change_password"] is True
    # can't demote the only admin
    r = await client.patch(f"/api/v1/users/{admin_user.id}", headers=admin_headers, json={"role": "viewer"})
    assert r.status_code == 409
    audit = await client.get("/api/v1/audit?entity=user", headers=admin_headers)
    assert any(a["action"] == "user_create" for a in audit.json())


# ------------------------------------------------------------------ kiosk
async def _device(client, admin_headers, kiosk_id="gate-1") -> str:
    r = await client.post("/api/v1/devices", headers=admin_headers, json={"kiosk_id": kiosk_id, "name": "Main gate"})
    assert r.status_code == 201
    return r.json()["token"]


def _event(kiosk_id="gate-1", **kw):
    body = {"client_event_id": kw.pop("cid", "e-" + now_iso()), "kiosk_id": kiosk_id, "occurred_at": now_iso(),
            "embedding": None, "reject_reason": "too_small"}
    body.update(kw)
    return body


async def test_per_camera_token_only_works_for_its_camera(client, admin_headers):
    token = await _device(client, admin_headers)
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/v1/kiosk/event", headers=h, json=_event())).status_code == 200
    r = await client.post("/api/v1/kiosk/event", headers=h, json=_event(kiosk_id="other-cam"))
    assert r.status_code == 403
    # rotate -> old token dead
    dev = (await client.get("/api/v1/devices", headers=admin_headers)).json()[0]
    await client.post(f"/api/v1/devices/{dev['id']}/rotate", headers=admin_headers)
    assert (await client.post("/api/v1/kiosk/event", headers=h, json=_event(cid="x2"))).status_code == 401


async def test_kiosk_id_path_traversal_is_rejected(client, kiosk_headers):
    body = _event(kiosk_id="../../../../tmp/pwned", crop_jpeg_base64=base64.b64encode(JPEG).decode())
    assert (await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=body)).status_code == 422


async def test_backdated_and_future_events_are_rejected(client, kiosk_headers, monkeypatch):
    from app.services import settings_service

    monkeypatch.setitem(settings_service.DEFAULT_SETTINGS, "max_event_age_hours", 72)
    old = _event(occurred_at=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    r = await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=old)
    assert r.status_code == 422 and r.json()["code"] == "event_too_old"
    fut = _event(cid="f1", occurred_at=now_iso(60))
    r = await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=fut)
    assert r.status_code == 422 and r.json()["code"] == "event_in_future"
    recent = _event(cid="r1", occurred_at=(datetime.now(timezone.utc) - timedelta(hours=10)).isoformat())
    assert (await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=recent)).status_code == 200


async def test_crop_must_be_a_real_jpeg(client, kiosk_headers):
    body = _event(crop_jpeg_base64=base64.b64encode(b"<?php system($_GET[c]); ?>").decode())
    r = await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=body)
    assert r.status_code == 422 and r.json()["code"] == "bad_crop"


async def test_embedding_must_be_512_finite_values(client, kiosk_headers):
    body = _event(embedding=[0.1] * 10, reject_reason=None, liveness_score=0.9)
    assert (await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=body)).status_code == 422


async def test_face_without_passing_liveness_is_not_recognised(client, kiosk_headers, db_session):
    from sqlalchemy import select

    from app.models.attendance_events import AttendanceEvent

    body = _event(cid="nolive", embedding=_emb(), reject_reason=None, liveness_score=None)
    r = await client.post("/api/v1/kiosk/event", headers=kiosk_headers, json=body)
    assert r.status_code == 200
    ev = (await db_session.execute(select(AttendanceEvent).where(AttendanceEvent.client_event_id == "nolive"))).scalar_one()
    assert ev.subject_type is None and ev.reject_reason.value == "liveness_failed"


# ------------------------------------------------------------------ files
def test_csv_cells_cannot_become_formulas():
    assert safe_cell('=HYPERLINK("http://x","y")') == '\'=HYPERLINK("http://x","y")'
    assert safe_cell("+cmd") == "'+cmd" and safe_cell("@SUM(1)") == "'@SUM(1)"
    assert safe_cell("-12.5") == "-12.5" and safe_cell(5) == 5 and safe_cell("Ravi") == "Ravi"


async def test_payroll_csv_is_sanitised(client, admin_headers):
    await client.post("/api/v1/employees", headers=admin_headers, json={"emp_code": "E9", "name": "=1+2"})
    month = datetime.now().strftime("%Y-%m")
    r = await client.get(f"/api/v1/reports/payroll?month={month}", headers=admin_headers)
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert any("'=1+2" in row for row in rows)


def test_media_paths_cannot_escape_media_root():
    from app.services.media import absolute_path

    assert not absolute_path("../../etc/passwd").exists()


async def test_settings_keep_their_types(client, admin_headers):
    bad = await client.patch("/api/v1/settings", headers=admin_headers, json={"values": {"similarity_threshold": "0.4a"}})
    assert bad.status_code == 422
    bad = await client.patch("/api/v1/settings", headers=admin_headers, json={"values": {"payroll_state": "XX"}})
    assert bad.status_code == 422
    ok = await client.patch("/api/v1/settings", headers=admin_headers,
                            json={"values": {"payroll_state": "mh", "attendance_start_date": "2026-09-15"}})
    assert ok.status_code == 200
    assert ok.json()["settings"]["payroll_state"] == "MH"
