from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ShiftOut(BaseModel):
    id: str
    name: str
    in_time: str
    out_time: str
    grace_minutes: int
    is_default: bool

    model_config = {"from_attributes": True}


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    emp_code: str = Field(min_length=1, max_length=50)
    department: str | None = None
    designation: str | None = None
    shift_id: str | None = None
    home_kiosk_id: str | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    designation: str | None = None
    shift_id: str | None = None
    home_kiosk_id: str | None = None
    is_active: bool | None = None


class EmployeeOut(BaseModel):
    id: str
    face_id: str
    emp_code: str
    name: str
    department: str | None
    designation: str | None
    shift_id: str | None
    home_kiosk_id: str | None = None
    is_active: bool
    created_at: datetime
    template_count: int = 0

    model_config = {"from_attributes": True}


class EmployeeListResponse(BaseModel):
    items: list[EmployeeOut]
    total: int
    page: int
    page_size: int


class ConsentCreate(BaseModel):
    policy_version: str
    purpose_text: str
    ip_address: str | None = None


class ConsentOut(BaseModel):
    id: str
    employee_id: str
    granted_at: datetime
    revoked_at: datetime | None
    policy_version: str
    purpose_text: str

    model_config = {"from_attributes": True}


class EnrollImageResult(BaseModel):
    filename: str
    accepted: bool
    reason: str | None
    quality_score: float
    template_id: str | None = None


class EnrollResponse(BaseModel):
    results: list[EnrollImageResult]
    accepted_count: int
    template_count: int


class FaceTemplateOut(BaseModel):
    id: str
    quality_score: float
    model_version: str
    created_at: datetime
    is_primary: bool
    crop_url: str | None = None

    model_config = {"from_attributes": True, "protected_namespaces": ()}
