from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UnknownIdentityOut(BaseModel):
    id: str
    face_id: str
    label: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    sighting_count: int
    best_crop_url: str | None = None
    status: str
    resolved_employee_id: str | None

    model_config = {"from_attributes": True}


class UnknownListResponse(BaseModel):
    items: list[UnknownIdentityOut]
    total: int
    page: int
    page_size: int


class UnknownUpdateRequest(BaseModel):
    label: str | None = None
    notes: str | None = None
    status: Literal["OPEN", "IGNORED"] | None = None


class LinkRequest(BaseModel):
    employee_id: str
    reason: str = Field(min_length=3)
    adopt_templates: bool = False


class ConsentPayload(BaseModel):
    policy_version: str
    purpose_text: str
    ip_address: str | None = None


class PromoteRequest(BaseModel):
    name: str
    emp_code: str
    department: str | None = None
    designation: str | None = None
    shift_id: str | None = None
    home_kiosk_id: str | None = None
    contractor: str | None = None
    # Optional at the schema level so a request that OMITS consent still
    # reaches the router's explicit check and gets a clear 422
    # {"code": "consent_required"} instead of a generic Pydantic validation
    # error -- spec: "Requires a consent record -- refuse with 422 without
    # it, create nothing."
    consent: ConsentPayload | None = None
    reason: str = Field(min_length=3)


class PromoteResponse(BaseModel):
    employee_id: str
    face_id: str


class SplitRequest(BaseModel):
    template_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=3)


class SplitResponse(BaseModel):
    new_unknown_id: str
    new_face_id: str


class NearestMatch(BaseModel):
    kind: Literal["EMPLOYEE", "UNKNOWN"]
    id: str
    face_id: str
    name: str | None
    similarity: float
