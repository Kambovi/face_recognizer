from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import http_error, require_admin
from app.models.consents import Consent
from app.models.employees import Employee
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.models.users import User
from app.schemas.employees import (
    ConsentCreate,
    ConsentOut,
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeOut,
    EmployeeUpdate,
    EnrollImageResult,
    EnrollResponse,
    FaceTemplateOut,
)
from app.security import encrypt_embedding
from app.services.audit import write_audit
from app.services.embedding import process_enrollment_image
from app.services.ids import next_employee_face_id
from app.services.media import save_face_crop
from app.services.roster import validate_assignment
from app.services.settings_service import get_setting

router = APIRouter(prefix="/employees", tags=["employees"])

MAX_TEMPLATES_PER_OWNER = 5


async def _template_count(db: AsyncSession, employee_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(FaceTemplate).where(
            FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee_id
        )
    )
    return result.scalar_one()


async def _get_employee_or_404(db: AsyncSession, employee_id: str) -> Employee:
    result = await db.execute(select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None)))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise http_error(404, "employee_not_found", "Employee not found")
    return employee


@router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(
    payload: EmployeeCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> EmployeeOut:
    existing = await db.execute(select(Employee).where(Employee.emp_code == payload.emp_code))
    if existing.scalar_one_or_none() is not None:
        raise http_error(409, "emp_code_taken", "An employee with this emp_code already exists")
    await validate_assignment(db, department=payload.department, home_kiosk_id=payload.home_kiosk_id)

    face_id = await next_employee_face_id(db)
    employee = Employee(
        face_id=face_id,
        emp_code=payload.emp_code,
        name=payload.name,
        department=payload.department,
        designation=payload.designation,
        shift_id=payload.shift_id,
        home_kiosk_id=payload.home_kiosk_id or None,
        contractor=(payload.contractor or "").strip() or None,
    )
    db.add(employee)
    await db.flush()
    await write_audit(db, user.id, "create", "employee", employee.id, before=None, after={"name": employee.name})
    await db.commit()
    return EmployeeOut.model_validate(employee)


@router.get("", response_model=EmployeeListResponse)
async def list_employees(
    department: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
) -> EmployeeListResponse:
    stmt = select(Employee).where(Employee.deleted_at.is_(None))
    if department:
        stmt = stmt.where(Employee.department == department)
    if is_active is not None:
        stmt = stmt.where(Employee.is_active == is_active)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Employee.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    employees = list((await db.execute(stmt)).scalars().all())

    items = []
    for emp in employees:
        out = EmployeeOut.model_validate(emp)
        out.template_count = await _template_count(db, emp.id)
        items.append(out)

    return EmployeeListResponse(items=items, total=total, page=page, page_size=page_size)


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> EmployeeOut:
    employee = await _get_employee_or_404(db, employee_id)
    changes = payload.model_dump(exclude_unset=True)
    if "home_kiosk_id" in changes and not changes["home_kiosk_id"]:
        changes["home_kiosk_id"] = None
    if "contractor" in changes:
        changes["contractor"] = (changes["contractor"] or "").strip() or None
    new_camera = changes.get("home_kiosk_id", employee.home_kiosk_id)
    new_active = changes.get("is_active", employee.is_active)
    await validate_assignment(
        db,
        department=changes.get("department", employee.department),
        home_kiosk_id=new_camera,
        will_be_active=bool(new_active),
        employee_id=employee.id,
        department_changed="department" in changes,
        # re-check the cap when moving camera OR re-activating someone
        camera_changed=new_camera != employee.home_kiosk_id or (bool(new_active) and not employee.is_active),
    )
    before = {"name": employee.name, "is_active": employee.is_active, "department": employee.department,
              "home_kiosk_id": employee.home_kiosk_id}
    for field, value in changes.items():
        setattr(employee, field, value)
    await db.flush()
    await write_audit(db, user.id, "update", "employee", employee.id, before=before, after=payload.model_dump(exclude_unset=True))
    await db.commit()
    return EmployeeOut.model_validate(employee)


@router.delete("/{employee_id}", status_code=204, response_model=None)
async def delete_employee(
    employee_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> None:
    employee = await _get_employee_or_404(db, employee_id)

    templates_result = await db.execute(
        select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee.id)
    )
    for template in templates_result.scalars().all():
        await db.delete(template)

    consents_result = await db.execute(select(Consent).where(Consent.employee_id == employee.id))
    for consent in consents_result.scalars().all():
        await db.delete(consent)

    employee.is_active = False
    employee.deleted_at = datetime.now(timezone.utc)

    await write_audit(db, user.id, "delete", "employee", employee.id, before={"name": employee.name}, after=None)
    await db.commit()


@router.post("/{employee_id}/consent", response_model=ConsentOut, status_code=201)
async def grant_consent(
    employee_id: str, payload: ConsentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> ConsentOut:
    employee = await _get_employee_or_404(db, employee_id)
    consent = Consent(
        employee_id=employee.id,
        policy_version=payload.policy_version,
        purpose_text=payload.purpose_text,
        ip_address=payload.ip_address,
    )
    db.add(consent)
    await write_audit(db, user.id, "grant_consent", "employee", employee.id)
    await db.commit()
    await db.refresh(consent)
    return ConsentOut.model_validate(consent)


@router.delete("/{employee_id}/consent", status_code=204, response_model=None)
async def revoke_consent(
    employee_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> None:
    employee = await _get_employee_or_404(db, employee_id)
    result = await db.execute(
        select(Consent).where(Consent.employee_id == employee.id, Consent.revoked_at.is_(None))
    )
    consents = list(result.scalars().all())
    if not consents:
        raise http_error(404, "no_active_consent", "No active consent to revoke")
    for consent in consents:
        consent.revoked_at = datetime.now(timezone.utc)
    employee.is_active = False
    # Revoking consent disables recognition for this person immediately.
    # Setting is_active=False alone does NOT do that: search_templates()
    # (app/services/matching.py) searches face_templates directly and never
    # joins against employees.is_active or consents.revoked_at (a real gap,
    # found and fixed in this pass -- see docs/DECISIONS.md, "consent
    # revocation must actually stop matching"). Deleting the templates here
    # -- the same action delete_employee() already takes -- is what actually
    # removes this person from the matchable pool, rather than only
    # recording that consent was revoked while leaving them fully
    # matchable.
    templates_result = await db.execute(
        select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee.id)
    )
    for template in templates_result.scalars().all():
        await db.delete(template)
    await write_audit(db, user.id, "revoke_consent", "employee", employee.id)
    await db.commit()


@router.post("/{employee_id}/enroll", response_model=EnrollResponse)
async def enroll_employee(
    employee_id: str,
    files: list[UploadFile],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> EnrollResponse:
    employee = await _get_employee_or_404(db, employee_id)

    if not (1 <= len(files) <= 5):
        raise http_error(422, "invalid_image_count", "Provide between 1 and 5 images")

    consent_result = await db.execute(
        select(Consent).where(Consent.employee_id == employee.id, Consent.revoked_at.is_(None))
    )
    if consent_result.scalar_one_or_none() is None:
        raise http_error(422, "consent_required", "An active consent record is required before enrollment")

    min_face_pixels = await get_setting(db, "min_face_pixels")
    existing_count = await _template_count(db, employee.id)

    results: list[EnrollImageResult] = []
    accepted_count = 0

    for upload in files:
        image_bytes = await upload.read()
        if existing_count + accepted_count >= MAX_TEMPLATES_PER_OWNER:
            results.append(
                EnrollImageResult(filename=upload.filename or "image", accepted=False, reason="template_limit_reached", quality_score=0.0)
            )
            continue

        outcome = process_enrollment_image(image_bytes, min_face_pixels)
        if not outcome.accepted or outcome.embedding is None:
            results.append(
                EnrollImageResult(filename=upload.filename or "image", accepted=False, reason=outcome.reason, quality_score=outcome.quality_score)
            )
            continue

        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2] if img is not None else (0, 0)
        box = (w * 0.2, h * 0.1, w * 0.8, h * 0.9) if img is not None else (0, 0, 0, 0)
        crop_path = save_face_crop(img, box, subdir=f"employees/{employee.id}") if img is not None else None

        template = FaceTemplate(
            owner_type=OwnerType.EMPLOYEE,
            owner_id=employee.id,
            embedding=outcome.embedding,
            embedding_encrypted=encrypt_embedding(outcome.embedding),
            quality_score=outcome.quality_score,
            model_version=outcome.model_version,
            source_image_path=crop_path,
            is_primary=(existing_count + accepted_count == 0),
        )
        db.add(template)
        await db.flush()
        accepted_count += 1
        results.append(
            EnrollImageResult(
                filename=upload.filename or "image",
                accepted=True,
                reason=None,
                quality_score=outcome.quality_score,
                template_id=template.id,
            )
        )
        # Raw uploaded bytes (`image_bytes`) go out of scope here and are
        # never written to disk -- only the derived crop above survives.

    await write_audit(db, user.id, "enroll", "employee", employee.id, after={"accepted": accepted_count})
    await db.commit()

    return EnrollResponse(results=results, accepted_count=accepted_count, template_count=existing_count + accepted_count)


@router.get("/{employee_id}/templates", response_model=list[FaceTemplateOut])
async def list_templates(
    employee_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)
) -> list[FaceTemplateOut]:
    await _get_employee_or_404(db, employee_id)
    result = await db.execute(
        select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee_id)
    )
    out = []
    for t in result.scalars().all():
        item = FaceTemplateOut.model_validate(t)
        item.crop_url = f"/api/v1/media/template/{t.id}" if t.source_image_path else None
        out.append(item)
    return out


@router.delete("/{employee_id}/templates/{template_id}", status_code=204, response_model=None)
async def delete_template(
    employee_id: str, template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
) -> None:
    await _get_employee_or_404(db, employee_id)
    result = await db.execute(
        select(FaceTemplate).where(
            FaceTemplate.id == template_id, FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee_id
        )
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise http_error(404, "template_not_found", "Face template not found")
    await db.delete(template)
    await write_audit(db, user.id, "delete_template", "face_template", template_id)
    await db.commit()
