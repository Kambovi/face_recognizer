"""GET /dashboard?date_from&date_to -- per-day rows, entry points, absences."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType, UnknownStatus
from app.models.unknown_identities import UnknownIdentity
from app.services.dashboard import LOCAL_TZ, local_today


def _at(day, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=LOCAL_TZ)


async def test_dashboard_range_rows_kiosks_and_absences(client, admin_headers, db_session, default_shift):
    today = local_today()
    d2, d1 = today - timedelta(days=2), today - timedelta(days=1)

    emp = Employee(face_id="EMP-0001", emp_code="E1", name="Asha Rao", department="Cardiology",
                   designation="Nurse", shift_id=default_shift.id, created_at=_at(d2, 0) - timedelta(days=1))
    retired = Employee(face_id="EMP-0002", emp_code="E2", name="Old Timer", is_active=False,
                       created_at=_at(d2, 0) - timedelta(days=30))
    unk = UnknownIdentity(face_id="UNK-0001", first_seen_at=_at(d1, 11), last_seen_at=_at(d1, 11),
                          sighting_count=1, status=UnknownStatus.OPEN)
    db_session.add_all([emp, retired, unk])
    await db_session.flush()

    db_session.add_all([
        # d2: late (09:30 > 09:00 + 15 min grace) via gate-1, with OUT
        AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=EventType.IN,
                        occurred_at=_at(d2, 9, 30), similarity=0.9, kiosk_id="gate-1"),
        AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=EventType.OUT,
                        occurred_at=_at(d2, 18, 0), similarity=0.9, kiosk_id="gate-1"),
        # d1: unknown visitor at the OPD camera; employee absent
        AttendanceEvent(subject_type=SubjectType.UNKNOWN, unknown_identity_id=unk.id, event_type=EventType.IN,
                        occurred_at=_at(d1, 11), kiosk_id="opd-cam"),
        # today: on time, no OUT yet
        AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=EventType.IN,
                        occurred_at=_at(today, 0, 5), similarity=0.9, kiosk_id="opd-cam"),
    ])
    await db_session.flush()

    resp = await client.get(
        "/api/v1/dashboard", params={"date_from": d2.isoformat(), "date_to": today.isoformat()}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    known = {r["date"]: r for r in body["known"]}
    assert set(known) == {d2.isoformat(), today.isoformat()}
    assert known[d2.isoformat()]["on_time"] is False
    assert known[d2.isoformat()]["kiosk_ids"] == ["gate-1"]
    assert known[d2.isoformat()]["total_hours"] == 8.5
    assert known[d2.isoformat()]["emp_code"] == "E1"
    assert known[today.isoformat()]["on_time"] is True
    # No OUT yet today -- total_hours is "still clocked in" elapsed time
    # (now - first IN), not 0 / blank.
    assert known[today.isoformat()]["out_time"] is None
    assert known[today.isoformat()]["total_hours"] > 0

    # Only the active employee is absent, and only on d1.
    assert [(r["face_id"], r["date"], r["emp_code"]) for r in body["absent"]] == [("EMP-0001", d1.isoformat(), "E1")]

    assert [(r["face_id"], r["date"], r["kiosk_ids"]) for r in body["unknown"]] == [
        ("UNK-0001", d1.isoformat(), ["opd-cam"])
    ]

    kinds = {(x["kind"], x["date"]) for x in body["exceptions"]}
    assert ("late_arrival", d2.isoformat()) in kinds
    assert ("no_out_recorded", today.isoformat()) in kinds

    assert body["kiosks"] == ["gate-1", "opd-cam"]
    assert body["counts"] == {"present": 2, "absent": 1, "unknown": 1, "exceptions": len(body["exceptions"])}

    # /today is the same computation for a single day.
    today_body = (await client.get("/api/v1/dashboard/today", headers=admin_headers)).json()
    assert today_body["counts"]["present"] == 1
    assert today_body["unknown"] == []  # unknown was seen yesterday, not today


async def test_dashboard_range_validation(client, admin_headers):
    today = local_today()
    reversed_resp = await client.get(
        "/api/v1/dashboard",
        params={"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat()},
        headers=admin_headers,
    )
    assert reversed_resp.status_code == 422

    too_long = await client.get(
        "/api/v1/dashboard",
        params={"date_from": (today - timedelta(days=400)).isoformat(), "date_to": today.isoformat()},
        headers=admin_headers,
    )
    assert too_long.status_code == 422
