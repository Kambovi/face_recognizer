from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum, utcnow
from app.models.enums import UserRole
from app.models.types import GUID, new_uuid_str, UTCDateTime


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole, "user_role"), nullable=False, default=UserRole.VIEWER
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
