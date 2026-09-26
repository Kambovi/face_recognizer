from __future__ import annotations

from pydantic import BaseModel, Field

# Fields added for the range dashboard (date, kiosk_ids, is_active, on_time,
# date_from/date_to/kiosks) all have defaults, so the /dashboard/today
# contract is a strict superset of what it was before.


class KnownRowOut(BaseModel):
    face_id: str
    emp_code: str | None = None
    name: str
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    in_time: str | None
    out_time: str | None
    total_hours: float
    status: str
    similarity: float | None
    thumb_url: str | None
    best_shot_url: str | None
    date: str = ""
    kiosk_ids: list[str] = Field(default_factory=list)
    is_active: bool = True
    on_time: bool | None = None
    subject_id: str = ""
    in_event_id: str | None = None
    out_event_id: str | None = None
    home_kiosk_id: str | None = None


class UnknownRowOut(BaseModel):
    face_id: str
    label: str | None
    first_seen: str
    last_seen: str
    sighting_count: int
    in_time: str | None
    out_time: str | None
    total_hours: float
    status: str
    best_crop_url: str | None
    date: str = ""
    kiosk_ids: list[str] = Field(default_factory=list)
    subject_id: str = ""
    in_event_id: str | None = None
    out_event_id: str | None = None


class AbsentRowOut(BaseModel):
    face_id: str
    emp_code: str | None = None
    name: str
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    thumb_url: str | None
    date: str = ""
    is_active: bool = True
    subject_id: str = ""
    home_kiosk_id: str | None = None


class ExceptionRowOut(BaseModel):
    kind: str
    face_id: str
    label: str | None
    detail: str
    date: str = ""
    kiosk_ids: list[str] = Field(default_factory=list)


class DashboardTodayResponse(BaseModel):
    known: list[KnownRowOut]
    unknown: list[UnknownRowOut]
    absent: list[AbsentRowOut]
    exceptions: list[ExceptionRowOut]
    counts: dict[str, int]
    date_from: str = ""
    date_to: str = ""
    kiosks: list[str] = Field(default_factory=list)
