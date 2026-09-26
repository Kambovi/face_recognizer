"""Broad end-to-end smoke test across the whole API surface, using a fake
insightface engine (no network/model weights needed) for enrollment."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image


class _FakeFace:
    def __init__(self, embedding: np.ndarray) -> None:
        self.bbox = np.array([10, 10, 90, 90], dtype=np.float32)
        self.kps = np.array([[30, 30], [70, 30], [50, 50], [35, 70], [65, 70]], dtype=np.float32)
        self.det_score = 0.99
        self.normed_embedding = embedding


class _FakeApp:
    def __init__(self, embedding: np.ndarray) -> None:
        self._embedding = embedding

    def get(self, img):
        return [_FakeFace(self._embedding)]


def _make_jpeg_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color=(120, 130, 140))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def test_full_flow_health_login_employee_enroll_dashboard_settings_analytics(client, admin_headers, default_shift):
    from app.services.embedding import _EngineSingleton

    health_resp = await client.get("/api/v1/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] in ("ok", "degraded")

    login_resp = await client.post("/api/v1/auth/login", json={"email": "admin@example.org", "password": "secret123"})
    assert login_resp.status_code == 200
    assert login_resp.json()["role"] == "admin"

    bad_login = await client.post("/api/v1/auth/login", json={"email": "admin@example.org", "password": "wrong"})
    assert bad_login.status_code == 401
    assert bad_login.json()["code"] == "invalid_credentials"

    create_resp = await client.post(
        "/api/v1/employees",
        json={"name": "Erin", "emp_code": "E500", "department": "Engineering", "shift_id": default_shift.id},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    employee = create_resp.json()
    assert employee["face_id"] == "EMP-0001"

    list_resp = await client.get("/api/v1/employees", headers=admin_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1

    consent_resp = await client.post(
        f"/api/v1/employees/{employee['id']}/consent",
        json={"policy_version": "v1", "purpose_text": "attendance tracking"},
        headers=admin_headers,
    )
    assert consent_resp.status_code == 201

    embedding = np.zeros(512, dtype=np.float32)
    embedding[0] = 1.0
    _EngineSingleton.inject_for_tests(_FakeApp(embedding))
    try:
        files = [("files", ("photo.jpg", _make_jpeg_bytes(), "image/jpeg"))]
        enroll_resp = await client.post(f"/api/v1/employees/{employee['id']}/enroll", files=files, headers=admin_headers)
        assert enroll_resp.status_code == 200, enroll_resp.text
        enroll_body = enroll_resp.json()
        assert enroll_body["accepted_count"] == 1
    finally:
        _EngineSingleton.reset_for_tests()

    templates_resp = await client.get(f"/api/v1/employees/{employee['id']}/templates", headers=admin_headers)
    assert templates_resp.status_code == 200
    assert len(templates_resp.json()) == 1

    # Kiosk posts a matching recognition event.
    import datetime as dt

    kiosk_resp = await client.post(
        "/api/v1/kiosk/event",
        json={
            "client_event_id": "smoke-event-1",
            "kiosk_id": "kiosk-01",
            "occurred_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "embedding": embedding.tolist(),
            "liveness_score": 0.95,
            "quality_score": 0.9,
        },
        headers={"Authorization": "Bearer test_token"},
    )
    assert kiosk_resp.status_code == 200, kiosk_resp.text
    assert kiosk_resp.json()["face_id"] == "EMP-0001"

    dashboard_resp = await client.get("/api/v1/dashboard/today", headers=admin_headers)
    assert dashboard_resp.status_code == 200
    dashboard_body = dashboard_resp.json()
    assert dashboard_body["counts"]["present"] == 1
    assert dashboard_body["known"][0]["face_id"] == "EMP-0001"

    events_resp = await client.get("/api/v1/attendance/events", headers=admin_headers)
    assert events_resp.status_code == 200
    assert events_resp.json()["total"] == 1

    settings_resp = await client.get("/api/v1/settings", headers=admin_headers)
    assert settings_resp.status_code == 200
    assert "similarity_threshold" in settings_resp.json()["settings"]

    analytics_resp = await client.get("/api/v1/analytics/summary", params={"period": "daily"}, headers=admin_headers)
    assert analytics_resp.status_code == 200
    assert analytics_resp.json()["rows"][0]["face_id"] == "EMP-0001"

    csv_resp = await client.get("/api/v1/analytics/export.csv", params={"period": "daily"}, headers=admin_headers)
    assert csv_resp.status_code == 200
    assert "Face ID" in csv_resp.text

    kiosk_config_resp = await client.get("/api/v1/kiosk/config", headers={"Authorization": "Bearer test_token"})
    assert kiosk_config_resp.status_code == 200

    heartbeat_resp = await client.post(
        "/api/v1/kiosk/heartbeat",
        json={"kiosk_id": "kiosk-01", "device": {"provider": "CPUExecutionProvider", "profile": "cpu", "status": "ok"}},
        headers={"Authorization": "Bearer test_token"},
    )
    assert heartbeat_resp.status_code == 200

    health_resp2 = await client.get("/api/v1/health")
    assert health_resp2.json()["device"]["provider"] == "CPUExecutionProvider"


async def test_viewer_cannot_write(client, viewer_user, db_session):
    from app.security import create_access_token

    token = create_access_token(subject=viewer_user.id, role="viewer")
    resp = await client.post(
        "/api/v1/employees", json={"name": "X", "emp_code": "X1"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


async def test_kiosk_token_required_for_kiosk_endpoints(client):
    import datetime as dt

    resp = await client.post(
        "/api/v1/kiosk/event",
        json={
            "client_event_id": "no-auth",
            "kiosk_id": "k1",
            "occurred_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "embedding": None,
            "reject_reason": "too_small",
        },
    )
    assert resp.status_code == 401
