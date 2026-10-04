"""Face templates and face photos in THIS database / disk.

Used by a standalone install directly, and by an edge box when the cloud
asks for something over the tunnel (edge/rpc.py). The cloud never calls
these: it has no templates and no photos (services/biometrics.py routes
its requests to the edge box instead).

Photo references (what the cloud stores instead of paths):
  det:<client_event_id>   photo of one detection
  unk:<unknown_id>        best photo of an unknown person
  tpl:<template_id>       enrolment photo of a template
  emp:<employee_id>       the person's primary enrolment photo
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.edge import EdgeDetection
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.security import encrypt_embedding
from app.services.media import absolute_path, save_face_crop

MAX_TEMPLATES_PER_OWNER = 5
MAX_ENROLL_BYTES = 10 * 1024 * 1024


def template_dict(t: FaceTemplate) -> dict[str, Any]:
    return {"id": t.id, "quality_score": t.quality_score, "model_version": t.model_version,
            "created_at": t.created_at.isoformat(), "is_primary": t.is_primary,
            "has_image": bool(t.source_image_path)}


async def count_templates(db: AsyncSession, owner_type: OwnerType, owner_ids: list[str] | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    q = select(FaceTemplate.owner_id, func.count()).where(FaceTemplate.owner_type == owner_type)
    if owner_ids is None:
        rows = await db.execute(q.group_by(FaceTemplate.owner_id))
        return {k: int(n) for k, n in rows.all()}
    for i in range(0, len(owner_ids), 500):
        rows = await db.execute(q.where(FaceTemplate.owner_id.in_(owner_ids[i:i + 500])).group_by(FaceTemplate.owner_id))
        counts.update({k: int(n) for k, n in rows.all()})
    return counts


async def enroll_images(db: AsyncSession, employee_id: str, images: list[tuple[str, bytes]],
                        min_face_pixels: int) -> dict[str, Any]:
    """Detect + embed each photo, keep the good ones as templates (max 5 per
    person). Only a face crop is kept on disk; the uploaded photo is not."""
    from app.services.embedding import process_enrollment_image

    existing = (await count_templates(db, OwnerType.EMPLOYEE, [employee_id])).get(employee_id, 0)
    results: list[dict[str, Any]] = []
    accepted = 0
    for filename, data in images:
        name = filename or "image"
        if len(data) > MAX_ENROLL_BYTES:
            results.append({"filename": name, "accepted": False, "reason": "file_too_large", "quality_score": 0.0})
            continue
        if existing + accepted >= MAX_TEMPLATES_PER_OWNER:
            results.append({"filename": name, "accepted": False, "reason": "template_limit_reached", "quality_score": 0.0})
            continue
        outcome = process_enrollment_image(data, min_face_pixels)
        if not outcome.accepted or outcome.embedding is None:
            results.append({"filename": name, "accepted": False, "reason": outcome.reason,
                            "quality_score": outcome.quality_score})
            continue
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2] if img is not None else (0, 0)
        box = (w * 0.2, h * 0.1, w * 0.8, h * 0.9) if img is not None else (0, 0, 0, 0)
        crop_path = save_face_crop(img, box, subdir=f"employees/{employee_id}") if img is not None else None
        t = FaceTemplate(owner_type=OwnerType.EMPLOYEE, owner_id=employee_id, embedding=outcome.embedding,
                         embedding_encrypted=encrypt_embedding(outcome.embedding), quality_score=outcome.quality_score,
                         model_version=outcome.model_version, source_image_path=crop_path,
                         is_primary=(existing + accepted == 0))
        db.add(t)
        await db.flush()
        accepted += 1
        results.append({"filename": name, "accepted": True, "reason": None, "quality_score": outcome.quality_score,
                        "template_id": t.id})
    return {"results": results, "accepted_count": accepted, "template_count": existing + accepted}


async def list_templates(db: AsyncSession, owner_type: OwnerType, owner_id: str) -> list[dict[str, Any]]:
    rows = await db.execute(select(FaceTemplate).where(FaceTemplate.owner_type == owner_type,
                                                       FaceTemplate.owner_id == owner_id)
                            .order_by(FaceTemplate.is_primary.desc(), FaceTemplate.created_at))
    return [template_dict(t) for t in rows.scalars().all()]


async def delete_template(db: AsyncSession, owner_type: OwnerType, owner_id: str, template_id: str) -> bool:
    t = (await db.execute(select(FaceTemplate).where(FaceTemplate.id == template_id, FaceTemplate.owner_type == owner_type,
                                                     FaceTemplate.owner_id == owner_id))).scalar_one_or_none()
    if t is None:
        return False
    await db.delete(t)
    await db.flush()
    return True


async def purge_owner(db: AsyncSession, owner_type: OwnerType, owner_id: str) -> int:
    rows = (await db.execute(select(FaceTemplate).where(FaceTemplate.owner_type == owner_type,
                                                        FaceTemplate.owner_id == owner_id))).scalars().all()
    for t in rows:
        await db.delete(t)
    if owner_type == OwnerType.EMPLOYEE:
        from app.services.retention import delete_employee_photos

        delete_employee_photos(owner_id)
    await db.flush()
    return len(rows)


async def adopt_unknown_templates(db: AsyncSession, unknown_id: str, employee_id: str, *, min_quality: float,
                                  capacity: int | None, delete_rest: bool) -> int:
    """Link / promote: the unknown person's good templates become the
    employee's (bad frames would make them match other people's bad frames)."""
    rows = (await db.execute(select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.UNKNOWN,
                                                        FaceTemplate.owner_id == unknown_id))).scalars().all()
    templates = sorted(rows, key=lambda t: t.quality_score, reverse=True)
    good = [t for t in templates if t.quality_score >= min_quality]
    if delete_rest and not good:
        good = templates[:1]
    existing = (await count_templates(db, OwnerType.EMPLOYEE, [employee_id])).get(employee_id, 0)
    room = max(0, (capacity if capacity is not None else MAX_TEMPLATES_PER_OWNER) - existing)
    moved = 0
    for t in templates:
        if t in good and moved < room:
            t.owner_type = OwnerType.EMPLOYEE
            t.owner_id = employee_id
            t.is_primary = existing == 0 and moved == 0
            moved += 1
        elif delete_rest:
            await db.delete(t)
    u = await db.get(UnknownIdentity, unknown_id)
    if u is not None:
        from app.models.enums import UnknownStatus

        u.status = UnknownStatus.RESOLVED
        u.resolved_employee_id = None  # the employee row lives in the cloud
    await db.flush()
    return moved


async def split_unknown_templates(db: AsyncSession, unknown_id: str, template_ids: list[str], new_unknown_id: str) -> int:
    rows = (await db.execute(select(FaceTemplate).where(FaceTemplate.id.in_(template_ids),
                                                        FaceTemplate.owner_type == OwnerType.UNKNOWN,
                                                        FaceTemplate.owner_id == unknown_id))).scalars().all()
    if not rows:
        return 0
    old = await db.get(UnknownIdentity, unknown_id)
    if await db.get(UnknownIdentity, new_unknown_id) is None and old is not None:
        db.add(UnknownIdentity(id=new_unknown_id, face_id=f"S-{new_unknown_id[:8]}", first_seen_at=old.first_seen_at,
                               last_seen_at=old.last_seen_at, sighting_count=len(rows)))
        await db.flush()
    for t in rows:
        t.owner_id = new_unknown_id
    await db.flush()
    return len(rows)


async def delete_unknown(db: AsyncSession, unknown_id: str) -> int:
    n = await purge_owner(db, OwnerType.UNKNOWN, unknown_id)
    u = await db.get(UnknownIdentity, unknown_id)
    if u is not None:
        await db.delete(u)
        await db.flush()
    return n


async def photo_path(db: AsyncSession, ref: str) -> Path | None:
    """Reference ("det:...", "unk:...", "tpl:...", "emp:...") or a stored
    relative path -> file on disk inside MEDIA_ROOT, or None."""
    kind, _, key = ref.partition(":")
    rel: str | None = None
    if kind == "det":
        d = await db.get(EdgeDetection, key)
        rel = d.crop_path if d else None
    elif kind == "unk":
        u = await db.get(UnknownIdentity, key)
        rel = u.best_crop_path if u else None
    elif kind == "tpl":
        t = await db.get(FaceTemplate, key)
        rel = t.source_image_path if t else None
    elif kind == "emp":
        t = (await db.execute(select(FaceTemplate).where(
            FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == key,
            FaceTemplate.source_image_path.is_not(None)).order_by(FaceTemplate.is_primary.desc(),
                                                                  FaceTemplate.created_at.desc()).limit(1))).scalar_one_or_none()
        rel = t.source_image_path if t else None
    else:
        rel = ref
    if not rel or rel.startswith(("det:", "unk:", "tpl:", "emp:")):
        return None
    p = absolute_path(rel)
    return p if p.exists() else None
