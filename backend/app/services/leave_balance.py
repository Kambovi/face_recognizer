"""Leave balances.

Leave year starts in `leave_year_start_month` (setting, 1 = Jan-Dec,
4 = Apr-Mar). Per paid leave type (settings.leave_types):

  credited  monthly accrual: annual/12 for each started month of the year
            the person was on the roll (up to the as-of month);
            yearly: the full annual quota (pro-rata if they joined mid-year);
  opening   leave_openings row (carry-forward / go-live balance);
  used      sum of leave days of that type in the leave year;
  balance   opening + credited - used.

Year end: carry_forward() writes next year's opening = min(balance,
carry_forward) per type.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.models.leave_openings import LeaveOpening
from app.models.leaves import Leave
from app.services.settings_service import get_all_settings
from app.services.shiftday import LOCAL_TZ


def leave_year_bounds(on: date, start_month: int) -> tuple[int, date, date]:
    """(label year, first day, last day) of the leave year containing `on`."""
    y = on.year if on.month >= start_month else on.year - 1
    first = date(y, start_month, 1)
    last = date(y + 1, start_month, 1) if start_month > 1 else date(y + 1, 1, 1)
    from datetime import timedelta

    return y, first, last - timedelta(days=1)


def _months_between(a: date, b: date) -> int:
    """Started months from a to b inclusive (a <= b)."""
    return (b.year - a.year) * 12 + (b.month - a.month) + 1


def types_by_code(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t["code"]).upper(): t for t in (cfg.get("leave_types") or []) if t.get("code")}


async def balances(db: AsyncSession, employee: Employee, on: date | None = None) -> list[dict[str, Any]]:
    cfg = await get_all_settings(db)
    on = on or date.today()
    start_month = int(cfg.get("leave_year_start_month") or 1)
    year, first, last = leave_year_bounds(on, start_month)
    joined = employee.date_of_joining or employee.created_at.astimezone(LOCAL_TZ).date()
    from_day = max(first, joined)
    used_rows = (await db.execute(
        select(Leave.leave_type, func.sum(Leave.portion)).where(
            Leave.employee_id == employee.id, Leave.day >= first, Leave.day <= last, Leave.leave_type.is_not(None)
        ).group_by(Leave.leave_type)
    )).all()
    used = {str(t).upper(): float(n or 0) for t, n in used_rows}
    openings = {o.leave_type.upper(): float(o.days) for o in (await db.execute(
        select(LeaveOpening).where(LeaveOpening.employee_id == employee.id, LeaveOpening.year == year)
    )).scalars().all()}
    out = []
    for code, t in types_by_code(cfg).items():
        annual = float(t.get("annual") or 0)
        accrual = t.get("accrual", "monthly")
        if not t.get("paid", True) or accrual == "none" or from_day > last:
            credited = 0.0
        elif accrual == "monthly":
            upto = min(on, last)
            credited = 0.0 if upto < from_day else annual / 12 * _months_between(from_day, upto)
        else:  # yearly, pro-rata for a mid-year joiner
            credited = annual * _months_between(from_day, last) / 12
        credited = math.floor(credited * 2) / 2  # whole / half days
        opening = openings.get(code, 0.0)
        u = used.get(code, 0.0)
        out.append({
            "code": code, "name": t.get("name", code), "paid": bool(t.get("paid", True)),
            "year": year, "year_from": first.isoformat(), "year_to": last.isoformat(),
            "opening": opening, "credited": credited, "used": u,
            "balance": round(opening + credited - u, 2) if t.get("paid", True) else None,
        })
    return out


async def balance_of(db: AsyncSession, employee: Employee, code: str, on: date) -> float | None:
    for b in await balances(db, employee, on):
        if b["code"] == code.upper():
            return b["balance"]
    return None


async def carry_forward(db: AsyncSession, year: int) -> int:
    """Close leave year `year`: next year's opening = min(balance, carry_forward)."""
    cfg = await get_all_settings(db)
    start_month = int(cfg.get("leave_year_start_month") or 1)
    _, _, last = leave_year_bounds(date(year, start_month, 1), start_month)
    types = types_by_code(cfg)
    n = 0
    people = (await db.execute(select(Employee).where(Employee.deleted_at.is_(None)))).scalars().all()
    for p in people:
        for b in await balances(db, p, last):
            cap = float(types[b["code"]].get("carry_forward") or 0)
            if not b["paid"] or cap <= 0:
                continue
            days = max(0.0, min(float(b["balance"] or 0), cap))
            row = (await db.execute(select(LeaveOpening).where(
                LeaveOpening.employee_id == p.id, LeaveOpening.year == year + 1, LeaveOpening.leave_type == b["code"]
            ))).scalar_one_or_none()
            if row is None:
                db.add(LeaveOpening(employee_id=p.id, year=year + 1, leave_type=b["code"], days=days))
            else:
                row.days = days
            n += 1
    await db.flush()
    return n
