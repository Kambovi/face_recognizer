"""Salary maths for the chatbot / payroll summary.

Payable = monthly salary / calendar days in the month x paid days.
Paid days come from timesheet.person_totals (present + half-day x 0.5 +
weekly off + paid leave; absent and leave-without-pay are not paid).
This is the common "calendar-day" method used by most Indian payroll
tools. OT is shown in hours only: OT pay rules differ by client.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def days_in_month(month_start: date) -> int:
    return calendar.monthrange(month_start.year, month_start.month)[1]


def payable_salary(monthly_salary: float | Decimal | None, paid_days: float, month_start: date) -> float | None:
    if monthly_salary is None:
        return None
    per_day = Decimal(str(monthly_salary)) / Decimal(days_in_month(month_start))
    return float((per_day * Decimal(str(paid_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
