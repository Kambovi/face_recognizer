"""Read-only client profile + camera list.

GET /profile is deliberately PUBLIC (no auth): the login page needs the
organisation name and sector theme before anyone has signed in. It contains
nothing sensitive -- the vendor PIN hash is never included (see
services/client_profile.public_view). There is intentionally NO write
endpoint: the profile is set by the vendor with scripts/setup_client.py.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
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
