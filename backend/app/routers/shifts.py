"""Shifts and the shift roster.

Shifts: list / create / edit / delete (admin). A shift whose out_time is
earlier than its in_time is a night shift (crosses midnight).

Roster (`/shifts/roster`): who works which shift on which dates -- used for
rotating shifts. Assigning a range to people replaces whatever they had on
those dates (older rows are trimmed or split), so there are never two rows
for one person on one day.

2026-09-26: POST /shifts now takes a JSON body -- the frontend always sent
JSON but the endpoint read query parameters, so creating a shift 422'd.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.employees import Employee
from app.models.shift_assignments import ShiftAssignment
from app.models.shifts import Shift
from app.models.users import User
from app.schemas.employees import ShiftOut
from app.services.audit import write_audit

router = APIRouter(prefix="/shifts", tags=["shifts"])


def _hhmm(v: str) -> str:
    try:
        h, m = v.split(":")
        time(int(h), int(m))
    except (ValueError, TypeError) as exc:
        raise ValueError("time must be HH:MM") from exc
    return f"{int(h):02d}:{int(m):02d}"


def _parse(v: str) -> time:
    h, m = v.split(":")
    return time(int(h), int(m))


class ShiftIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    in_time: str
    out_time: str
    grace_minutes: int = Field(default=15, ge=0, le=240)
    is_default: bool = False

    @field_validator("in_time", "out_time")
    @classmethod
    def _v(cls, v: str) -> str:
        return _hhmm(v)


class ShiftPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    in_time: str | None = None
    out_time: str | None = None
    grace_minutes: int | None = Field(default=None, ge=0, le=240)
    is_default: bool | None = None

    @field_validator("in_time", "out_time")
    @classmethod
    def _v(cls, v: str | None) -> str | None:
        return _hhmm(v) if v is not None else None


def _out(s: Shift) -> ShiftOut:
    return ShiftOut(
        id=s.id, name=s.name, in_time=s.in_time.strftime("%H:%M"), out_time=s.out_time.strftime("%H:%M"),
        grace_minutes=s.grace_minutes, is_default=s.is_default,
    )


async def _clear_default(db: AsyncSession, keep_id: str) -> None:
    await db.execute(update(Shift).where(Shift.id != keep_id).values(is_default=False))


@router.get("", response_model=list[ShiftOut])
async def list_shifts(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[ShiftOut]:
    shifts = (await db.execute(select(Shift).order_by(Shift.in_time))).scalars().all()
    return [_out(s) for s in shifts]


@router.post("", response_model=ShiftOut, status_code=201)
async def create_shift(
    payload: ShiftIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> ShiftOut:
    shift = Shift(
        name=payload.name, in_time=_parse(payload.in_time), out_time=_parse(payload.out_time),
        grace_minutes=payload.grace_minutes, is_default=payload.is_default,
    )
    db.add(shift)
    await db.flush()
    if payload.is_default:
        await _clear_default(db, shift.id)
    await write_audit(db, user.id, "shift_create", "shift", shift.id, after=payload.model_dump())
    await db.commit()
    return _out(shift)


@router.patch("/{shift_id}", response_model=ShiftOut)
async def update_shift(
    shift_id: str, payload: ShiftPatch, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> ShiftOut:
    shift = await db.get(Shift, shift_id)
    if shift is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Shift not found")
    before = _out(shift).model_dump()
    data = payload.model_dump(exclude_unset=True)
    for key in ("in_time", "out_time"):
        if data.get(key):
            data[key] = _parse(data[key])
    if data.get("is_default") is False and shift.is_default:
        raise http_error(status.HTTP_409_CONFLICT, "is_default", "Make another shift the default instead")
    for key, value in data.items():
        if value is not None:
            setattr(shift, key, value)
    if data.get("is_default"):
        await _clear_default(db, shift.id)
    await write_audit(db, user.id, "shift_update", "shift", shift.id, before=before, after=_out(shift).model_dump())
    await db.commit()
    return _out(shift)


@router.delete("/{shift_id}", status_code=204, response_model=None)
async def delete_shift(shift_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> None:
    shift = await db.get(Shift, shift_id)
    if shift is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Shift not found")
    if shift.is_default:
        raise http_error(status.HTTP_409_CONFLICT, "is_default", "Make another shift the default first")
    await db.execute(update(Employee).where(Employee.shift_id == shift_id).values(shift_id=None))
    await db.execute(delete(ShiftAssignment).where(ShiftAssignment.shift_id == shift_id))
    await write_audit(db, user.id, "shift_delete", "shift", shift_id, before=_out(shift).model_dump())
    await db.delete(shift)
    await db.commit()


# ---------------------------------------------------------------- roster
class RosterAssign(BaseModel):
    employee_ids: list[str] = Field(min_length=1, max_length=2000)
    shift_id: str
    start_date: date
    end_date: date


class RosterRow(BaseModel):
    id: str
    employee_id: str
    emp_code: str
    name: str
    shift_id: str
    shift_name: str
    start_date: date
    end_date: date


@router.get("/roster", response_model=list[RosterRow])
async def list_roster(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[RosterRow]:
    rows = (
        await db.execute(
            select(ShiftAssignment, Employee, Shift)
            .join(Employee, Employee.id == ShiftAssignment.employee_id)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .where(ShiftAssignment.start_date <= date_to, ShiftAssignment.end_date >= date_from)
            .order_by(Employee.emp_code, ShiftAssignment.start_date)
        )
    ).all()
    return [
        RosterRow(
            id=a.id, employee_id=e.id, emp_code=e.emp_code, name=e.name, shift_id=s.id, shift_name=s.name,
            start_date=a.start_date, end_date=a.end_date,
        )
        for a, e, s in rows
    ]


async def assign_range(db: AsyncSession, employee_id: str, shift_id: str, start: date, end: date) -> None:
    """Put `shift_id` on [start, end] for one person, trimming/splitting any
    existing rows that overlap so dates never have two shifts."""
    overlapping = (
        await db.execute(
            select(ShiftAssignment).where(
                ShiftAssignment.employee_id == employee_id,
                ShiftAssignment.start_date <= end,
                ShiftAssignment.end_date >= start,
            )
        )
    ).scalars().all()
    one_day = timedelta(days=1)
    for a in overlapping:
        if a.start_date < start and a.end_date > end:  # split around the new range
            db.add(ShiftAssignment(
                employee_id=employee_id, shift_id=a.shift_id, start_date=end + one_day, end_date=a.end_date
            ))
            a.end_date = start - one_day
        elif a.start_date < start:
            a.end_date = start - one_day
        elif a.end_date > end:
            a.start_date = end + one_day
        else:
            await db.delete(a)
    db.add(ShiftAssignment(employee_id=employee_id, shift_id=shift_id, start_date=start, end_date=end))


@router.post("/roster", status_code=201)
async def assign_roster(
    payload: RosterAssign, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> dict[str, int]:
    if payload.end_date < payload.start_date:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_range", "end_date is before start_date")
    if (payload.end_date - payload.start_date).days > 366:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_range", "Assign at most one year at a time")
    if await db.get(Shift, payload.shift_id) is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Shift not found")
    known = set((await db.execute(select(Employee.id).where(Employee.id.in_(payload.employee_ids)))).scalars())
    for eid in payload.employee_ids:
        if eid in known:
            await assign_range(db, eid, payload.shift_id, payload.start_date, payload.end_date)
            await db.flush()
    await write_audit(
        db, user.id, "roster_assign", "shift", payload.shift_id,
        after={**payload.model_dump(mode="json", exclude={"employee_ids"}), "people": len(known)},
    )
    await db.commit()
    return {"assigned": len(known)}


@router.delete("/roster/{assignment_id}", status_code=204, response_model=None)
async def delete_roster_row(
    assignment_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> None:
    row = await db.get(ShiftAssignment, assignment_id)
    if row is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Roster row not found")
    await write_audit(db, user.id, "roster_delete", "shift_assignment", assignment_id)
    await db.delete(row)
    await db.commit()
