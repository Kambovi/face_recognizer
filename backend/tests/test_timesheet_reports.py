"""Timesheet engine + shift roster + contractor / payroll / muster reports."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.models.shifts import Shift
from app.services.attendance import RecognitionEventInput, upsert_attendance_event
from app.services.settings_service import set_setting
from app.services.shiftday import load_resolver
from app.services.timesheet import build_timesheet, person_totals

IST = ZoneInfo("Asia/Kolkata")
MON = date(2026, 9, 21)  # a Monday


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=IST)


async def _person(db, code: str, *, contractor: str | None = None, shift: Shift | None = None) -> Employee:
    e = Employee(
        face_id=f"F-{code}", emp_code=code, name=f"Person {code}", department="Ops",
        contractor=contractor, shift_id=shift.id if shift else None,
        created_at=datetime(2026, 1, 1, tzinfo=IST),
    )
    db.add(e)
    await db.flush()
    return e


def _seen(db, emp: Employee, ts: datetime, kind: EventType = EventType.IN) -> None:
    db.add(AttendanceEvent(
        subject_type=SubjectType.EMPLOYEE, employee_id=emp.id, event_type=kind, occurred_at=ts, kiosk_id="gate",
    ))


@pytest.fixture
async def night_shift(db_session):
    s = Shift(name="Night", in_time=time(22, 0), out_time=time(6, 0), grace_minutes=10, is_default=False)
    db_session.add(s)
    await db_session.flush()
    return s


async def test_day_shift_late_overtime_and_absent(db_session, default_shift):
    a = await _person(db_session, "A1")
    b = await _person(db_session, "B1")
    _seen(db_session, a, at(MON, 9, 40))                     # 25 min late (09:00 + 15 grace)
    _seen(db_session, a, at(MON, 19, 50), EventType.OUT)     # 110 min after 18:00 -> 105 OT (15-min steps)
    await db_session.flush()

    ts = await build_timesheet(db_session, MON, MON)
    ra, rb = ts.records[(a.id, MON)], ts.records[(b.id, MON)]
    assert ra.status == "P"
    assert ra.late_minutes == 25
    assert ra.ot_minutes == 105
    assert ra.worked_minutes == 610
    assert rb.status == "A"


async def test_ot_below_minimum_is_ignored_and_weekly_off_work_is_all_ot(db_session, default_shift):
    a = await _person(db_session, "A2")
    _seen(db_session, a, at(MON, 9, 0))
    _seen(db_session, a, at(MON, 18, 20), EventType.OUT)     # 20 min < 30 min minimum
    sunday = date(2026, 9, 27)
    _seen(db_session, a, at(sunday, 10, 0))
    _seen(db_session, a, at(sunday, 14, 10), EventType.OUT)  # 250 min on the weekly off -> 240
    await db_session.flush()

    ts = await build_timesheet(db_session, MON, sunday)
    assert ts.records[(a.id, MON)].ot_minutes == 0
    sun = ts.records[(a.id, sunday)]
    assert sun.status == "WOP" and sun.ot_minutes == 240
    t = person_totals(ts, a.id)
    assert t["weekly_off"] == 0 and t["worked_on_off"] == 1
    assert t["absent"] == 5  # Tue-Sat
    assert t["lop_days"] == 5.0 and t["paid_days"] == 2.0


async def test_night_shift_is_one_day_not_two(db_session, default_shift, night_shift):
    n = await _person(db_session, "N1", shift=night_shift)
    _seen(db_session, n, at(MON, 22, 5))
    _seen(db_session, n, at(date(2026, 9, 22), 7, 0), EventType.OUT)  # next morning, 60 min after 06:00
    await db_session.flush()

    ts = await build_timesheet(db_session, MON, date(2026, 9, 22))
    mon = ts.records[(n.id, MON)]
    assert mon.status == "P"
    assert mon.worked_minutes == 535
    assert mon.late_minutes == 0
    assert mon.ot_minutes == 60
    assert ts.records[(n.id, date(2026, 9, 22))].status == "A"  # nothing that night


async def test_state_machine_keeps_night_shift_arrival(db_session, default_shift, night_shift):
    """Before the fix, 06:00 was 'IN of the next day' and a later sighting
    overwrote it; now both halves of the shift are one IN + one OUT."""
    n = await _person(db_session, "N2", shift=night_shift)
    resolver = await load_resolver(db_session, [n.id])

    def ev(ts: datetime, cid: str) -> RecognitionEventInput:
        return RecognitionEventInput(
            subject_type=SubjectType.EMPLOYEE, employee_id=n.id, unknown_identity_id=None, occurred_at=ts,
            similarity=0.9, liveness_score=0.9, kiosk_id="gate", crop_path=None, reject_reason=None,
            client_event_id=cid,
        )

    def day_of(ts: datetime):
        return resolver.attendance_date(n.id, ts)

    first, _ = await upsert_attendance_event(db_session, ev(at(MON, 22, 0), "e1"), 5, day_of=day_of)
    second, _ = await upsert_attendance_event(db_session, ev(at(date(2026, 9, 22), 6, 5), "e2"), 5, day_of=day_of)
    assert first.event_type == EventType.IN
    assert second.event_type == EventType.OUT


async def test_roster_rotation_overrides_fixed_shift_and_splits_ranges(client, admin_headers, db_session, default_shift, night_shift):
    p = await _person(db_session, "R1")
    await db_session.commit()
    r = await client.post("/api/v1/shifts/roster", headers=admin_headers, json={
        "employee_ids": [p.id], "shift_id": night_shift.id, "start_date": "2026-09-01", "end_date": "2026-09-30"})
    assert r.status_code == 201
    r = await client.post("/api/v1/shifts/roster", headers=admin_headers, json={
        "employee_ids": [p.id], "shift_id": default_shift.id, "start_date": "2026-09-10", "end_date": "2026-09-12"})
    assert r.status_code == 201
    rows = (await client.get("/api/v1/shifts/roster?date_from=2026-09-01&date_to=2026-09-30", headers=admin_headers)).json()
    assert [(x["shift_name"], x["start_date"], x["end_date"]) for x in rows] == [
        ("Night", "2026-09-01", "2026-09-09"),
        ("General", "2026-09-10", "2026-09-12"),
        ("Night", "2026-09-13", "2026-09-30"),
    ]
    resolver = await load_resolver(db_session, [p.id])
    assert resolver.shift_for(p.id, date(2026, 9, 11)).name == "General"
    assert resolver.shift_for(p.id, date(2026, 9, 20)).name == "Night"


async def test_shift_crud_accepts_json_and_keeps_one_default(client, admin_headers, default_shift):
    r = await client.post("/api/v1/shifts", headers=admin_headers, json={
        "name": "Morning", "in_time": "6:00", "out_time": "14:00", "grace_minutes": 10, "is_default": True})
    assert r.status_code == 201, r.text
    assert r.json()["in_time"] == "06:00"
    shifts = (await client.get("/api/v1/shifts", headers=admin_headers)).json()
    assert [s["name"] for s in shifts if s["is_default"]] == ["Morning"]
    bad = await client.post("/api/v1/shifts", headers=admin_headers, json={"name": "X", "in_time": "25:00", "out_time": "1:00"})
    assert bad.status_code == 422


async def test_contractor_report_and_csv(client, admin_headers, db_session, default_shift):
    a = await _person(db_session, "C1", contractor="Sharma Manpower")
    b = await _person(db_session, "C2", contractor="Sharma Manpower")
    c = await _person(db_session, "C3")
    for e in (a, b, c):
        _seen(db_session, e, at(MON, 9, 0))
    _seen(db_session, a, at(date(2026, 9, 22), 9, 0))
    await db_session.commit()

    r = await client.get("/api/v1/reports/contractors?date_from=2026-09-21&date_to=2026-09-22", headers=admin_headers)
    assert r.status_code == 200
    rows = {x["contractor"]: x for x in r.json()["contractors"]}
    sharma = rows["Sharma Manpower"]
    assert sharma["headcount"] == 2 and sharma["man_days"] == 3.0
    assert [d["present"] for d in sharma["daily"]] == [2, 1]
    assert rows["Own staff"]["man_days"] == 1.0

    names = (await client.get("/api/v1/reports/contractor-names", headers=admin_headers)).json()
    assert names == ["Sharma Manpower"]

    csv_r = await client.get("/api/v1/reports/contractors.csv?date_from=2026-09-21&date_to=2026-09-22", headers=admin_headers)
    lines = list(csv.reader(io.StringIO(csv_r.text.lstrip("\ufeff"))))
    assert lines[0][0] == "Contractor"
    assert ["Sharma Manpower", "TOTAL", "2", "", "", "3.0", "0.0"] in lines


async def test_payroll_formats(client, admin_headers, db_session, default_shift):
    await set_setting(db_session, "weekly_off_days", [5, 6])
    a = await _person(db_session, "P1")
    for day in range(1, 32):
        d = date(2026, 8, day)
        if d.weekday() < 5 and day != 14:
            _seen(db_session, a, at(d, 9, 0))
    await db_session.commit()

    r = await client.get("/api/v1/reports/payroll?month=2026-08&format=generic", headers=admin_headers)
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert rows[0]["Emp ID"] == "P1"
    assert rows[0]["Working days"] == "21" and rows[0]["Absent"] == "1"
    assert rows[0]["LOP days"] == "1.0" and rows[0]["Paid days"] == "30.0"

    keka = await client.get("/api/v1/reports/payroll?month=2026-08&format=keka", headers=admin_headers)
    assert keka.text.lstrip("﻿").splitlines()[0] == "Employee Number,Employee Name,Payable Days,Loss Of Pay Days,Overtime Hours"

    tally = await client.get("/api/v1/reports/payroll?month=2026-08&format=tally&tally_company=Acme", headers=admin_headers)
    assert tally.headers["content-type"].startswith("application/xml")
    assert "<SVCURRENTCOMPANY>Acme</SVCURRENTCOMPANY>" in tally.text
    assert "<NAME>Person P1</NAME><ATTENDANCETYPE>Present</ATTENDANCETYPE><ATTDTYPEVALUE> 30.0</ATTDTYPEVALUE>" in tally.text


async def test_muster_roll_grid(client, admin_headers, db_session, default_shift):
    a = await _person(db_session, "M1")
    _seen(db_session, a, at(date(2026, 8, 17), 9, 0))
    await db_session.commit()
    r = await client.get("/api/v1/reports/muster-roll.csv?date_from=2026-08-17&date_to=2026-08-23", headers=admin_headers)
    rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert rows[0][4:11] == ["17 Aug", "18 Aug", "19 Aug", "20 Aug", "21 Aug", "22 Aug", "23 Aug"]
    assert rows[1][4:11] == ["P", "A", "A", "A", "A", "A", "WO"]


async def test_report_range_is_capped(client, admin_headers):
    r = await client.get("/api/v1/reports/timesheet?date_from=2026-01-01&date_to=2026-12-31", headers=admin_headers)
    assert r.status_code == 422


async def test_future_days_are_not_absent(db_session, default_shift):
    from datetime import timedelta

    a = await _person(db_session, "F1")
    today = datetime.now(IST).date()
    ts = await build_timesheet(db_session, today, today + timedelta(days=3))
    assert [ts.records[(a.id, today + timedelta(days=i))].status for i in (1, 2, 3)] == ["-", "-", "-"]
