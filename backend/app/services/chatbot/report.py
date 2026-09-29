"""The attendance + payroll summary for one confirmed target and month.

Built straight from the timesheet (services/timesheet.py) -- the same
numbers as the payroll export -- never by the language model.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.services.payroll import payable_salary
from app.services.shiftday import LOCAL_TZ
from app.services.timesheet import build_timesheet, person_totals

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS.update({"sept": 9, "janvari": 1, "farvari": 2, "march": 3, "aprail": 4, "mai": 5, "joon": 6,
               "julai": 7, "agast": 8, "sitambar": 9, "aktubar": 10, "navambar": 11, "disambar": 12})


def today() -> date:
    return datetime.now(LOCAL_TZ).date()


def parse_month(text: str | None, now: date | None = None) -> str:
    """'2026-08', 'august', 'aug 2025', 'last month', 'pichle mahine' -> YYYY-MM.
    Anything else -> the current month."""
    now = now or today()
    t = (text or "").lower()
    m = re.search(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    if re.search(r"last month|previous month|pichl[ea] mahin[ea]|pichhl[ea] mahin[ea]|gaye mahine", t):
        prev = now.replace(day=1) - timedelta(days=1)
        return prev.strftime("%Y-%m")
    for word in re.findall(r"[a-z]+", t):
        if word in MONTHS:
            y = re.search(r"\b(20\d\d)\b", t)
            mon = MONTHS[word]
            year = int(y.group(1)) if y else (now.year if mon <= now.month else now.year - 1)
            return f"{year}-{mon:02d}"
    return now.strftime("%Y-%m")


def parse_date(text: str | None, now: date | None = None) -> str | None:
    """A single day in the text, or None: '2026-09-28', '28/09', '28 sep',
    'sep 28', 'aaj' / 'today', 'kal' / 'yesterday'."""
    now = now or today()
    t = (text or "").lower()
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    if re.search(r"\b(aaj|today)\b", t):
        return now.isoformat()
    if re.search(r"\b(kal|yesterday)\b", t):  # 'kal' in a question about the past = yesterday
        return (now - timedelta(days=1)).isoformat()
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t)
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        year += 2000 if year < 100 else 0
    else:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\b", t) or re.search(r"\b([a-z]+)\s+(\d{1,2})\b", t)
        if not m:
            return None
        a, b = m.group(1), m.group(2)
        word, num = (b, a) if a.isdigit() else (a, b)
        if word not in MONTHS:
            return None
        day, mon = int(num), MONTHS[word]
        y = re.search(r"\b(20\d\d)\b", t)
        year = int(y.group(1)) if y else now.year
    try:
        d = date(year, mon, day)
    except ValueError:
        return None
    if d > now and not re.search(r"\b20\d\d\b", t):
        d = d.replace(year=d.year - 1)
    return d.isoformat()


def shift_month(month: str, by: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    m += by
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y}-{m:02d}"


def _nav(kind: str, target: str, report: str, month: str, day: str | None, camera: str | None = None) -> dict[str, Any]:
    """Prev / next buttons on the report card, as ready-made actions."""
    base: dict[str, Any] = {"type": "report", "kind": kind, "id": target, "report": report}
    if camera:
        base["camera"] = camera
    if day:
        d = date.fromisoformat(day)
        nxt = d + timedelta(days=1)
        return {"prev": {**base, "date": (d - timedelta(days=1)).isoformat(), "label": "Previous day"},
                "next": {**base, "date": nxt.isoformat(), "label": "Next day"} if nxt <= today() else None}
    nxt_m = shift_month(month, 1)
    return {"prev": {**base, "month": shift_month(month, -1), "label": "Previous month"},
            "next": {**base, "month": nxt_m, "label": "Next month"} if nxt_m <= today().strftime("%Y-%m") else None}


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


async def _people_for(db: AsyncSession, kind: str, target: str, start: date, end: date) -> tuple[list[Employee], str]:
    base = select(Employee).where(Employee.deleted_at.is_(None))
    if kind == "employee":
        rows = (await db.execute(base.where(Employee.id == target))).scalars().all()
        title = f"{rows[0].name} ({rows[0].emp_code})" if rows else target
    elif kind == "department":
        cond = Employee.department.is_(None) if target == "No department" else Employee.department == target
        rows = (await db.execute(base.where(cond, Employee.is_active.is_(True)))).scalars().all()
        title = f"Department: {target}"
    elif kind == "contractor":
        rows = (await db.execute(base.where(Employee.contractor == target, Employee.is_active.is_(True)))).scalars().all()
        title = f"Contractor: {target}"
    elif kind == "camera":
        lo = datetime.combine(start, time.min, tzinfo=LOCAL_TZ)
        hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
        seen = select(AttendanceEvent.employee_id).where(
            AttendanceEvent.kiosk_id == target, AttendanceEvent.employee_id.is_not(None),
            AttendanceEvent.occurred_at >= lo, AttendanceEvent.occurred_at < hi,
        )
        rows = (await db.execute(base.where(or_(Employee.home_kiosk_id == target, Employee.id.in_(seen))))).scalars().all()
        title = f"Camera: {target}"
    else:
        raise ValueError(f"unknown target kind {kind!r}")
    return sorted(rows, key=lambda p: p.emp_code), title


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "-"
    s = f"{int(round(v)):,}"
    return f"₹{s}"


async def build_report(db: AsyncSession, kind: str, target: str, month: str, include_salary: bool) -> dict[str, Any]:
    start, end = month_bounds(month)
    people, title = await _people_for(db, kind, target, start, end)
    ts = await build_timesheet(db, start, end, employee_ids=[p.id for p in people]) if people else None

    columns: list[dict[str, Any]] = [
        {"key": "emp_code", "label": "Emp ID"}, {"key": "name", "label": "Name"},
        {"key": "department", "label": "Dept"}, {"key": "present", "label": "Present"},
        {"key": "half_days", "label": "Half day"}, {"key": "absent", "label": "Absent"},
        {"key": "leave", "label": "Leave"}, {"key": "late_days", "label": "Late (days)"},
        {"key": "ot_hours", "label": "OT hrs"}, {"key": "paid_days", "label": "Paid days"},
    ]
    if include_salary:
        columns += [{"key": "salary", "label": "Salary / month", "money": True},
                    {"key": "payable", "label": "Payable", "money": True}]

    rows: list[dict[str, Any]] = []
    for p in people:
        t = person_totals(ts, p.id) if ts else {}
        if not t or t["days_in_range"] == 0:
            continue
        row = {
            "employee_id": p.id, "emp_code": p.emp_code, "name": p.name, "department": p.department or "-",
            "present": t["present"] + t["worked_on_off"], "half_days": t["half_days"], "absent": t["absent"],
            "leave": t["leave"] + t["unpaid_leave"], "unpaid_leave": t["unpaid_leave"],
            "late_days": t["late_days"], "late_minutes": t["late_minutes"], "ot_hours": t["ot_hours"],
            "paid_days": t["paid_days"], "lop_days": t["lop_days"],
        }
        if include_salary:
            sal = float(p.monthly_salary) if p.monthly_salary is not None else None
            row["salary"] = sal
            row["payable"] = payable_salary(sal, t["paid_days"], start)
        rows.append(row)

    num_keys = ["present", "half_days", "absent", "leave", "late_days", "ot_hours", "paid_days"]
    if include_salary:
        num_keys += ["salary", "payable"]
    totals: dict[str, Any] = {"emp_code": "", "name": f"Total ({len(rows)})", "department": ""}
    for k in num_keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        totals[k] = round(sum(vals), 2) if vals else None

    last_day = min(end, today())
    upto = f" (till {last_day.strftime('%d %b')})" if start <= today() < end else ""
    month_label = start.strftime("%B %Y") + upto

    details = None
    if kind == "employee" and rows and ts:
        details = {
            "columns": [{"key": "date", "label": "Date"}, {"key": "status", "label": "Status"},
                        {"key": "in", "label": "In"}, {"key": "out", "label": "Out"},
                        {"key": "late", "label": "Late (min)"}, {"key": "ot", "label": "OT (min)"}],
            "rows": [
                {"date": r.day.strftime("%a %d"), "status": r.status,
                 "in": r.as_dict()["first_seen"] or "-", "out": r.as_dict()["last_seen"] or "-",
                 "late": r.late_minutes or "", "ot": r.ot_minutes or ""}
                for r in ts.for_person(people[0].id) if r.status != "-"
            ],
        }

    return {
        "kind": kind, "target": target, "title": title, "month": month, "month_label": month_label,
        "columns": columns, "rows": rows, "totals": totals if len(rows) > 1 else None,
        "details": details, "summary": summary_text(kind, title, month_label, rows, totals, include_salary),
        "salary_hidden": not include_salary,
        "report": "attendance", "date": None, "nav": _nav(kind, target, "attendance", month, None),
    }


def summary_text(kind: str, title: str, month_label: str, rows: list[dict[str, Any]],
                 totals: dict[str, Any], include_salary: bool) -> str:
    if not rows:
        return f"{title}: no attendance data for {month_label}."
    if len(rows) == 1:
        r = rows[0]
        parts = [f"{r['present']} present", f"{r['absent']} absent"]
        if r["half_days"]:
            parts.append(f"{r['half_days']} half day")
        if r["leave"]:
            parts.append(f"{r['leave']} leave" + (f" ({r['unpaid_leave']} unpaid)" if r["unpaid_leave"] else ""))
        parts.append(f"late on {r['late_days']} day(s)" if r["late_days"] else "never late")
        if r["ot_hours"]:
            parts.append(f"{r['ot_hours']} h OT")
        s = f"{r['name']} ({r['emp_code']}), {month_label}: " + ", ".join(parts) + f". Paid days {r['paid_days']}."
        if include_salary:
            s += (f" Payable {_fmt_money(r['payable'])} of {_fmt_money(r['salary'])}." if r.get("salary") is not None
                  else " Salary not set for this person.")
        return s
    n = len(rows)
    worst_absent = max(rows, key=lambda r: r["absent"])
    worst_late = max(rows, key=lambda r: r["late_days"])
    s = (f"{title}, {month_label}: {n} people, {totals['present']} present-days, {totals['absent']} absent-days, "
         f"{totals['leave']} leave-days, {totals['late_days']} late-days, {totals['ot_hours']} h OT.")
    if worst_absent["absent"]:
        s += f" Most absent: {worst_absent['name']} ({worst_absent['absent']})."
    if worst_late["late_days"]:
        s += f" Most late: {worst_late['name']} ({worst_late['late_days']} days)."
    if include_salary and totals.get("payable") is not None:
        s += f" Total payable {_fmt_money(totals['payable'])}."
    return s


async def build_detection_report(
    db: AsyncSession, kind: str, target: str, month: str, day: str | None, camera: str | None = None,
) -> dict[str, Any]:
    """How many times each person was seen, per camera: for one day, or per
    day across a month. From the sightings log (models/sightings.py)."""
    from app.services.sightings import counts

    start, end = (date.fromisoformat(day),) * 2 if day else month_bounds(month)
    people, title = await _people_for(db, kind, target, start, end)
    by_id = {p.id: p for p in people}
    data = await counts(db, list(by_id), start, end, kiosk_id=camera)
    rows = []
    for c in data:
        p = by_id[c["employee_id"]]
        rows.append({"date": c["date"].strftime("%a %d %b"), "emp_code": p.emp_code, "name": p.name,
                     "camera": c["kiosk_id"], "count": c["count"], "first": c["first"], "last": c["last"]})
    single = kind == "employee"
    cols = ([] if day else [{"key": "date", "label": "Date"}]) + \
        ([] if single else [{"key": "emp_code", "label": "Emp ID"}, {"key": "name", "label": "Name"}]) + [
        {"key": "camera", "label": "Camera"}, {"key": "count", "label": "Times seen"},
        {"key": "first", "label": "First"}, {"key": "last", "label": "Last"}]
    period = date.fromisoformat(day).strftime("%d %b %Y") if day else start.strftime("%B %Y")
    where = f" at {camera}" if camera else ""
    total = sum(r["count"] for r in rows)
    if not rows:
        summary = f"{title}: not seen{where} on {period}." if day else f"{title}: not seen{where} in {period}."
    elif single:
        per_cam: dict[str, int] = {}
        for r in rows:
            per_cam[r["camera"]] = per_cam.get(r["camera"], 0) + r["count"]
        parts = ", ".join(f"{k} {v}x" for k, v in per_cam.items())
        summary = (f"{title} was seen {total} time(s){where} on {period} ({parts}); "
                   f"first {rows[0]['first']}, last {rows[-1]['last']}." if day else
                   f"{title} was seen {total} time(s){where} in {period} on {len({r['date'] for r in rows})} day(s) ({parts}).")
    else:
        summary = f"{title}, {period}{where}: {len({r['emp_code'] for r in rows})} people seen, {total} detections in all."
    return {
        "kind": kind, "target": target, "title": f"{title} · detections", "month": month, "month_label": period,
        "columns": cols, "rows": rows,
        "totals": {"count": total, cols[0]["key"]: "Total"} if len(rows) > 1 else None,
        "details": None, "summary": summary, "salary_hidden": False,
        "report": "detections", "date": day, "camera": camera,
        "nav": _nav(kind, target, "detections", month, day, camera),
    }
