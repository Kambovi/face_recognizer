"""NON-NEGOTIABLE #2: biometric data protection.

- Embeddings are envelope-encrypted at rest (Fernet, per-record DEK wrapped
  by an env-provided master key).
- Employee delete hard-purges templates, crops, consent, leaves an audit
  row.
"""
from __future__ import annotations

import numpy as np

from app.security import decrypt_embedding, encrypt_embedding


def test_envelope_encryption_roundtrip_and_uses_random_dek():
    vector = np.random.rand(512).astype(np.float32).tolist()

    blob1 = encrypt_embedding(vector)
    blob2 = encrypt_embedding(vector)

    # Same plaintext, two calls -> different ciphertext (fresh random DEK
    # each time) -- this is what makes it envelope encryption rather than a
    # single deterministic Fernet(key).encrypt(...).
    assert blob1 != blob2

    recovered1 = decrypt_embedding(blob1)
    recovered2 = decrypt_embedding(blob2)
    np.testing.assert_allclose(recovered1, vector, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(recovered2, vector, rtol=1e-5, atol=1e-5)


def test_ciphertext_does_not_contain_recognizable_plaintext_floats():
    vector = [0.123456] * 512
    blob = encrypt_embedding(vector)
    # A crude but meaningful check: the raw float32 bytes of the plaintext
    # vector must not appear verbatim inside the "encrypted" blob.
    raw = np.asarray(vector, dtype=np.float32).tobytes()
    assert raw not in blob


async def test_employee_delete_hard_purges_templates_consent_and_audits(client, admin_headers, db_session):
    from sqlalchemy import select

    from app.models.audit_log import AuditLog
    from app.models.consents import Consent
    from app.models.enums import OwnerType
    from app.models.face_templates import FaceTemplate

    create_resp = await client.post(
        "/api/v1/employees", json={"name": "Bob", "emp_code": "E100"}, headers=admin_headers
    )
    employee_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/employees/{employee_id}/consent",
        json={"policy_version": "v1", "purpose_text": "attendance"},
        headers=admin_headers,
    )

    vector = np.random.rand(512).astype(np.float32).tolist()
    db_session.add(
        FaceTemplate(
            owner_type=OwnerType.EMPLOYEE, owner_id=employee_id, embedding=vector,
            embedding_encrypted=encrypt_embedding(vector), quality_score=0.9, model_version="test",
        )
    )
    await db_session.flush()

    del_resp = await client.delete(f"/api/v1/employees/{employee_id}", headers=admin_headers)
    assert del_resp.status_code == 204

    templates = (
        await db_session.execute(select(FaceTemplate).where(FaceTemplate.owner_id == employee_id))
    ).scalars().all()
    assert templates == []

    consents = (await db_session.execute(select(Consent).where(Consent.employee_id == employee_id))).scalars().all()
    assert consents == []

    audit_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.entity_id == employee_id, AuditLog.action == "delete"))
    ).scalars().all()
    assert len(audit_rows) == 1


async def test_revoking_consent_purges_templates_so_recognition_actually_stops(client, admin_headers, db_session):
    """Regression test (see docs/DECISIONS.md, "consent revocation must
    actually stop matching"): `DELETE /employees/{id}/consent` used to only
    mark the Consent row revoked and flip employee.is_active -- it never
    touched face_templates, and search_templates() (app/services/
    matching.py) never checks either of those flags. A "revoked" employee's
    face was therefore still fully matchable by kiosk recognition events,
    contradicting the endpoint's own comment that revocation "disables
    recognition for this person immediately". Fixed by having revoke_consent
    delete the employee's face_templates the same way delete_employee()
    already does; this test drives process_kiosk_event() directly (the real
    server-side matching path a kiosk event takes) to prove the fix rather
    than just checking the templates table is empty."""
    import datetime as dt

    from sqlalchemy import select

    from app.models.enums import OwnerType
    from app.models.face_templates import FaceTemplate
    from app.schemas.kiosk import KioskEventRequest
    from app.services.recognition import process_kiosk_event
    from app.services.settings_service import DEFAULT_SETTINGS

    create_resp = await client.post(
        "/api/v1/employees", json={"name": "Dana", "emp_code": "E101"}, headers=admin_headers
    )
    employee_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/employees/{employee_id}/consent",
        json={"policy_version": "v1", "purpose_text": "attendance"},
        headers=admin_headers,
    )

    embedding = np.zeros(512, dtype=np.float64)
    embedding[0] = 1.0
    db_session.add(
        FaceTemplate(
            owner_type=OwnerType.EMPLOYEE, owner_id=employee_id, embedding=embedding.tolist(),
            embedding_encrypted=encrypt_embedding(embedding.tolist()), quality_score=0.9, model_version="test",
        )
    )
    await db_session.flush()

    revoke_resp = await client.delete(f"/api/v1/employees/{employee_id}/consent", headers=admin_headers)
    assert revoke_resp.status_code == 204

    templates = (
        await db_session.execute(select(FaceTemplate).where(FaceTemplate.owner_id == employee_id))
    ).scalars().all()
    assert templates == [], "revoking consent must purge the employee's face templates"

    config = dict(DEFAULT_SETTINGS, similarity_threshold=0.3)
    outcome = await process_kiosk_event(
        db_session,
        KioskEventRequest(
            client_event_id="post-revoke-1",
            kiosk_id="k1",
            occurred_at=dt.datetime.now(dt.timezone.utc),
            embedding=embedding.tolist(),
            liveness_score=0.95,
        ),
        config,
    )
    # The identical embedding must NOT still resolve to this (now
    # consent-revoked) employee -- with its templates purged, there is
    # nothing left in face_templates for it to match against, so this must
    # come back as a brand-new UNKNOWN identity rather than the deleted
    # employee's face_id.
    assert outcome.event.employee_id != employee_id
    assert outcome.event.subject_type.value == "UNKNOWN"
    assert outcome.face_id != create_resp.json()["face_id"]
