"""Approved leave, one row per person per day.

A leave day with no sighting shows as L (paid leave) or LWP (leave without
pay) in the timesheet instead of A (absent). If the person turns up anyway,
the sighting wins (P). Weekly offs stay WO.
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str

# paid -> L, unpaid -> LWP, off -> WO (rotating weekly off / comp-off day taken
# as an off day, not deducted from a leave balance unless leave_type says so).
LEAVE_KINDS = ("paid", "unpaid", "off")


class Leave(Base):
    __tablename__ = "leaves"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[dt.date] = mapped_column(sa.Date(), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(10), nullable=False, default="paid")
    note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    # Code from settings.leave_types (CL, SL, EL, ...). None = untyped (old rows).
    leave_type: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    # 1.0 full day, 0.5 half day (the other half is worked or absent).
    portion: Mapped[float] = mapped_column(sa.Float, nullable=False, default=1.0, server_default="1")
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    __table_args__ = (sa.UniqueConstraint("employee_id", "day", name="uq_leaves_employee_day"),)
