"""Read-only client profile + camera list.

GET /profile is deliberately PUBLIC (no auth): the login page needs the
organisation name and sector theme before anyone has signed in. It contains
nothing sensitive -- the vendor PIN hash is never included (see
services/client_profile.public_view). There is intentionally NO write
endpoint: the profile is set by the vendor with scripts/setup_client.py.
"""
from __future__ import annotations

from typing import Any

import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import csvsafe
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.services.audit import write_audit
from app.services.muster import CameraRole, muster, set_camera_role
from app.models.users import User
from app.services.client_profile import get_profile
from app.services.roster import camera_overview

router = APIRouter(tags=["profile"])


@router.get("/profile")
async def read_profile(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return await get_profile(db)


@router.get("/cameras")
async def list_cameras(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return await camera_overview(db)


class CameraRoleIn(BaseModel):
    role: CameraRole


@router.patch("/cameras/{kiosk_id}")
async def update_camera_role(
    kiosk_id: str, payload: CameraRoleIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> dict[str, str]:
    """Entry / exit / both -- decides who counts as inside for the muster."""
    roles = await set_camera_role(db, kiosk_id, payload.role)
    await write_audit(db, user.id, "camera_role", "camera", kiosk_id, after={"role": payload.role})
    await db.commit()
    return roles


@router.get("/muster")
async def read_muster(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> dict[str, Any]:
    return await muster(db)


@router.get("/muster.csv")
async def muster_csv(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> Response:
    m = await muster(db)
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csvsafe.writer(buf)
    w.writerow(["Status", "ID", "Name", "Department", "Contractor", "Last seen", "Camera", "Safe (tick)"])
    for r in m["inside"]:
        w.writerow(["Inside", r["emp_code"], r["name"], r["department"] or "", r["contractor"] or "",
                    r["last_seen_at"].isoformat(timespec="minutes"), r["last_camera"], ""])
    for v in m["visitors_inside"]:
        w.writerow(["Visitor", v["face_id"], v["label"] or "Unidentified", "", "",
                    v["last_seen_at"].isoformat(timespec="minutes"), v["last_camera"], ""])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="muster.csv"'})
