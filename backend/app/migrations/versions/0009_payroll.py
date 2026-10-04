"""statutory payroll: payroll profile, adjustments, runs, payslips, leave openings

Revision ID: 0009_payroll
Revises: 0008_security_hr_core
Create Date: 2026-10-04

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0009_payroll"
down_revision: Union[str, None] = "0008_security_hr_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employee_payroll",
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("gender", sa.String(1), nullable=True),
        sa.Column("pt_state", sa.String(5), nullable=True),
        sa.Column("pf_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pf_on_full_wage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eps_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("uan", sa.String(20), nullable=True),
        sa.Column("esi_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("esic_ip", sa.String(20), nullable=True),
        sa.Column("pan_enc", sa.Text(), nullable=True),
        sa.Column("bank_name", sa.String(120), nullable=True),
        sa.Column("bank_account_enc", sa.Text(), nullable=True),
        sa.Column("ifsc", sa.String(11), nullable=True),
        sa.Column("payment_mode", sa.String(10), nullable=False, server_default="bank"),
        sa.Column("tax_regime", sa.String(5), nullable=False, server_default="new"),
        sa.Column("tds_monthly", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("components", sa.JSON(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "payroll_adjustments",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_payroll_adjustments_month", "payroll_adjustments", ["month"])
    op.create_index("ix_payroll_adjustments_employee_id", "payroll_adjustments", ["employee_id"])
    op.create_table(
        "payroll_runs",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("generated_at", UTCDateTime(), nullable=False),
        sa.Column("generated_by", sa.String(255), nullable=True),
        sa.Column("locked_at", UTCDateTime(), nullable=True),
        sa.Column("locked_by", sa.String(255), nullable=True),
        sa.Column("totals", sa.JSON(), nullable=True),
        sa.Column("settings_snapshot", sa.JSON(), nullable=True),
        sa.UniqueConstraint("month", name="uq_payroll_runs_month"),
    )
    op.create_index("ix_payroll_runs_month", "payroll_runs", ["month"])
    op.create_table(
        "payslips",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("run_id", GUID, sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("net_pay", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "employee_id", name="uq_payslips_run_employee"),
    )
    op.create_index("ix_payslips_run_id", "payslips", ["run_id"])
    op.create_index("ix_payslips_employee_id", "payslips", ["employee_id"])
    op.create_table(
        "leave_openings",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("days", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("employee_id", "year", "leave_type", name="uq_leave_openings"),
    )
    op.create_index("ix_leave_openings_employee_id", "leave_openings", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_leave_openings_employee_id", table_name="leave_openings")
    op.drop_table("leave_openings")
    op.drop_index("ix_payslips_employee_id", table_name="payslips")
    op.drop_index("ix_payslips_run_id", table_name="payslips")
    op.drop_table("payslips")
    op.drop_index("ix_payroll_runs_month", table_name="payroll_runs")
    op.drop_table("payroll_runs")
    op.drop_index("ix_payroll_adjustments_employee_id", table_name="payroll_adjustments")
    op.drop_index("ix_payroll_adjustments_month", table_name="payroll_adjustments")
    op.drop_table("payroll_adjustments")
    op.drop_table("employee_payroll")
