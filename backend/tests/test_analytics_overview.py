"""GET /analytics/overview -- KPIs, trend, per-camera headcount, departments."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.services.dashboard import LOCAL_TZ, local_today


def _at(d, hh, mm=0):
    return datetime.combine(d, time(hh, mm), tzinfo=LOCAL_TZ)


async def test_overview_numbers(client, admin_headers, db_session, default_shift):
    today = local_today()
    # pick a Monday-to-today window that contains at least one working day
    start = today - timedelta(days=today.weekday())
    long_ago = _at(start, 0) - timedelta(days=30)
    a = Employee(face_id="EMP-1", emp_code="E1", name="Asha", department="ER", shift_id=default_shift.id,
                 home_kiosk_id="gate-1", created_at=long_ago)
    b = Employee(face_id="EMP-2", emp_code="E2", name="Bala", department="OPD", shift_id=default_shift.id,
                 created_at=long_ago)  # home inferred from where she's seen
    c = Employee(face_id="EMP-3", emp_code="E3", name="Chitra", department="OPD", shift_id=default_shift.id,
                 home_kiosk_id="gate-1", created_at=long_ago)  # never comes
    db_session.add_all([a, b, c])
    await db_session.flush()
    db_session.add_all([
        AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=a.id, event_type=EventType.IN,
                        occurred_at=_at(today, 9, 40), kiosk_id="gate-1"),  # late
        AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=b.id, event_type=EventType.IN,
                        occurred_at=_at(today, 8, 50), kiosk_id="opd-cam"),
    ])
    await db_session.flush()

    r = await client.get("/api/v1/analytics/overview",
                         params={"date_from": today.isoformat(), "date_to": today.isoformat()}, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    k = body["kpis"]
    assert k["roster"] == 3 and k["present_latest_day"] == 2
    if today.weekday() < 5:
        assert k["attendance_pct"] == 66.7 and k["late_count"] == 1 and k["on_time_pct"] == 50.0

    locs = {loc["kiosk_id"]: loc for loc in body["locations"]}
    assert locs["gate-1"]["roster"] == 2 and locs["gate-1"]["present_latest_day"] == 1
    assert locs["gate-1"]["absent_latest_day"] == 1
    assert locs["opd-cam"]["roster"] == 1 and locs["opd-cam"]["present_latest_day"] == 1

    depts = {d["department"]: d for d in body["departments"]}
    assert depts["OPD"]["roster"] == 2 and depts["OPD"]["present_latest_day"] == 1
    assert [t["date"] for t in body["trend"]] == [today.isoformat()]
    assert sum(b["count"] for b in body["arrivals"]) == (2 if today.weekday() < 5 else 0)


async def test_overview_rejects_bad_range(client, admin_headers):
    today = local_today()
    r = await client.get("/api/v1/analytics/overview", headers=admin_headers,
                         params={"date_from": today.isoformat(), "date_to": (today - timedelta(days=2)).isoformat()})
    assert r.status_code == 422
