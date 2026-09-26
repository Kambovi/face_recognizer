from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.types import GUID, new_uuid_str

if TYPE_CHECKING:
    # Import cycle (Employee <-> Shift) resolved via TYPE_CHECKING -- only
    # needed so mypy can resolve the "Employee" forward reference below;
    # the relationship() call itself resolves it at runtime via SQLAlchemy's
    # mapper registry, not this import.
    from app.models.employees import Employee  # noqa: F401


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    in_time: Mapped[dt.time] = mapped_column(sa.Time(), nullable=False)
    out_time: Mapped[dt.time] = mapped_column(sa.Time(), nullable=False)
    grace_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=15)
    is_default: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    employees: Mapped[list["Employee"]] = relationship(back_populates="shift")
