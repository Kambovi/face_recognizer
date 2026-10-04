"""Opening leave balance per person, leave year and leave type (carried
forward from last year, or entered by HR when the system goes live)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.types import GUID, new_uuid_str


class LeaveOpening(Base):
    __tablename__ = "leave_openings"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(sa.Integer, nullable=False)  # leave year it opens
    leave_type: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    days: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0)

    __table_args__ = (sa.UniqueConstraint("employee_id", "year", "leave_type", name="uq_leave_openings"),)
