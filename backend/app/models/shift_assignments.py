"""Shift roster: "person X works shift S from date A to date B".

Rotating shifts (week 1 morning, week 2 night ...) are just consecutive
assignments. A person's shift on a day is resolved as:
roster assignment covering that day -> their fixed `employees.shift_id`
-> the default shift (see app/services/shiftday.py).
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str


class ShiftAssignment(Base):
    __tablename__ = "shift_assignments"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shift_id: Mapped[str] = mapped_column(GUID, sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False)
    start_date: Mapped[dt.date] = mapped_column(sa.Date(), nullable=False)
    end_date: Mapped[dt.date] = mapped_column(sa.Date(), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    __table_args__ = (sa.Index("ix_shift_assignments_emp_start", "employee_id", "start_date"),)
