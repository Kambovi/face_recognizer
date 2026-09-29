"""Unknown-identity clustering, link, promote, and split.

Clustering (step 7 of the recognition pipeline): a face that doesn't match
any enrolled employee above `similarity_threshold` is matched against
existing UNKNOWN-owned templates using the SAME 1:N search
(app/services/matching.py) with `unknown_cluster_threshold` (default 0.40),
plus a same-camera temporal prior: a stranger seen at the same kiosk within
`unknown_recent_window_seconds` is accepted at `unknown_recent_threshold`.
The old default (0.55, stricter than the 0.38 employee threshold) split one
real person into dozens of UNK- ids on a live deployment (2026-09-25).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, OwnerType, SubjectType, UnknownStatus
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.security import encrypt_embedding
from app.services import matching
from app.services.attendance import local_date
from app.services.ids import next_unknown_face_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ClusterResult:
    unknown: UnknownIdentity
    created: bool
    similarity: float | None


# A new sighting this similar to a template the identity already has adds no
# new "angle" -- skip storing it so the template slots hold varied views.
NEAR_DUPLICATE_TEMPLATE_SIMILARITY = 0.90


def _cos(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) or 1e-9
    return float(np.dot(va, vb) / denom)


async def _templates_of(db: AsyncSession, unknown_ids: list[str]) -> dict[str, list[FaceTemplate]]:
    if not unknown_ids:
        return {}
    rows = await db.execute(
        select(FaceTemplate).where(FaceTemplate.owner_type == OwnerType.UNKNOWN, FaceTemplate.owner_id.in_(unknown_ids))
    )
    out: dict[str, list[FaceTemplate]] = {}
    for t in rows.scalars().all():
        out.setdefault(t.owner_id, []).append(t)
    return out


async def _recent_same_camera_match(
    db: AsyncSession,
    embedding: list[float],
    kiosk_id: str | None,
    occurred_at: datetime,
    window_seconds: float,
    threshold: float,
) -> tuple[str, float] | None:
    """Temporal prior: an unknown seen at the SAME camera in the last
    `window_seconds` is very likely the same person still standing there, so
    it's accepted at a lower similarity than a cold match. Returns
    (unknown_id, similarity) or None."""
    if not kiosk_id or window_seconds <= 0:
        return None
    since = occurred_at - timedelta(seconds=window_seconds)
    rows = await db.execute(
        select(AttendanceEvent.unknown_identity_id)
        .where(
            AttendanceEvent.kiosk_id == kiosk_id,
            AttendanceEvent.unknown_identity_id.is_not(None),
            AttendanceEvent.occurred_at >= since,
            AttendanceEvent.occurred_at <= occurred_at,
        )
        .distinct()
    )
    recent_ids = [r for (r,) in rows.all() if r]
    best: tuple[str, float] | None = None
    for uid, templates in (await _templates_of(db, recent_ids)).items():
        sim = max((_cos(embedding, t.embedding) for t in templates), default=-1.0)
        if sim >= threshold and (best is None or sim > best[1]):
            best = (uid, sim)
    return best


async def cluster_or_create_unknown(
    db: AsyncSession,
    embedding: list[float],
    quality_score: float,
    crop_path: str | None,
    model_version: str,
    unknown_cluster_threshold: float,
    unknown_max_templates: int,
    occurred_at: datetime,
    kiosk_id: str | None = None,
    recent_window_seconds: float = 0.0,
    recent_threshold: float = 1.0,
) -> ClusterResult:
    matches = await matching.search_templates(db, OwnerType.UNKNOWN, embedding, limit=5)
    best = matches[0] if matches else None

    target_id: str | None = None
    target_sim: float | None = None
    if best is not None and best.similarity >= unknown_cluster_threshold:
        target_id, target_sim = best.owner_id, best.similarity
    else:
        recent = await _recent_same_camera_match(
            db, embedding, kiosk_id, occurred_at, recent_window_seconds, recent_threshold
        )
        if recent is not None:
            target_id, target_sim = recent

    if target_id is not None:
        result = await db.execute(select(UnknownIdentity).where(UnknownIdentity.id == target_id))
        unknown = result.scalar_one()

        existing_templates = (await _templates_of(db, [unknown.id])).get(unknown.id, [])
        best_existing_quality = max((t.quality_score for t in existing_templates), default=-1.0)

        unknown.sighting_count += 1
        unknown.last_seen_at = occurred_at
        if crop_path and quality_score > best_existing_quality:
            unknown.best_crop_path = crop_path

        is_new_angle = all(_cos(embedding, t.embedding) < NEAR_DUPLICATE_TEMPLATE_SIMILARITY for t in existing_templates)
        if len(existing_templates) < unknown_max_templates and is_new_angle:
            db.add(
                FaceTemplate(
                    owner_type=OwnerType.UNKNOWN,
                    owner_id=unknown.id,
                    embedding=embedding,
                    embedding_encrypted=encrypt_embedding(embedding),
                    quality_score=quality_score,
                    model_version=model_version,
                    source_image_path=None,
                    is_primary=False,
                )
            )
        await db.flush()
        return ClusterResult(unknown=unknown, created=False, similarity=target_sim)

    face_id = await next_unknown_face_id(db)
    unknown = UnknownIdentity(
        face_id=face_id,
        first_seen_at=occurred_at,
        last_seen_at=occurred_at,
        sighting_count=1,
        best_crop_path=crop_path,
        status=UnknownStatus.OPEN,
    )
    db.add(unknown)
    await db.flush()
    db.add(
        FaceTemplate(
            owner_type=OwnerType.UNKNOWN,
            owner_id=unknown.id,
            embedding=embedding,
            embedding_encrypted=encrypt_embedding(embedding),
            quality_score=quality_score,
            model_version=model_version,
            source_image_path=None,
            is_primary=True,
        )
    )
    await db.flush()
    return ClusterResult(unknown=unknown, created=True, similarity=best.similarity if best else None)


def _merge_and_collapse_day(
    events: list[AttendanceEvent],
    new_subject_type: SubjectType,
    employee_id: str | None,
    unknown_identity_id: str | None,
) -> list[AttendanceEvent]:
    """Collapses every event for one subject on one local day down to at most
    one IN (earliest) and one OUT (latest) row, re-pointed at the new owner,
    and returns the rows that should be deleted (the orphans)."""
    if not events:
        return []
    ordered = sorted(events, key=lambda e: e.occurred_at)

    def _repoint(e: AttendanceEvent) -> None:
        if e.employee_id != employee_id:
            e.original_employee_id = e.original_employee_id or e.employee_id
        if e.unknown_identity_id != unknown_identity_id:
            e.original_unknown_identity_id = e.original_unknown_identity_id or e.unknown_identity_id
        e.subject_type = new_subject_type
        e.employee_id = employee_id
        e.unknown_identity_id = unknown_identity_id

    keep_in = ordered[0]
    _repoint(keep_in)
    keep_in.event_type = EventType.IN

    if len(ordered) == 1:
        return []

    keep_out = ordered[-1]
    _repoint(keep_out)
    keep_out.event_type = EventType.OUT

    return ordered[1:-1]


async def link_unknown_to_employee(
    db: AsyncSession,
    unknown: UnknownIdentity,
    employee: Employee,
    reason: str,
    adopt_templates: bool,
    actor: str,
) -> None:
    unknown_events_result = await db.execute(
        select(AttendanceEvent).where(AttendanceEvent.unknown_identity_id == unknown.id)
    )
    unknown_events = list(unknown_events_result.scalars().all())

    employee_events_result = await db.execute(
        select(AttendanceEvent).where(AttendanceEvent.employee_id == employee.id)
    )
    employee_events = list(employee_events_result.scalars().all())

    affected_days = {local_date(e.occurred_at) for e in unknown_events}
    orphans: list[AttendanceEvent] = []
    for day in affected_days:
        day_events = [e for e in unknown_events if local_date(e.occurred_at) == day] + [
            e for e in employee_events if local_date(e.occurred_at) == day
        ]
        orphans.extend(_merge_and_collapse_day(day_events, SubjectType.EMPLOYEE, employee.id, None))

    for orphan in orphans:
        await db.delete(orphan)
    from app.services.sightings import repoint

    await repoint(db, new_type=SubjectType.EMPLOYEE, employee_id=employee.id, unknown_identity_id=None,
                  from_unknown_id=unknown.id)

    if adopt_templates:
        templates_result = await db.execute(
            select(FaceTemplate).where(
                FaceTemplate.owner_type == OwnerType.UNKNOWN, FaceTemplate.owner_id == unknown.id
            )
        )
        unknown_templates = sorted(templates_result.scalars().all(), key=lambda t: t.quality_score, reverse=True)

        count_result = await db.execute(
            select(func.count()).select_from(FaceTemplate).where(
                FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee.id
            )
        )
        existing_count = count_result.scalar_one()
        capacity = max(0, 5 - existing_count)
        for template in unknown_templates[:capacity]:
            template.owner_type = OwnerType.EMPLOYEE
            template.owner_id = employee.id
            template.is_primary = False

    unknown.status = UnknownStatus.RESOLVED
    unknown.resolved_employee_id = employee.id
    unknown.resolved_by = actor
    unknown.resolved_at = utcnow()
    await db.flush()


async def promote_unknown_to_employee(
    db: AsyncSession,
    unknown: UnknownIdentity,
    name: str,
    emp_code: str,
    department: str | None,
    designation: str | None,
    shift_id: str | None,
    actor: str,
    home_kiosk_id: str | None = None,
    contractor: str | None = None,
) -> Employee:
    from app.services.ids import next_employee_face_id

    face_id = await next_employee_face_id(db)
    employee = Employee(
        face_id=face_id,
        emp_code=emp_code,
        name=name,
        department=department,
        designation=designation,
        shift_id=shift_id,
        home_kiosk_id=home_kiosk_id or None,
        contractor=(contractor or "").strip() or None,
        is_active=True,
    )
    db.add(employee)
    await db.flush()

    templates_result = await db.execute(
        select(FaceTemplate).where(
            FaceTemplate.owner_type == OwnerType.UNKNOWN, FaceTemplate.owner_id == unknown.id
        )
    )
    for template in templates_result.scalars().all():
        template.owner_type = OwnerType.EMPLOYEE
        template.owner_id = employee.id

    events_result = await db.execute(
        select(AttendanceEvent).where(AttendanceEvent.unknown_identity_id == unknown.id)
    )
    for event in events_result.scalars().all():
        event.original_unknown_identity_id = event.original_unknown_identity_id or unknown.id
        event.subject_type = SubjectType.EMPLOYEE
        event.employee_id = employee.id
        event.unknown_identity_id = None
    from app.services.sightings import repoint

    await repoint(db, new_type=SubjectType.EMPLOYEE, employee_id=employee.id, unknown_identity_id=None,
                  from_unknown_id=unknown.id)

    unknown.status = UnknownStatus.RESOLVED
    unknown.resolved_employee_id = employee.id
    unknown.resolved_by = actor
    unknown.resolved_at = utcnow()
    await db.flush()
    return employee


async def split_unknown(
    db: AsyncSession, unknown: UnknownIdentity, template_ids: list[str], reason: str, actor: str
) -> UnknownIdentity:
    """Moves the listed templates into a brand-new UNK-nnnn identity.

    Historical attendance_events stay attributed to the original identity:
    an event only stores a similarity SCORE, not the raw query embedding or
    which specific template matched, so there is no reliable way to
    re-attribute a past sighting to one of several split-off templates
    without re-running detection+embedding against its stored crop. An
    admin who also needs specific historical events moved can follow up with
    PATCH /attendance/events/{id}/reassign. See docs/DECISIONS.md.
    """
    templates_result = await db.execute(
        select(FaceTemplate).where(
            FaceTemplate.id.in_(template_ids),
            FaceTemplate.owner_type == OwnerType.UNKNOWN,
            FaceTemplate.owner_id == unknown.id,
        )
    )
    templates = list(templates_result.scalars().all())
    if not templates:
        raise ValueError("no_matching_templates")

    face_id = await next_unknown_face_id(db)
    new_unknown = UnknownIdentity(
        face_id=face_id,
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        sighting_count=len(templates),
        status=UnknownStatus.OPEN,
        notes=f"Split from {unknown.face_id}: {reason}",
    )
    db.add(new_unknown)
    await db.flush()

    best_crop = None
    best_quality = -1.0
    for template in templates:
        template.owner_id = new_unknown.id
        if template.quality_score > best_quality:
            best_quality = template.quality_score
            best_crop = template.source_image_path

    new_unknown.best_crop_path = best_crop or unknown.best_crop_path
    await db.flush()
    return new_unknown
