"""watchlist reasons on employees / unknown faces + alerts table

Revision ID: 0004_watchlist_alerts
Revises: 0003_contractor_roster
Create Date: 2026-09-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0004_watchlist_alerts"
down_revision: Union[str, None] = "0003_contractor_roster"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("watchlist_reason", sa.Text(), nullable=True))
    with op.batch_alter_table("unknown_identities") as batch:
        batch.add_column(sa.Column("watchlist_reason", sa.Text(), nullable=True))
    op.create_table(
        "alerts",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("kiosk_id", sa.String(100), nullable=False),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("unknown_identity_id", GUID, sa.ForeignKey("unknown_identities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", GUID, sa.ForeignKey("attendance_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", UTCDateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])
    op.create_index("ix_alerts_acknowledged_at", "alerts", ["acknowledged_at"])


def downgrade() -> None:
    op.drop_index("ix_alerts_acknowledged_at", table_name="alerts")
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_table("alerts")
    with op.batch_alter_table("unknown_identities") as batch:
        batch.drop_column("watchlist_reason")
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("watchlist_reason")
