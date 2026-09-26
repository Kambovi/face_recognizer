from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum, utcnow
from app.models.enums import EventType, RejectReason, SubjectType
from app.models.types import GUID, new_uuid_str, UTCDateTime


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    # Nullable ONLY for liveness_failed/too_small rejects, which happen
    # before the pipeline ever attempts to identify the face (see the CHECK
    # constraint below and docs/DECISIONS.md).
    subject_type: Mapped[SubjectType | None] = mapped_column(
        str_enum(SubjectType, "subject_type"), nullable=True
    )
    employee_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unknown_identity_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("unknown_identities.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )
    similarity: Mapped[float | None] = mapped_column(sa.Float(), nullable=True)
    liveness_score: Mapped[float | None] = mapped_column(sa.Float(), nullable=True)
    kiosk_id: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    crop_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    reject_reason: Mapped[RejectReason | None] = mapped_column(
        str_enum(RejectReason, "reject_reason"), nullable=True
    )
    is_manual_override: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    overridden_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    original_employee_id: Mapped[str | None] = mapped_column(GUID, nullable=True)
    original_unknown_identity_id: Mapped[str | None] = mapped_column(GUID, nullable=True)

    # Idempotency key for offline-queue replay (NON-NEGOTIABLE #5). Not named
    # in the spec's literal column list; documented in docs/DECISIONS.md as
    # the mechanism satisfying "Use a client-generated UUID per event as the
    # idempotency key."
    client_event_id: Mapped[str | None] = mapped_column(GUID, unique=True, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )

    __table_args__ = (
        # "Exactly one of employee_id / unknown_identity_id is set" (spec),
        # EXCEPT for liveness_failed / too_small rejects: those happen before
        # the pipeline ever attempts to identify who the face belongs to
        # (step 7's clustering never runs for them), so neither FK can be
        # populated. See docs/DECISIONS.md.
        sa.CheckConstraint(
            "(employee_id IS NOT NULL AND unknown_identity_id IS NULL) OR "
            "(employee_id IS NULL AND unknown_identity_id IS NOT NULL) OR "
            "(employee_id IS NULL AND unknown_identity_id IS NULL "
            " AND reject_reason IN ('liveness_failed', 'too_small'))",
            name="ck_attendance_events_exactly_one_subject",
        ),
        sa.Index("ix_attendance_events_employee_occurred", "employee_id", "occurred_at"),
        sa.Index("ix_attendance_events_unknown_occurred", "unknown_identity_id", "occurred_at"),
    )
