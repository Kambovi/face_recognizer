"""GET /analytics/overview -- everything the Analytics page shows, in one call.

Answers the questions an owner / principal / hospital admin actually asks:
  * How is attendance overall, and is it better or worse than last period?  (KPIs + deltas)
  * How did it move day by day?                                              (daily trend)
  * At each camera / entry point: how many people belong there, how many
    came today?                                                              (locations)
  * Which departments / classes lag?                                         (departments)
  * When do people actually arrive?                                          (arrival histogram)
  * Who needs attention?                                                     (lowest attendance, most late)

Definitions (kept deliberately simple and stated in the UI):
  * Roster        = active people enrolled on or before that day.
  * Working day   = weekday index < `working_days_per_week` (5 -> Mon-Fri).
  * Present       = seen by any camera at least once that day.
  * Late          = first IN after shift start + grace (people with a shift only).
  * Hours         = first IN -> last OUT (or last detection if no OUT).
  * Home camera   = the person's assigned `home_kiosk_id`, else the camera
                    they are seen at most often (all-time).
Query count is constant (no per-person queries).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.models.shifts import Shift
from app.services.roster import liveness_state

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
MANUAL_KIOSK = "manual"
ARRIVAL_BUCKET_MIN = 30
ARRIVAL_START = time(6, 0)
ARRIVAL_END = time(12, 0)
ONLINE_WINDOW = timedelta(minutes=5)


def _local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def _pct(num: float, den: float) -> float:
    return round(num / den * 100, 1) if den > 0 else 0.0


@dataclass
class _DayStat:
    present: set[str]
    late: set[str]
    first_in_minutes: dict[str, int]  # minutes after midnight
    hours: dict[str, float]


async def _events(db: AsyncSession, start: datetime, end: datetime) -> list[AttendanceEvent]:
    return list(
        (
            await db.execute(
                select(AttendanceEvent)
                .where(AttendanceEvent.occurred_at >= start, AttendanceEvent.occurred_at < end)
                .order_by(AttendanceEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )


def _day_stats(events: list[AttendanceEvent], shift_of: dict[str, Shift | None], today: date) -> dict[date, _DayStat]:
    by_person_day: dict[tuple[str, date], list[AttendanceEvent]] = defaultdict(list)
    for e in events:
        if e.subject_type == SubjectType.EMPLOYEE and e.employee_id is not None and e.employee_id in shift_of:
            by_person_day[(e.employee_id, _local(e.occurred_at).date())].append(e)
    stats: dict[date, _DayStat] = defaultdict(lambda: _DayStat(set(), set(), {}, {}))
    now = datetime.now(LOCAL_TZ)
    for (pid, d), evs in by_person_day.items():
        st = stats[d]
        st.present.add(pid)
        ins = [e for e in evs if e.event_type == EventType.IN]
        outs = [e for e in evs if e.event_type == EventType.OUT]
        first = _local(ins[0].occurred_at) if ins else _local(evs[0].occurred_at)
        st.first_in_minutes[pid] = first.hour * 60 + first.minute
        shift = shift_of.get(pid)
        if shift is not None and ins:
            threshold = datetime.combine(d, shift.in_time) + timedelta(minutes=shift.grace_minutes)
            if first.replace(tzinfo=None) > threshold:
                st.late.add(pid)
        end = _local(outs[-1].occurred_at) if outs else (now if d == today else _local(evs[-1].occurred_at))
        st.hours[pid] = max(0.0, (end - first).total_seconds() / 3600.0)
    return stats


async def compute_overview(
    db: AsyncSession, date_from: date, date_to: date, working_days_per_week: int
) -> dict[str, Any]:
    today = datetime.now(LOCAL_TZ).date()
    last_day = min(date_to, today)
    days = [date_from + timedelta(days=i) for i in range(max(0, (last_day - date_from).days + 1))]
    work_days = [d for d in days if d.weekday() < working_days_per_week]
    span = (date_to - date_from).days + 1
    prev_from, prev_to = date_from - timedelta(days=span), date_from - timedelta(days=1)

    people = list(
        (await db.execute(select(Employee).where(Employee.deleted_at.is_(None), Employee.is_active.is_(True)))).scalars().all()
    )
    shifts = {s.id: s for s in (await db.execute(select(Shift))).scalars().all()}
    shift_of: dict[str, Shift | None] = {p.id: shifts.get(p.shift_id) if p.shift_id else None for p in people}
    enrolled_on = {p.id: _local(p.created_at).date() for p in people}

    start = datetime.combine(prev_from, time.min, tzinfo=LOCAL_TZ)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    events = await _events(db, start, end)
    cur_events = [e for e in events if _local(e.occurred_at).date() >= date_from]
    prev_events = [e for e in events if _local(e.occurred_at).date() < date_from]
    stats = _day_stats(cur_events, shift_of, today)
    prev_stats = _day_stats(prev_events, shift_of, today)

    _roster_cache: dict[date, set[str]] = {}

    def roster_on(d: date) -> set[str]:
        if d not in _roster_cache:
            _roster_cache[d] = {p.id for p in people if enrolled_on[p.id] <= d}
        return _roster_cache[d]

    def summarise(st: dict[date, _DayStat], wdays: list[date]) -> dict[str, float]:
        expected = sum(len(roster_on(d)) for d in wdays)
        present = sum(len(st[d].present & roster_on(d)) for d in wdays if d in st)
        late = sum(len(st[d].late) for d in wdays if d in st)
        hours = [h for d in wdays if d in st for h in st[d].hours.values()]
        arrivals = [m for d in wdays if d in st for m in st[d].first_in_minutes.values()]
        return {
            "attendance_pct": _pct(present, expected),
            "present_person_days": present,
            "late_count": late,
            "on_time_pct": _pct(present - late, present),
            "avg_hours": round(sum(hours) / len(hours), 2) if hours else 0.0,
            "avg_arrival_minutes": round(sum(arrivals) / len(arrivals)) if arrivals else -1,
        }

    prev_days = [prev_from + timedelta(days=i) for i in range(span)]
    prev_work = [d for d in prev_days if d.weekday() < working_days_per_week and d <= today]
    cur = summarise(stats, work_days)
    prev = summarise(prev_stats, prev_work)

    unknown_ids = {e.unknown_identity_id for e in cur_events if e.unknown_identity_id}
    prev_unknown_ids = {e.unknown_identity_id for e in prev_events if e.unknown_identity_id}
    headline_day = last_day
    present_today = len(stats[headline_day].present) if headline_day in stats else 0

    kpis = {
        "roster": len(people),
        "present_latest_day": present_today,
        "latest_day": headline_day.isoformat(),
        **cur,
        "unknown_visitors": len(unknown_ids),
        "previous": {**prev, "unknown_visitors": len(prev_unknown_ids)},
        "previous_from": prev_from.isoformat(),
        "previous_to": prev_to.isoformat(),
    }

    # -- daily trend ---------------------------------------------------------
    trend = []
    for d in days:
        roster = roster_on(d)
        st = stats.get(d)
        present = len(st.present & roster) if st else 0
        trend.append({
            "date": d.isoformat(),
            "working_day": d.weekday() < working_days_per_week,
            "roster": len(roster),
            "present": present,
            "late": len(st.late) if st else 0,
            "attendance_pct": _pct(present, len(roster)),
        })

    # -- locations (camera / entry point) ------------------------------------
    visits = (
        await db.execute(
            select(AttendanceEvent.employee_id, AttendanceEvent.kiosk_id, func.count())
            .where(AttendanceEvent.employee_id.is_not(None), AttendanceEvent.kiosk_id != MANUAL_KIOSK)
            .group_by(AttendanceEvent.employee_id, AttendanceEvent.kiosk_id)
        )
    ).all()
    visit_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for pid, kid, n in visits:
        visit_counts[pid][kid] += int(n)
    home: dict[str, str | None] = {}
    for p in people:
        home[p.id] = p.home_kiosk_id or (visit_counts[p.id].most_common(1)[0][0] if visit_counts[p.id] else None)

    heartbeats = {h.kiosk_id: h for h in (await db.execute(select(KioskHeartbeat))).scalars().all()}
    now_utc = datetime.now(timezone.utc)
    kiosk_ids = {k for k in home.values() if k} | set(heartbeats) | {
        e.kiosk_id for e in cur_events if e.kiosk_id != MANUAL_KIOSK
    }
    seen_at_day: dict[tuple[str, date], set[str]] = defaultdict(set)
    for e in cur_events:
        if e.employee_id and e.subject_type == SubjectType.EMPLOYEE:
            seen_at_day[(e.kiosk_id, _local(e.occurred_at).date())].add(e.employee_id)
    locations = []
    for kid in sorted(kiosk_ids):
        members = {pid for pid, h in home.items() if h == kid}
        present_now = len(members & (stats[headline_day].present if headline_day in stats else set()))
        exp = sum(len(members & roster_on(d)) for d in work_days)
        got = sum(len(members & roster_on(d) & (stats[d].present if d in stats else set())) for d in work_days)
        hb = heartbeats.get(kid)
        online = False
        if hb is not None:
            seen = hb.last_seen_at if hb.last_seen_at.tzinfo else hb.last_seen_at.replace(tzinfo=timezone.utc)
            online = now_utc - seen < ONLINE_WINDOW
        visitors_today = len({
            e.unknown_identity_id for e in cur_events
            if e.kiosk_id == kid and e.unknown_identity_id and _local(e.occurred_at).date() == headline_day
        })
        locations.append({
            "kiosk_id": kid,
            "roster": len(members),
            "present_latest_day": present_now,
            "absent_latest_day": max(0, len(members) - present_now),
            "attendance_pct": _pct(got, exp),
            "unknown_visitors_latest_day": visitors_today,
            "online": online,
            "liveness": liveness_state(hb.device_json if hb is not None else None),
            "assigned": sum(1 for p in people if p.home_kiosk_id == kid),
        })
    locations.sort(key=lambda r: (-r["roster"], r["kiosk_id"]))

    # -- departments ----------------------------------------------------------
    dept_members: dict[str, set[str]] = defaultdict(set)
    for p in people:
        dept_members[p.department or "Unassigned"].add(p.id)
    departments: list[dict[str, Any]] = []
    for dept, members in dept_members.items():
        exp = sum(len(members & roster_on(d)) for d in work_days)
        got = sum(len(members & roster_on(d) & (stats[d].present if d in stats else set())) for d in work_days)
        late = sum(len(members & stats[d].late) for d in work_days if d in stats)
        departments.append({
            "department": dept,
            "roster": len(members),
            "attendance_pct": _pct(got, exp),
            "late_count": late,
            "present_latest_day": len(members & (stats[headline_day].present if headline_day in stats else set())),
        })
    departments.sort(key=lambda r: float(r["attendance_pct"]))

    # -- arrival histogram ------------------------------------------------------
    start_m = ARRIVAL_START.hour * 60
    end_m = ARRIVAL_END.hour * 60
    buckets = Counter[int]()
    for d in work_days:
        if d not in stats:
            continue
        for m in stats[d].first_in_minutes.values():
            b = start_m - ARRIVAL_BUCKET_MIN if m < start_m else (end_m if m >= end_m else start_m + (m - start_m) // ARRIVAL_BUCKET_MIN * ARRIVAL_BUCKET_MIN)
            buckets[b] += 1
    arrivals = []
    for b in range(start_m - ARRIVAL_BUCKET_MIN, end_m + 1, ARRIVAL_BUCKET_MIN):
        if b < start_m:
            label = f"before {ARRIVAL_START.strftime('%H:%M')}"
        elif b >= end_m:
            label = f"after {ARRIVAL_END.strftime('%H:%M')}"
        else:
            label = f"{b // 60:02d}:{b % 60:02d}"
        arrivals.append({"bucket": label, "start_minutes": b, "count": buckets.get(b, 0)})

    # -- people needing attention ------------------------------------------------
    per_person: list[dict[str, Any]] = []
    for p in people:
        exp_days = [d for d in work_days if enrolled_on[p.id] <= d]
        if not exp_days:
            continue
        present_days = sum(1 for d in exp_days if d in stats and p.id in stats[d].present)
        late_days = sum(1 for d in exp_days if d in stats and p.id in stats[d].late)
        per_person.append({
            "employee_id": p.id, "face_id": p.face_id, "emp_code": p.emp_code, "name": p.name,
            "department": p.department, "home_kiosk_id": home.get(p.id),
            "expected_days": len(exp_days), "present_days": present_days, "late_days": late_days,
            "attendance_pct": _pct(present_days, len(exp_days)),
        })
    lowest = sorted(per_person, key=lambda r: (r["attendance_pct"], r["name"]))[:8]
    most_late = [r for r in sorted(per_person, key=lambda r: (-r["late_days"], r["name"])) if r["late_days"] > 0][:8]

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "working_days": len(work_days),
        "kpis": kpis,
        "trend": trend,
        "locations": locations,
        "departments": departments,
        "arrivals": arrivals,
        "lowest_attendance": lowest,
        "most_late": most_late,
    }
