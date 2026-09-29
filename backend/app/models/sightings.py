"""Every recognised detection, one row each -- the raw log behind the
merged IN / OUT rows in attendance_events.

attendance_events keeps at most one IN and one OUT per person per
attendance day (what payroll needs). This table keeps each time the person
was actually seen, on which camera, so "how many times was X seen at the
entry camera on 28 Sep" can be answered. Kept forever (client choice,
2026-09-29); reset_data.py clears it with the attendance.

The kiosk already suppresses repeat sends of the same face within
`dedupe_window_minutes`, so one row ~ one pass in front of the camera.
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum, utcnow
from app.models.enums import SubjectType
from app.models.types import GUID, UTCDateTime, new_uuid_str


class Sighting(Base):
    __tablename__ = "sightings"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    kiosk_id: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    subject_type: Mapped[SubjectType] = mapped_column(str_enum(SubjectType, "sighting_subject_type"), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True
    )
    unknown_identity_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("unknown_identities.id", ondelete="CASCADE"), nullable=True
    )
    # the IN / OUT row this detection went into (NULL once that row is gone)
    event_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("attendance_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    similarity: Mapped[float | None] = mapped_column(sa.Float(), nullable=True)
    liveness_score: Mapped[float | None] = mapped_column(sa.Float(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    __table_args__ = (
        sa.Index("ix_sightings_employee_occurred", "employee_id", "occurred_at"),
        sa.Index("ix_sightings_unknown_occurred", "unknown_identity_id", "occurred_at"),
        sa.Index("ix_sightings_kiosk_occurred", "kiosk_id", "occurred_at"),
    )
