"""Leave register + balances.

  GET    /leaves?employee_id=&date_from=&date_to=   list
  POST   /leaves          mark a date range as leave / off day        (HR)
  DELETE /leaves/{id}                                                  (HR)
  GET    /leaves/types                                 configured leave types
  GET    /leaves/balance/{employee_id}?on=YYYY-MM-DD   balances per type
  PUT    /leaves/opening  {employee_id, year, leave_type, days}        (HR)
  POST   /leaves/carry-forward?year=2026   close a leave year           (HR)

POST body: employee_id, date_from, date_to, leave_type (code from
Settings -> leave types; decides paid / unpaid) or kind "off" (rotating
weekly off / comp-off day), portion 1 or 0.5 (half day: single date only),
note. Weekly offs and holidays inside the range are skipped (they are not
leave days). A paid type without enough balance is refused unless
force=true (HR override, audited).

Marking a range again overwrites the days already marked. Days in a month
whose payroll is locked can't be changed.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_hr
from app.models.employees import Employee
from app.models.holidays import Holiday
from app.models.leave_openings import LeaveOpening
from app.models.leaves import Leave
from app.models.users import User
from app.services.audit import write_audit
from app.services.leave_balance import balance_of, balances, carry_forward, types_by_code
from app.services.payroll_lock import ensure_unlocked
from app.services.settings_service import get_all_settings

router = APIRouter(prefix="/leaves", tags=["leaves"])
MAX_RANGE = 366


class LeaveIn(BaseModel):
    employee_id: str
    date_from: date
    date_to: date
    leave_type: str | None = Field(default=None, max_length=20)
    # legacy / explicit: paid | unpaid | off. With leave_type set, the type decides.
    kind: Literal["paid", "unpaid", "off"] | None = None
    portion: float = Field(default=1.0)
    note: str | None = Field(default=None, max_length=300)
    skip_off_days: bool = True
    force: bool = False

    @model_validator(mode="after")
    def _range(self) -> "LeaveIn":
        if self.date_to < self.date_from:
            raise ValueError("date_to is before date_from")
        if (self.date_to - self.date_from).days + 1 > MAX_RANGE:
            raise ValueError(f"At most {MAX_RANGE} days at once")
        if self.portion not in (1.0, 0.5):
            raise ValueError("portion must be 1 (full day) or 0.5 (half day)")
        if self.portion == 0.5 and self.date_from != self.date_to:
            raise ValueError("A half-day leave is for one date only")
        return self


class OpeningIn(BaseModel):
    employee_id: str
    year: int = Field(ge=2000, le=2100)
    leave_type: str = Field(min_length=1, max_length=20)
    days: float = Field(ge=0, le=1000)


def _out(lv: Leave) -> dict[str, Any]:
    return {"id": lv.id, "employee_id": lv.employee_id, "day": lv.day.isoformat(), "kind": lv.kind,
            "leave_type": lv.leave_type, "portion": lv.portion, "note": lv.note}


async def _employee(db: AsyncSession, employee_id: str) -> Employee:
    emp = (await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None))
    )).scalar_one_or_none()
    if emp is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "employee_not_found", "Employee not found")
    return emp


@router.get("")
async def list_leaves(
    employee_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    q = select(Leave)
    if employee_id:
        q = q.where(Leave.employee_id == employee_id)
    if date_from:
        q = q.where(Leave.day >= date_from)
    if date_to:
        q = q.where(Leave.day <= date_to)
    rows = (await db.execute(q.order_by(Leave.day.desc()).limit(500))).scalars().all()
    return [_out(r) for r in rows]


@router.get("/types")
async def leave_types(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return list(types_by_code(await get_all_settings(db)).values())


@router.get("/balance/{employee_id}")
async def leave_balance(employee_id: str, on: date | None = None, db: AsyncSession = Depends(get_db),
                        _user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await balances(db, await _employee(db, employee_id), on)


@router.post("", status_code=201)
async def add_leave(payload: LeaveIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    emp = await _employee(db, payload.employee_id)
    cfg = await get_all_settings(db)
    types = types_by_code(cfg)
    code = payload.leave_type.upper() if payload.leave_type else None
    if code is not None:
        if code not in types:
            raise http_error(422, "unknown_leave_type", f"Leave type {code} is not set up (Settings -> Leave types)")
        kind = "paid" if types[code].get("paid", True) else "unpaid"
    else:
        kind = payload.kind or "paid"

    # which dates actually become leave
    weekly = set(cfg.get("weekly_off_days") or []) if emp.weekly_off_days is None else set(emp.weekly_off_days)
    holidays = {h.day for h in (await db.execute(select(Holiday).where(
        Holiday.day >= payload.date_from, Holiday.day <= payload.date_to, Holiday.kind != "optional"))).scalars().all()}
    days: list[date] = []
    d = payload.date_from
    while d <= payload.date_to:
        if not (payload.skip_off_days and kind != "off" and (d.weekday() in weekly or d in holidays)):
            days.append(d)
        d += timedelta(days=1)
    if not days:
        raise http_error(422, "no_working_days", "Every date in the range is a weekly off or holiday")
    await ensure_unlocked(db, *days)

    existing = {
        lv.day: lv for lv in (await db.execute(
            select(Leave).where(Leave.employee_id == emp.id, Leave.day >= payload.date_from, Leave.day <= payload.date_to)
        )).scalars().all()
    }
    needed = len(days) * float(payload.portion)
    if code and kind == "paid":
        # days already marked with this type in the range are being replaced
        already = sum(float(lv.portion or 1) for dd, lv in existing.items() if dd in days and (lv.leave_type or "") == code)
        bal = await balance_of(db, emp, code, payload.date_to)
        if bal is not None and bal + already < needed and not payload.force:
            raise http_error(422, "insufficient_balance",
                             f"{code} balance is {bal + already:g} day(s), {needed:g} requested")

    for day in days:
        if day in existing:
            lv = existing[day]
            lv.kind, lv.note, lv.leave_type, lv.portion = kind, payload.note, code, float(payload.portion)
        else:
            db.add(Leave(employee_id=emp.id, day=day, kind=kind, note=payload.note, leave_type=code,
                         portion=float(payload.portion)))
    await write_audit(db, user.id, "add_leave", "employee", emp.id, before=None,
                      after={"from": payload.date_from.isoformat(), "to": payload.date_to.isoformat(), "kind": kind,
                             "leave_type": code, "portion": payload.portion, "days": len(days),
                             "forced": bool(payload.force)})
    await db.commit()
    return {"days": len(days), "kind": kind, "leave_type": code}


@router.delete("/{leave_id}", status_code=204, response_model=None)
async def delete_leave(leave_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> None:
    lv = (await db.execute(select(Leave).where(Leave.id == leave_id))).scalar_one_or_none()
    if lv is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "leave_not_found", "Leave not found")
    await ensure_unlocked(db, lv.day)
    await write_audit(db, user.id, "delete_leave", "employee", lv.employee_id, before=_out(lv), after=None)
    await db.delete(lv)
    await db.commit()


@router.put("/opening")
async def set_opening(payload: OpeningIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    emp = await _employee(db, payload.employee_id)
    code = payload.leave_type.upper()
    row = (await db.execute(select(LeaveOpening).where(
        LeaveOpening.employee_id == emp.id, LeaveOpening.year == payload.year, LeaveOpening.leave_type == code
    ))).scalar_one_or_none()
    before = row.days if row else None
    if row is None:
        db.add(LeaveOpening(employee_id=emp.id, year=payload.year, leave_type=code, days=payload.days))
    else:
        row.days = payload.days
    await write_audit(db, user.id, "leave_opening", "employee", emp.id, before={"days": before},
                      after={"year": payload.year, "type": code, "days": payload.days})
    await db.commit()
    return {"ok": True}


@router.post("/carry-forward")
async def close_year(year: int = Query(..., ge=2000, le=2100), db: AsyncSession = Depends(get_db),
                     user: User = Depends(require_hr)) -> dict[str, int]:
    n = await carry_forward(db, year)
    await write_audit(db, user.id, "leave_carry_forward", "leave_year", str(year), after={"rows": n})
    await db.commit()
    return {"rows": n}
