from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_kiosk_token
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.schemas.kiosk import (
    KioskConfigResponse,
    KioskEventRequest,
    KioskEventResponse,
    KioskHeartbeatRequest,
    KioskHeartbeatResponse,
)
from app.services.recognition import process_kiosk_event
from app.services.settings_service import apply_device_profile_defaults_if_unset, get_all_settings

router = APIRouter(prefix="/kiosk", tags=["kiosk"])


@router.post("/event", response_model=KioskEventResponse)
async def post_kiosk_event(
    payload: KioskEventRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_kiosk_token),
) -> KioskEventResponse:
    config = await get_all_settings(db)
    outcome = await process_kiosk_event(db, payload, config)
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


@router.post("/heartbeat", response_model=KioskHeartbeatResponse)
async def post_heartbeat(
    payload: KioskHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    _token: str = Depends(require_kiosk_token),
) -> KioskHeartbeatResponse:
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
    _token: str = Depends(require_kiosk_token),
) -> KioskConfigResponse:
    settings_dict = await get_all_settings(db)
    return KioskConfigResponse(settings=settings_dict)
