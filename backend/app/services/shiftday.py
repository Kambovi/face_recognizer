"""Which shift a person works on a date, and which "attendance day" a
sighting belongs to.

A night shift (22:00 -> 06:00) spans two calendar dates. Grouping sightings
by calendar date splits it in two and, worse, the IN/OUT state machine used
to overwrite the 22:00 arrival with a later sighting. So for anyone whose
shift crosses midnight, a sighting before (shift end + `night_shift_tail_hours`)
counts toward the PREVIOUS date's shift.

Shift for a date (first match wins):
  1. a roster row (shift_assignments) covering that date
  2. the person's fixed shift (employees.shift_id)
  3. the default shift (shifts.is_default)
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.models.shift_assignments import ShiftAssignment
from app.models.shifts import Shift

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
DEFAULT_NIGHT_TAIL_HOURS = 4.0


def crosses_midnight(shift: Shift) -> bool:
    return shift.out_time <= shift.in_time


def shift_minutes(shift: Shift) -> int:
    start = shift.in_time.hour * 60 + shift.in_time.minute
    end = shift.out_time.hour * 60 + shift.out_time.minute
    return (end - start) % (24 * 60) or 24 * 60


def shift_bounds(shift: Shift, day: date) -> tuple[datetime, datetime]:
    """Local-time start/end of `shift` worked on `day` (end may be next day)."""
    start = datetime.combine(day, shift.in_time, tzinfo=LOCAL_TZ)
    return start, start + timedelta(minutes=shift_minutes(shift))


def _night_cutoff(shift: Shift, tail_hours: float) -> time:
    """Sightings earlier than this (local) belong to yesterday's night shift.
    Never later than 1h before the shift's own start."""
    end = datetime.combine(date(2000, 1, 2), shift.out_time) + timedelta(hours=tail_hours)
    latest = datetime.combine(date(2000, 1, 2), shift.in_time) - timedelta(hours=1)
    return min(end, latest).time()


class ShiftResolver:
    def __init__(
        self,
        shifts: dict[str, Shift],
        default: Shift | None,
        fixed: dict[str, str | None],
        assignments: dict[str, list[ShiftAssignment]],
        tail_hours: float = DEFAULT_NIGHT_TAIL_HOURS,
    ) -> None:
        self.shifts = shifts
        self.default = default
        self.fixed = fixed
        self.tail_hours = tail_hours
        self._assign = {k: sorted(v, key=lambda a: a.start_date) for k, v in assignments.items()}
        self._starts = {k: [a.start_date for a in v] for k, v in self._assign.items()}

    def rostered(self, employee_id: str, day: date) -> Shift | None:
        rows = self._assign.get(employee_id)
        if not rows:
            return None
        i = bisect_right(self._starts[employee_id], day) - 1
        # later assignments win, so walk back over any that start earlier
        while i >= 0:
            a = rows[i]
            if a.start_date <= day <= a.end_date:
                return self.shifts.get(a.shift_id)
            i -= 1
        return None

    def explicit(self, employee_id: str, day: date) -> Shift | None:
        """Roster row or fixed shift -- NOT the default."""
        s = self.rostered(employee_id, day)
        if s is not None:
            return s
        sid = self.fixed.get(employee_id)
        return self.shifts.get(sid) if sid else None

    def shift_for(self, employee_id: str, day: date) -> Shift | None:
        return self.explicit(employee_id, day) or self.default

    def attendance_date(self, employee_id: str, occurred_at: datetime) -> date:
        local = occurred_at.astimezone(LOCAL_TZ)
        prev = local.date() - timedelta(days=1)
        s_prev = self.shift_for(employee_id, prev)
        if s_prev is not None and crosses_midnight(s_prev) and local.time() < _night_cutoff(s_prev, self.tail_hours):
            return prev
        return local.date()


async def load_resolver(
    db: AsyncSession,
    employee_ids: list[str] | None = None,
    tail_hours: float = DEFAULT_NIGHT_TAIL_HOURS,
) -> ShiftResolver:
    shifts = {s.id: s for s in (await db.execute(select(Shift))).scalars().all()}
    default = next((s for s in shifts.values() if s.is_default), None)
    emp_q = select(Employee.id, Employee.shift_id)
    asg_q = select(ShiftAssignment)
    if employee_ids is not None:
        emp_q = emp_q.where(Employee.id.in_(employee_ids))
        asg_q = asg_q.where(ShiftAssignment.employee_id.in_(employee_ids))
    fixed = {eid: sid for eid, sid in (await db.execute(emp_q)).all()}
    assignments: dict[str, list[ShiftAssignment]] = defaultdict(list)
    for a in (await db.execute(asg_q)).scalars().all():
        assignments[a.employee_id].append(a)
    return ShiftResolver(shifts, default, fixed, assignments, tail_hours)
