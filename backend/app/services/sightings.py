"""Sighting log helpers: record each detection, keep it pointing at the
right person when events are re-assigned / linked / promoted, and count."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubjectType
from app.models.sightings import Sighting
from app.services.shiftday import LOCAL_TZ


async def repoint(
    db: AsyncSession,
    *,
    new_type: SubjectType,
    employee_id: str | None,
    unknown_identity_id: str | None,
    from_unknown_id: str | None = None,
    event_id: str | None = None,
) -> None:
    """Move sightings to a new subject: all of one unknown face (link /
    promote), or the ones behind one event (reassign)."""
    q = update(Sighting)
    if from_unknown_id is not None:
        q = q.where(Sighting.unknown_identity_id == from_unknown_id)
    elif event_id is not None:
        q = q.where(Sighting.event_id == event_id)
    else:
        raise ValueError("from_unknown_id or event_id required")
    await db.execute(q.values(subject_type=new_type, employee_id=employee_id, unknown_identity_id=unknown_identity_id))


def day_bounds(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    return (datetime.combine(d_from, time.min, tzinfo=LOCAL_TZ),
            datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=LOCAL_TZ))


async def counts(
    db: AsyncSession, employee_ids: list[str], d_from: date, d_to: date, kiosk_id: str | None = None,
) -> list[dict[str, Any]]:
    """Per person, per local day, per camera: detections, first, last."""
    if not employee_ids:
        return []
    lo, hi = day_bounds(d_from, d_to)
    q = select(Sighting.employee_id, Sighting.kiosk_id, Sighting.occurred_at).where(
        Sighting.employee_id.in_(employee_ids), Sighting.occurred_at >= lo, Sighting.occurred_at < hi)
    if kiosk_id:
        q = q.where(Sighting.kiosk_id == kiosk_id)
    groups: dict[tuple[str, date, str], list[datetime]] = {}
    for emp, kiosk, ts in (await db.execute(q)).all():
        local = ts.astimezone(LOCAL_TZ)
        groups.setdefault((emp, local.date(), kiosk), []).append(local)
    out = []
    for (emp, d, kiosk), times in sorted(groups.items(), key=lambda x: (x[0][1], x[0][0], x[0][2])):
        times.sort()
        out.append({"employee_id": emp, "date": d, "kiosk_id": kiosk, "count": len(times),
                    "first": times[0].strftime("%H:%M"), "last": times[-1].strftime("%H:%M")})
    return out

