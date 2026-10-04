"""GET /analytics/summary + /analytics/export.csv.

Assumption (documented per spec's "pick simplest defensible option" rule,
see docs/DECISIONS.md and docs/TUNING.md): `working_days_per_week` (N)
defines the expected working days in a range as every calendar day whose
Python `weekday()` (0=Monday) is `< N` -- i.e. N=5 means Mon-Fri. This is a
simplification (it doesn't model per-employee weekly-off rotation or
holiday calendars, neither of which the spec's data model has a table for);
a real deployment would extend `shifts` with a working-days bitmask.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import csvsafe
from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.models.shifts import Shift
from app.models.unknown_identities import UnknownIdentity

LOCAL_TZ = ZoneInfo("Asia/Kolkata")


@dataclass
class SummaryRow:
    face_id: str
    name: str | None
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    avg_in_time: str | None
    avg_out_time: str | None
    total_hours: float
    present_days: int
    absent_days: int
    late_count: int
    early_exit_count: int
    attendance_pct: float
    is_unknown: bool = False
    label: str | None = None


def _expected_working_days(date_from: date, date_to: date, working_days_per_week: int) -> int:
    days = 0
    d = date_from
    while d <= date_to:
        if d.weekday() < working_days_per_week:
            days += 1
        d += timedelta(days=1)
    return days


def _fmt_time(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _avg_time_of_day(times: list[datetime]) -> time | None:
    if not times:
        return None
    total_seconds = sum(t.astimezone(LOCAL_TZ).hour * 3600 + t.astimezone(LOCAL_TZ).minute * 60 + t.astimezone(LOCAL_TZ).second for t in times)
    avg_seconds = int(total_seconds / len(times))
    return time(hour=(avg_seconds // 3600) % 24, minute=(avg_seconds % 3600) // 60)


def _group_by_local_day(events: list[AttendanceEvent]) -> dict[str, list[AttendanceEvent]]:
    grouped: dict[str, list[AttendanceEvent]] = {}
    for e in events:
        day = e.occurred_at.astimezone(LOCAL_TZ).date().isoformat()
        grouped.setdefault(day, []).append(e)
    return grouped


async def compute_summary(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    working_days_per_week: int,
    subject_id: str | None = None,
    include_unknowns: bool = False,
) -> list[SummaryRow]:
    range_start = datetime.combine(date_from, time.min, tzinfo=LOCAL_TZ)
    range_end = datetime.combine(date_to, time.max, tzinfo=LOCAL_TZ)
    expected_days = _expected_working_days(date_from, date_to, working_days_per_week)

    emp_stmt = select(Employee).where(Employee.is_active.is_(True))
    if subject_id:
        emp_stmt = emp_stmt.where(Employee.id == subject_id)
    employees = list((await db.execute(emp_stmt)).scalars().all())

    shifts_by_id = {s.id: s for s in (await db.execute(select(Shift))).scalars().all()}

    rows: list[SummaryRow] = []
    for emp in employees:
        events_result = await db.execute(
            select(AttendanceEvent).where(
                AttendanceEvent.employee_id == emp.id,
                AttendanceEvent.subject_type == SubjectType.EMPLOYEE,
                AttendanceEvent.occurred_at >= range_start,
                AttendanceEvent.occurred_at <= range_end,
            )
        )
        events = list(events_result.scalars().all())
        by_day = _group_by_local_day(events)

        shift = shifts_by_id.get(emp.shift_id) if emp.shift_id else None
        total_hours = 0.0
        late_count = 0
        early_exit_count = 0
        in_times: list[datetime] = []
        out_times: list[datetime] = []

        for _day, day_events in by_day.items():
            ordered = sorted(day_events, key=lambda e: e.occurred_at)
            ins = [e for e in ordered if e.event_type == EventType.IN]
            outs = [e for e in ordered if e.event_type == EventType.OUT]
            if ins:
                in_times.append(ins[0].occurred_at)
                if shift is not None:
                    local_in = ins[0].occurred_at.astimezone(LOCAL_TZ).time()
                    grace = timedelta(minutes=shift.grace_minutes)
                    threshold = (datetime.combine(date.today(), shift.in_time) + grace).time()
                    if local_in > threshold:
                        late_count += 1
            if outs:
                out_times.append(outs[-1].occurred_at)
                if shift is not None:
                    local_out = outs[-1].occurred_at.astimezone(LOCAL_TZ).time()
                    if local_out < shift.out_time:
                        early_exit_count += 1
            if ins and outs:
                total_hours += max(0.0, (outs[-1].occurred_at - ins[0].occurred_at).total_seconds() / 3600.0)

        present_days = len(by_day)
        absent_days = max(0, expected_days - present_days)
        attendance_pct = round((present_days / expected_days) * 100, 1) if expected_days > 0 else 0.0

        rows.append(
            SummaryRow(
                face_id=emp.face_id,
                name=emp.name,
                designation=emp.designation,
                department=emp.department,
                shift_in=_fmt_time(shift.in_time) if shift else None,
                shift_out=_fmt_time(shift.out_time) if shift else None,
                avg_in_time=_fmt_time(_avg_time_of_day(in_times)),
                avg_out_time=_fmt_time(_avg_time_of_day(out_times)),
                total_hours=round(total_hours, 2),
                present_days=present_days,
                absent_days=absent_days,
                late_count=late_count,
                early_exit_count=early_exit_count,
                attendance_pct=attendance_pct,
            )
        )

    if include_unknowns:
        unk_stmt = select(UnknownIdentity)
        if subject_id:
            unk_stmt = unk_stmt.where(UnknownIdentity.id == subject_id)
        unknowns = list((await db.execute(unk_stmt)).scalars().all())
        for unk in unknowns:
            events_result = await db.execute(
                select(AttendanceEvent).where(
                    AttendanceEvent.unknown_identity_id == unk.id,
                    AttendanceEvent.occurred_at >= range_start,
                    AttendanceEvent.occurred_at <= range_end,
                )
            )
            events = list(events_result.scalars().all())
            by_day = _group_by_local_day(events)
            total_hours = 0.0
            in_times, out_times = [], []
            for _day, day_events in by_day.items():
                ordered = sorted(day_events, key=lambda e: e.occurred_at)
                ins = [e for e in ordered if e.event_type == EventType.IN]
                outs = [e for e in ordered if e.event_type == EventType.OUT]
                if ins:
                    in_times.append(ins[0].occurred_at)
                if outs:
                    out_times.append(outs[-1].occurred_at)
                if ins and outs:
                    total_hours += max(0.0, (outs[-1].occurred_at - ins[0].occurred_at).total_seconds() / 3600.0)
            rows.append(
                SummaryRow(
                    face_id=unk.face_id,
                    name=None,
                    designation=None,
                    department=None,
                    shift_in=None,
                    shift_out=None,
                    avg_in_time=_fmt_time(_avg_time_of_day(in_times)),
                    avg_out_time=_fmt_time(_avg_time_of_day(out_times)),
                    total_hours=round(total_hours, 2),
                    present_days=len(by_day),
                    absent_days=0,
                    late_count=0,
                    early_exit_count=0,
                    attendance_pct=0.0,
                    is_unknown=True,
                    label=unk.label,
                )
            )

    return rows


def rows_to_csv(rows: list[SummaryRow]) -> str:
    buf = io.StringIO()
    writer = csvsafe.writer(buf)
    writer.writerow(
        [
            "Face ID", "Name", "Designation", "Department", "Shift IN", "Shift OUT",
            "Actual IN", "Actual OUT", "Total Hours", "Present Days", "Absent Days",
            "Late", "Early Exit", "Attendance %",
        ]
    )
    for r in rows:
        name = r.label if r.is_unknown else r.name
        writer.writerow(
            [
                r.face_id, name or ("Unknown" if r.is_unknown else ""), r.designation or "", r.department or "",
                r.shift_in or "", r.shift_out or "", r.avg_in_time or "", r.avg_out_time or "",
                r.total_hours, r.present_days, r.absent_days, r.late_count, r.early_exit_count, r.attendance_pct,
            ]
        )
    return buf.getvalue()
