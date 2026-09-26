from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.models.users import User
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.audit import write_audit
from app.services.settings_service import DEFAULT_SETTINGS, get_all_settings, set_setting

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings_endpoint(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> SettingsResponse:
    settings_dict = await get_all_settings(db)
    heartbeats = list((await db.execute(select(KioskHeartbeat))).scalars().all())
    device = None
    if heartbeats:
        latest = max(heartbeats, key=lambda h: h.last_seen_at)
        device = dict(latest.device_json)
        device["kiosk_id"] = latest.kiosk_id
    return SettingsResponse(settings=settings_dict, device=device)


@router.patch("", response_model=SettingsResponse)
async def update_settings_endpoint(
    payload: SettingsUpdateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> SettingsResponse:
    before = await get_all_settings(db)
    for key, value in payload.values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        await set_setting(db, key, value)
    after = await get_all_settings(db)
    await write_audit(db, user.id, "update_settings", "settings", "global", before=before, after=after)
    await db.commit()
    return SettingsResponse(settings=after, device=None)
