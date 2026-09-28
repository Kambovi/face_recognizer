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

LEAVE_KINDS = ("paid", "unpaid")


class Leave(Base):
    __tablename__ = "leaves"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[dt.date] = mapped_column(sa.Date(), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(10), nullable=False, default="paid")
    note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    __table_args__ = (sa.UniqueConstraint("employee_id", "day", name="uq_leaves_employee_day"),)
