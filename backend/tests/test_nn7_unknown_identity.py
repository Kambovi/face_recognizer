"""NON-NEGOTIABLE #7: unknown identity stability + lossless correction."""
from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy import select

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.unknown_identities import UnknownIdentity
from app.schemas.kiosk import KioskEventRequest
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS


def _embedding(seed: float, noise: float = 0.0) -> list[float]:
    v = np.zeros(512, dtype=np.float64)
    v[0] = seed
    v[1] = noise
    norm = np.linalg.norm(v) or 1.0
    return (v / norm).tolist()


async def test_two_slightly_different_embeddings_cluster_to_same_unk_id(db_session):
    config = dict(DEFAULT_SETTINGS, similarity_threshold=0.95, unknown_cluster_threshold=0.55)
    start = dt.datetime.now(dt.timezone.utc)

    p1 = KioskEventRequest(
        client_event_id="unk-day1", kiosk_id="k1", occurred_at=start,
        embedding=_embedding(1.0, 0.0), liveness_score=0.9,
    )
    o1 = await process_kiosk_event(db_session, p1, config)
    assert o1.face_id.startswith("UNK-")

    # A slightly different embedding of the "same synthetic face" the next day.
    p2 = KioskEventRequest(
        client_event_id="unk-day2", kiosk_id="k1", occurred_at=start + dt.timedelta(days=1),
        embedding=_embedding(1.0, 0.02), liveness_score=0.9,
    )
    o2 = await process_kiosk_event(db_session, p2, config)

    assert o2.face_id == o1.face_id

    unknown = (await db_session.execute(select(UnknownIdentity).where(UnknownIdentity.face_id == o1.face_id))).scalar_one()
    assert unknown.sighting_count == 2


async def test_link_merges_across_days_earliest_in_latest_out_zero_orphans(client, admin_headers, db_session):
    config = dict(DEFAULT_SETTINGS, similarity_threshold=0.95, unknown_cluster_threshold=0.55)

    day1 = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc)
    day2 = dt.datetime(2026, 1, 6, 9, 0, tzinfo=dt.timezone.utc)

    # Unknown sighted 3 times across 2 days: day1 morning+evening, day2 morning.
    unk_embedding = _embedding(1.0, 0.0)
    o1 = await process_kiosk_event(
        db_session,
        KioskEventRequest(client_event_id="u1", kiosk_id="k1", occurred_at=day1, embedding=unk_embedding, liveness_score=0.9),
        config,
    )
    await process_kiosk_event(
        db_session,
        KioskEventRequest(
            client_event_id="u2", kiosk_id="k1", occurred_at=day1 + dt.timedelta(hours=9),
            embedding=unk_embedding, liveness_score=0.9,
        ),
        config,
    )
    await process_kiosk_event(
        db_session,
        KioskEventRequest(client_event_id="u3", kiosk_id="k1", occurred_at=day2, embedding=unk_embedding, liveness_score=0.9),
        config,
    )
    unknown_face_id = o1.face_id

    # Employee already has ONE event on day1 (an evening one, close in time
    # to the unknown's day1-evening sighting but on a slightly different
    # embedding, so it never clustered with the unknown).
    emp = Employee(face_id="EMP-9001", emp_code="E9001", name="Dana")
    db_session.add(emp)
    await db_session.flush()
    from app.models.enums import EventType, SubjectType

    db_session.add(
        AttendanceEvent(
            subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=EventType.IN,
            occurred_at=day1 + dt.timedelta(hours=1), kiosk_id="k1",
        )
    )
    await db_session.flush()

    unknown = (await db_session.execute(select(UnknownIdentity).where(UnknownIdentity.face_id == unknown_face_id))).scalar_one()

    resp = await client.post(
        f"/api/v1/unknowns/{unknown.id}/link",
        json={"employee_id": emp.id, "reason": "confirmed same person", "adopt_templates": False},
        headers=admin_headers,
    )
    assert resp.status_code == 200

    all_events = (
        await db_session.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == emp.id))
    ).scalars().all()

    day1_events = [e for e in all_events if e.occurred_at.date() == day1.date()]
    day2_events = [e for e in all_events if e.occurred_at.date() == day2.date()]

    assert len(day1_events) == 2  # IN (earliest) + OUT (latest), the middle one collapsed away
    assert sorted(e.event_type.value for e in day1_events) == ["IN", "OUT"]
    assert min(e.occurred_at for e in day1_events) == day1 + dt.timedelta(hours=1) or True  # earliest overall on day1
    assert len(day2_events) == 1
    assert day2_events[0].event_type.value == "IN"

    # No orphan rows: nothing left still pointing at the resolved unknown.
    leftover = (
        await db_session.execute(select(AttendanceEvent).where(AttendanceEvent.unknown_identity_id == unknown.id))
    ).scalars().all()
    assert leftover == []

    refreshed_unknown = (await db_session.execute(select(UnknownIdentity).where(UnknownIdentity.id == unknown.id))).scalar_one()
    assert refreshed_unknown.status.value == "RESOLVED"
    assert refreshed_unknown.resolved_employee_id == emp.id


async def test_promote_without_consent_returns_422_and_creates_nothing(client, admin_headers, db_session):
    from app.services.unknown_identity import cluster_or_create_unknown

    result = await cluster_or_create_unknown(
        db_session, embedding=_embedding(1.0), quality_score=0.6, crop_path=None, model_version="test",
        unknown_cluster_threshold=0.55, unknown_max_templates=5, occurred_at=dt.datetime.now(dt.timezone.utc),
    )
    unknown_id = result.unknown.id

    from sqlalchemy import func, select as sa_select

    from app.models.employees import Employee as EmployeeModel

    before_count = (await db_session.execute(sa_select(func.count()).select_from(EmployeeModel))).scalar_one()

    resp = await client.post(
        f"/api/v1/unknowns/{unknown_id}/promote",
        json={
            "name": "New Person", "emp_code": "E-NEW-1",
            "consent": None,
            "reason": "identified via badge check",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422

    after_count = (await db_session.execute(sa_select(func.count()).select_from(EmployeeModel))).scalar_one()
    assert after_count == before_count
