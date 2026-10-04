from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.kiosk_devices import KIOSK_ID_PATTERN

EMBEDDING_DIM = 512
MAX_CROP_B64 = 400_000  # ~300 KB JPEG; the kiosk sends a 224 px crop (~15 KB)


def _finite(v: float | None, lo: float, hi: float, name: str) -> float | None:
    if v is None:
        return None
    if not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{name} out of range")
    return v


class KioskEventRequest(BaseModel):
    """Posted by the kiosk after steps 1-6 of the pipeline run locally. If
    `embedding` is None, `reject_reason` MUST be 'liveness_failed' or
    'too_small' (steps 3/5 stopped the pipeline before recognition ever
    ran) -- see docs/DECISIONS.md."""

    client_event_id: str = Field(min_length=1, max_length=64)
    kiosk_id: str = Field(pattern=KIOSK_ID_PATTERN)
    occurred_at: datetime
    embedding: list[float] | None = None
    quality_score: float | None = None
    liveness_score: float | None = None
    crop_jpeg_base64: str | None = Field(default=None, max_length=MAX_CROP_B64)
    box: tuple[float, float, float, float] | None = None
    reject_reason: Literal["liveness_failed", "too_small"] | None = None

    @field_validator("embedding")
    @classmethod
    def _embedding(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if len(v) != EMBEDDING_DIM:
            raise ValueError(f"embedding must have {EMBEDDING_DIM} values")
        norm = math.sqrt(sum(x * x for x in v))
        if not math.isfinite(norm) or norm < 1e-6:
            raise ValueError("embedding is not a valid vector")
        return v

    @field_validator("quality_score")
    @classmethod
    def _quality(cls, v: float | None) -> float | None:
        return _finite(v, 0.0, 1.0, "quality_score")

    @field_validator("liveness_score")
    @classmethod
    def _liveness(cls, v: float | None) -> float | None:
        return _finite(v, 0.0, 1.0, "liveness_score")

    @field_validator("box")
    @classmethod
    def _box(cls, v: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
        if v is not None and not all(math.isfinite(x) and -10_000 <= x <= 20_000 for x in v):
            raise ValueError("box out of range")
        return v


class KioskEventResponse(BaseModel):
    event_id: str | None  # None = unclear face, not recorded as attendance
    subject_type: str | None
    face_id: str | None
    event_type: str | None
    similarity: float | None
    created: bool


class KioskHeartbeatRequest(BaseModel):
    kiosk_id: str = Field(pattern=KIOSK_ID_PATTERN)
    device: dict[str, Any]

    @field_validator("device")
    @classmethod
    def _small(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(repr(v)) > 20_000:
            raise ValueError("device info too large")
        return v


class KioskHeartbeatResponse(BaseModel):
    ok: bool


class KioskConfigResponse(BaseModel):
    settings: dict
