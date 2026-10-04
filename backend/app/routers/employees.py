from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import http_error, require_hr
from app.models.consents import Consent
from app.models.employees import Employee
from app.models.enums import OwnerType
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
from app.services import biometrics
from app.services.audit import write_audit
from app.services.face_store import MAX_ENROLL_BYTES
from app.services.ids import next_employee_face_id
from app.services.shiftday import LOCAL_TZ
from app.services.roster import validate_assignment
from app.services.settings_service import get_setting

router = APIRouter(prefix="/employees", tags=["employees"])



def _template_out(t: dict) -> FaceTemplateOut:
    return FaceTemplateOut(id=t["id"], quality_score=t["quality_score"], model_version=t["model_version"],
                           created_at=t["created_at"], is_primary=t["is_primary"],
                           crop_url=f"/api/v1/media/template/{t['id']}" if t.get("has_image") else None)


async def _get_employee_or_404(db: AsyncSession, employee_id: str) -> Employee:
    result = await db.execute(select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None)))
    employee = result.scalar_one_or_none()
    if employee is None:
        raise http_error(404, "employee_not_found", "Employee not found")
    return employee


@router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(
    payload: EmployeeCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)
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
        monthly_salary=payload.monthly_salary,
        date_of_joining=payload.date_of_joining,
        date_of_leaving=payload.date_of_leaving,
        weekly_off_days=payload.weekly_off_days,
    )
    if employee.date_of_leaving and employee.date_of_joining and employee.date_of_leaving < employee.date_of_joining:
        raise http_error(422, "bad_dates", "Leaving date is before joining date")
    db.add(employee)
    await db.flush()
    await write_audit(db, user.id, "create", "employee", employee.id, before=None, after={"name": employee.name})
    await db.commit()
    biometrics.config_changed()
    return EmployeeOut.model_validate(employee)


@router.get("", response_model=EmployeeListResponse)
async def list_employees(
    department: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = Query(50, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_hr),
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

    # one grouped query instead of one per person (1000-person clients)
    counts = await biometrics.counts(db, [e.id for e in employees])
    items = []
    for emp in employees:
        out = EmployeeOut.model_validate(emp)
        out.template_count = counts.get(emp.id, 0)
        items.append(out)

    return EmployeeListResponse(items=items, total=total, page=page, page_size=page_size)


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
) -> EmployeeOut:
    employee = await _get_employee_or_404(db, employee_id)
    changes = payload.model_dump(exclude_unset=True)
    if "home_kiosk_id" in changes and not changes["home_kiosk_id"]:
        changes["home_kiosk_id"] = None
    if "contractor" in changes:
        changes["contractor"] = (changes["contractor"] or "").strip() or None
    if "watchlist_reason" in changes:
        changes["watchlist_reason"] = (changes["watchlist_reason"] or "").strip() or None
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
              "home_kiosk_id": employee.home_kiosk_id, "monthly_salary": float(employee.monthly_salary or 0) or None,
              "date_of_joining": str(employee.date_of_joining or ""), "date_of_leaving": str(employee.date_of_leaving or "")}
    doj = changes.get("date_of_joining", employee.date_of_joining)
    dol = changes.get("date_of_leaving", employee.date_of_leaving)
    if doj and dol and dol < doj:
        raise http_error(422, "bad_dates", "Leaving date is before joining date")
    for field, value in changes.items():
        setattr(employee, field, value)
    await db.flush()
    await write_audit(db, user.id, "update", "employee", employee.id, before=before, after=payload.model_dump(mode="json", exclude_unset=True))
    await db.commit()
    biometrics.config_changed()
    return EmployeeOut.model_validate(employee)


@router.delete("/{employee_id}", status_code=204, response_model=None)
async def delete_employee(
    employee_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)
) -> None:
    employee = await _get_employee_or_404(db, employee_id)
    # face templates + enrolment photos erased first (cloud: on the edge box;
    # if the box is offline this fails and nothing is marked deleted)
    await biometrics.purge(db, OwnerType.EMPLOYEE, employee.id)

    # Consent records are KEPT (marked revoked): they are the proof that the
    # face data was collected lawfully and has now been erased (DPDP).
    now = datetime.now(timezone.utc)
    consents_result = await db.execute(select(Consent).where(Consent.employee_id == employee.id))
    for consent in consents_result.scalars().all():
        if consent.revoked_at is None:
            consent.revoked_at = now

    employee.is_active = False
    employee.deleted_at = now
    if employee.date_of_leaving is None:
        employee.date_of_leaving = now.astimezone(LOCAL_TZ).date()

    await write_audit(db, user.id, "delete", "employee", employee.id, before={"name": employee.name}, after=None)
    await db.commit()
    biometrics.config_changed()


@router.post("/{employee_id}/consent", response_model=ConsentOut, status_code=201)
async def grant_consent(
    employee_id: str, payload: ConsentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)
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
    employee_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)
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
    await biometrics.purge(db, OwnerType.EMPLOYEE, employee.id)
    await write_audit(db, user.id, "revoke_consent", "employee", employee.id)
    await db.commit()


@router.post("/{employee_id}/enroll", response_model=EnrollResponse)
async def enroll_employee(
    employee_id: str,
    files: list[UploadFile],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_hr),
) -> EnrollResponse:
    employee = await _get_employee_or_404(db, employee_id)

    if not (1 <= len(files) <= 5):
        raise http_error(422, "invalid_image_count", "Provide between 1 and 5 images")

    consent_result = await db.execute(
        select(Consent).where(Consent.employee_id == employee.id, Consent.revoked_at.is_(None))
    )
    if consent_result.scalar_one_or_none() is None:
        raise http_error(422, "consent_required", "An active consent record is required before enrollment")

    min_face_pixels = int(await get_setting(db, "min_face_pixels"))
    images: list[tuple[str, bytes]] = []
    too_big: list[EnrollImageResult] = []
    for upload in files:
        data = await upload.read(MAX_ENROLL_BYTES + 1)
        if len(data) > MAX_ENROLL_BYTES:
            too_big.append(EnrollImageResult(filename=upload.filename or "image", accepted=False,
                                             reason="file_too_large", quality_score=0.0))
        else:
            images.append((upload.filename or "image", data))
    # cloud: the photos go straight to the site's edge box (never stored here)
    res = await biometrics.enroll(db, employee.id, images, min_face_pixels) if images else \
        {"results": [], "accepted_count": 0, "template_count": (await biometrics.counts(db, [employee.id])).get(employee.id, 0)}
    results = too_big + [EnrollImageResult(**r) for r in res["results"]]
    accepted_count = int(res["accepted_count"])
    await write_audit(db, user.id, "enroll", "employee", employee.id, after={"accepted": accepted_count})
    await db.commit()
    return EnrollResponse(results=results, accepted_count=accepted_count, template_count=int(res["template_count"]))


@router.get("/{employee_id}/templates", response_model=list[FaceTemplateOut])
async def list_templates(
    employee_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_hr)
) -> list[FaceTemplateOut]:
    await _get_employee_or_404(db, employee_id)
    return [_template_out(t) for t in await biometrics.list_templates(db, OwnerType.EMPLOYEE, employee_id)]


@router.delete("/{employee_id}/templates/{template_id}", status_code=204, response_model=None)
async def delete_template(
    employee_id: str, template_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)
) -> None:
    await _get_employee_or_404(db, employee_id)
    if not await biometrics.delete_template(db, OwnerType.EMPLOYEE, employee_id, template_id):
        raise http_error(404, "template_not_found", "Face template not found")
    await write_audit(db, user.id, "delete_template", "face_template", template_id)
    await db.commit()
