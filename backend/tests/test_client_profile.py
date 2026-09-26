"""Vendor-locked client profile + per-camera licence cap."""
from __future__ import annotations

from app.security import hash_password
from app.services.client_profile import save_raw


async def _setup(db, **over):
    profile = {"org_type": "school", "org_name": "Green Valley School", "departments": ["Class 1-A", "Class 1-B"],
               "max_enrolled_per_camera": 2, "vendor_pin_hash": hash_password("vendor123")}
    profile.update(over)
    await save_raw(db, profile)
    await db.flush()


async def test_unconfigured_profile_is_public_business_default(client):
    body = (await client.get("/api/v1/profile")).json()  # no auth header on purpose
    assert body["configured"] is False and body["person_label"] == "Employee"


async def test_profile_wording_follows_sector_and_hides_pin(client, db_session):
    await _setup(db_session)
    body = (await client.get("/api/v1/profile")).json()
    assert body["configured"] and body["org_name"] == "Green Valley School"
    assert body["person_label"] == "Student" and body["department_label"] == "Class" and body["id_label"] == "Roll No"
    assert "vendor_pin_hash" not in body


async def test_client_admin_cannot_change_profile_through_settings(client, admin_headers, db_session):
    await _setup(db_session)
    r = await client.patch("/api/v1/settings", json={"values": {"client_profile": {"org_type": "business"}}}, headers=admin_headers)
    assert r.status_code == 200
    assert "client_profile" not in r.json()["settings"]
    assert (await client.get("/api/v1/profile")).json()["org_type"] == "school"


async def test_department_must_be_from_the_locked_list(client, admin_headers, db_session):
    await _setup(db_session)
    bad = await client.post("/api/v1/employees", json={"name": "A", "emp_code": "R1", "department": "Class 9-Z"}, headers=admin_headers)
    assert bad.status_code == 422 and bad.json()["code"] == "unknown_department"
    ok = await client.post("/api/v1/employees", json={"name": "A", "emp_code": "R1", "department": "Class 1-A"}, headers=admin_headers)
    assert ok.status_code == 201


async def test_camera_cap_blocks_the_extra_person(client, admin_headers, db_session):
    await _setup(db_session)
    for i in range(2):
        r = await client.post("/api/v1/employees", json={"name": f"P{i}", "emp_code": f"R{i}", "home_kiosk_id": "gate-1"}, headers=admin_headers)
        assert r.status_code == 201, r.text
    full = await client.post("/api/v1/employees", json={"name": "P3", "emp_code": "R3", "home_kiosk_id": "gate-1"}, headers=admin_headers)
    assert full.status_code == 422 and full.json()["code"] == "camera_full"
    # another camera is fine
    other = await client.post("/api/v1/employees", json={"name": "P3", "emp_code": "R3", "home_kiosk_id": "gate-2"}, headers=admin_headers)
    assert other.status_code == 201

    cams = {c["kiosk_id"]: c for c in (await client.get("/api/v1/cameras", headers=admin_headers)).json()}
    assert cams["gate-1"]["enrolled"] == 2 and cams["gate-1"]["cap"] == 2

    # moving the gate-2 person onto the full camera is also blocked
    emp_id = other.json()["id"]
    move = await client.patch(f"/api/v1/employees/{emp_id}", json={"home_kiosk_id": "gate-1"}, headers=admin_headers)
    assert move.status_code == 422 and move.json()["code"] == "camera_full"


async def test_dashboard_rows_carry_ids_and_manual_out_closes_the_day(client, admin_headers, db_session):
    from datetime import datetime, time

    from app.models.attendance_events import AttendanceEvent
    from app.models.employees import Employee
    from app.models.enums import EventType, SubjectType
    from app.services.dashboard import LOCAL_TZ, local_today

    today = local_today()
    emp = Employee(face_id="EMP-0009", emp_code="E9", name="Asha")
    db_session.add(emp)
    await db_session.flush()
    ev = AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=EventType.IN,
                         occurred_at=datetime.combine(today, time(0, 5), tzinfo=LOCAL_TZ), kiosk_id="gate-1")
    db_session.add(ev)
    await db_session.flush()

    row = (await client.get("/api/v1/dashboard/today", headers=admin_headers)).json()["known"][0]
    assert row["subject_id"] == emp.id and row["in_event_id"] == ev.id and row["out_event_id"] is None

    out_at = datetime.combine(today, time(0, 35), tzinfo=LOCAL_TZ).isoformat()
    r = await client.post("/api/v1/attendance/events/manual", headers=admin_headers,
                          json={"employee_id": emp.id, "event_type": "OUT", "occurred_at": out_at, "reason": "forgot to check out"})
    assert r.status_code == 201, r.text
    assert r.json()["is_manual_override"] is True

    row = (await client.get("/api/v1/dashboard/today", headers=admin_headers)).json()["known"][0]
    assert row["out_time"] == "00:35" and row["total_hours"] == 0.5
    cams = [c["kiosk_id"] for c in (await client.get("/api/v1/cameras", headers=admin_headers)).json()]
    assert "manual" not in cams
