"""Indian statutory deductions: PF (EPF/EPS/EDLI), ESI, Professional Tax,
labour-code wage rule. Pure functions, no database -- easy to test and to
check against a CA's sheet.

!! Rates and slabs change. The defaults below were checked in Oct 2026
(EPF ceiling Rs 25,000 from 17-Sep-2026; ESI limit Rs 21,000; PT slabs per
state). Every number is a setting, so a client's CA can correct it without
a code change (Settings -> Payroll, `pt_slabs_custom`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# ------------------------------------------------------------------ PT slabs
# slabs: [[upper limit of monthly gross (inclusive) or None for "above", amount], ...]
# period "half-yearly": slabs are on half-year gross and the amount is
# deducted in the last month of each half (Sep and Mar).
PT_SLABS: dict[str, dict[str, Any]] = {
    "MH": {"name": "Maharashtra", "period": "monthly",
           "slabs": [[7500, 0], [10000, 175], [None, 200]], "feb_top": 300,
           # women earning up to Rs 25,000 a month are exempt
           "women_exempt_upto": 25000},
    "KA": {"name": "Karnataka", "period": "monthly", "slabs": [[24999, 0], [None, 200]], "feb_top": 300},
    "WB": {"name": "West Bengal", "period": "monthly",
           "slabs": [[10000, 0], [15000, 110], [25000, 130], [40000, 150], [None, 200]]},
    "GJ": {"name": "Gujarat", "period": "monthly", "slabs": [[11999, 0], [None, 200]]},
    "TG": {"name": "Telangana", "period": "monthly", "slabs": [[15000, 0], [20000, 150], [None, 200]]},
    "AP": {"name": "Andhra Pradesh", "period": "monthly", "slabs": [[15000, 0], [20000, 150], [None, 200]]},
    "MP": {"name": "Madhya Pradesh", "period": "monthly",
           "slabs": [[18750, 0], [25000, 125], [33333, 167], [None, 208]]},
    "OD": {"name": "Odisha", "period": "monthly",
           "slabs": [[13304, 0], [25000, 125], [41666, 167], [None, 208]]},
    "BR": {"name": "Bihar", "period": "monthly", "slabs": [[25000, 0], [41666, 83], [None, 208]]},
    "JH": {"name": "Jharkhand", "period": "monthly", "slabs": [[25000, 0], [41667, 100], [None, 208]]},
    "AS": {"name": "Assam", "period": "monthly", "slabs": [[10000, 0], [14999, 150], [24999, 180], [None, 208]]},
    "TN": {"name": "Tamil Nadu", "period": "half-yearly",
           "slabs": [[21000, 0], [30000, 135], [45000, 315], [60000, 690], [75000, 1025], [None, 1250]]},
    "KL": {"name": "Kerala", "period": "half-yearly",
           "slabs": [[11999, 0], [17999, 120], [29999, 180], [44999, 300], [59999, 450], [74999, 600],
                     [99999, 750], [124999, 1000], [None, 1250]]},
}
NO_PT_STATES = "Delhi, Uttar Pradesh, Haryana, Rajasthan, Punjab, Himachal, Uttarakhand, J&K, Goa (none)"


def r(x: float | Decimal) -> int:
    """Round half-up to the rupee."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _slab(amount: float, slabs: list[list[Any]]) -> tuple[int, bool]:
    """(tax, is_top_slab)"""
    for i, (upto, tax) in enumerate(slabs):
        if upto is None or amount <= float(upto):
            return int(tax), i == len(slabs) - 1
    return int(slabs[-1][1]), True


def professional_tax(state: str | None, month: int, gross: float, gender: str | None = None,
                     half_year_gross: float | None = None, custom: dict[str, Any] | None = None) -> int:
    """PT to deduct this month. `half_year_gross` is needed for half-yearly
    states (sum of the 6 months' gross; pass the estimate gross x 6 if unknown)."""
    if not state:
        return 0
    spec = (custom or {}).get(state) or PT_SLABS.get(state.upper())
    if not spec:
        return 0
    if spec.get("period") == "half-yearly":
        if month not in (9, 3):
            return 0
        tax, _ = _slab(half_year_gross if half_year_gross is not None else gross * 6, spec["slabs"])
        return tax
    if gender == "F" and spec.get("women_exempt_upto") and gross <= float(spec["women_exempt_upto"]):
        return 0
    tax, top = _slab(gross, spec["slabs"])
    if month == 2 and top and spec.get("feb_top"):
        return int(spec["feb_top"])
    return tax


# ------------------------------------------------------------------ PF
def pf_ceiling(on: date, history: list[dict[str, Any]]) -> float:
    ceiling = 15000.0
    for h in sorted(history or [], key=lambda x: x["from"]):
        if date.fromisoformat(str(h["from"])) <= on:
            ceiling = float(h["ceiling"])
    return ceiling


@dataclass
class PfResult:
    pf_wage: int        # wage PF is worked out on (after the labour-code rule)
    epf_wage: int       # capped at the ceiling unless PF on full wage
    eps_wage: int
    edli_wage: int
    employee: int       # 12% of epf_wage
    eps: int            # employer -> pension (8.33% of eps_wage)
    employer_epf: int   # employer -> EPF (12% of epf_wage - eps)
    edli: int
    admin: int


def provident_fund(pf_wage: float, ceiling: float, cfg: dict[str, Any], *, full_wage: bool = False,
                   eps_eligible: bool = True) -> PfResult:
    w = max(0.0, pf_wage)
    epf_wage = w if full_wage else min(w, ceiling)
    eps_wage = min(w, ceiling) if eps_eligible else 0.0
    edli_wage = min(w, ceiling)
    ee = r(epf_wage * float(cfg.get("pf_employee_rate", 12)) / 100)
    er_total = r(epf_wage * float(cfg.get("pf_employer_rate", 12)) / 100)
    eps = r(eps_wage * float(cfg.get("eps_rate", 8.33)) / 100)
    return PfResult(
        pf_wage=r(w), epf_wage=r(epf_wage), eps_wage=r(eps_wage), edli_wage=r(edli_wage),
        employee=ee, eps=eps, employer_epf=max(0, er_total - eps),
        edli=r(edli_wage * float(cfg.get("edli_rate", 0.5)) / 100),
        admin=r(epf_wage * float(cfg.get("pf_admin_rate", 0.5)) / 100),
    )


# ------------------------------------------------------------------ ESI
def esi(esi_wage: float, days_paid: float, cfg: dict[str, Any]) -> tuple[int, int]:
    """(employee, employer). ESIC rounds contributions UP to the next rupee.
    Low-wage rule: daily average wage <= Rs 176 -> no employee share."""
    if esi_wage <= 0:
        return 0, 0
    er = math.ceil(esi_wage * float(cfg.get("esi_employer_rate", 3.25)) / 100 - 1e-9)
    daily = esi_wage / days_paid if days_paid else 0
    ee = 0 if daily and daily <= 176 else math.ceil(esi_wage * float(cfg.get("esi_employee_rate", 0.75)) / 100 - 1e-9)
    return ee, er


# ------------------------------------------------------------------ labour codes
WAGE_PARTS = ("basic", "da")  # basic pay + dearness allowance (+ retaining allowance)


def code_wages(earned: dict[str, float], extra_excluded: float = 0.0) -> float:
    """Code on Wages, 2019 (in force 21-Nov-2025): wages = basic + DA; if the
    excluded payments (HRA, conveyance, special/other allowances, OT ...)
    are more than half of total remuneration, the excess is added to wages."""
    wages = sum(float(earned.get(k, 0)) for k in WAGE_PARTS)
    excluded = sum(float(v) for k, v in earned.items() if k not in WAGE_PARTS) + extra_excluded
    total = wages + excluded
    if total > 0 and excluded > total / 2:
        wages += excluded - total / 2
    return wages
