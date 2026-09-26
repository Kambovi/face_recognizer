"""employees.home_kiosk_id (home camera / entry point)

Revision ID: 0002_home_kiosk
Revises: 0001_initial
Create Date: 2026-09-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_home_kiosk"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("home_kiosk_id", sa.String(length=100), nullable=True))
        batch.create_index("ix_employees_home_kiosk_id", ["home_kiosk_id"])


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.drop_index("ix_employees_home_kiosk_id")
        batch.drop_column("home_kiosk_id")
