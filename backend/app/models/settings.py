from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(sa.String(100), primary_key=True)
    value_json: Mapped[dict] = mapped_column(sa.JSON(), nullable=False)
