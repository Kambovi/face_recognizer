from __future__ import annotations

import math
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.models.users import User
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest
from app.services.audit import write_audit
from app.services.settings_service import DEFAULT_SETTINGS, get_all_settings, set_setting
from app.services.statutory import PT_SLABS

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


def _validate(key: str, value: Any) -> Any:
    """A setting must keep the type of its default (a typo like "0.4a" for a
    threshold would otherwise reach every camera)."""
    default = DEFAULT_SETTINGS[key]
    bad = http_error(422, "bad_setting", f"{key}: expected {type(default).__name__ if default is not None else 'text'}")
    if key == "attendance_start_date":
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise http_error(422, "bad_setting", f"{key}: use YYYY-MM-DD") from exc
    if key == "payroll_state":
        v = str(value or "").upper()
        if v and v not in PT_SLABS:
            raise http_error(422, "bad_setting", f"payroll_state: one of {', '.join(PT_SLABS)} or empty")
        return v
    if key == "leave_types":
        if not isinstance(value, list) or not all(isinstance(t, dict) and str(t.get("code", "")).strip() for t in value):
            raise http_error(422, "bad_setting", "leave_types: a list of {code, name, paid, annual, accrual, carry_forward}")
        return value
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise bad
        return value
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise bad
        return value
    if isinstance(default, str):
        if not isinstance(value, str) or len(value) > 500:
            raise bad
        return value
    if isinstance(default, list) and not isinstance(value, list):
        raise bad
    if isinstance(default, dict) and not isinstance(value, dict):
        raise bad
    return value


@router.patch("", response_model=SettingsResponse)
async def update_settings_endpoint(
    payload: SettingsUpdateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> SettingsResponse:
    before = await get_all_settings(db)
    for key, value in payload.values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        await set_setting(db, key, _validate(key, value))
    after = await get_all_settings(db)
    await write_audit(db, user.id, "update_settings", "settings", "global", before=before, after=after)
    await db.commit()
    return SettingsResponse(settings=after, device=None)
