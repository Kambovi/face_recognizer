"""HR core (holidays, joining/leaving dates, go-live, weekly offs, leave
types/balances, half days) and statutory payroll (PF / ESI / PT, runs,
lock, files)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.models.employees import Employee
from app.models.holidays import Holiday
from app.models.leaves import Leave
from app.security import create_access_token
from app.services import statutory as st
from app.services.payroll import PayslipInput, compute_payslip, structure
from app.services.settings_service import DEFAULT_SETTINGS, set_setting
from app.services.timesheet import build_timesheet, person_totals
from tests.test_timesheet_reports import _seen

IST = ZoneInfo("Asia/Kolkata")
CFG = dict(DEFAULT_SETTINGS)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=IST)


async def _emp(db, code, *, created=datetime(2026, 1, 1, tzinfo=IST), doj=None, dol=None, active=True,
               salary=30000, weekly_off=None, shift=None) -> Employee:
    e = Employee(face_id=f"F-{code}", emp_code=code, name=f"Person {code}", department="Ops", created_at=created,
                 date_of_joining=doj, date_of_leaving=dol, is_active=active, monthly_salary=salary,
                 weekly_off_days=weekly_off, shift_id=shift.id if shift else None)
    db.add(e)
    await db.flush()
    return e


def _work_all(db, e, d1: date, d2: date, skip_sundays=True):
    d = d1
    while d <= d2:
        if not (skip_sundays and d.weekday() == 6):
            _seen(db, e, at(d, 9))
        d = date.fromordinal(d.toordinal() + 1)


# ------------------------------------------------------------------ timesheet
async def test_holiday_is_paid_and_work_on_it_is_overtime(db_session, default_shift):
    e = await _emp(db_session, "H1")
    db_session.add(Holiday(day=date(2026, 10, 2), name="Gandhi Jayanti", kind="national"))
    _seen(db_session, e, at(date(2026, 8, 15), 9))
    _seen(db_session, e, at(date(2026, 8, 15), 13))
    db_session.add(Holiday(day=date(2026, 8, 15), name="Independence Day", kind="national"))
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 10, 2), date(2026, 10, 2))
    t = person_totals(ts, e.id)
    assert ts.records[(e.id, date(2026, 10, 2))].status == "H" and t["lop_days"] == 0 and t["paid_days"] == 1
    ts = await build_timesheet(db_session, date(2026, 8, 15), date(2026, 8, 15))
    r = ts.records[(e.id, date(2026, 8, 15))]
    assert r.status == "HP" and r.ot_minutes == 240


async def test_install_month_existing_staff_are_paid_for_days_before_go_live(db_session, default_shift):
    # the audit's case: system installed 15 Sep, everyone added that day
    e = await _emp(db_session, "G1", created=datetime(2026, 9, 15, 10, tzinfo=IST))
    await set_setting(db_session, "attendance_start_date", "2026-09-15")
    _work_all(db_session, e, date(2026, 9, 15), date(2026, 9, 30))
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 9, 1), date(2026, 9, 30))
    t = person_totals(ts, e.id)
    assert ts.records[(e.id, date(2026, 9, 3))].status == "NT"
    assert t["paid_days"] == 30 and t["lop_days"] == 0


async def test_new_joiner_is_prorated_from_joining_date(db_session, default_shift):
    e = await _emp(db_session, "J1", doj=date(2026, 9, 21), created=datetime(2026, 9, 10, tzinfo=IST))
    _work_all(db_session, e, date(2026, 9, 21), date(2026, 9, 30))
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 9, 1), date(2026, 9, 30))
    t = person_totals(ts, e.id)
    assert ts.records[(e.id, date(2026, 9, 20))].status == "-"
    assert t["days_in_range"] == 10 and t["paid_days"] == 10


async def test_leaver_stays_in_their_last_payroll(db_session, default_shift):
    e = await _emp(db_session, "L1", dol=date(2026, 9, 20), active=False)
    _work_all(db_session, e, date(2026, 9, 1), date(2026, 9, 20))
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 9, 1), date(2026, 9, 30))
    assert any(p.id == e.id for p in ts.people)
    t = person_totals(ts, e.id)
    assert t["days_in_range"] == 20 and t["paid_days"] == 20
    ts_oct = await build_timesheet(db_session, date(2026, 10, 1), date(2026, 10, 31))
    assert not any(p.id == e.id for p in ts_oct.people)


async def test_own_weekly_off_and_rostered_off_day(db_session, default_shift):
    e = await _emp(db_session, "W1", weekly_off=[2])  # Wednesdays off
    db_session.add(Leave(employee_id=e.id, day=date(2026, 9, 21), kind="off"))  # Monday swapped off
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 9, 20), date(2026, 9, 23))
    st_ = {d.isoformat(): ts.records[(e.id, d)].status for d in ts.days}
    assert st_ == {"2026-09-20": "A", "2026-09-21": "WO", "2026-09-22": "A", "2026-09-23": "WO"}


async def test_half_day_leave(db_session, default_shift):
    e = await _emp(db_session, "HL")
    db_session.add(Leave(employee_id=e.id, day=date(2026, 9, 22), kind="paid", leave_type="CL", portion=0.5))
    db_session.add(Leave(employee_id=e.id, day=date(2026, 9, 23), kind="paid", leave_type="CL", portion=0.5))
    _seen(db_session, e, at(date(2026, 9, 23), 13))
    await db_session.flush()
    ts = await build_timesheet(db_session, date(2026, 9, 22), date(2026, 9, 23))
    a, b = ts.records[(e.id, date(2026, 9, 22))], ts.records[(e.id, date(2026, 9, 23))]
    assert a.status == "HL" and a.paid_value == 0.5     # half leave, half absent
    assert b.status == "P" and b.paid_value == 1        # came in: full day


# ------------------------------------------------------------------ leave API
async def test_leave_types_balance_and_off_days_skipped(client, admin_headers, db_session):
    e = await _emp(db_session, "LB", doj=date(2026, 1, 1))
    await db_session.commit()
    bal = (await client.get(f"/api/v1/leaves/balance/{e.id}?on=2026-03-15", headers=admin_headers)).json()
    cl = next(b for b in bal if b["code"] == "CL")
    assert cl["credited"] == 3 and cl["balance"] == 3  # 12/yr monthly accrual, Jan-Mar
    # Mon 16 .. Sun 22 Mar: Sunday skipped -> 6 days > 3 balance -> refused
    body = {"employee_id": e.id, "date_from": "2026-03-16", "date_to": "2026-03-22", "leave_type": "CL"}
    r = await client.post("/api/v1/leaves", json=body, headers=admin_headers)
    assert r.status_code == 422 and r.json()["code"] == "insufficient_balance"
    r = await client.post("/api/v1/leaves", json={**body, "date_to": "2026-03-18"}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["days"] == 3
    bal = (await client.get(f"/api/v1/leaves/balance/{e.id}?on=2026-03-31", headers=admin_headers)).json()
    assert next(b for b in bal if b["code"] == "CL")["balance"] == 0
    r = await client.post("/api/v1/leaves", json={**body, "date_from": "2026-03-19", "date_to": "2026-03-19",
                                                  "force": True}, headers=admin_headers)
    assert r.status_code == 201


# ------------------------------------------------------------------ statutory maths
def test_pf_ceiling_follows_effective_date():
    hist = CFG["pf_wage_ceiling_history"]
    assert st.pf_ceiling(date(2026, 8, 31), hist) == 15000
    assert st.pf_ceiling(date(2026, 10, 31), hist) == 25000
    pf = st.provident_fund(40000, 25000, CFG)
    assert (pf.epf_wage, pf.employee, pf.eps, pf.employer_epf) == (25000, 3000, 2083, 917)  # 1250 at the old 15k ceiling
    full = st.provident_fund(40000, 25000, CFG, full_wage=True)
    assert full.employee == 4800 and full.eps == 2083  # pension stays capped


def test_labour_code_50_percent_rule():
    # basic 30k of 100k -> wages become 50k
    assert st.code_wages({"basic": 30000, "hra": 20000, "special": 50000}) == 50000
    assert st.code_wages({"basic": 60000, "hra": 40000}) == 60000


def test_esi_rounds_up_and_low_wage_exemption():
    assert st.esi(18000, 30, CFG) == (135, 585)
    assert st.esi(4500, 30, CFG) == (0, 147)  # Rs 150/day <= 176: no employee share


def test_professional_tax_rules():
    assert st.professional_tax("MH", 10, 20000, "M") == 200
    assert st.professional_tax("MH", 2, 20000, "M") == 300
    assert st.professional_tax("MH", 10, 20000, "F") == 0      # women up to 25k exempt
    assert st.professional_tax("KA", 10, 24000) == 0
    assert st.professional_tax("TN", 10, 20000) == 0             # half-yearly: Sep / Mar only
    assert st.professional_tax("TN", 9, 20000, half_year_gross=120000) == 1250
    assert st.professional_tax("", 10, 90000) == 0


def test_payslip_maths_end_to_end():
    full = structure(30000, None, CFG)
    assert full == {"basic": 15000, "da": 0.0, "hra": 6000, "conveyance": 0.0, "special": 9000, "other": 0.0}
    inp = PayslipInput(employee_id="x", emp_code="E1", name="A", department=None, designation=None, month="2026-10",
                       full=full, totals={"paid_days": 29, "days_in_range": 31, "ot_hours": 0},
                       profile={"pt_state": "MH", "gender": "M", "has_bank": True, "ifsc": "HDFC0000001",
                                "uan": "100000000001"},
                       adjustments=[{"kind": "deduction", "label": "Advance", "amount": 1000}],
                       date_of_joining="2020-01-01")
    s = compute_payslip(inp, CFG)
    # 29/31 of 30,000
    assert s["gross"] == 14032 + 5613 + 8419
    assert s["pf"]["pf_wage"] == 14032 and s["pf"]["employee"] == 1684
    assert s["esi"] is None  # 30k > 21k
    ded = {d["label"]: d["amount"] for d in s["deductions"]}
    assert ded["Professional tax (MH)"] == 200 and ded["Advance"] == 1000
    assert s["net"] == s["gross"] - 1684 - 200 - 1000
    assert s["warnings"] == []


# ------------------------------------------------------------------ payroll API
async def test_payroll_run_lock_and_files(client, admin_headers, admin_user, db_session, viewer_user, default_shift):
    await set_setting(db_session, "payroll_state", "MH")
    e = await _emp(db_session, "P1", salary=18000, doj=date(2025, 1, 1))
    _work_all(db_session, e, date(2026, 9, 1), date(2026, 9, 30))
    await db_session.commit()
    prof = {"gender": "M", "uan": "100000000001", "esic_ip": "1234567890", "pan": "abcde1234f",
            "bank_name": "HDFC", "bank_account": "50100012345678", "ifsc": "hdfc0001234"}
    r = await client.put(f"/api/v1/payroll/profile/{e.id}", json=prof, headers=admin_headers)
    assert r.status_code == 200 and r.json()["pan_masked"] == "******234F"
    assert r.json()["bank_account_masked"].endswith("5678") and "5010001" not in r.json()["bank_account_masked"]

    viewer = {"Authorization": f"Bearer {create_access_token(viewer_user.id, 'viewer')}"}
    assert (await client.post("/api/v1/payroll/runs/2026-09/generate", headers=viewer)).status_code == 403

    r = await client.post("/api/v1/payroll/runs/2026-09/generate", headers=admin_headers)
    assert r.status_code == 200
    slip = r.json()["payslips"][0]
    assert slip["paid_days"] == 30 and slip["gross"] == 18000
    assert slip["esi"]["employee"] == 135 and slip["pf"]["employee"] == 1080  # 12% of basic 9000
    assert r.json()["totals"]["people"] == 1

    pdf = await client.get("/api/v1/payroll/runs/2026-09/payslips.pdf", headers=admin_headers)
    assert pdf.content[:4] == b"%PDF"
    ecr = (await client.get("/api/v1/payroll/runs/2026-09/ecr.txt", headers=admin_headers)).text.strip()
    assert ecr.split("#~#")[:3] == ["100000000001", "PERSON P1", "18000"]
    bank = list(csv.reader(io.StringIO((await client.get("/api/v1/payroll/runs/2026-09/bank.csv",
                                                          headers=admin_headers)).text.lstrip("﻿"))))
    assert bank[1][1] == "50100012345678" and bank[1][2] == "HDFC0001234"

    # lock: September attendance / leave / adjustments frozen
    assert (await client.post("/api/v1/payroll/runs/2026-09/lock", headers=admin_headers)).json()["status"] == "locked"
    r = await client.post("/api/v1/leaves", headers=admin_headers,
                          json={"employee_id": e.id, "date_from": "2026-09-10", "date_to": "2026-09-10", "kind": "unpaid"})
    assert r.status_code == 409 and r.json()["code"] == "month_locked"
    r = await client.post("/api/v1/attendance/events/manual", headers=admin_headers,
                          json={"employee_id": e.id, "event_type": "IN", "occurred_at": "2026-09-12T09:00:00+05:30",
                                "reason": "forgot"})
    assert r.status_code == 409
    assert (await client.post("/api/v1/payroll/runs/2026-09/generate", headers=admin_headers)).status_code == 409
    # HR can't unlock, admin can
    hr = admin_user  # same db; make an HR token for a fresh user
    from app.models.enums import UserRole
    from app.models.users import User
    from app.security import hash_password

    hr = User(email="hr2@example.org", password_hash=hash_password("x"), role=UserRole.HR)
    db_session.add(hr)
    await db_session.commit()
    hr_h = {"Authorization": f"Bearer {create_access_token(hr.id, 'hr')}"}
    assert (await client.post("/api/v1/payroll/runs/2026-09/unlock", headers=hr_h)).status_code == 403
    assert (await client.post("/api/v1/payroll/runs/2026-09/unlock", headers=admin_headers)).json()["status"] == "draft"


@pytest.mark.parametrize("n,words", [(0, "Zero"), (15, "Fifteen"), (123456, "One Lakh Twenty Three Thousand Four Hundred Fifty Six"),
                                     (10000000, "One Crore")])
def test_amount_in_words(n, words):
    from app.services.payroll_files import amount_in_words

    assert amount_in_words(n) == words
