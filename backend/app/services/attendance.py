"""Steps 8-10 of the recognition pipeline, run server-side inside
POST /api/v1/kiosk/event (see routers/kiosk.py):

  8. Dedupe: a new detection within `dedupe_window_minutes` of the subject's
     most recent event UPDATES that row in place instead of inserting a new
     one.
  9. IN vs OUT: the first event of the local (Asia/Kolkata) day is IN; every
     later one is OUT, with "latest wins" -- once an OUT row exists for the
     day, further detections keep moving its `occurred_at` forward rather
     than creating more rows.
  10. Persist event + crop.

Both rules collapse into one small state machine (`upsert_attendance_event`)
keyed off the subject's most recent event *for that local day*.

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
    dedupe_window_minutes: float,
    day_of: DayOf | None = None,
) -> tuple[AttendanceEvent, bool]:
    """Returns (event, created). `created=False` means an existing row was
    updated in place (dedupe merge or idempotent replay).

    `day_of` maps a timestamp to its attendance day; default is the local
    calendar date. For employees the caller passes a shift-aware one
    (services/shiftday.py) so a night shift's 22:00 IN and 06:00 OUT land
    on the same day."""

    if data.client_event_id:
        existing = await _find_by_client_event_id(db, data.client_event_id)
        if existing is not None:
            return existing, False

    # Pre-identification rejects (liveness_failed / too_small) never merge
    # with anything -- there is no subject to key a "most recent event" off
    # of -- they are simply inserted.
    if data.subject_type is None:
        event = AttendanceEvent(
            subject_type=None,
            employee_id=None,
            unknown_identity_id=None,
            event_type=EventType.IN,  # placeholder; meaningless for rejects, never read
            occurred_at=data.occurred_at,
            similarity=data.similarity,
            liveness_score=data.liveness_score,
            kiosk_id=data.kiosk_id,
            crop_path=data.crop_path,
            reject_reason=data.reject_reason,
            client_event_id=data.client_event_id,
        )
        db.add(event)
        await db.flush()
        return event, True

    day = (day_of or local_date)(data.occurred_at)
    todays_events = await _events_today_for_subject(
        db, data.subject_type, data.employee_id, data.unknown_identity_id, day, day_of
    )

    if not todays_events:
        event = AttendanceEvent(
            subject_type=data.subject_type,
            employee_id=data.employee_id,
            unknown_identity_id=data.unknown_identity_id,
            event_type=EventType.IN,
            occurred_at=data.occurred_at,
            similarity=data.similarity,
            liveness_score=data.liveness_score,
            kiosk_id=data.kiosk_id,
            crop_path=data.crop_path,
            reject_reason=data.reject_reason,
            client_event_id=data.client_event_id,
        )
        db.add(event)
        await db.flush()
        return event, True

    last_event = todays_events[-1]
    gap = data.occurred_at - last_event.occurred_at
    within_dedupe_window = timedelta(seconds=0) <= gap <= timedelta(minutes=dedupe_window_minutes)

    if within_dedupe_window:
        last_event.occurred_at = max(last_event.occurred_at, data.occurred_at)
        last_event.similarity = data.similarity
        last_event.liveness_score = data.liveness_score
        last_event.crop_path = data.crop_path or last_event.crop_path
        last_event.kiosk_id = data.kiosk_id
        await db.flush()
        return last_event, False

    if last_event.event_type == EventType.IN:
        event = AttendanceEvent(
            subject_type=data.subject_type,
            employee_id=data.employee_id,
            unknown_identity_id=data.unknown_identity_id,
            event_type=EventType.OUT,
            occurred_at=data.occurred_at,
            similarity=data.similarity,
            liveness_score=data.liveness_score,
            kiosk_id=data.kiosk_id,
            crop_path=data.crop_path,
            reject_reason=data.reject_reason,
            client_event_id=data.client_event_id,
        )
        db.add(event)
        await db.flush()
        return event, True

    # Already have an OUT for today and we're past the dedupe window:
    # "latest wins" -- keep pushing the OUT time forward.
    last_event.occurred_at = data.occurred_at
    last_event.similarity = data.similarity
    last_event.liveness_score = data.liveness_score
    last_event.crop_path = data.crop_path or last_event.crop_path
    last_event.kiosk_id = data.kiosk_id
    await db.flush()
    return last_event, False


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
