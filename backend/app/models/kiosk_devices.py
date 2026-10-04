"""One row per camera / kiosk allowed to post events.

Each camera gets its OWN random token (shown once when the admin adds the
camera; only its SHA-256 is stored). A token only works for its own
kiosk_id, so a leaked token can be revoked for one camera without touching
the others, and nobody can post events "from" another camera.
"""
from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str

KIOSK_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"


class KioskDevice(Base):
    __tablename__ = "kiosk_devices"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    kiosk_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime(), nullable=True)
