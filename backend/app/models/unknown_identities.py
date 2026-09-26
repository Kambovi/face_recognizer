from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum, utcnow
from app.models.enums import UnknownStatus
from app.models.types import GUID, new_uuid_str, UTCDateTime


class UnknownIdentity(Base):
    __tablename__ = "unknown_identities"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    face_id: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    sighting_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    best_crop_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    status: Mapped[UnknownStatus] = mapped_column(
        str_enum(UnknownStatus, "unknown_status"), nullable=False, default=UnknownStatus.OPEN
    )
    resolved_employee_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    __table_args__ = (sa.Index("ix_unknown_identities_status", "status"),)
