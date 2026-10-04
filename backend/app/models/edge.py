"""Tables used only on an EDGE box (APP_ROLE=edge): the outbox of
recognition results waiting to reach the cloud, and the local index of
detection photos (the photos themselves never leave the site)."""
from __future__ import annotations

import datetime as dt
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import UTCDateTime


class EdgeOutbox(Base):
    __tablename__ = "edge_outbox"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    client_event_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON(), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)


class EdgeDetection(Base):
    __tablename__ = "edge_detections"

    client_event_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    kiosk_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    crop_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
