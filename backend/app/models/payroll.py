"""Statutory payroll (India): per-person payroll profile, monthly
adjustments, payroll runs and frozen payslips. Maths in services/payroll.py.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str


class EmployeePayroll(Base):
    """Bank / statutory details + salary structure of one person.

    `components` = monthly full-month amounts, e.g. {"basic": 15000,
    "da": 0, "hra": 6000, "conveyance": 1600, "special": 2400, "other": 0}.
    Empty -> derived from employees.monthly_salary with the company template
    (payroll_basic_percent / payroll_hra_percent). PAN and bank account are
    stored encrypted (security.encrypt_text)."""

    __tablename__ = "employee_payroll"

    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    gender: Mapped[str | None] = mapped_column(sa.String(1), nullable=True)  # M / F / O
    pt_state: Mapped[str | None] = mapped_column(sa.String(5), nullable=True)  # None = company state
    pf_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    pf_on_full_wage: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    eps_eligible: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    uan: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    esi_enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    esic_ip: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    pan_enc: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    bank_name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    bank_account_enc: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    ifsc: Mapped[str | None] = mapped_column(sa.String(11), nullable=True)
    payment_mode: Mapped[str] = mapped_column(sa.String(10), nullable=False, default="bank")  # bank/cash/cheque
    tax_regime: Mapped[str] = mapped_column(sa.String(5), nullable=False, default="new")
    tds_monthly: Mapped[float] = mapped_column(sa.Numeric(12, 2), nullable=False, default=0)
    components: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow)


class PayrollAdjustment(Base):
    """One-off earning or deduction for a month: arrears, bonus, incentive,
    advance / loan recovery, canteen, LWF, TDS top-up ..."""

    __tablename__ = "payroll_adjustments"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    month: Mapped[str] = mapped_column(sa.String(7), nullable=False, index=True)  # YYYY-MM
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(10), nullable=False)  # earning / deduction
    label: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    amount: Mapped[float] = mapped_column(sa.Numeric(12, 2), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    month: Mapped[str] = mapped_column(sa.String(7), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(sa.String(10), nullable=False, default="draft")  # draft / locked
    generated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    generated_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    locked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    totals: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), nullable=True)
    settings_snapshot: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), nullable=True)


class Payslip(Base):
    __tablename__ = "payslips"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    run_id: Mapped[str] = mapped_column(GUID, sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(sa.JSON(), nullable=False)
    net_pay: Mapped[float] = mapped_column(sa.Numeric(12, 2), nullable=False, default=0)

    __table_args__ = (sa.UniqueConstraint("run_id", "employee_id", name="uq_payslips_run_employee"),)
