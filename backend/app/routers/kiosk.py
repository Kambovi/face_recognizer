from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import KioskAuth, http_error, require_kiosk_token
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.schemas.kiosk import (
    KioskConfigResponse,
    KioskEventRequest,
    KioskEventResponse,
    KioskHeartbeatRequest,
    KioskHeartbeatResponse,
)
from app.services.media import BadImage
from app.services.recognition import process_kiosk_event
from app.services.settings_service import apply_device_profile_defaults_if_unset, get_all_settings

router = APIRouter(prefix="/kiosk", tags=["kiosk"])

# SQLite has no row locks: two cameras seeing the same person in the same
# second could both create that day's IN. Kiosk events are few per second at
# most, so on SQLite they are simply processed one at a time (Postgres uses
# a per-person advisory lock instead, see services/attendance.py).
_sqlite_event_lock = asyncio.Lock()


@router.post("/event", response_model=KioskEventResponse)
async def post_kiosk_event(
    payload: KioskEventRequest,
    db: AsyncSession = Depends(get_db),
    auth: KioskAuth = Depends(require_kiosk_token),
) -> KioskEventResponse:
    auth.check(payload.kiosk_id)
    config = await get_all_settings(db)
    _check_event_time(payload, config)
    _enforce_liveness(payload, config)
    is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    try:
        async with (nullcontext() if is_pg else _sqlite_event_lock):
            outcome = await process_kiosk_event(db, payload, config)
    except BadImage as exc:
        raise http_error(422, "bad_crop", str(exc)) from exc
    if outcome.event is None:  # unclear face: logged as a sighting, nothing else
        return KioskEventResponse(event_id=None, subject_type=None, face_id=None, event_type=None,
                                  similarity=None, created=False)
    return KioskEventResponse(
        event_id=outcome.event.id,
        subject_type=outcome.event.subject_type.value if outcome.event.subject_type else None,
        face_id=outcome.face_id,
        event_type=outcome.event.event_type.value if outcome.event.subject_type else None,
        similarity=outcome.event.similarity,
        created=outcome.created,
    )


def _check_event_time(payload: KioskEventRequest, config: dict) -> None:
    """The kiosk stamps the time, so a stolen camera token could back-date
    attendance. Accept only "now" (with a little clock drift) or a recent
    offline-queued event. 422 = the kiosk drops the event (not retried)."""
    ts = payload.occurred_at if payload.occurred_at.tzinfo else payload.occurred_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if ts > now + timedelta(minutes=float(config.get("max_event_future_minutes", 5))):
        raise http_error(422, "event_in_future", "Event time is in the future -- check the camera PC's clock")
    if ts < now - timedelta(hours=float(config.get("max_event_age_hours", 72))):
        raise http_error(422, "event_too_old", "Event is older than max_event_age_hours")


def _enforce_liveness(payload: KioskEventRequest, config: dict) -> None:
    """Server-side backstop for the kiosk's anti-spoofing: with liveness on
    and required, a face for recognition must carry a passing score."""
    if payload.embedding is None:
        return
    if not (config.get("liveness_enabled", True) and config.get("liveness_required", True)):
        return
    score = payload.liveness_score
    if score is None or score < float(config.get("liveness_threshold", 0.5)):
        payload.embedding = None
        payload.reject_reason = "liveness_failed"


@router.post("/heartbeat", response_model=KioskHeartbeatResponse)
async def post_heartbeat(
    payload: KioskHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    auth: KioskAuth = Depends(require_kiosk_token),
) -> KioskHeartbeatResponse:
    auth.check(payload.kiosk_id)
    result = await db.execute(select(KioskHeartbeat).where(KioskHeartbeat.kiosk_id == payload.kiosk_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = KioskHeartbeat(kiosk_id=payload.kiosk_id, device_json=payload.device)
        db.add(row)
    else:
        row.device_json = payload.device
        row.last_seen_at = datetime.now(timezone.utc)

    profile = payload.device.get("profile")
    if profile:
        await apply_device_profile_defaults_if_unset(db, profile)

    await db.commit()
    return KioskHeartbeatResponse(ok=True)


@router.get("/config", response_model=KioskConfigResponse)
async def get_kiosk_config(
    db: AsyncSession = Depends(get_db),
    _auth: KioskAuth = Depends(require_kiosk_token),
) -> KioskConfigResponse:
    settings_dict = await get_all_settings(db)
    return KioskConfigResponse(settings=settings_dict)
