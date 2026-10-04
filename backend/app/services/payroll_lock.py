"""Month lock: once a month's payroll is locked (final), nothing that
changes pay for that month may be edited -- attendance fixes, leave,
holidays. Unlock (admin, audited) to correct, then lock again."""
from __future__ import annotations

from datetime import date

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import http_error


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


async def locked_months(db: AsyncSession) -> set[str]:
    from app.models.payroll import PayrollRun

    rows = await db.execute(select(PayrollRun.month).where(PayrollRun.status == "locked"))
    return {m for (m,) in rows.all()}


async def ensure_unlocked(db: AsyncSession, *days: date) -> None:
    if not days:
        return
    locked = await locked_months(db)
    hit = sorted({month_key(d) for d in days if d is not None} & locked)
    if hit:
        raise http_error(status.HTTP_409_CONFLICT, "month_locked",
                         f"Payroll for {', '.join(hit)} is locked. Unlock it in Payroll to make changes.")
