"""Not in the spec's literal DATA MODEL section. The backend API itself
never runs the recognition pipeline's ONNX inference, so it has no device
state of its own to report; but GET /health is required to return a
`device` block, and device resolution happens once per KIOSK process (see
app/device.py's docstring on why the backend also has a copy for
enrollment). This tiny table is how a kiosk's self-reported resolved
provider reaches /health and the Settings page. See docs/DECISIONS.md."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import utcnow
from app.models.types import UTCDateTime


class KioskHeartbeat(Base):
    __tablename__ = "kiosk_heartbeats"

    kiosk_id: Mapped[str] = mapped_column(sa.String(100), primary_key=True)
    device_json: Mapped[dict] = mapped_column(sa.JSON(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow
    )
