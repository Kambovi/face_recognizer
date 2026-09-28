"""Per-person, per-day timesheet -- the single source for every report that
pays people: contractor report, payroll export, muster roll, OT.

For each person and each date in the range it answers: which shift, first
and last sighting, hours worked, late minutes, early-leave minutes, overtime,
and a status code:

  P    present            HD   half day (below `full_day_min_hours`)
  A    absent             WO   weekly off
  WOP  worked on a weekly off (all worked time is overtime)
  L    approved paid leave  LWP  leave without pay (models/leaves.py)
  -    not on the roster yet (joined later), or a future date -- not counted anywhere

Rules (all tunable in Settings, see settings_service.DEFAULT_SETTINGS):
  * Sightings are grouped into attendance days shift-aware (shiftday.py),
    so night shifts are one day, not two halves.
  * Worked = last sighting - first sighting. With only an entry camera,
    people are usually seen once, so worked is ~0: that's why the hour-based
    HD / A rules are OFF (0) by default.
  * Late  = first sighting after shift start + grace.
  * OT    = time after shift end, >= ot_min_minutes, rounded DOWN to
    ot_rounding_minutes. Nothing counts before shift start.
  * No explicit shift + auto_shift_detect: the shift whose start is nearest
    the first sighting is used for late/OT maths.
Query count is constant.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.leaves import Leave
from app.models.enums import SubjectType
from app.models.shifts import Shift
from app.services.settings_service import get_all_settings
from app.services.shiftday import LOCAL_TZ, ShiftResolver, load_resolver, shift_bounds, shift_minutes

STATUSES = ("P", "HD", "A", "WO", "WOP", "L", "LWP", "-")


@dataclass
class DayRecord:
    employee_id: str
    day: date
    status: str
    shift: Shift | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    worked_minutes: int = 0
    late_minutes: int = 0
    early_leave_minutes: int = 0
    ot_minutes: int = 0
    manual: bool = False
    kiosks: list[str] = field(default_factory=list)

    @property
    def present_value(self) -> float:
        """Paid-day weight: P/WOP = 1, HD = 0.5, else 0."""
        return {"P": 1.0, "WOP": 1.0, "HD": 0.5}.get(self.status, 0.0)

    def as_dict(self) -> dict[str, Any]:
        def hm(dt: datetime | None) -> str | None:
            return dt.astimezone(LOCAL_TZ).strftime("%H:%M") if dt else None

        return {
            "employee_id": self.employee_id,
            "date": self.day.isoformat(),
            "status": self.status,
            "shift": self.shift.name if self.shift else None,
            "shift_in": self.shift.in_time.strftime("%H:%M") if self.shift else None,
            "shift_out": self.shift.out_time.strftime("%H:%M") if self.shift else None,
            "first_seen": hm(self.first_seen),
            "last_seen": hm(self.last_seen),
            "worked_minutes": self.worked_minutes,
            "late_minutes": self.late_minutes,
            "early_leave_minutes": self.early_leave_minutes,
            "ot_minutes": self.ot_minutes,
            "manual": self.manual,
            "kiosks": self.kiosks,
        }


@dataclass
class Rules:
    weekly_off: set[int]
    ot_enabled: bool
    ot_min: int
    ot_round: int
    full_day_min: float
    half_day_min: float
    auto_shift: bool
    tail_hours: float

    @classmethod
    def from_settings(cls, cfg: dict[str, Any]) -> Rules:
        return cls(
            weekly_off={int(d) for d in (cfg.get("weekly_off_days") or [])},
            ot_enabled=bool(cfg.get("ot_enabled", True)),
            ot_min=int(cfg.get("ot_min_minutes", 30)),
            ot_round=max(1, int(cfg.get("ot_rounding_minutes", 15))),
            full_day_min=float(cfg.get("full_day_min_hours", 0) or 0),
            half_day_min=float(cfg.get("half_day_min_hours", 0) or 0),
            auto_shift=bool(cfg.get("auto_shift_detect", True)),
            tail_hours=float(cfg.get("night_shift_tail_hours", 4)),
        )


def _nearest_shift(shifts: list[Shift], first: datetime) -> Shift | None:
    if not shifts:
        return None
    local = first.astimezone(LOCAL_TZ)
    mins = local.hour * 60 + local.minute

    def dist(s: Shift) -> int:
        d = abs(mins - (s.in_time.hour * 60 + s.in_time.minute))
        return min(d, 24 * 60 - d)

    return min(shifts, key=dist)


def _round_down(minutes: int, step: int) -> int:
    return (minutes // step) * step


def build_day(
    employee_id: str,
    day: date,
    events: list[AttendanceEvent],
    shift: Shift | None,
    rules: Rules,
    leave: str | None = None,
) -> DayRecord:
    off = day.weekday() in rules.weekly_off
    if not events:
        if off:
            return DayRecord(employee_id, day, "WO", shift=shift)
        status = {"paid": "L", "unpaid": "LWP"}.get(leave or "", "A")
        return DayRecord(employee_id, day, status, shift=shift)
    ev = sorted(events, key=lambda e: e.occurred_at)
    first, last = ev[0].occurred_at, ev[-1].occurred_at
    worked = int((last - first).total_seconds() // 60)
    rec = DayRecord(
        employee_id,
        day,
        "P",
        shift=shift,
        first_seen=first,
        last_seen=last,
        worked_minutes=worked,
        manual=any(e.is_manual_override for e in ev),
        kiosks=sorted({e.kiosk_id for e in ev}),
    )
    if off:
        rec.status = "WOP"
        if rules.ot_enabled and worked >= rules.ot_min:
            rec.ot_minutes = _round_down(worked, rules.ot_round)
        return rec
    if shift is not None:
        start, end = shift_bounds(shift, day)
        grace = timedelta(minutes=shift.grace_minutes or 0)
        rec.late_minutes = max(0, int((first - (start + grace)).total_seconds() // 60))
        if worked > 0 and start < last < end:
            rec.early_leave_minutes = int((end - last).total_seconds() // 60)
        if rules.ot_enabled and last > end:
            extra = int((last - end).total_seconds() // 60)
            if extra >= rules.ot_min:
                rec.ot_minutes = _round_down(extra, rules.ot_round)
    if rules.full_day_min and worked < rules.full_day_min * 60:
        rec.status = "HD"
    if rules.half_day_min and worked < rules.half_day_min * 60:
        rec.status = "A"
    return rec


@dataclass
class Timesheet:
    people: list[Employee]
    days: list[date]
    records: dict[tuple[str, date], DayRecord]
    rules: Rules

    def for_person(self, employee_id: str) -> list[DayRecord]:
        return [self.records[(employee_id, d)] for d in self.days if (employee_id, d) in self.records]


def _daterange(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


async def build_timesheet(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    employee_ids: list[str] | None = None,
    contractor: str | None = None,
    resolver: ShiftResolver | None = None,
) -> Timesheet:
    rules = Rules.from_settings(await get_all_settings(db))
    q = select(Employee).where(Employee.deleted_at.is_(None))
    if employee_ids is not None:
        q = q.where(Employee.id.in_(employee_ids))
    if contractor is not None:
        q = q.where(Employee.contractor == contractor) if contractor else q.where(Employee.contractor.is_(None))
    people = [
        p for p in (await db.execute(q.order_by(Employee.emp_code))).scalars().all()
        if p.is_active or employee_ids is not None
    ]
    ids = [p.id for p in people]
    resolver = resolver or await load_resolver(db, ids, rules.tail_hours)
    all_shifts = list(resolver.shifts.values())

    start = datetime.combine(date_from - timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    end = datetime.combine(date_to + timedelta(days=2), time.min, tzinfo=LOCAL_TZ)
    by_day: dict[tuple[str, date], list[AttendanceEvent]] = defaultdict(list)
    if ids:
        rows = (
            await db.execute(
                select(AttendanceEvent).where(
                    AttendanceEvent.subject_type == SubjectType.EMPLOYEE,
                    AttendanceEvent.employee_id.in_(ids),
                    AttendanceEvent.reject_reason.is_(None),
                    AttendanceEvent.occurred_at >= start,
                    AttendanceEvent.occurred_at < end,
                )
            )
        ).scalars().all()
        for e in rows:
            if e.employee_id is None:
                continue
            by_day[(e.employee_id, resolver.attendance_date(e.employee_id, e.occurred_at))].append(e)

    leaves: dict[tuple[str, date], str] = {}
    if ids:
        for lv in (await db.execute(
            select(Leave).where(Leave.employee_id.in_(ids), Leave.day >= date_from, Leave.day <= date_to)
        )).scalars().all():
            leaves[(lv.employee_id, lv.day)] = lv.kind

    days = _daterange(date_from, date_to)
    today = datetime.now(LOCAL_TZ).date()
    records: dict[tuple[str, date], DayRecord] = {}
    for p in people:
        joined = p.created_at.astimezone(LOCAL_TZ).date()
        for d in days:
            evs = by_day.get((p.id, d), [])
            # not on the roll yet, or a day that hasn't happened: counted nowhere
            if (d < joined or d > today) and not evs:
                records[(p.id, d)] = DayRecord(p.id, d, "-")
                continue
            shift = resolver.explicit(p.id, d)
            if shift is None:
                shift = (_nearest_shift(all_shifts, min(e.occurred_at for e in evs))
                         if evs and rules.auto_shift else None) or resolver.default
            records[(p.id, d)] = build_day(p.id, d, evs, shift, rules, leaves.get((p.id, d)))
    return Timesheet(people, days, records, rules)


def person_totals(ts: Timesheet, employee_id: str) -> dict[str, float]:
    recs = ts.for_person(employee_id)
    count = {s: sum(1 for r in recs if r.status == s) for s in STATUSES}
    # LWP is a working day that isn't paid; L is paid, like a weekly off
    working = sum(1 for r in recs if r.status in ("P", "HD", "A", "LWP"))
    paid_working = sum(r.present_value for r in recs if r.status in ("P", "HD"))
    return {
        "days_in_range": len([r for r in recs if r.status != "-"]),
        "working_days": working,
        "present": count["P"],
        "half_days": count["HD"],
        "absent": count["A"],
        "weekly_off": count["WO"],
        "worked_on_off": count["WOP"],
        "leave": count["L"],
        "unpaid_leave": count["LWP"],
        "late_days": sum(1 for r in recs if r.late_minutes > 0),
        "late_minutes": sum(r.late_minutes for r in recs),
        "early_leave_minutes": sum(r.early_leave_minutes for r in recs),
        "ot_hours": round(sum(r.ot_minutes for r in recs) / 60, 2),
        "worked_hours": round(sum(r.worked_minutes for r in recs) / 60, 2),
        # payroll: loss-of-pay = working days not paid; paid days = the rest
        "lop_days": round(working - paid_working, 1),
        "paid_days": round(len([r for r in recs if r.status != "-"]) - (working - paid_working), 1),
    }


def shift_label(shift: Shift | None) -> str:
    if shift is None:
        return ""
    return f"{shift.name} ({shift.in_time.strftime('%H:%M')}-{shift.out_time.strftime('%H:%M')})"


__all__ = ["DayRecord", "Rules", "Timesheet", "build_day", "build_timesheet", "person_totals", "shift_minutes"]
