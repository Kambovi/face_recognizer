"""Leave register.

  GET    /leaves?employee_id=&date_from=&date_to=   list
  POST   /leaves     mark a date range as paid / unpaid leave (admin)
  DELETE /leaves/{id}                                  (admin)

Marking a range again overwrites the kind / note of days already marked.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.employees import Employee
from app.models.leaves import Leave
from app.models.users import User
from app.services.audit import write_audit

router = APIRouter(prefix="/leaves", tags=["leaves"])
MAX_RANGE = 366


class LeaveIn(BaseModel):
    employee_id: str
    date_from: date
    date_to: date
    kind: Literal["paid", "unpaid"] = "paid"
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _range(self) -> "LeaveIn":
        if self.date_to < self.date_from:
            raise ValueError("date_to is before date_from")
        if (self.date_to - self.date_from).days + 1 > MAX_RANGE:
            raise ValueError(f"At most {MAX_RANGE} days at once")
        return self


def _out(lv: Leave) -> dict[str, Any]:
    return {"id": lv.id, "employee_id": lv.employee_id, "day": lv.day.isoformat(), "kind": lv.kind, "note": lv.note}


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


@router.post("", status_code=201)
async def add_leave(payload: LeaveIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    emp = (await db.execute(
        select(Employee).where(Employee.id == payload.employee_id, Employee.deleted_at.is_(None))
    )).scalar_one_or_none()
    if emp is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "employee_not_found", "Employee not found")
    existing = {
        lv.day: lv for lv in (await db.execute(
            select(Leave).where(Leave.employee_id == emp.id, Leave.day >= payload.date_from, Leave.day <= payload.date_to)
        )).scalars().all()
    }
    d, n = payload.date_from, 0
    while d <= payload.date_to:
        if d in existing:
            existing[d].kind, existing[d].note = payload.kind, payload.note
        else:
            db.add(Leave(employee_id=emp.id, day=d, kind=payload.kind, note=payload.note))
        n += 1
        d += timedelta(days=1)
    await write_audit(db, user.id, "add_leave", "employee", emp.id, before=None,
                      after={"from": payload.date_from.isoformat(), "to": payload.date_to.isoformat(), "kind": payload.kind})
    await db.commit()
    return {"days": n}


@router.delete("/{leave_id}", status_code=204, response_model=None)
async def delete_leave(leave_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> None:
    lv = (await db.execute(select(Leave).where(Leave.id == leave_id))).scalar_one_or_none()
    if lv is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "leave_not_found", "Leave not found")
    await write_audit(db, user.id, "delete_leave", "employee", lv.employee_id, before=_out(lv), after=None)
    await db.delete(lv)
    await db.commit()
