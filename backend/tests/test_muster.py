"""Emergency muster: who is inside, by camera role."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType, UnknownStatus
from app.models.unknown_identities import UnknownIdentity
from app.services.muster import muster, set_camera_role

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


async def _emp(db, code: str) -> Employee:
    e = Employee(face_id=f"F{code}", emp_code=code, name=f"P {code}", department="Ops")
    db.add(e)
    await db.flush()
    return e


def _ev(db, emp, mins_ago: int, kiosk: str, kind=EventType.IN, unknown=None) -> None:
    db.add(AttendanceEvent(
        subject_type=SubjectType.UNKNOWN if unknown else SubjectType.EMPLOYEE,
        employee_id=None if unknown else emp.id, unknown_identity_id=unknown.id if unknown else None,
        event_type=kind, occurred_at=NOW - timedelta(minutes=mins_ago), kiosk_id=kiosk,
    ))


async def test_single_both_camera_first_sighting_inside_second_left(db_session):
    a, b = await _emp(db_session, "A"), await _emp(db_session, "B")
    _ev(db_session, a, 180, "gate")                       # came in, not seen since -> inside
    _ev(db_session, b, 300, "gate")
    _ev(db_session, b, 30, "gate", EventType.OUT)         # seen again -> treated as left
    await db_session.flush()
    m = await muster(db_session, now=NOW)
    assert [r["emp_code"] for r in m["inside"]] == ["A"]
    assert m["left_count"] == 1
    assert m["has_exit_camera"] is False


async def test_entry_and_exit_cameras_decide_by_last_camera(db_session):
    await set_camera_role(db_session, "in-gate", "entry")
    await set_camera_role(db_session, "out-gate", "exit")
    a, b, c = await _emp(db_session, "A"), await _emp(db_session, "B"), await _emp(db_session, "C")
    _ev(db_session, a, 200, "in-gate")
    _ev(db_session, a, 20, "in-gate", EventType.OUT)      # walked past the entry cam again: still inside
    _ev(db_session, b, 200, "in-gate")
    _ev(db_session, b, 10, "out-gate", EventType.OUT)     # left
    _ev(db_session, c, 60 * 20, "in-gate")                # outside the 16h window: ignored
    unk = UnknownIdentity(face_id="UNK-9", first_seen_at=NOW, last_seen_at=NOW, sighting_count=1, status=UnknownStatus.OPEN)
    db_session.add(unk)
    await db_session.flush()
    _ev(db_session, None, 15, "in-gate", unknown=unk)
    await db_session.flush()
    m = await muster(db_session, now=NOW)
    assert [r["emp_code"] for r in m["inside"]] == ["A"]
    assert [v["face_id"] for v in m["visitors_inside"]] == ["UNK-9"]
    assert m["left_count"] == 1 and m["has_exit_camera"] is True


async def test_camera_role_api_and_csv(client, admin_headers, db_session):
    r = await client.patch("/api/v1/cameras/gate", headers=admin_headers, json={"role": "exit"})
    assert r.status_code == 200 and r.json()["gate"] == "exit"
    bad = await client.patch("/api/v1/cameras/gate", headers=admin_headers, json={"role": "sideways"})
    assert bad.status_code == 422
    csv_r = await client.get("/api/v1/muster.csv", headers=admin_headers)
    assert csv_r.status_code == 200 and "Safe (tick)" in csv_r.text
