"""Face photos for the dashboard (login required).

standalone: read from MEDIA_ROOT. cloud: fetched from the client's edge box
over the tunnel and passed straight to the browser (never stored here).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.attendance_events import AttendanceEvent
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.models.users import User
from app.services import biometrics

router = APIRouter(prefix="/media", tags=["media"])


def _jpeg(data: bytes | None) -> Response:
    if not data:
        raise http_error(404, "crop_not_found", "Photo not available")
    # private: face photos must not sit in shared caches
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/crop/{event_id}")
async def get_event_crop(event_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> Response:
    event = (await db.execute(select(AttendanceEvent).where(AttendanceEvent.id == event_id))).scalar_one_or_none()
    if event is None or not event.crop_path:
        raise http_error(404, "crop_not_found", "No crop stored for this event")
    return _jpeg(await biometrics.photo(db, event.crop_path))


@router.get("/template/{template_id}")
async def get_template_crop(template_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> Response:
    if biometrics.cloud():
        return _jpeg(await biometrics.photo(db, f"tpl:{template_id}"))
    template = (await db.execute(select(FaceTemplate).where(FaceTemplate.id == template_id))).scalar_one_or_none()
    if template is None or not template.source_image_path:
        raise http_error(404, "crop_not_found", "No crop stored for this template")
    return _jpeg(await biometrics.photo(db, template.source_image_path))


@router.get("/unknown/{unknown_id}")
async def get_unknown_crop(unknown_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> Response:
    unknown = (await db.execute(select(UnknownIdentity).where(UnknownIdentity.id == unknown_id))).scalar_one_or_none()
    if unknown is None or not unknown.best_crop_path:
        raise http_error(404, "crop_not_found", "No crop stored for this identity")
    return _jpeg(await biometrics.photo(db, unknown.best_crop_path))


@router.get("/employee/{employee_id}")
async def get_employee_photo(employee_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> Response:
    """The person's primary enrolment photo (avatar)."""
    return _jpeg(await biometrics.photo(db, f"emp:{employee_id}"))
