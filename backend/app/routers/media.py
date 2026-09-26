from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.attendance_events import AttendanceEvent
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.models.users import User
from app.services.media import absolute_path

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/crop/{event_id}")
async def get_event_crop(event_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> FileResponse:
    result = await db.execute(select(AttendanceEvent).where(AttendanceEvent.id == event_id))
    event = result.scalar_one_or_none()
    if event is None or not event.crop_path:
        raise http_error(404, "crop_not_found", "No crop stored for this event")
    path = absolute_path(event.crop_path)
    if not path.exists():
        raise http_error(404, "crop_not_found", "Crop file missing on disk")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/template/{template_id}")
async def get_template_crop(template_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> FileResponse:
    result = await db.execute(select(FaceTemplate).where(FaceTemplate.id == template_id))
    template = result.scalar_one_or_none()
    if template is None or not template.source_image_path:
        raise http_error(404, "crop_not_found", "No crop stored for this template")
    path = absolute_path(template.source_image_path)
    if not path.exists():
        raise http_error(404, "crop_not_found", "Crop file missing on disk")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/unknown/{unknown_id}")
async def get_unknown_crop(unknown_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> FileResponse:
    result = await db.execute(select(UnknownIdentity).where(UnknownIdentity.id == unknown_id))
    unknown = result.scalar_one_or_none()
    if unknown is None or not unknown.best_crop_path:
        raise http_error(404, "crop_not_found", "No crop stored for this identity")
    path = absolute_path(unknown.best_crop_path)
    if not path.exists():
        raise http_error(404, "crop_not_found", "Crop file missing on disk")
    return FileResponse(path, media_type="image/jpeg")
