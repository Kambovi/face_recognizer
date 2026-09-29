from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.consents import Consent
from app.models.employees import Employee
from app.models.enums import OwnerType, UnknownStatus
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.models.users import User
from app.schemas.employees import FaceTemplateOut
from app.schemas.unknowns import (
    LinkRequest,
    PromoteRequest,
    PromoteResponse,
    SplitRequest,
    SplitResponse,
    UnknownIdentityOut,
    UnknownListResponse,
    UnknownUpdateRequest,
)
from app.services.audit import write_audit
from app.services.roster import validate_assignment
from app.services.settings_service import DEFAULT_SETTINGS, get_setting
from app.services.unknown_identity import link_unknown_to_employee, promote_unknown_to_employee, split_unknown

router = APIRouter(prefix="/unknowns", tags=["unknowns"])


def _to_out(u: UnknownIdentity) -> UnknownIdentityOut:
    out = UnknownIdentityOut.model_validate(u)
    out.best_crop_url = f"/api/v1/media/unknown/{u.id}" if u.best_crop_path else None
    out.status = u.status.value
    return out


async def _get_unknown_or_404(db: AsyncSession, unknown_id: str) -> UnknownIdentity:
    result = await db.execute(select(UnknownIdentity).where(UnknownIdentity.id == unknown_id))
    unknown = result.scalar_one_or_none()
    if unknown is None:
        raise http_error(404, "unknown_not_found", "Unknown identity not found")
    return unknown


@router.get("", response_model=UnknownListResponse)
async def list_unknowns(
    status: str | None = None,
    sort: str = "sighting_count",
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> UnknownListResponse:
    stmt = select(UnknownIdentity)
    if status:
        stmt = stmt.where(UnknownIdentity.status == UnknownStatus(status))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    if sort == "last_seen":
        stmt = stmt.order_by(UnknownIdentity.last_seen_at.desc())
    else:
        stmt = stmt.order_by(UnknownIdentity.sighting_count.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    items = list((await db.execute(stmt)).scalars().all())
    return UnknownListResponse(items=[_to_out(u) for u in items], total=total, page=page, page_size=page_size)


@router.get("/{unknown_id}/templates", response_model=list[FaceTemplateOut])
async def list_unknown_templates(
    unknown_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)
) -> list[FaceTemplateOut]:
    """Mirrors GET /employees/{id}/templates -- needed so the HR dashboard's
    Split action can show which sightings exist on an unknown identity
    before choosing which ones to peel off into a new one (see
    services/unknown_identity.split_unknown, which already takes explicit
    template_ids and therefore always needed a way to list them first)."""
    await _get_unknown_or_404(db, unknown_id)
    result = await db.execute(
        select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.UNKNOWN, FaceTemplate.owner_id == unknown_id)
    )
    out = []
    for t in result.scalars().all():
        item = FaceTemplateOut.model_validate(t)
        item.crop_url = f"/api/v1/media/template/{t.id}" if t.source_image_path else None
        out.append(item)
    return out


@router.patch("/{unknown_id}", response_model=UnknownIdentityOut)
async def update_unknown(
    unknown_id: str, payload: UnknownUpdateRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> UnknownIdentityOut:
    unknown = await _get_unknown_or_404(db, unknown_id)
    before = {"label": unknown.label, "status": unknown.status.value}
    if payload.label is not None:
        unknown.label = payload.label
    if payload.notes is not None:
        unknown.notes = payload.notes
    if payload.status is not None:
        unknown.status = UnknownStatus(payload.status)
    if payload.watchlist_reason is not None:
        unknown.watchlist_reason = payload.watchlist_reason.strip() or None
    await write_audit(db, user.id, "update", "unknown_identity", unknown.id, before=before, after=payload.model_dump(exclude_unset=True))
    await db.commit()
    return _to_out(unknown)


@router.delete("/{unknown_id}", status_code=204, response_model=None)
async def delete_unknown(
    unknown_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> None:
    from app.models.attendance_events import AttendanceEvent
    from app.models.enums import OwnerType
    from app.models.face_templates import FaceTemplate

    unknown = await _get_unknown_or_404(db, unknown_id)

    for model, col in ((FaceTemplate, FaceTemplate.owner_id), (AttendanceEvent, AttendanceEvent.unknown_identity_id)):
        if model is FaceTemplate:
            result = await db.execute(select(model).where(FaceTemplate.owner_type == OwnerType.UNKNOWN, col == unknown.id))
        else:
            result = await db.execute(select(model).where(col == unknown.id))
        for row in result.scalars().all():
            await db.delete(row)

    await write_audit(db, user.id, "delete", "unknown_identity", unknown.id, before={"face_id": unknown.face_id})
    await db.delete(unknown)
    await db.commit()


@router.post("/{unknown_id}/link", response_model=UnknownIdentityOut)
async def link_unknown(
    unknown_id: str, payload: LinkRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> UnknownIdentityOut:
    unknown = await _get_unknown_or_404(db, unknown_id)
    result = await db.execute(select(Employee).where(Employee.id == payload.employee_id, Employee.deleted_at.is_(None)))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise http_error(404, "employee_not_found", "Target employee not found")

    min_q = float(await get_setting(db, "quality_min_score") or DEFAULT_SETTINGS["quality_min_score"])
    await link_unknown_to_employee(db, unknown, employee, payload.reason, payload.adopt_templates, user.email,
                                   min_template_quality=min_q)
    await write_audit(
        db, user.id, "link", "unknown_identity", unknown.id,
        after={"employee_id": employee.id, "adopt_templates": payload.adopt_templates, "reason": payload.reason},
    )
    await db.commit()
    return _to_out(unknown)


@router.post("/{unknown_id}/promote", response_model=PromoteResponse)
async def promote_unknown(
    unknown_id: str, payload: PromoteRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> PromoteResponse:
    unknown = await _get_unknown_or_404(db, unknown_id)

    if payload.consent is None:
        raise http_error(422, "consent_required", "Consent is required to promote an unknown identity")
    taken = await db.execute(select(Employee).where(Employee.emp_code == payload.emp_code))
    if taken.scalar_one_or_none() is not None:
        raise http_error(409, "emp_code_taken", f"ID '{payload.emp_code}' is already used by someone else")
    await validate_assignment(db, department=payload.department, home_kiosk_id=payload.home_kiosk_id)

    employee = await promote_unknown_to_employee(
        db, unknown, payload.name, payload.emp_code, payload.department, payload.designation, payload.shift_id, user.email,
        home_kiosk_id=payload.home_kiosk_id,
        contractor=payload.contractor,
        min_template_quality=float(await get_setting(db, "quality_min_score") or DEFAULT_SETTINGS["quality_min_score"]),
    )
    db.add(
        Consent(
            employee_id=employee.id,
            policy_version=payload.consent.policy_version,
            purpose_text=payload.consent.purpose_text,
            ip_address=payload.consent.ip_address,
        )
    )
    await write_audit(db, user.id, "promote", "unknown_identity", unknown.id, after={"employee_id": employee.id, "reason": payload.reason})
    await db.commit()
    return PromoteResponse(employee_id=employee.id, face_id=employee.face_id)


@router.post("/{unknown_id}/split", response_model=SplitResponse)
async def split_unknown_endpoint(
    unknown_id: str, payload: SplitRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> SplitResponse:
    unknown = await _get_unknown_or_404(db, unknown_id)
    try:
        new_unknown = await split_unknown(db, unknown, payload.template_ids, payload.reason, user.email)
    except ValueError as exc:
        raise http_error(422, "no_matching_templates", str(exc)) from exc

    await write_audit(db, user.id, "split", "unknown_identity", unknown.id, after={"new_unknown_id": new_unknown.id, "reason": payload.reason})
    await db.commit()
    return SplitResponse(new_unknown_id=new_unknown.id, new_face_id=new_unknown.face_id)
