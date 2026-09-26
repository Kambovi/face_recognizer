"""NON-NEGOTIABLE #5: offline replay is idempotent -- kill DB, generate 10
events, restore DB, replay twice, result must be exactly 10 rows.

The kiosk-side queue (kiosk/kiosk/offline_queue.py) is what actually buffers
events on disk while the write path is down; what makes replaying it safe is
the backend guarantee tested here: POSTing the same `client_event_id` any
number of times ("kill DB" -> queue -> "restore" -> replay -> replay AGAIN)
never creates more than one row for it."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.attendance_events import AttendanceEvent
from app.schemas.kiosk import KioskEventRequest
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS


async def test_replaying_ten_queued_events_twice_yields_exactly_ten_rows(db_session):
    config = dict(DEFAULT_SETTINGS)
    start = dt.datetime.now(dt.timezone.utc)

    # Simulate 10 distinct sightings (rejects, so no employee/matching setup
    # needed -- this test is about idempotency, not identification) that
    # were generated while "the DB was down" and queued client-side.
    queued_payloads = [
        KioskEventRequest(
            client_event_id=f"offline-event-{i}",
            kiosk_id="kiosk-1",
            occurred_at=start + dt.timedelta(minutes=i),
            embedding=None,
            reject_reason="too_small",
        )
        for i in range(10)
    ]

    # "restore" -> first replay drains the queue.
    for payload in queued_payloads:
        await process_kiosk_event(db_session, payload, config)

    # A second replay pass (e.g. a reconnect race re-sends the same queue
    # before the kiosk received the first batch's acks).
    for payload in queued_payloads:
        await process_kiosk_event(db_session, payload, config)

    events = (await db_session.execute(select(AttendanceEvent))).scalars().all()
    assert len(events) == 10
    assert len({e.client_event_id for e in events}) == 10
