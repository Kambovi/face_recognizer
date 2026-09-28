from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, new_uuid_str, UTCDateTime

if TYPE_CHECKING:
    # Import cycle (Employee <-> Shift) resolved via TYPE_CHECKING -- only
    # needed so mypy can resolve the "Shift" forward reference below; the
    # relationship() call itself resolves it at runtime via SQLAlchemy's
    # mapper registry, not this import.
    from app.models.shifts import Shift  # noqa: F401


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    face_id: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False, index=True)
    emp_code: Mapped[str] = mapped_column(sa.String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    designation: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    shift_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True
    )
    # Home camera / entry point (a kiosk_id) this person is enrolled at. Used
    # for per-location headcount and the per-camera licence cap. Optional:
    # people without one are inferred from where they're usually seen.
    home_kiosk_id: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    # Labour contractor / agency supplying this person (None = own staff).
    # Drives the contractor-wise report used to verify contractor bills.
    contractor: Mapped[str | None] = mapped_column(sa.String(120), nullable=True, index=True)
    # Set = on the watchlist: every sighting raises an alert (e.g. a
    # dismissed worker who must not re-enter). None = not watchlisted.
    watchlist_reason: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    # Gross monthly salary (INR). Payable = salary / days in month x paid days
    # (services/payroll.py). Only admins ever see it. None = not set.
    monthly_salary: Mapped[float | None] = mapped_column(sa.Numeric(12, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    shift: Mapped["Shift | None"] = relationship(back_populates="employees")

    __table_args__ = (sa.Index("ix_employees_department", "department"),)
