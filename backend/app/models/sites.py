"""Sites reporting to this install when it acts as the head-office (HQ)
dashboard: one row per factory / branch, each with its own push token."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, UTCDateTime, new_uuid_str


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    # sha256 of the push token; the token itself is shown once, at creation.
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_push_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), nullable=True)
