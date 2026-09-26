"""Real-time alerts shown on the dashboard bell (and sent on WhatsApp if set up).

kind:
  watchlist -- a person or face on the watchlist was seen
  spoof     -- a photo / screen was held up to a camera (liveness failed)
"""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    kiosk_id: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    employee_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    unknown_identity_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("unknown_identities.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("attendance_events.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
