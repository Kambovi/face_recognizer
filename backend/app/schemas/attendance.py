from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AttendanceEventOut(BaseModel):
    id: str
    subject_type: str | None
    employee_id: str | None
    unknown_identity_id: str | None
    event_type: str
    occurred_at: datetime
    similarity: float | None
    liveness_score: float | None
    kiosk_id: str
    crop_url: str | None = None
    reject_reason: str | None
    is_manual_override: bool
    overridden_by: str | None
    override_reason: str | None

    model_config = {"from_attributes": True}


class AttendanceEventListResponse(BaseModel):
    items: list[AttendanceEventOut]
    total: int
    page: int
    page_size: int


class ManualOverrideRequest(BaseModel):
    event_type: Literal["IN", "OUT"] | None = None
    occurred_at: datetime | None = None
    reason: str = Field(min_length=3)


class ReassignRequest(BaseModel):
    target_type: Literal["EMPLOYEE", "UNKNOWN", "NEW_UNKNOWN"]
    target_id: str | None = None
    reason: str = Field(min_length=3)


class ManualEventCreate(BaseModel):
    """Add a missing IN/OUT by hand (e.g. someone forgot to face the camera on
    the way out). Always flagged is_manual_override and audit-logged."""

    employee_id: str
    event_type: Literal["IN", "OUT"]
    occurred_at: datetime
    reason: str = Field(min_length=3)
