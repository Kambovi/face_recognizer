"""Company holiday calendar. A holiday is a paid day off for everyone (status
H); a person seen on a holiday gets HP (worked on holiday, all time is OT),
same as working on a weekly off."""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    day: Mapped[dt.date] = mapped_column(sa.Date(), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    # national / festival / optional (optional = shown, but not a day off)
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="festival")
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
