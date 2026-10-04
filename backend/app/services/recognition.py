"""Steps 7-10 of the recognition pipeline, split in two so the SaaS edge box
can do the biometric half and the cloud the bookkeeping half:

  match_locally()  face -> employee / unknown / unclear / reject, using the
                   face templates in THIS database (standalone or edge box).
                   Saves the photo and learns unknown templates.
  record_result()  the match -> attendance event, sighting, alerts, unknown
                   person row (standalone, or the cloud tenant database).

process_kiosk_event() = both, on one database (standalone install). On an
edge box, match_locally() runs on the box and the MatchResult (no face data,
no photo) is sent to the cloud, which runs record_result() there.

NON-NEGOTIABLE #3: when liveness failed (embedding None) matching is never
called -- match_locally returns a reject before any template search.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import OwnerType, RejectReason, SubjectType, UnknownStatus
from app.models.sightings import Sighting
from app.models.unknown_identities import UnknownIdentity
from app.schemas.kiosk import KioskEventRequest
from app.services import alerts, matching
from app.services.attendance import RecognitionEventInput, local_date, upsert_attendance_event
from app.services.media import save_base64_jpeg
from app.services.muster import camera_roles
from app.services.shiftday import DEFAULT_NIGHT_TAIL_HOURS, load_resolver
from app.services.unknown_identity import cluster_or_create_unknown

MODEL_VERSION = "buffalo_l"
logger = structlog.get_logger(__name__)

Outcome = Literal["employee", "unknown", "unclear", "reject"]


@dataclass
class RecognitionOutcome:
    event: AttendanceEvent | None  # None = unclear face, logged as a sighting only
    created: bool
    face_id: str | None


@dataclass
class MatchResult:
    """What a camera saw, after matching -- safe to send to the cloud: ids,
    scores and photo REFERENCES only, never a face template or a photo."""

    client_event_id: str
    kiosk_id: str
    occurred_at: datetime
    outcome: Outcome
    similarity: float | None = None
    liveness_score: float | None = None
    quality_score: float | None = None
    reject_reason: str | None = None
    employee_id: str | None = None
    unknown_id: str | None = None
    unknown_created: bool = False
    crop_ref: str | None = None          # photo of this detection
    unknown_crop_ref: str | None = None  # new best photo of the unknown person, if it changed

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["occurred_at"] = self.occurred_at.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "MatchResult":
        ts = datetime.fromisoformat(str(d["occurred_at"]))
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "occurred_at"}
        return cls(occurred_at=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc), **fields)


def _occurred(payload: KioskEventRequest) -> datetime:
    ts = payload.occurred_at
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


async def match_locally(
    db: AsyncSession, payload: KioskEventRequest, config: dict[str, Any], *, edge: bool = False,
) -> tuple[MatchResult, str | None]:
    """Returns (result, local photo path). With edge=True the result carries
    photo references ("det:<event id>", "unk:<unknown id>") instead of paths."""
    occurred_at = _occurred(payload)
    crop_path: str | None = None
    if payload.crop_jpeg_base64:
        # one folder per local day, camera inside it: retention = delete old day folders
        crop_path = save_base64_jpeg(payload.crop_jpeg_base64, subdir=f"events/{local_date(occurred_at)}/{payload.kiosk_id}")
    crop_ref = (f"det:{payload.client_event_id}" if edge else crop_path) if crop_path else None
    base: dict[str, Any] = dict(client_event_id=payload.client_event_id, kiosk_id=payload.kiosk_id,
                                occurred_at=occurred_at, liveness_score=payload.liveness_score,
                                quality_score=payload.quality_score, crop_ref=crop_ref)

    # Pre-identification reject: liveness failed or the face was too small.
    # The embedding is None BY CONTRACT here: no recognition call at all.
    if payload.embedding is None:
        return MatchResult(outcome="reject", reject_reason=payload.reject_reason, **base), crop_path

    matches = await matching.search_templates(db, OwnerType.EMPLOYEE, payload.embedding, limit=5)
    best = matches[0] if matches else None
    if best is not None and best.similarity >= float(config.get("similarity_threshold", 0.38)):
        return MatchResult(outcome="employee", employee_id=best.owner_id, similarity=best.similarity, **base), crop_path

    # UNKNOWN PATH -- never guess an employee. Only a CLEAR face that looks
    # like nobody on the roll becomes an unknown person; a poor frame, or one
    # close to an employee but below the threshold (2026-09-29: an employee
    # leaving with a hand over the face became "UNK-0051"), is only logged as
    # an unclear sighting: no attendance, no unknown identity, no template.
    quality = payload.quality_score if payload.quality_score is not None else 1.0
    near = best.similarity if best is not None else 0.0
    if (quality < float(config.get("unknown_min_quality", 0.6))
            or near >= float(config.get("unknown_near_match_similarity", 0.30))):
        logger.info("unclear_face_not_recorded", kiosk_id=payload.kiosk_id, quality=round(quality, 2),
                    best_similarity=round(near, 3))
        return MatchResult(outcome="unclear", similarity=near, **base), crop_path

    cluster = await cluster_or_create_unknown(
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
    best_changed = crop_path is not None and cluster.unknown.best_crop_path == crop_path
    unknown_crop_ref = (f"unk:{cluster.unknown.id}" if edge else crop_path) if best_changed else None
    return MatchResult(
        outcome="unknown", unknown_id=cluster.unknown.id, unknown_created=cluster.created,
        similarity=best.similarity if best else cluster.similarity, unknown_crop_ref=unknown_crop_ref, **base,
    ), crop_path


async def _mirror_unknown(db: AsyncSession, r: MatchResult) -> UnknownIdentity:
    """Cloud side: the unknown person lives on the edge box; keep a row here
    (no templates, no photo) so the dashboard can list, label and resolve it."""
    from app.services.ids import next_unknown_face_id

    u = await db.get(UnknownIdentity, r.unknown_id)
    if u is None:
        u = UnknownIdentity(id=r.unknown_id, face_id=await next_unknown_face_id(db), first_seen_at=r.occurred_at,
                            last_seen_at=r.occurred_at, sighting_count=0, status=UnknownStatus.OPEN)
        db.add(u)
        await db.flush()
    u.sighting_count = (u.sighting_count or 0) + 1
    if r.occurred_at >= u.last_seen_at:
        u.last_seen_at = r.occurred_at
        u.last_kiosk_id = r.kiosk_id
    if r.occurred_at < u.first_seen_at:
        u.first_seen_at = r.occurred_at
    if r.unknown_crop_ref:
        u.best_crop_path = r.unknown_crop_ref
    return u


async def record_result(
    db: AsyncSession, r: MatchResult, config: dict[str, Any], *, mirror_unknowns: bool = False,
) -> RecognitionOutcome:
    """Bookkeeping for one match. With mirror_unknowns (cloud ingesting an
    edge box's results) a result sent twice is recorded once."""
    if mirror_unknowns:
        dup = (await db.execute(select(AttendanceEvent.id).where(AttendanceEvent.client_event_id == r.client_event_id))).first()
        if dup is not None:
            return RecognitionOutcome(event=await db.get(AttendanceEvent, dup[0]), created=False, face_id=None)

    dedupe_window = float(config.get("dedupe_window_minutes", 5))
    rules: dict[str, Any] = {
        "camera_role": (await camera_roles(db)).get(r.kiosk_id, "both"),
        "min_out_gap_minutes": float(config.get("min_out_gap_minutes", 120)),
    }

    if r.outcome == "reject":
        data = RecognitionEventInput(
            subject_type=None, employee_id=None, unknown_identity_id=None, occurred_at=r.occurred_at,
            similarity=None, liveness_score=r.liveness_score, kiosk_id=r.kiosk_id, crop_path=r.crop_ref,
            reject_reason=RejectReason(r.reject_reason) if r.reject_reason else None,
            client_event_id=r.client_event_id,
        )
        event, created = await upsert_attendance_event(db, data, dedupe_window)
        if created:
            await alerts.on_event(db, event, config)
        await db.commit()
        return RecognitionOutcome(event=event, created=created, face_id=None)

    if r.outcome == "unclear":
        db.add(Sighting(occurred_at=r.occurred_at, kiosk_id=r.kiosk_id, subject_type=SubjectType.UNKNOWN,
                        employee_id=None, unknown_identity_id=None, event_id=None,
                        similarity=r.similarity, liveness_score=r.liveness_score))
        await db.commit()
        return RecognitionOutcome(event=None, created=False, face_id=None)

    if r.outcome == "employee":
        employee = await db.get(Employee, r.employee_id) if r.employee_id else None
        if employee is None:  # removed on the cloud before the edge box heard about it
            logger.warning("match_for_missing_employee", employee_id=r.employee_id)
            return await record_result(db, replace(r, outcome="unclear"), config)
        data = RecognitionEventInput(
            subject_type=SubjectType.EMPLOYEE, employee_id=employee.id, unknown_identity_id=None,
            occurred_at=r.occurred_at, similarity=r.similarity, liveness_score=r.liveness_score,
            kiosk_id=r.kiosk_id, crop_path=r.crop_ref, reject_reason=None, client_event_id=r.client_event_id,
        )
        resolver = await load_resolver(db, [employee.id], float(config.get("night_shift_tail_hours", DEFAULT_NIGHT_TAIL_HOURS)))
        event, created = await upsert_attendance_event(
            db, data, dedupe_window, day_of=lambda ts: resolver.attendance_date(employee.id, ts), **rules
        )
        await alerts.on_event(db, event, config, employee=employee, seen_at=r.occurred_at, seen_kiosk=r.kiosk_id)
        await db.commit()
        return RecognitionOutcome(event=event, created=created, face_id=employee.face_id)

    # unknown person
    unknown = await _mirror_unknown(db, r) if mirror_unknowns else await db.get(UnknownIdentity, r.unknown_id)
    if unknown is None:
        return await record_result(db, replace(r, outcome="unclear"), config)
    data = RecognitionEventInput(
        subject_type=SubjectType.UNKNOWN, employee_id=None, unknown_identity_id=unknown.id,
        occurred_at=r.occurred_at, similarity=r.similarity, liveness_score=r.liveness_score,
        kiosk_id=r.kiosk_id, crop_path=r.crop_ref, reject_reason=RejectReason.BELOW_THRESHOLD,
        client_event_id=r.client_event_id,
    )
    event, created = await upsert_attendance_event(db, data, dedupe_window, **rules)
    await alerts.on_event(db, event, config, unknown=unknown, seen_at=r.occurred_at, seen_kiosk=r.kiosk_id)
    await db.commit()
    return RecognitionOutcome(event=event, created=created, face_id=unknown.face_id)


async def process_kiosk_event(db: AsyncSession, payload: KioskEventRequest, config: dict[str, Any]) -> RecognitionOutcome:
    """Standalone install: match and record on the same database."""
    result, _ = await match_locally(db, payload, config)
    return await record_result(db, result, config)
