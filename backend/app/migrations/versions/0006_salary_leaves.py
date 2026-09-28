"""monthly salary on employees + leaves table (chatbot payroll summary)

Revision ID: 0006_salary_leaves
Revises: 0005_sites
Create Date: 2026-09-28

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0006_salary_leaves"
down_revision: Union[str, None] = "0005_sites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("monthly_salary", sa.Numeric(12, 2), nullable=True))
    op.create_table(
        "leaves",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("employee_id", "day", name="uq_leaves_employee_day"),
    )
    op.create_index("ix_leaves_employee_id", "leaves", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_leaves_employee_id", table_name="leaves")
    op.drop_table("leaves")
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("monthly_salary")
