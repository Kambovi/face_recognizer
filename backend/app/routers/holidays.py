"""Holiday calendar.

  GET    /holidays?year=2026        list (everyone)
  POST   /holidays                  {day, name, kind}         (HR)
  POST   /holidays/bulk             [{day, name, kind}, ...]  (HR, upsert by day)
  DELETE /holidays/{id}                                       (HR)
  GET    /holidays/presets/india?year=2026   national holidays to start from

kind: national / festival = paid day off for everyone (status H),
optional = listed only (restricted holiday, take it as leave).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_hr
from app.models.holidays import Holiday
from app.models.users import User
from app.services.audit import write_audit
from app.services.payroll_lock import ensure_unlocked

router = APIRouter(prefix="/holidays", tags=["holidays"])
Kind = Literal["national", "festival", "optional"]


class HolidayIn(BaseModel):
    day: date
    name: str = Field(min_length=1, max_length=120)
    kind: Kind = "festival"


def _out(h: Holiday) -> dict[str, Any]:
    return {"id": h.id, "day": h.day.isoformat(), "name": h.name, "kind": h.kind, "weekday": h.day.strftime("%a")}


@router.get("")
async def list_holidays(year: int | None = Query(None, ge=2000, le=2100), db: AsyncSession = Depends(get_db),
                        _u: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    q = select(Holiday)
    if year:
        q = q.where(Holiday.day >= date(year, 1, 1), Holiday.day <= date(year, 12, 31))
    return [_out(h) for h in (await db.execute(q.order_by(Holiday.day))).scalars().all()]


async def _upsert(db: AsyncSession, item: HolidayIn) -> Holiday:
    h = (await db.execute(select(Holiday).where(Holiday.day == item.day))).scalar_one_or_none()
    if h is None:
        h = Holiday(day=item.day, name=item.name.strip(), kind=item.kind)
        db.add(h)
    else:
        h.name, h.kind = item.name.strip(), item.kind
    await db.flush()
    return h


@router.post("", status_code=201)
async def add_holiday(payload: HolidayIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    await ensure_unlocked(db, payload.day)
    h = await _upsert(db, payload)
    await write_audit(db, user.id, "holiday_set", "holiday", h.day.isoformat(), after={"name": h.name, "kind": h.kind})
    await db.commit()
    return _out(h)


@router.post("/bulk", status_code=201)
async def add_bulk(payload: list[HolidayIn], db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, int]:
    if len(payload) > 100:
        raise http_error(422, "too_many", "At most 100 holidays at once")
    await ensure_unlocked(db, *[p.day for p in payload])
    for item in payload:
        await _upsert(db, item)
    await write_audit(db, user.id, "holiday_bulk", "holiday", str(len(payload)),
                      after={"days": [p.day.isoformat() for p in payload]})
    await db.commit()
    return {"saved": len(payload)}


@router.delete("/{holiday_id}", status_code=204, response_model=None)
async def delete_holiday(holiday_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> None:
    h = await db.get(Holiday, holiday_id)
    if h is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Holiday not found")
    await ensure_unlocked(db, h.day)
    await write_audit(db, user.id, "holiday_delete", "holiday", h.day.isoformat(), before={"name": h.name})
    await db.delete(h)
    await db.commit()


# Fixed-date national holidays. Festival dates move every year (Holi, Eid,
# Diwali ...) and differ by state, so they are added by HR from the
# state government's list.
NATIONAL = [((1, 26), "Republic Day"), ((8, 15), "Independence Day"), ((10, 2), "Gandhi Jayanti")]


@router.get("/presets/india")
async def india_preset(year: int = Query(..., ge=2000, le=2100), _u: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [{"day": date(year, m, d).isoformat(), "name": n, "kind": "national"} for (m, d), n in NATIONAL]
