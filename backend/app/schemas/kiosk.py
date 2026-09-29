from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class KioskEventRequest(BaseModel):
    """Posted by the kiosk after steps 1-6 of the pipeline run locally. If
    `embedding` is None, `reject_reason` MUST be 'liveness_failed' or
    'too_small' (steps 3/5 stopped the pipeline before recognition ever
    ran) -- see docs/DECISIONS.md."""

    client_event_id: str
    kiosk_id: str
    occurred_at: datetime
    embedding: list[float] | None = None
    quality_score: float | None = None
    liveness_score: float | None = None
    crop_jpeg_base64: str | None = None
    box: tuple[float, float, float, float] | None = None
    reject_reason: Literal["liveness_failed", "too_small"] | None = None


class KioskEventResponse(BaseModel):
    event_id: str | None  # None = unclear face, not recorded as attendance
    subject_type: str | None
    face_id: str | None
    event_type: str | None
    similarity: float | None
    created: bool


class KioskHeartbeatRequest(BaseModel):
    kiosk_id: str
    device: dict


class KioskHeartbeatResponse(BaseModel):
    ok: bool


class KioskConfigResponse(BaseModel):
    settings: dict
