from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.users import User
from app.schemas.dashboard import AbsentRowOut, DashboardTodayResponse, ExceptionRowOut, KnownRowOut, UnknownRowOut
from app.services.dashboard import DashboardRangeError, DashboardResult, get_dashboard, local_today

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _to_response(result: DashboardResult) -> DashboardTodayResponse:
    return DashboardTodayResponse(
        known=[KnownRowOut(**asdict(row)) for row in result.known],
        unknown=[UnknownRowOut(**asdict(row)) for row in result.unknown],
        absent=[AbsentRowOut(**asdict(row)) for row in result.absent],
        exceptions=[ExceptionRowOut(**asdict(row)) for row in result.exceptions],
        counts=result.counts,
        date_from=result.date_from,
        date_to=result.date_to,
        kiosks=result.kiosks,
    )


@router.get("", response_model=DashboardTodayResponse)
async def dashboard_range(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DashboardTodayResponse:
    """Dashboard for an inclusive local-date (Asia/Kolkata) range; defaults to today."""
    start = date_from or date_to or local_today()
    end = date_to or start
    try:
        result = await get_dashboard(db, start, end)
    except DashboardRangeError as exc:
        raise http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_date_range", str(exc)) from exc
    return _to_response(result)


@router.get("/today", response_model=DashboardTodayResponse)
async def dashboard_today(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> DashboardTodayResponse:
    today = local_today()
    return _to_response(await get_dashboard(db, today, today))
