from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum, utcnow
from app.models.enums import OwnerType
from app.models.types import GUID, Vector, new_uuid_str, UTCDateTime

EMBEDDING_DIM = 512


class FaceTemplate(Base):
    """Serves BOTH employees and unknown identities (owner_type/owner_id),
    per spec DATA MODEL. No FK constraint on owner_id since it is polymorphic;
    referential integrity for it is enforced in app/services/*."""

    __tablename__ = "face_templates"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    owner_type: Mapped[OwnerType] = mapped_column(str_enum(OwnerType, "owner_type"), nullable=False)
    owner_id: Mapped[str] = mapped_column(GUID, nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_encrypted: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
    quality_score: Mapped[float] = mapped_column(sa.Float(), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    source_image_path: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
    is_primary: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    __table_args__ = (
        sa.Index("ix_face_templates_owner", "owner_type", "owner_id"),
    )
