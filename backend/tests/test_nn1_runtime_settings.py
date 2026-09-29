"""NON-NEGOTIABLE #1: thresholds are runtime config, never hardcoded (read
from `settings` table w/ env fallback)."""
from __future__ import annotations

from app.services.settings_service import DEFAULT_SETTINGS, get_all_settings, get_setting, set_setting


async def test_default_falls_back_when_no_row_exists(db_session):
    value = await get_setting(db_session, "similarity_threshold")
    assert value == DEFAULT_SETTINGS["similarity_threshold"]


async def test_set_setting_overrides_default_and_persists(db_session):
    await set_setting(db_session, "similarity_threshold", 0.55)
    value = await get_setting(db_session, "similarity_threshold")
    assert value == 0.55

    all_settings = await get_all_settings(db_session)
    assert all_settings["similarity_threshold"] == 0.55
    # Untouched keys still fall back to defaults.
    assert all_settings["liveness_threshold"] == DEFAULT_SETTINGS["liveness_threshold"]


async def test_settings_endpoint_roundtrip(client, admin_headers):
    resp = await client.patch("/api/v1/settings", json={"values": {"similarity_threshold": 0.6}}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["settings"]["similarity_threshold"] == 0.6

    resp2 = await client.get("/api/v1/settings", headers=admin_headers)
    assert resp2.json()["settings"]["similarity_threshold"] == 0.6


async def test_recognition_uses_settings_table_value_not_a_hardcoded_constant(db_session):
    """The literal proof: process_kiosk_event must consult the settings dict
    it's given, not a module-level constant -- flip the threshold via the
    settings table and confirm the SAME embedding flips from EMPLOYEE match
    to UNKNOWN."""
    import numpy as np

    from app.models.employees import Employee
    from app.models.enums import OwnerType
    from app.models.face_templates import FaceTemplate
    from app.schemas.kiosk import KioskEventRequest
    from app.security import encrypt_embedding
    from app.services.recognition import process_kiosk_event
    from app.services.settings_service import get_all_settings

    emp = Employee(face_id="EMP-0001", emp_code="E1", name="Alice")
    db_session.add(emp)
    await db_session.flush()

    enrolled = np.zeros(512, dtype=np.float64)
    enrolled[0] = 1.0
    db_session.add(
        FaceTemplate(
            owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=enrolled.tolist(),
            embedding_encrypted=encrypt_embedding(enrolled.tolist()), quality_score=0.9, model_version="test",
        )
    )
    await db_session.flush()

    # A query vector at ~cos(theta)=0.5 similarity to the enrolled one.
    query = np.zeros(512, dtype=np.float64)
    query[0] = 0.5
    query[1] = (1 - 0.5**2) ** 0.5

    config_strict = await get_all_settings(db_session)
    # stricter than 0.5 similarity; near-match guard off so the miss becomes UNKNOWN
    config_strict = dict(config_strict, similarity_threshold=0.9, unknown_near_match_similarity=1.1)
    payload = KioskEventRequest(
        client_event_id="11111111-1111-1111-1111-111111111111",
        kiosk_id="kiosk-1",
        occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        embedding=query.tolist(),
        quality_score=0.8,
        liveness_score=0.95,
    )
    outcome = await process_kiosk_event(db_session, payload, config_strict)
    assert outcome.face_id.startswith("UNK-")

    config_loose = dict(config_strict, similarity_threshold=0.3)
    payload2 = payload.model_copy(update={"client_event_id": "22222222-2222-2222-2222-222222222222"})
    outcome2 = await process_kiosk_event(db_session, payload2, config_loose)
    assert outcome2.face_id == "EMP-0001"
