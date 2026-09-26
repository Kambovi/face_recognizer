from __future__ import annotations

from pydantic import BaseModel


class SummaryRowOut(BaseModel):
    face_id: str
    name: str | None
    designation: str | None
    department: str | None
    shift_in: str | None
    shift_out: str | None
    avg_in_time: str | None
    avg_out_time: str | None
    total_hours: float
    present_days: int
    absent_days: int
    late_count: int
    early_exit_count: int
    attendance_pct: float
    is_unknown: bool
    label: str | None


class AnalyticsSummaryResponse(BaseModel):
    period: str
    date_from: str
    date_to: str
    rows: list[SummaryRowOut]
