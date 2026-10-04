"""Camera / kiosk registration with per-camera tokens (admin).

  GET    /devices                 registered cameras (+ last used)
  POST   /devices                 {kiosk_id, name} -> token shown ONCE
  POST   /devices/{id}/rotate     new token (old one stops working at once)
  PATCH  /devices/{id}            {name?, enabled?}
  DELETE /devices/{id}

Put the token in the camera PC's kiosk .env as KIOSK_SERVICE_TOKEN with the
same KIOSK_ID. Once every camera has its own token, clear the shared
KIOSK_SERVICE_TOKEN in the backend .env.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import hash_device_token, http_error, require_admin
from app.models.kiosk_devices import KIOSK_ID_PATTERN, KioskDevice
from app.models.users import User
from app.services import biometrics
from app.services.audit import write_audit

router = APIRouter(prefix="/devices", tags=["devices"])


def _out(d: KioskDevice) -> dict[str, Any]:
    return {"id": d.id, "kiosk_id": d.kiosk_id, "name": d.name, "enabled": d.enabled,
            "created_at": d.created_at, "last_used_at": d.last_used_at}


class DeviceIn(BaseModel):
    kiosk_id: str = Field(pattern=KIOSK_ID_PATTERN)
    name: str | None = Field(default=None, max_length=120)


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


def _new_token() -> tuple[str, str]:
    token = "kt_" + secrets.token_urlsafe(32)
    return token, hash_device_token(token)


@router.get("")
async def list_devices(db: AsyncSession = Depends(get_db), _a: User = Depends(require_admin)) -> list[dict[str, Any]]:
    return [_out(d) for d in (await db.execute(select(KioskDevice).order_by(KioskDevice.kiosk_id))).scalars().all()]


@router.post("", status_code=201)
async def add_device(payload: DeviceIn, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict[str, Any]:
    if (await db.execute(select(KioskDevice).where(KioskDevice.kiosk_id == payload.kiosk_id))).scalar_one_or_none():
        raise http_error(409, "exists", "This camera ID is already registered -- rotate its token instead")
    if biometrics.cloud():  # SaaS plan limit
        from sqlalchemy import func

        from app.tenancy import current_tenant

        t = current_tenant.get()
        n = int((await db.execute(select(func.count()).select_from(KioskDevice))).scalar_one())
        if t is not None and n >= t.max_cameras:
            raise http_error(402, "camera_limit", f"Your plan allows {t.max_cameras} camera(s). Contact your provider to add more.")
    token, digest = _new_token()
    d = KioskDevice(kiosk_id=payload.kiosk_id, name=payload.name, token_hash=digest)
    db.add(d)
    await db.flush()
    await write_audit(db, admin.id, "device_add", "camera", payload.kiosk_id)
    await db.commit()
    biometrics.config_changed()
    return {**_out(d), "token": token}


async def _get(db: AsyncSession, device_id: str) -> KioskDevice:
    d = await db.get(KioskDevice, device_id)
    if d is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Camera not found")
    return d


@router.post("/{device_id}/rotate")
async def rotate(device_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict[str, Any]:
    d = await _get(db, device_id)
    token, d.token_hash = _new_token()
    await write_audit(db, admin.id, "device_rotate", "camera", d.kiosk_id)
    await db.commit()
    biometrics.config_changed()
    return {**_out(d), "token": token}


@router.patch("/{device_id}")
async def update(device_id: str, payload: DevicePatch, db: AsyncSession = Depends(get_db),
                 admin: User = Depends(require_admin)) -> dict[str, Any]:
    d = await _get(db, device_id)
    if payload.name is not None:
        d.name = payload.name
    if payload.enabled is not None:
        d.enabled = payload.enabled
    await write_audit(db, admin.id, "device_update", "camera", d.kiosk_id, after=payload.model_dump(exclude_unset=True))
    await db.commit()
    biometrics.config_changed()
    return _out(d)


@router.delete("/{device_id}", status_code=204, response_model=None)
async def delete(device_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    d = await _get(db, device_id)
    await write_audit(db, admin.id, "device_delete", "camera", d.kiosk_id)
    await db.delete(d)
    await db.commit()
    biometrics.config_changed()
