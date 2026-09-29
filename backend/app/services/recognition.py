"""Orchestrates step 7-10 of the recognition pipeline server-side, inside
POST /api/v1/kiosk/event. This is the ONE function that decides employee vs
unknown vs reject, and is exactly what NON-NEGOTIABLE #3's test mocks a
failing liveness result against to assert zero calls into
`matching.search_templates` (i.e. zero "recognition calls")."""
from __future__ import annotations

from typing import Any

from dataclasses import dataclass
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import OwnerType, RejectReason, SubjectType
from app.schemas.kiosk import KioskEventRequest
from app.services import matching
from app.services import alerts
from app.services.shiftday import DEFAULT_NIGHT_TAIL_HOURS, load_resolver
from app.services.muster import camera_roles
from app.services.attendance import RecognitionEventInput, local_date, upsert_attendance_event
from app.services.media import save_base64_jpeg
from app.services.unknown_identity import cluster_or_create_unknown

MODEL_VERSION = "buffalo_l"


@dataclass
class RecognitionOutcome:
    event: AttendanceEvent
    created: bool
    face_id: str | None


async def process_kiosk_event(
    db: AsyncSession, payload: KioskEventRequest, config: dict
) -> RecognitionOutcome:
    occurred_at = payload.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    crop_path: str | None = None
    if payload.crop_jpeg_base64:
        # One folder per local calendar day (docs/DECISIONS.md's "daily
        # attendance" framing), kiosk_id nested inside it: this makes the
        # disclosed-but-unautomated `crop_retention_days` purge
        # (docs/DPDP_COMPLIANCE.md) a trivial "delete date folders older
        # than N days" instead of a per-row DB scan, and lets an operator
        # browse/back up a single day's crops directly. No new DB column --
        # `occurred_at` (already indexed) remains the source of truth for
        # date-range queries; this only changes where the JPEG lands on disk.
        day = local_date(occurred_at)
        crop_path = save_base64_jpeg(payload.crop_jpeg_base64, subdir=f"events/{day}/{payload.kiosk_id}")

    dedupe_window = float(config.get("dedupe_window_minutes", 5))
    rules: dict[str, Any] = {
        "camera_role": (await camera_roles(db)).get(payload.kiosk_id, "both"),
        "min_out_gap_minutes": float(config.get("min_out_gap_minutes", 120)),
    }

    # Pre-identification reject: liveness failed, or the face was too small.
    # `payload.embedding` is None here BY CONTRACT -- the kiosk never runs
    # the recognition model when liveness fails (NON-NEGOTIABLE #3), and
    # never bothers embedding a too-small crop either.
    if payload.embedding is None:
        data = RecognitionEventInput(
            subject_type=None,
            employee_id=None,
            unknown_identity_id=None,
            occurred_at=occurred_at,
            similarity=None,
            liveness_score=payload.liveness_score,
            kiosk_id=payload.kiosk_id,
            crop_path=crop_path,
            reject_reason=RejectReason(payload.reject_reason) if payload.reject_reason else None,
            client_event_id=payload.client_event_id,
        )
        event, created = await upsert_attendance_event(db, data, dedupe_window)
        if created:
            await alerts.on_event(db, event, config)
        await db.commit()
        return RecognitionOutcome(event=event, created=created, face_id=None)

    similarity_threshold = float(config.get("similarity_threshold", 0.38))
    matches = await matching.search_templates(db, OwnerType.EMPLOYEE, payload.embedding, limit=5)
    best = matches[0] if matches else None

    if best is not None and best.similarity >= similarity_threshold:
        employee = (await db.execute(select(Employee).where(Employee.id == best.owner_id))).scalar_one()
        data = RecognitionEventInput(
            subject_type=SubjectType.EMPLOYEE,
            employee_id=employee.id,
            unknown_identity_id=None,
            occurred_at=occurred_at,
            similarity=best.similarity,
            liveness_score=payload.liveness_score,
            kiosk_id=payload.kiosk_id,
            crop_path=crop_path,
            reject_reason=None,
            client_event_id=payload.client_event_id,
        )
        resolver = await load_resolver(
            db, [employee.id], float(config.get("night_shift_tail_hours", DEFAULT_NIGHT_TAIL_HOURS))
        )
        event, created = await upsert_attendance_event(
            db, data, dedupe_window, day_of=lambda ts: resolver.attendance_date(employee.id, ts), **rules
        )
        await alerts.on_event(db, event, config, employee=employee, seen_at=occurred_at, seen_kiosk=payload.kiosk_id)
        await db.commit()
        return RecognitionOutcome(event=event, created=created, face_id=employee.face_id)

    # UNKNOWN PATH -- never guess an employee.
    cluster_result = await cluster_or_create_unknown(
        db,
        embedding=payload.embedding,
        quality_score=payload.quality_score or 0.5,
        crop_path=crop_path,
        model_version=MODEL_VERSION,
        unknown_cluster_threshold=float(config.get("unknown_cluster_threshold", 0.40)),
        unknown_max_templates=int(config.get("unknown_max_templates", 15)),
        occurred_at=occurred_at,
        kiosk_id=payload.kiosk_id,
        recent_window_seconds=float(config.get("unknown_recent_window_seconds", 120)),
        recent_threshold=float(config.get("unknown_recent_threshold", 0.30)),
        min_template_quality=float(config.get("quality_min_score", 0.5)),
    )
    data = RecognitionEventInput(
        subject_type=SubjectType.UNKNOWN,
        employee_id=None,
        unknown_identity_id=cluster_result.unknown.id,
        occurred_at=occurred_at,
        similarity=best.similarity if best else cluster_result.similarity,
        liveness_score=payload.liveness_score,
        kiosk_id=payload.kiosk_id,
        crop_path=crop_path,
        reject_reason=RejectReason.BELOW_THRESHOLD,
        client_event_id=payload.client_event_id,
    )
    event, created = await upsert_attendance_event(db, data, dedupe_window, **rules)
    await alerts.on_event(db, event, config, unknown=cluster_result.unknown, seen_at=occurred_at,
                          seen_kiosk=payload.kiosk_id)
    await db.commit()
    return RecognitionOutcome(event=event, created=created, face_id=cluster_result.unknown.face_id)
