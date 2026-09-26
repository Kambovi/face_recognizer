"""employees.contractor + shift_assignments (roster)

Revision ID: 0003_contractor_roster
Revises: 0002_home_kiosk
Create Date: 2026-09-26

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0003_contractor_roster"
down_revision: Union[str, None] = "0002_home_kiosk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("contractor", sa.String(length=120), nullable=True))
        batch.create_index("ix_employees_contractor", ["contractor"])
    op.create_table(
        "shift_assignments",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shift_id", GUID, sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_shift_assignments_employee_id", "shift_assignments", ["employee_id"])
    op.create_index("ix_shift_assignments_emp_start", "shift_assignments", ["employee_id", "start_date"])


def downgrade() -> None:
    op.drop_index("ix_shift_assignments_emp_start", table_name="shift_assignments")
    op.drop_index("ix_shift_assignments_employee_id", table_name="shift_assignments")
    op.drop_table("shift_assignments")
    with op.batch_alter_table("employees") as batch:
        batch.drop_index("ix_employees_contractor")
        batch.drop_column("contractor")
