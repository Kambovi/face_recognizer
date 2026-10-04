"""GET /dashboard (date range) and GET /dashboard/today.

One row per subject per LOCAL calendar day in the requested range:
  * known      -- an employee with at least one event that day
  * unknown    -- an unknown identity with at least one event that day
  * absent     -- an active employee with no events that day (only for days
                  on/after the employee was created, never for future days)
  * exceptions -- late arrival, missing OUT, low-confidence match, liveness
                  failure, long-unresolved unknown

Every row also carries the `kiosk_ids` (entry points / cameras) it was seen
at that day, so the frontend can filter by unit/entry point without another
round-trip; `kiosks` lists every known entry point (heartbeats + events in
range) to populate that filter.

Query count is constant, not per-employee / per-unknown: events, employees,
shifts, templates, unknown identities and heartbeats are each fetched once.

Behaviour change vs. the old today-only version: `unknown` now lists only
identities actually SEEN in the range (it used to list every OPEN identity
ever, which contradicted the "today" label -- see the 2026-09-23 status note).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, OwnerType, RejectReason, SubjectType, UnknownStatus
from app.models.face_templates import FaceTemplate
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.models.sightings import Sighting
from app.models.shifts import Shift
from app.models.unknown_identities import UnknownIdentity

LOCAL_TZ = ZoneInfo("Asia/Kolkata")

# Guards payload size: one calendar year x ~100 employees is the intended ceiling.
MAX_RANGE_DAYS = 366
LOW_CONFIDENCE_SIMILARITY = 0.5
UNRESOLVED_UNKNOWN_DAYS = 7


class DashboardRangeError(ValueError):
    """Invalid or oversized date range (mapped to HTTP 422 by the router)."""


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _local_date(dt: datetime) -> date:
    return dt.astimezone(LOCAL_TZ).date()


def _hhmm(dt: datetime | None) -> str | None:
    return dt.astimezone(LOCAL_TZ).strftime("%H:%M") if dt else None


@dataclass
class KnownRow:
    face_id: str
    emp_code: str | None
    name: str
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    in_time: str | None
    out_time: str | None
    total_hours: float
    status: str
    similarity: float | None
    thumb_url: str | None
    best_shot_url: str | None
    date: str = ""
    kiosk_ids: list[str] = field(default_factory=list)
    is_active: bool = True
    on_time: bool | None = None
    # ids the dashboard's inline edit actions need
    subject_id: str = ""
    in_event_id: str | None = None
    out_event_id: str | None = None
    home_kiosk_id: str | None = None


@dataclass
class UnknownRow:
    face_id: str
    label: str | None
    first_seen: str
    last_seen: str
    sighting_count: int
    in_time: str | None
    out_time: str | None
    total_hours: float
    status: str
    best_crop_url: str | None
    date: str = ""
    kiosk_ids: list[str] = field(default_factory=list)
    subject_id: str = ""
    in_event_id: str | None = None
    out_event_id: str | None = None


@dataclass
class AbsentRow:
    face_id: str
    emp_code: str | None
    name: str
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    thumb_url: str | None
    date: str = ""
    is_active: bool = True
    subject_id: str = ""
    home_kiosk_id: str | None = None


@dataclass
class ExceptionRow:
    kind: str
    face_id: str
    label: str | None
    detail: str
    date: str = ""
    kiosk_ids: list[str] = field(default_factory=list)


@dataclass
class DashboardResult:
    known: list[KnownRow]
    unknown: list[UnknownRow]
    absent: list[AbsentRow]
    exceptions: list[ExceptionRow]
    counts: dict[str, int]
    date_from: str = ""
    date_to: str = ""
    kiosks: list[str] = field(default_factory=list)


# Old name, kept so any other importer keeps working.
DashboardToday = DashboardResult


def _event_crop_url(event: AttendanceEvent | None) -> str | None:
    return f"/api/v1/media/crop/{event.id}" if event is not None and event.crop_path else None


def _in_out(
    events: list[AttendanceEvent], *, is_today: bool, now_local: datetime
) -> tuple[datetime | None, datetime | None, float]:
    """First IN, last OUT, and hours worked. `events` must be time-sorted.

    No OUT yet -> still counts as "worked so far": elapsed = (now - first IN)
    for today's still-open row, or (last detection - first IN) for a past day
    that never got a formal OUT (kiosk missed it / OUT never happened).
    """
    ins = [e for e in events if e.event_type == EventType.IN]
    outs = [e for e in events if e.event_type == EventType.OUT]
    in_time = ins[0].occurred_at if ins else None
    out_time = outs[-1].occurred_at if outs else None
    if in_time is None:
        return in_time, out_time, 0.0
    end_for_hours = out_time or (now_local if is_today else events[-1].occurred_at)
    total = round(max(0.0, (end_for_hours - in_time).total_seconds() / 3600.0), 2)
    return in_time, out_time, total


def _in_out_ids(events: list[AttendanceEvent]) -> tuple[str | None, str | None]:
    ins = [e for e in events if e.event_type == EventType.IN]
    outs = [e for e in events if e.event_type == EventType.OUT]
    return (ins[0].id if ins else None), (outs[-1].id if outs else None)


def _kiosks(events: list[AttendanceEvent]) -> list[str]:
    return sorted({e.kiosk_id for e in events})


async def _employee_thumbs(db: AsyncSession) -> dict[str, str]:
    """employee id -> primary (else newest) template image URL, in one query.
    Selects only the columns needed -- never the embedding blobs."""
    rows = await db.execute(
        select(FaceTemplate.id, FaceTemplate.owner_id, FaceTemplate.source_image_path)
        .where(FaceTemplate.owner_type == OwnerType.EMPLOYEE)
        .order_by(FaceTemplate.is_primary.desc(), FaceTemplate.created_at.desc())
    )
    thumbs: dict[str, str] = {}
    for tpl_id, owner_id, path in rows.all():
        if owner_id not in thumbs and path:
            thumbs[owner_id] = f"/api/v1/media/template/{tpl_id}"
    return thumbs


async def get_dashboard(db: AsyncSession, date_from: date, date_to: date) -> DashboardResult:
    if date_to < date_from:
        raise DashboardRangeError("date_to must be on or after date_from")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise DashboardRangeError(f"Date range may not exceed {MAX_RANGE_DAYS} days")

    today = local_today()
    start_utc = datetime.combine(date_from, time.min, tzinfo=LOCAL_TZ)
    end_utc = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    last_day = min(date_to, today)  # never report absences for the future
    days = [date_from + timedelta(days=i) for i in range((last_day - date_from).days + 1)]

    now_local = datetime.now(LOCAL_TZ)
    employees = list((await db.execute(select(Employee).where(Employee.deleted_at.is_(None)))).scalars().all())
    shifts_by_id = {s.id: s for s in (await db.execute(select(Shift))).scalars().all()}
    thumbs = await _employee_thumbs(db)

    all_events = list(
        (
            await db.execute(
                select(AttendanceEvent)
                .where(AttendanceEvent.occurred_at >= start_utc, AttendanceEvent.occurred_at < end_utc)
                .order_by(AttendanceEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )

    emp_day_events: dict[tuple[str, date], list[AttendanceEvent]] = {}
    unk_day_events: dict[tuple[str, date], list[AttendanceEvent]] = {}
    liveness_failures: list[AttendanceEvent] = []
    for e in all_events:
        d = _local_date(e.occurred_at)
        if e.subject_type == SubjectType.EMPLOYEE and e.employee_id is not None:
            emp_day_events.setdefault((e.employee_id, d), []).append(e)
        elif e.unknown_identity_id is not None:
            unk_day_events.setdefault((e.unknown_identity_id, d), []).append(e)
        if e.reject_reason == RejectReason.LIVENESS_FAILED:
            liveness_failures.append(e)

    known: list[KnownRow] = []
    absent: list[AbsentRow] = []
    exceptions: list[ExceptionRow] = []

    for emp in employees:
        shift = shifts_by_id.get(emp.shift_id) if emp.shift_id else None
        shift_in = shift.in_time.strftime("%H:%M") if shift else None
        shift_out = shift.out_time.strftime("%H:%M") if shift else None
        thumb = thumbs.get(emp.id)
        enrolled_on = _local_date(emp.created_at)

        for d in days:
            iso_day = d.isoformat()
            day_events = emp_day_events.get((emp.id, d))

            if not day_events:
                # Inactive employees and pre-enrolment days are not absences.
                if emp.is_active and d >= enrolled_on:
                    absent.append(
                        AbsentRow(
                            face_id=emp.face_id, emp_code=emp.emp_code, name=emp.name, designation=emp.designation,
                            department=emp.department, shift_in=shift_in, shift_out=shift_out,
                            thumb_url=thumb, date=iso_day, is_active=emp.is_active,
                            subject_id=emp.id, home_kiosk_id=emp.home_kiosk_id,
                        )
                    )
                continue

            in_time, out_time, total_hours = _in_out(day_events, is_today=d == today, now_local=now_local)
            kiosk_ids = _kiosks(day_events)

            status = "Present"
            on_time: bool | None = None
            if shift is not None and in_time is not None:
                local_in = in_time.astimezone(LOCAL_TZ).time()
                threshold = (datetime.combine(d, shift.in_time) + timedelta(minutes=shift.grace_minutes)).time()
                on_time = local_in <= threshold
                if not on_time:
                    status = "Late"
                    exceptions.append(
                        ExceptionRow(
                            kind="late_arrival", face_id=emp.face_id, label=emp.name,
                            detail=f"In at {local_in.strftime('%H:%M')}", date=iso_day, kiosk_ids=kiosk_ids,
                        )
                    )

            if in_time and not out_time:
                exceptions.append(
                    ExceptionRow(
                        kind="no_out_recorded", face_id=emp.face_id, label=emp.name,
                        detail="No OUT recorded yet today" if d == today else "No OUT recorded",
                        date=iso_day, kiosk_ids=kiosk_ids,
                    )
                )

            last_event = day_events[-1]
            if last_event.similarity is not None and last_event.similarity < LOW_CONFIDENCE_SIMILARITY:
                exceptions.append(
                    ExceptionRow(
                        kind="low_confidence_match", face_id=emp.face_id, label=emp.name,
                        detail=f"similarity={last_event.similarity:.2f}", date=iso_day, kiosk_ids=kiosk_ids,
                    )
                )

            known.append(
                KnownRow(
                    face_id=emp.face_id, emp_code=emp.emp_code, name=emp.name, designation=emp.designation, department=emp.department,
                    shift_in=shift_in, shift_out=shift_out, in_time=_hhmm(in_time), out_time=_hhmm(out_time),
                    total_hours=total_hours, status=status, similarity=last_event.similarity,
                    thumb_url=thumb, best_shot_url=_event_crop_url(last_event),
                    date=iso_day, kiosk_ids=kiosk_ids, is_active=emp.is_active, on_time=on_time,
                    subject_id=emp.id, in_event_id=_in_out_ids(day_events)[0], out_event_id=_in_out_ids(day_events)[1],
                    home_kiosk_id=emp.home_kiosk_id,
                )
            )

    # -- unknown visitors actually seen in the range --------------------------
    unk_ids = {uid for uid, _ in unk_day_events}
    unknowns_by_id: dict[str, UnknownIdentity] = {}
    if unk_ids:
        result = await db.execute(select(UnknownIdentity).where(UnknownIdentity.id.in_(unk_ids)))
        unknowns_by_id = {u.id: u for u in result.scalars().all()}

    unknown_rows: list[UnknownRow] = []
    latest_day_by_unknown: dict[str, date] = {}
    for (uid, d), day_events in sorted(unk_day_events.items(), key=lambda kv: kv[0][1]):
        unk = unknowns_by_id.get(uid)
        if unk is None:
            continue
        # Visitors: time between first and last sighting -- "still here, clock
        # running" only makes sense for staff, not a courier seen once at 11:05.
        in_time, out_time, total_hours = _in_out(day_events, is_today=False, now_local=now_local)
        unknown_rows.append(
            UnknownRow(
                face_id=unk.face_id, label=unk.label,
                first_seen=unk.first_seen_at.isoformat(), last_seen=unk.last_seen_at.isoformat(),
                sighting_count=unk.sighting_count, in_time=_hhmm(in_time), out_time=_hhmm(out_time),
                total_hours=total_hours, status=unk.status.value,
                best_crop_url=f"/api/v1/media/unknown/{unk.id}" if unk.best_crop_path else None,
                date=d.isoformat(), kiosk_ids=_kiosks(day_events),
                subject_id=unk.id, in_event_id=_in_out_ids(day_events)[0], out_event_id=_in_out_ids(day_events)[1],
            )
        )
        latest_day_by_unknown[uid] = d

    for uid, d in latest_day_by_unknown.items():
        unk = unknowns_by_id[uid]
        open_days = (now_local - unk.first_seen_at.astimezone(LOCAL_TZ)).days
        if unk.status == UnknownStatus.OPEN and open_days > UNRESOLVED_UNKNOWN_DAYS:
            exceptions.append(
                ExceptionRow(
                    kind="unresolved_unknown", face_id=unk.face_id, label=unk.label,
                    detail=f"Open for more than {UNRESOLVED_UNKNOWN_DAYS} days", date=d.isoformat(),
                    kiosk_ids=_kiosks(unk_day_events[(uid, d)]),
                )
            )

    for e in liveness_failures:
        exceptions.append(
            ExceptionRow(
                kind="liveness_failure", face_id=e.kiosk_id, label=None, detail=e.occurred_at.isoformat(),
                date=_local_date(e.occurred_at).isoformat(), kiosk_ids=[e.kiosk_id],
            )
        )

    # unclear / covered faces the server refused to turn into anyone
    # (recognition.py): one exception per camera per day with the count
    unclear = (await db.execute(
        select(Sighting.kiosk_id, Sighting.occurred_at).where(
            Sighting.employee_id.is_(None), Sighting.unknown_identity_id.is_(None),
            Sighting.occurred_at >= start_utc, Sighting.occurred_at < end_utc)
    )).all()
    per: dict[tuple[str, date], list[datetime]] = {}
    for kiosk_id, ts in unclear:
        per.setdefault((kiosk_id, _local_date(ts)), []).append(ts)
    for (kiosk_id, d), times in sorted(per.items()):
        hhmm = ", ".join(sorted(t.astimezone(LOCAL_TZ).strftime("%H:%M") for t in times)[:6])
        exceptions.append(ExceptionRow(
            kind="unclear_face", face_id=kiosk_id, label=None,
            detail=f"{len(times)} unclear / covered face(s) not recorded: {hhmm}", date=d.isoformat(),
            kiosk_ids=[kiosk_id],
        ))

    heartbeat_kiosks = (await db.execute(select(KioskHeartbeat.kiosk_id))).scalars().all()
    kiosks = sorted(set(heartbeat_kiosks) | {e.kiosk_id for e in all_events})

    counts = {
        "present": len(known),
        "absent": len(absent),
        "unknown": len(unknown_rows),
        "exceptions": len(exceptions),
    }

    return DashboardResult(
        known=known, unknown=unknown_rows, absent=absent, exceptions=exceptions, counts=counts,
        date_from=date_from.isoformat(), date_to=date_to.isoformat(), kiosks=kiosks,
    )


async def get_dashboard_today(db: AsyncSession, grace_late_minutes_default: int = 15) -> DashboardResult:
    """Kept for existing callers. Grace now always comes from each employee's
    shift; the parameter is accepted but unused (it was unused before too)."""
    today = local_today()
    return await get_dashboard(db, today, today)
