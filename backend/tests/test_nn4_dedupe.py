"""NON-NEGOTIABLE #4: dedupe enforced at data layer -- 8 seconds of frames of
the same person -> exactly 1 event.

This drives `process_kiosk_event` directly with a burst of detections spaced
well under a second apart (as a kiosk running its subject_gate would still
occasionally forward, e.g. right after a track re-acquire) across an 8
second window, and asserts the DATA LAYER (upsert_attendance_event's
dedupe-window merge, not any kiosk-side suppression) collapses them to
exactly one row."""
from __future__ import annotations

import datetime as dt

import numpy as np

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.schemas.kiosk import KioskEventRequest
from app.security import encrypt_embedding
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS
from sqlalchemy import select


async def test_eight_seconds_of_repeated_frames_yields_exactly_one_event(db_session):
    emp = Employee(face_id="EMP-0001", emp_code="E1", name="Alice")
    db_session.add(emp)
    await db_session.flush()

    embedding = np.zeros(512, dtype=np.float64)
    embedding[0] = 1.0
    db_session.add(
        FaceTemplate(
            owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=embedding.tolist(),
            embedding_encrypted=encrypt_embedding(embedding.tolist()), quality_score=0.9, model_version="test",
        )
    )
    await db_session.flush()

    config = dict(DEFAULT_SETTINGS, similarity_threshold=0.3, dedupe_window_minutes=5)
    start = dt.datetime.now(dt.timezone.utc)

    # 8 seconds of frames at ~6fps => ~48 detections reaching the backend.
    for i in range(48):
        payload = KioskEventRequest(
            client_event_id=f"event-{i}",
            kiosk_id="kiosk-1",
            occurred_at=start + dt.timedelta(seconds=i * (8 / 48)),
            embedding=embedding.tolist(),
            liveness_score=0.95,
        )
        await process_kiosk_event(db_session, payload, config)

    events = (
        await db_session.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == emp.id))
    ).scalars().all()
    assert len(events) == 1
    assert events[0].event_type.value == "IN"


async def test_detection_after_dedupe_window_creates_the_out_event(db_session):
    emp = Employee(face_id="EMP-0002", emp_code="E2", name="Carol")
    db_session.add(emp)
    await db_session.flush()
    embedding = np.zeros(512, dtype=np.float64)
    embedding[0] = 1.0
    db_session.add(
        FaceTemplate(
            owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=embedding.tolist(),
            embedding_encrypted=encrypt_embedding(embedding.tolist()), quality_score=0.9, model_version="test",
        )
    )
    await db_session.flush()

    config = dict(DEFAULT_SETTINGS, similarity_threshold=0.3, dedupe_window_minutes=5)
    start = dt.datetime.now(dt.timezone.utc)

    await process_kiosk_event(
        db_session,
        KioskEventRequest(client_event_id="in-1", kiosk_id="k1", occurred_at=start, embedding=embedding.tolist(), liveness_score=0.9),
        config,
    )
    await process_kiosk_event(
        db_session,
        KioskEventRequest(
            client_event_id="out-1", kiosk_id="k1",
            occurred_at=start + dt.timedelta(minutes=10), embedding=embedding.tolist(), liveness_score=0.9,
        ),
        config,
    )

    events = (
        await db_session.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == emp.id))
    ).scalars().all()
    assert len(events) == 2
    types = sorted(e.event_type.value for e in events)
    assert types == ["IN", "OUT"]
