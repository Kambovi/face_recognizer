from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, new_uuid_str, UTCDateTime


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    actor_user_id: Mapped[str | None] = mapped_column(
        GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    entity: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    before: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)
    after: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)
    at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )
