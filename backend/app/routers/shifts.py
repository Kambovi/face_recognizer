"""Not in the spec's literal API list, but employees.shift_id and the
Employees/Settings pages both need a way to enumerate shifts -- added as a
small, obviously-necessary read (+ admin create) endpoint. See
docs/DECISIONS.md."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models.shifts import Shift
from app.models.users import User
from app.schemas.employees import ShiftOut

router = APIRouter(prefix="/shifts", tags=["shifts"])


@router.get("", response_model=list[ShiftOut])
async def list_shifts(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[ShiftOut]:
    result = await db.execute(select(Shift))
    shifts = list(result.scalars().all())
    return [
        ShiftOut(
            id=s.id, name=s.name, in_time=s.in_time.strftime("%H:%M"),
            out_time=s.out_time.strftime("%H:%M"), grace_minutes=s.grace_minutes, is_default=s.is_default,
        )
        for s in shifts
    ]


@router.post("", response_model=ShiftOut, status_code=201)
async def create_shift(
    name: str, in_time: str, out_time: str, grace_minutes: int = 15, is_default: bool = False,
    db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin),
) -> ShiftOut:
    from datetime import time as time_cls

    def _parse(t: str) -> time_cls:
        h, m = t.split(":")
        return time_cls(hour=int(h), minute=int(m))

    shift = Shift(name=name, in_time=_parse(in_time), out_time=_parse(out_time), grace_minutes=grace_minutes, is_default=is_default)
    db.add(shift)
    await db.commit()
    return ShiftOut(id=shift.id, name=shift.name, in_time=in_time, out_time=out_time, grace_minutes=grace_minutes, is_default=is_default)
