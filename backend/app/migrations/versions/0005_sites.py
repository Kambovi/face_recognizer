"""sites (multi-site / head-office dashboard)

Revision ID: 0005_sites
Revises: 0004_watchlist_alerts
Create Date: 2026-09-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0005_sites"
down_revision: Union[str, None] = "0004_watchlist_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_push_at", UTCDateTime(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sites")
