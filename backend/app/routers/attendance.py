from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, RejectReason, SubjectType
from app.models.users import User
from app.schemas.attendance import (
    AttendanceEventListResponse,
    AttendanceEventOut,
    ManualEventCreate,
    ManualOverrideRequest,
    ReassignRequest,
)
from app.services.attendance import reassign_single_event
from app.services.audit import write_audit

router = APIRouter(prefix="/attendance", tags=["attendance"])
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def _to_out(event: AttendanceEvent) -> AttendanceEventOut:
    out = AttendanceEventOut.model_validate(event)
    out.crop_url = f"/api/v1/media/crop/{event.id}" if event.crop_path else None
    out.subject_type = event.subject_type.value if event.subject_type else None
    # event_type is NOT NULL at the model level (Mapped[EventType], not
    # EventType | None) -- unlike subject_type/reject_reason, there's no
    # real "unset" case to guard against here.
    out.event_type = event.event_type.value
    out.reject_reason = event.reject_reason.value if event.reject_reason else None
    return out


@router.get("/events", response_model=AttendanceEventListResponse)
async def list_events(
    date_from: date | None = None,
    date_to: date | None = None,
    subject_type: str | None = None,
    reject_reason: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AttendanceEventListResponse:
    stmt = select(AttendanceEvent)
    if date_from:
        stmt = stmt.where(AttendanceEvent.occurred_at >= datetime.combine(date_from, time.min, tzinfo=LOCAL_TZ))
    if date_to:
        stmt = stmt.where(AttendanceEvent.occurred_at <= datetime.combine(date_to, time.max, tzinfo=LOCAL_TZ))
    if subject_type:
        stmt = stmt.where(AttendanceEvent.subject_type == SubjectType(subject_type))
    if reject_reason:
        stmt = stmt.where(AttendanceEvent.reject_reason == RejectReason(reject_reason))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(AttendanceEvent.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size)
    events = list((await db.execute(stmt)).scalars().all())

    return AttendanceEventListResponse(items=[_to_out(e) for e in events], total=total, page=page, page_size=page_size)


@router.patch("/events/{event_id}", response_model=AttendanceEventOut)
async def manual_override(
    event_id: str,
    payload: ManualOverrideRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AttendanceEventOut:
    result = await db.execute(select(AttendanceEvent).where(AttendanceEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise http_error(404, "event_not_found", "Attendance event not found")

    before = {"event_type": event.event_type.value, "occurred_at": event.occurred_at.isoformat()}
    if payload.event_type:
        from app.models.enums import EventType

        event.event_type = EventType(payload.event_type)
    if payload.occurred_at:
        event.occurred_at = payload.occurred_at
    event.is_manual_override = True
    event.overridden_by = user.email
    event.override_reason = payload.reason

    await write_audit(db, user.id, "manual_override", "attendance_event", event.id, before=before, after={"reason": payload.reason})
    await db.commit()
    return _to_out(event)


@router.patch("/events/{event_id}/reassign", response_model=AttendanceEventOut)
async def reassign_event(
    event_id: str,
    payload: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AttendanceEventOut:
    result = await db.execute(select(AttendanceEvent).where(AttendanceEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise http_error(404, "event_not_found", "Attendance event not found")

    if payload.target_type in ("EMPLOYEE", "UNKNOWN") and not payload.target_id:
        raise http_error(422, "target_id_required", "target_id is required for this target_type")

    before = {"employee_id": event.employee_id, "unknown_identity_id": event.unknown_identity_id}
    updated = await reassign_single_event(db, event, payload.target_type, payload.target_id, payload.reason, user.email)

    await write_audit(
        db, user.id, "reassign", "attendance_event", event.id, before=before,
        after={"target_type": payload.target_type, "target_id": payload.target_id},
    )
    await db.commit()
    return _to_out(updated)


MANUAL_KIOSK_ID = "manual"


@router.post("/events/manual", response_model=AttendanceEventOut, status_code=201)
async def create_manual_event(
    payload: ManualEventCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AttendanceEventOut:
    employee = (
        await db.execute(select(Employee).where(Employee.id == payload.employee_id, Employee.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if employee is None:
        raise http_error(404, "employee_not_found", "Employee not found")
    event = AttendanceEvent(
        subject_type=SubjectType.EMPLOYEE,
        employee_id=employee.id,
        event_type=EventType(payload.event_type),
        occurred_at=payload.occurred_at,
        kiosk_id=MANUAL_KIOSK_ID,
        is_manual_override=True,
        overridden_by=user.email,
        override_reason=payload.reason,
    )
    db.add(event)
    await db.flush()
    await write_audit(
        db, user.id, "manual_create", "attendance_event", event.id,
        after={"employee_id": employee.id, "event_type": payload.event_type,
               "occurred_at": payload.occurred_at.isoformat(), "reason": payload.reason},
    )
    await db.commit()
    return _to_out(event)
