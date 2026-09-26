"""Alert feed for the dashboard bell, plus the watchlist.

  GET  /alerts               newest first (?open_only=true)
  GET  /alerts/count         open (unacknowledged) count -- polled by the bell
  POST /alerts/{id}/ack      acknowledge one
  POST /alerts/ack-all       acknowledge everything open
  GET  /alerts/watchlist     everyone / every face on the watchlist
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.alerts import Alert
from app.models.employees import Employee
from app.models.unknown_identities import UnknownIdentity
from app.models.users import User

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _photo(a: Alert) -> str | None:
    if a.event_id:
        return f"/api/v1/media/crop/{a.event_id}"
    if a.unknown_identity_id:
        return f"/api/v1/media/unknown/{a.unknown_identity_id}"
    return None


def _out(a: Alert) -> dict[str, Any]:
    return {
        "id": a.id,
        "created_at": a.created_at,
        "kind": a.kind,
        "kiosk_id": a.kiosk_id,
        "title": a.title,
        "detail": a.detail,
        "employee_id": a.employee_id,
        "unknown_identity_id": a.unknown_identity_id,
        "photo_url": _photo(a),
        "acknowledged_at": a.acknowledged_at,
        "acknowledged_by": a.acknowledged_by,
    }


@router.get("")
async def list_alerts(
    open_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    q = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if open_only:
        q = q.where(Alert.acknowledged_at.is_(None))
    return [_out(a) for a in (await db.execute(q)).scalars().all()]


@router.get("/count")
async def open_count(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> dict[str, Any]:
    n = (await db.execute(select(func.count()).select_from(Alert).where(Alert.acknowledged_at.is_(None)))).scalar_one()
    latest = (await db.execute(select(func.max(Alert.created_at)))).scalar_one_or_none()
    return {"open": int(n), "latest_at": latest}


@router.post("/{alert_id}/ack")
async def ack(alert_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    a = await db.get(Alert, alert_id)
    if a is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Alert not found")
    if a.acknowledged_at is None:
        a.acknowledged_at = datetime.now(timezone.utc)
        a.acknowledged_by = user.email
        await db.commit()
    return _out(a)


@router.post("/ack-all")
async def ack_all(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:
    res = await db.execute(
        update(Alert)
        .where(Alert.acknowledged_at.is_(None))
        .values(acknowledged_at=datetime.now(timezone.utc), acknowledged_by=user.email)
    )
    await db.commit()
    return {"acknowledged": int(getattr(res, "rowcount", 0) or 0)}


@router.get("/watchlist")
async def watchlist(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    people = (await db.execute(select(Employee).where(Employee.watchlist_reason.is_not(None)))).scalars().all()
    faces = (await db.execute(select(UnknownIdentity).where(UnknownIdentity.watchlist_reason.is_not(None)))).scalars().all()
    out: list[dict[str, Any]] = [
        {"type": "person", "id": p.id, "name": p.name, "code": p.emp_code, "reason": p.watchlist_reason,
         "active": p.is_active, "photo_url": None}
        for p in people
    ]
    out += [
        {"type": "face", "id": u.id, "name": u.label or u.face_id, "code": u.face_id, "reason": u.watchlist_reason,
         "active": True, "photo_url": f"/api/v1/media/unknown/{u.id}" if u.best_crop_path else None}
        for u in faces
    ]
    return out
