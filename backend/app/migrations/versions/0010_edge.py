"""SaaS edge support: unknown last camera, cloud face count, edge outbox +
detection photo index

Revision ID: 0010_edge
Revises: 0009_payroll
Create Date: 2026-10-04

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import UTCDateTime

revision: str = "0010_edge"
down_revision: Union[str, None] = "0009_payroll"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("unknown_identities") as b:
        b.add_column(sa.Column("last_kiosk_id", sa.String(64), nullable=True))
    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("face_count", sa.Integer(), nullable=False, server_default="0"))
    # where each open unknown was last seen (for the "same camera, a moment ago" prior)
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE unknown_identities SET last_kiosk_id = ("
        " SELECT e.kiosk_id FROM attendance_events e WHERE e.unknown_identity_id = unknown_identities.id"
        " ORDER BY e.occurred_at DESC LIMIT 1)"
    ))
    op.create_table(
        "edge_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(300), nullable=True),
    )
    op.create_table(
        "edge_detections",
        sa.Column("client_event_id", sa.String(64), primary_key=True),
        sa.Column("kiosk_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column("crop_path", sa.String(500), nullable=True),
    )
    op.create_index("ix_edge_detections_occurred_at", "edge_detections", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_edge_detections_occurred_at", table_name="edge_detections")
    op.drop_table("edge_detections")
    op.drop_table("edge_outbox")
    with op.batch_alter_table("employees") as b:
        b.drop_column("face_count")
    with op.batch_alter_table("unknown_identities") as b:
        b.drop_column("last_kiosk_id")
