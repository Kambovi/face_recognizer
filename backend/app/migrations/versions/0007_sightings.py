"""sightings: every recognised detection (raw log behind IN / OUT)

Backfills one sighting per existing identified attendance event, so older
days show at least the IN / OUT detections.

Revision ID: 0007_sightings
Revises: 0006_salary_leaves
Create Date: 2026-09-29

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.base import str_enum
from app.models.enums import SubjectType
from app.models.types import GUID, UTCDateTime

revision: str = "0007_sightings"
down_revision: Union[str, None] = "0006_salary_leaves"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sightings",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("kiosk_id", sa.String(100), nullable=False),
        sa.Column("subject_type", str_enum(SubjectType, "sighting_subject_type"), nullable=False),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True),
        sa.Column("unknown_identity_id", GUID, sa.ForeignKey("unknown_identities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_id", GUID, sa.ForeignKey("attendance_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("liveness_score", sa.Float(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_sightings_occurred_at", "sightings", ["occurred_at"])
    op.create_index("ix_sightings_event_id", "sightings", ["event_id"])
    op.create_index("ix_sightings_employee_occurred", "sightings", ["employee_id", "occurred_at"])
    op.create_index("ix_sightings_unknown_occurred", "sightings", ["unknown_identity_id", "occurred_at"])
    op.create_index("ix_sightings_kiosk_occurred", "sightings", ["kiosk_id", "occurred_at"])
    # one sighting per existing identified camera event (ids reused: unique already)
    op.execute(
        "INSERT INTO sightings (id, occurred_at, kiosk_id, subject_type, employee_id, unknown_identity_id, "
        "event_id, similarity, liveness_score, created_at) "
        "SELECT id, occurred_at, kiosk_id, subject_type, employee_id, unknown_identity_id, id, similarity, "
        "liveness_score, created_at FROM attendance_events "
        "WHERE subject_type IS NOT NULL AND kiosk_id <> 'manual' AND is_manual_override = false"
    )


def downgrade() -> None:
    for ix in ("ix_sightings_kiosk_occurred", "ix_sightings_unknown_occurred", "ix_sightings_employee_occurred",
               "ix_sightings_event_id", "ix_sightings_occurred_at"):
        op.drop_index(ix, table_name="sightings")
    op.drop_table("sightings")
