"""Steps 8-10 of the recognition pipeline, run server-side inside
POST /api/v1/kiosk/event (see routers/kiosk.py).

Rules (changed 2026-09-29 after a client saw an 08:10 entry become 08:35):
  * Every recognised detection is logged in `sightings` (the raw log).
  * attendance_events keeps at most ONE IN and ONE OUT per subject per
    attendance day (shift-aware for employees, see shiftday.py).
  * IN = the first detection of the day. It never moves later.
  * OUT depends on the camera's role (Muster page: entry / exit / both):
      entry  never sets OUT; later detections are only counted
      exit   every detection sets OUT = latest exit detection
      both   (one camera for in and out, the default) a detection at least
             `min_out_gap_minutes` (default 120) after IN sets OUT = latest;
             earlier ones are only counted (walking past the gate again
             at 08:35 doesn't end the day)
  * The last OUT is the final exit; hours = OUT - IN.

NON-NEGOTIABLE #4 ("dedupe enforced at data layer, not just an application
if") is satisfied two ways: (a) `client_event_id` carries a DB UNIQUE
constraint, so replaying/duplicating the exact same physical detection is
rejected at the schema level regardless of application logic; and (b) the
read-modify-write below runs under `SELECT ... FOR UPDATE` (a genuine DB
row lock on Postgres) around the subject's events-for-the-day, so two
concurrent requests for the same subject cannot race past each other into
two rows -- the second one blocks until the first commits, then sees the
row it just created/updated and folds into it. (On SQLite, used only by the
test suite, `with_for_update()` is a no-op since SQLite has no row-level
locking and the test suite is single-threaded, so this doesn't weaken the
production guarantee.)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.enums import EventType, RejectReason, SubjectType
from app.models.sightings import Sighting

LOCAL_TZ = ZoneInfo("Asia/Kolkata")


@dataclass
class RecognitionEventInput:
    subject_type: SubjectType | None
    employee_id: str | None
    unknown_identity_id: str | None
    occurred_at: datetime
    similarity: float | None
    liveness_score: float | None
    kiosk_id: str
    crop_path: str | None
    reject_reason: RejectReason | None
    client_event_id: str | None


def local_date(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).date().isoformat()


async def _find_by_client_event_id(db: AsyncSession, client_event_id: str) -> AttendanceEvent | None:
    result = await db.execute(
        select(AttendanceEvent).where(AttendanceEvent.client_event_id == client_event_id)
    )
    return result.scalar_one_or_none()


DayOf = Callable[[datetime], "date | str"]


async def _events_today_for_subject(
    db: AsyncSession,
    subject_type: SubjectType,
    employee_id: str | None,
    unknown_identity_id: str | None,
    day: "date | str",
    day_of: DayOf | None = None,
) -> list[AttendanceEvent]:
    stmt = select(AttendanceEvent).where(AttendanceEvent.subject_type == subject_type)
    if subject_type == SubjectType.EMPLOYEE:
        stmt = stmt.where(AttendanceEvent.employee_id == employee_id)
    else:
        stmt = stmt.where(AttendanceEvent.unknown_identity_id == unknown_identity_id)
    stmt = stmt.order_by(AttendanceEvent.occurred_at.asc())
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    all_events = list(result.scalars().all())
    key = day_of or local_date
    return [e for e in all_events if key(e.occurred_at) == day]


async def upsert_attendance_event(
    db: AsyncSession,
    data: RecognitionEventInput,
    dedupe_window_minutes: float = 0,
    day_of: DayOf | None = None,
    *,
    camera_role: str = "both",
    min_out_gap_minutes: float = 120,
) -> tuple[AttendanceEvent, bool]:
    """Returns (event, created). `created=False` means an existing row was
    kept or updated (repeat detection, idempotent replay).

    `day_of` maps a timestamp to its attendance day; default is the local
    calendar date. For employees the caller passes a shift-aware one
    (services/shiftday.py) so a night shift's 22:00 IN and 06:00 OUT land
    on the same day. `dedupe_window_minutes` is kept for callers but no
    longer changes anything here: IN is fixed and OUT follows the rules in
    the module docstring."""

    if data.client_event_id:
        existing = await _find_by_client_event_id(db, data.client_event_id)
        if existing is not None:
            return existing, False

    # Pre-identification rejects (liveness_failed / too_small) never merge
    # with anything -- there is no subject to key a "most recent event" off
    # of -- they are simply inserted.
    if data.subject_type is None:
        event = _new_event(data, EventType.IN)  # event_type meaningless for rejects, never read
        db.add(event)
        await db.flush()
        return event, True

    day = (day_of or local_date)(data.occurred_at)
    todays_events = await _events_today_for_subject(
        db, data.subject_type, data.employee_id, data.unknown_identity_id, day, day_of
    )
    event, created = _apply_rules(db, data, todays_events, camera_role, min_out_gap_minutes)
    await db.flush()
    db.add(Sighting(
        occurred_at=data.occurred_at, kiosk_id=data.kiosk_id, subject_type=data.subject_type,
        employee_id=data.employee_id, unknown_identity_id=data.unknown_identity_id, event_id=event.id,
        similarity=data.similarity, liveness_score=data.liveness_score,
    ))
    await db.flush()
    return event, created


def _new_event(data: RecognitionEventInput, kind: EventType) -> AttendanceEvent:
    return AttendanceEvent(
        subject_type=data.subject_type,
        employee_id=data.employee_id,
        unknown_identity_id=data.unknown_identity_id,
        event_type=kind,
        occurred_at=data.occurred_at,
        similarity=data.similarity,
        liveness_score=data.liveness_score,
        kiosk_id=data.kiosk_id,
        crop_path=data.crop_path,
        reject_reason=data.reject_reason,
        client_event_id=data.client_event_id,
    )


def _refresh(ev: AttendanceEvent, data: RecognitionEventInput) -> None:
    ev.occurred_at = data.occurred_at
    ev.similarity = data.similarity
    ev.liveness_score = data.liveness_score
    ev.crop_path = data.crop_path or ev.crop_path
    ev.kiosk_id = data.kiosk_id


def _apply_rules(
    db: AsyncSession,
    data: RecognitionEventInput,
    todays: list[AttendanceEvent],
    role: str,
    min_gap_minutes: float,
) -> tuple[AttendanceEvent, bool]:
    ins = [e for e in todays if e.event_type == EventType.IN]
    outs = [e for e in todays if e.event_type == EventType.OUT]
    in_ev = ins[0] if ins else None
    out_ev = outs[-1] if outs else None
    t = data.occurred_at

    if in_ev is None:
        ev = _new_event(data, EventType.IN)
        db.add(ev)
        return ev, True
    if t < in_ev.occurred_at:
        # a late-arriving (offline-queued) earlier detection: IN = the earliest
        _refresh(in_ev, data)
        return in_ev, False
    if role == "entry":
        return in_ev, False
    if role != "exit" and t - in_ev.occurred_at < timedelta(minutes=min_gap_minutes):
        return in_ev, False
    if out_ev is None:
        ev = _new_event(data, EventType.OUT)
        db.add(ev)
        return ev, True
    if t >= out_ev.occurred_at:
        _refresh(out_ev, data)
    return out_ev, False


def recompute_day_in_out(events: list[AttendanceEvent]) -> None:
    """Recomputes IN=earliest/OUT=latest for a set of events belonging to one
    subject on one local day, in place. Used by /unknowns/{id}/link and
    /attendance/events/{id}/reassign after merging events across subjects
    (spec: "recompute that day's IN/OUT/total_hours")."""
    if not events:
        return
    ordered = sorted(events, key=lambda e: e.occurred_at)
    ordered[0].event_type = EventType.IN
    for e in ordered[1:]:
        e.event_type = EventType.OUT


async def reassign_single_event(
    db: AsyncSession,
    event: AttendanceEvent,
    target_type: str,
    target_id: str | None,
    reason: str,
    actor: str,
) -> AttendanceEvent:
    """PATCH /attendance/events/{id}/reassign. Re-points ONE event to a
    different subject, preserving where it came from, then recomputes
    IN/OUT for both the old and new subject's day."""
    from app.models.unknown_identities import UnknownIdentity
    from app.services.ids import next_unknown_face_id

    old_subject_type = event.subject_type
    old_employee_id = event.employee_id
    old_unknown_id = event.unknown_identity_id
    day = local_date(event.occurred_at)

    event.original_employee_id = event.original_employee_id or old_employee_id
    event.original_unknown_identity_id = event.original_unknown_identity_id or old_unknown_id
    event.is_manual_override = True
    event.overridden_by = actor
    event.override_reason = reason

    if target_type == "EMPLOYEE":
        event.subject_type = SubjectType.EMPLOYEE
        event.employee_id = target_id
        event.unknown_identity_id = None
    elif target_type == "UNKNOWN":
        event.subject_type = SubjectType.UNKNOWN
        event.employee_id = None
        event.unknown_identity_id = target_id
    else:  # NEW_UNKNOWN
        face_id = await next_unknown_face_id(db)
        new_unknown = UnknownIdentity(
            face_id=face_id,
            first_seen_at=event.occurred_at,
            last_seen_at=event.occurred_at,
            sighting_count=1,
        )
        db.add(new_unknown)
        await db.flush()
        event.subject_type = SubjectType.UNKNOWN
        event.employee_id = None
        event.unknown_identity_id = new_unknown.id

    await db.flush()
    from app.services.sightings import repoint

    await repoint(db, new_type=event.subject_type, employee_id=event.employee_id,
                  unknown_identity_id=event.unknown_identity_id, event_id=event.id)

    # Recompute IN/OUT for the OLD subject's remaining events that day.
    if old_subject_type == SubjectType.EMPLOYEE and old_employee_id:
        old_events = await _events_today_for_subject(db, SubjectType.EMPLOYEE, old_employee_id, None, day)
        recompute_day_in_out([e for e in old_events if e.id != event.id])
    elif old_subject_type == SubjectType.UNKNOWN and old_unknown_id:
        old_events = await _events_today_for_subject(db, SubjectType.UNKNOWN, None, old_unknown_id, day)
        recompute_day_in_out([e for e in old_events if e.id != event.id])

    # Recompute IN/OUT for the NEW subject's events that day (including this one).
    new_events = await _events_today_for_subject(db, event.subject_type, event.employee_id, event.unknown_identity_id, day)
    recompute_day_in_out(new_events)

    await db.flush()
    return event


def total_hours(events: list[AttendanceEvent]) -> float:
    ins = [e.occurred_at for e in events if e.event_type == EventType.IN]
    outs = [e.occurred_at for e in events if e.event_type == EventType.OUT]
    if not ins:
        return 0.0
    start = min(ins)
    end = max(outs) if outs else max(e.occurred_at for e in events)
    delta = (end - start).total_seconds() / 3600.0
    return round(max(0.0, delta), 2)
