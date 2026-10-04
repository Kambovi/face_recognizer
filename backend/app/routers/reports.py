"""Reports that turn attendance into money: timesheet, contractor bill
check, payroll export, muster roll. All built on services/timesheet.py.

  GET /reports/timesheet          per person-day rows (JSON)
  GET /reports/contractors        per contractor: headcount, man-days, OT (JSON)
  GET /reports/contractors.csv    same, one row per contractor per day
  GET /reports/contractor-names   distinct contractor names (form suggestions)
  GET /reports/payroll            month summary in a payroll tool's import format
  GET /reports/muster-roll.csv    person x day grid of P / A / HD / WO codes

CSV files carry a UTF-8 BOM so Excel opens Hindi / accented names correctly.
"""
from __future__ import annotations

import calendar
import io
from collections import defaultdict
from datetime import date
from typing import Any, Literal
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import csvsafe
from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.employees import Employee
from app.models.users import User
from app.services.timesheet import Timesheet, build_timesheet, person_totals

router = APIRouter(prefix="/reports", tags=["reports"])

OWN_STAFF = "Own staff"
MAX_DAYS = 92


def _check_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_range", "date_to is before date_from")
    if (date_to - date_from).days + 1 > MAX_DAYS:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_range", f"At most {MAX_DAYS} days per report")


def _csv(rows: list[list[Any]], filename: str) -> Response:
    buf = io.StringIO()
    buf.write("﻿")
    csvsafe.writer(buf).writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _person_info(p: Employee) -> dict[str, Any]:
    return {
        "employee_id": p.id,
        "emp_code": p.emp_code,
        "name": p.name,
        "department": p.department,
        "contractor": p.contractor or OWN_STAFF,
    }


# ---------------------------------------------------------------- timesheet
@router.get("/timesheet")
async def timesheet(
    date_from: date,
    date_to: date,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _check_range(date_from, date_to)
    ts = await build_timesheet(db, date_from, date_to, contractor=None if contractor is None else
                               ("" if contractor == OWN_STAFF else contractor))
    people = []
    for p in ts.people:
        people.append({
            **_person_info(p),
            "totals": person_totals(ts, p.id),
            "days": [r.as_dict() for r in ts.for_person(p.id)],
        })
    return {"date_from": date_from, "date_to": date_to, "people": people}


# ---------------------------------------------------------------- contractors
def _contractor_rollup(ts: Timesheet) -> list[dict[str, Any]]:
    groups: dict[str, list[Employee]] = defaultdict(list)
    for p in ts.people:
        groups[p.contractor or OWN_STAFF].append(p)
    out: list[dict[str, Any]] = []
    for name, members in groups.items():
        daily: list[dict[str, Any]] = []
        for d in ts.days:
            recs = [ts.records[(p.id, d)] for p in members if (p.id, d) in ts.records]
            on_roll = [r for r in recs if r.status != "-"]
            daily.append({
                "date": d.isoformat(),
                "on_roll": len(on_roll),
                "present": sum(1 for r in recs if r.status in ("P", "WOP")),
                "half_day": sum(1 for r in recs if r.status == "HD"),
                "man_days": sum(r.present_value for r in recs),
                "ot_hours": round(sum(r.ot_minutes for r in recs) / 60, 2),
            })
        totals = [person_totals(ts, p.id) for p in members]
        out.append({
            "contractor": name,
            "headcount": len(members),
            "man_days": round(sum(d["man_days"] for d in daily), 1),
            "ot_hours": round(sum(t["ot_hours"] for t in totals), 2),
            "worked_hours": round(sum(t["worked_hours"] for t in totals), 2),
            "late_days": sum(int(t["late_days"]) for t in totals),
            "avg_daily_present": round(sum(d["present"] for d in daily) / max(1, len(daily)), 1),
            "daily": daily,
            "people": [
                {**_person_info(p), **person_totals(ts, p.id)} for p in sorted(members, key=lambda m: m.emp_code)
            ],
        })
    out.sort(key=lambda r: (r["contractor"] == OWN_STAFF, -r["headcount"], r["contractor"]))
    return out


@router.get("/contractors")
async def contractors_report(
    date_from: date, date_to: date, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> dict[str, Any]:
    _check_range(date_from, date_to)
    ts = await build_timesheet(db, date_from, date_to)
    return {"date_from": date_from, "date_to": date_to, "contractors": _contractor_rollup(ts)}


@router.get("/contractors.csv")
async def contractors_csv(
    date_from: date, date_to: date, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> Response:
    _check_range(date_from, date_to)
    ts = await build_timesheet(db, date_from, date_to)
    rows: list[list[Any]] = [["Contractor", "Date", "On roll", "Present", "Half day", "Man-days", "OT hours"]]
    for c in _contractor_rollup(ts):
        for d in c["daily"]:
            rows.append([c["contractor"], d["date"], d["on_roll"], d["present"], d["half_day"], d["man_days"], d["ot_hours"]])
        rows.append([c["contractor"], "TOTAL", c["headcount"], "", "", c["man_days"], c["ot_hours"]])
    return _csv(rows, f"contractors_{date_from}_{date_to}.csv")


@router.get("/contractor-names", response_model=list[str])
async def contractor_names(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[str]:
    rows = await db.execute(
        select(Employee.contractor).where(Employee.contractor.is_not(None)).distinct().order_by(Employee.contractor)
    )
    return [r for (r,) in rows.all() if r]


# ---------------------------------------------------------------- payroll
PayrollFormat = Literal["generic", "tally", "zoho", "greythr", "keka"]

# Column headers per payroll tool's attendance / LOP import. The values are
# the same everywhere; only names differ. Check them against the client's
# own downloaded template once and adjust here if their account differs.
PAYROLL_HEADERS: dict[str, list[tuple[str, str]]] = {
    "zoho": [("Employee ID", "emp_code"), ("Employee Name", "name"), ("Paid Days", "paid_days"),
             ("LOP Days", "lop_days"), ("Overtime Hours", "ot_hours")],
    "greythr": [("Employee No", "emp_code"), ("Employee Name", "name"), ("Paid Days", "paid_days"),
                ("LOP Days", "lop_days"), ("OT Hours", "ot_hours")],
    "keka": [("Employee Number", "emp_code"), ("Employee Name", "name"), ("Payable Days", "paid_days"),
             ("Loss Of Pay Days", "lop_days"), ("Overtime Hours", "ot_hours")],
}
GENERIC_COLUMNS: list[tuple[str, str]] = [
    ("Emp ID", "emp_code"), ("Name", "name"), ("Department", "department"), ("Contractor", "contractor"),
    ("Days in month", "days_in_range"), ("Working days", "working_days"), ("Present", "present"),
    ("Half days", "half_days"), ("Absent", "absent"), ("Leave", "leave"), ("Unpaid leave", "unpaid_leave"),
    ("Weekly off", "weekly_off"),
    ("Worked on weekly off", "worked_on_off"), ("Paid days", "paid_days"), ("LOP days", "lop_days"),
    ("Late days", "late_days"), ("Late minutes", "late_minutes"), ("OT hours", "ot_hours"),
    ("Worked hours", "worked_hours"),
]


def _tally_xml(month_end: date, rows: list[dict[str, Any]], company: str) -> str:
    """Tally Prime 'Attendance' voucher import. Employee names must match
    the employee ledgers in Tally, and the attendance types ('Present',
    'Overtime') must exist in the company (Payroll > Attendance/Production
    Types) -- the names are query parameters so they can be matched."""
    entries = []
    for r in rows:
        for typ, value, unit in ((r["_present_type"], r["paid_days"], ""), (r["_ot_type"], r["ot_hours"], " Hrs")):
            if not value:
                continue
            entries.append(
                "<ATTENDANCEENTRIES.LIST>"
                f"<NAME>{escape(r['name'])}</NAME>"
                f"<ATTENDANCETYPE>{escape(typ)}</ATTENDANCETYPE>"
                f"<ATTDTYPEVALUE> {value}{unit}</ATTDTYPEVALUE>"
                "</ATTENDANCEENTRIES.LIST>"
            )
    return (
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>"
        "<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>"
        "<REQUESTDATA><TALLYMESSAGE xmlns:UDF=\"TallyUDF\">"
        '<VOUCHER VCHTYPE="Attendance" ACTION="Create">'
        f"<DATE>{month_end.strftime('%Y%m%d')}</DATE><VOUCHERTYPENAME>Attendance</VOUCHERTYPENAME>"
        f"<NARRATION>Face attendance {month_end.strftime('%b %Y')}</NARRATION>"
        + "".join(entries)
        + "</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
    )


@router.get("/payroll")
async def payroll_export(
    month: str = Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
    format: PayrollFormat = "generic",
    contractor: str | None = None,
    tally_company: str = "Company",
    tally_present_type: str = "Present",
    tally_ot_type: str = "Overtime",
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    y, m = (int(x) for x in month.split("-"))
    if not 1 <= m <= 12:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_month", "month must be YYYY-MM")
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    ts = await build_timesheet(db, start, end, contractor=None if contractor is None else
                               ("" if contractor == OWN_STAFF else contractor))
    rows = [{**_person_info(p), **person_totals(ts, p.id)} for p in ts.people]
    rows = [r for r in rows if r["days_in_range"] > 0]
    if format == "tally":
        for r in rows:
            r["_present_type"], r["_ot_type"] = tally_present_type, tally_ot_type
        return Response(
            content=_tally_xml(end, rows, tally_company),
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="tally_attendance_{month}.xml"'},
        )
    cols = PAYROLL_HEADERS.get(format, GENERIC_COLUMNS)
    table: list[list[Any]] = [[h for h, _ in cols]] + [[r.get(k, "") for _, k in cols] for r in rows]
    return _csv(table, f"payroll_{format}_{month}.csv")


# ---------------------------------------------------------------- monthly PDF
@router.get("/monthly.pdf")
async def monthly_report_pdf(
    month: str = Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    from app.services.pdf_report import monthly_pdf

    y, m = (int(x) for x in month.split("-"))
    if not 1 <= m <= 12:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_month", "month must be YYYY-MM")
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    pdf = await monthly_pdf(db, start, end)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="attendance_{month}.pdf"'})


# ---------------------------------------------------------------- muster roll
@router.get("/muster-roll.csv")
async def muster_roll(
    date_from: date,
    date_to: date,
    contractor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Response:
    """Register-style grid: one row per person, one column per day (P / A /
    HD / WO / WOP), then totals -- what labour inspectors and contractors
    ask to see."""
    _check_range(date_from, date_to)
    ts = await build_timesheet(db, date_from, date_to, contractor=None if contractor is None else
                               ("" if contractor == OWN_STAFF else contractor))
    header = ["Emp ID", "Name", "Department", "Contractor"] + [d.strftime("%d %b") for d in ts.days] + [
        "Present", "Half days", "Absent", "Leave", "Weekly off", "Paid days", "OT hours"]
    rows: list[list[Any]] = [header]
    for p in ts.people:
        t = person_totals(ts, p.id)
        codes = [ts.records[(p.id, d)].status for d in ts.days]
        rows.append([p.emp_code, p.name, p.department or "", p.contractor or OWN_STAFF, *codes,
                     t["present"], t["half_days"], t["absent"], t["leave"] + t["unpaid_leave"], t["weekly_off"], t["paid_days"], t["ot_hours"]])
    return _csv(rows, f"muster_roll_{date_from}_{date_to}.csv")
