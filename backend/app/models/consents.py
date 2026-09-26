from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import GUID, new_uuid_str, UTCDateTime


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    employee_id: Mapped[str] = mapped_column(
        GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    policy_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    purpose_text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
