from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.users import User
from app.schemas.analytics import AnalyticsSummaryResponse, SummaryRowOut
from app.services.analytics import compute_summary, rows_to_csv
from app.services.analytics_overview import compute_overview
from app.services.settings_service import get_setting

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _resolve_range(period: str, date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    if date_from and date_to:
        return date_from, date_to
    if period == "daily":
        return today, today
    if period == "weekly":
        return today - timedelta(days=today.weekday()), today
    if period == "monthly":
        return today.replace(day=1), today
    if period == "annual":
        return today.replace(month=1, day=1), today
    return today, today


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    period: Literal["daily", "weekly", "monthly", "annual"] = "daily",
    date_from: date | None = None,
    date_to: date | None = None,
    subject_id: str | None = None,
    include_unknowns: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AnalyticsSummaryResponse:
    range_from, range_to = _resolve_range(period, date_from, date_to)
    working_days = await get_setting(db, "working_days_per_week")
    rows = await compute_summary(db, range_from, range_to, working_days, subject_id, include_unknowns)
    return AnalyticsSummaryResponse(
        period=period, date_from=range_from.isoformat(), date_to=range_to.isoformat(),
        rows=[SummaryRowOut(**r.__dict__) for r in rows],
    )


@router.get("/overview")
async def analytics_overview(
    period: Literal["daily", "weekly", "monthly", "annual"] = "weekly",
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """KPIs (+ previous-period deltas), daily trend, per-camera headcount,
    departments, arrival-time histogram and people needing attention -- see
    services/analytics_overview.py for every definition."""
    range_from, range_to = _resolve_range(period, date_from, date_to)
    if range_to < range_from or (range_to - range_from).days > 366:
        raise http_error(422, "bad_range", "date_to must be on/after date_from and the range at most 1 year")
    working_days = int(await get_setting(db, "working_days_per_week"))
    return await compute_overview(db, range_from, range_to, working_days)


@router.get("/export.csv")
async def analytics_export_csv(
    period: Literal["daily", "weekly", "monthly", "annual"] = "daily",
    date_from: date | None = None,
    date_to: date | None = None,
    subject_id: str | None = None,
    include_unknowns: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    range_from, range_to = _resolve_range(period, date_from, date_to)
    working_days = await get_setting(db, "working_days_per_week")
    rows = await compute_summary(db, range_from, range_to, working_days, subject_id, include_unknowns)
    csv_text = rows_to_csv(rows)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendance_{period}_{range_from}_{range_to}.csv"},
    )
