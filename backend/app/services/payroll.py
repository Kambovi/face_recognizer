"""Monthly payroll.

  payable_salary()   simple gross pro-rata (chatbot summary, kept as-is)
  compute_payslip()  one person's month: earnings, PF / ESI / PT / TDS,
                     adjustments, net pay, employer cost (pure function)
  generate_run()     every person on the roll that month -> payroll_runs +
                     payslips (draft; regenerate freely until locked)

Earned salary = full-month components x (paid days / days in month)
("calendar" method), or full - full/26 x unpaid days ("fixed26").
Paid days come from the timesheet (present, half days, weekly offs,
holidays, paid leave, not-tracked days before go-live). OT pay is optional.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.models.payroll import EmployeePayroll, PayrollAdjustment, PayrollRun, Payslip
from app.services import statutory as st
from app.services.settings_service import get_all_settings
from app.services.timesheet import build_timesheet, person_totals

COMPONENT_ORDER = ("basic", "da", "hra", "conveyance", "special", "other")
COMPONENT_LABEL = {"basic": "Basic", "da": "Dearness allowance", "hra": "HRA", "conveyance": "Conveyance",
                   "special": "Special allowance", "other": "Other allowance"}


def days_in_month(month_start: date) -> int:
    return calendar.monthrange(month_start.year, month_start.month)[1]


def payable_salary(monthly_salary: float | Decimal | None, paid_days: float, month_start: date) -> float | None:
    if monthly_salary is None:
        return None
    per_day = Decimal(str(monthly_salary)) / Decimal(days_in_month(month_start))
    return float((per_day * Decimal(str(paid_days))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def structure(monthly_salary: float | None, components: dict[str, Any] | None, cfg: dict[str, Any]) -> dict[str, float]:
    """Full-month salary components. Explicit components win; otherwise
    split the gross with the company template."""
    if components:
        out = {k: float(components.get(k) or 0) for k in COMPONENT_ORDER}
        if sum(out.values()) > 0:
            return out
    gross = float(monthly_salary or 0)
    if gross <= 0:
        return {k: 0.0 for k in COMPONENT_ORDER}
    basic = round(gross * float(cfg.get("payroll_basic_percent", 50)) / 100)
    hra = float(min(round(basic * float(cfg.get("payroll_hra_percent", 40)) / 100), gross - basic))
    return {"basic": float(basic), "da": 0.0, "hra": hra, "conveyance": 0.0, "special": gross - basic - hra, "other": 0.0}


@dataclass
class PayslipInput:
    employee_id: str
    emp_code: str
    name: str
    department: str | None
    designation: str | None
    month: str
    full: dict[str, float]
    totals: dict[str, float]          # timesheet person_totals
    profile: dict[str, Any] = field(default_factory=dict)
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    esi_covered_from_period_start: bool | None = None  # ESI contribution-period continuation
    date_of_joining: str | None = None
    date_of_leaving: str | None = None


def compute_payslip(inp: PayslipInput, cfg: dict[str, Any]) -> dict[str, Any]:
    start, end = month_bounds(inp.month)
    dim = days_in_month(start)
    t = inp.totals
    paid = float(t.get("paid_days", 0))
    counted = float(t.get("days_in_range", 0))
    unpaid = max(0.0, dim - paid)
    gross_full = sum(inp.full.values())

    if cfg.get("payroll_proration") == "fixed26":
        factor = max(0.0, 1 - unpaid / 26)
    else:
        factor = paid / dim if dim else 0
    earned: dict[str, float] = {k: float(st.r(v * factor)) for k, v in inp.full.items()}

    # OT
    ot_hours = float(t.get("ot_hours", 0))
    ot_pay = 0
    if cfg.get("ot_pay_enabled") and ot_hours > 0 and gross_full > 0:
        hourly = gross_full / (float(cfg.get("ot_rate_divisor_days", 26)) * float(cfg.get("ot_rate_hours_per_day", 8)))
        ot_pay = st.r(hourly * ot_hours * float(cfg.get("ot_pay_multiplier", 2)))

    adj_earn = [a for a in inp.adjustments if a["kind"] == "earning"]
    adj_ded = [a for a in inp.adjustments if a["kind"] == "deduction"]
    earnings: list[dict[str, Any]] = [{"code": k, "label": COMPONENT_LABEL[k], "full": st.r(inp.full[k]), "amount": int(earned[k])}
                for k in COMPONENT_ORDER if inp.full.get(k)]
    if ot_pay:
        earnings.append({"code": "ot", "label": f"Overtime ({ot_hours:g} h)", "full": 0, "amount": ot_pay})
    for a in adj_earn:
        earnings.append({"code": "adj", "label": a["label"], "full": 0, "amount": st.r(a["amount"])})
    gross = sum(e["amount"] for e in earnings)

    p = inp.profile
    deductions: list[dict[str, Any]] = []
    employer: list[dict[str, Any]] = []

    # PF
    pf_info: dict[str, Any] | None = None
    if cfg.get("pf_enabled", True) and p.get("pf_enabled", True) and gross > 0:
        base = st.code_wages(earned, extra_excluded=ot_pay) if cfg.get("labour_code_wages", True) \
            else earned.get("basic", 0) + earned.get("da", 0)
        ceiling = st.pf_ceiling(end, cfg.get("pf_wage_ceiling_history") or [])
        pf = st.provident_fund(base, ceiling, cfg, full_wage=bool(p.get("pf_on_full_wage")),
                               eps_eligible=bool(p.get("eps_eligible", True)))
        deductions.append({"code": "pf", "label": "Provident fund (EE)", "amount": pf.employee})
        employer += [{"code": "eps", "label": "Pension (EPS)", "amount": pf.eps},
                     {"code": "epf_er", "label": "PF (ER)", "amount": pf.employer_epf},
                     {"code": "edli", "label": "EDLI", "amount": pf.edli},
                     {"code": "pf_admin", "label": "PF admin charges", "amount": pf.admin}]
        pf_info = {"ceiling": ceiling, **pf.__dict__}

    # ESI: covered if full-month gross is within the limit, or if covered at
    # the start of this contribution period (Apr-Sep / Oct-Mar)
    esi_info: dict[str, Any] | None = None
    limit = float(cfg.get("esi_wage_limit", 21000))
    eligible = gross_full <= limit or bool(inp.esi_covered_from_period_start)
    if cfg.get("esi_enabled", True) and p.get("esi_enabled", True) and eligible and gross > 0:
        esi_wage = gross  # ESI wages include OT and adjustments paid as wages
        ee, er = st.esi(esi_wage, paid, cfg)
        deductions.append({"code": "esi", "label": "ESI (EE)", "amount": ee})
        employer.append({"code": "esi_er", "label": "ESI (ER)", "amount": er})
        esi_info = {"wage": st.r(esi_wage), "employee": ee, "employer": er, "days": paid}

    # PT
    state = (p.get("pt_state") or cfg.get("payroll_state") or "").upper()
    pt = st.professional_tax(state, start.month, gross, p.get("gender"), custom=cfg.get("pt_slabs_custom") or {})
    if pt:
        deductions.append({"code": "pt", "label": f"Professional tax ({state})", "amount": pt})

    tds = st.r(float(p.get("tds_monthly") or 0))
    if tds and gross > 0:
        deductions.append({"code": "tds", "label": "Income tax (TDS)", "amount": tds})
    for a in adj_ded:
        deductions.append({"code": "adj", "label": a["label"], "amount": st.r(a["amount"])})

    total_ded = sum(d["amount"] for d in deductions)
    net = gross - total_ded
    warnings = []
    if gross_full <= 0:
        warnings.append("No salary set")
    if net < 0:
        warnings.append("Deductions exceed earnings -- net set to 0, carry the rest to next month")
        net = 0
    if p.get("payment_mode", "bank") == "bank" and (not p.get("has_bank") or not p.get("ifsc")):
        warnings.append("Bank account / IFSC missing")
    if pf_info and not p.get("uan"):
        warnings.append("UAN missing (needed for the PF ECR file)")
    if esi_info and not p.get("esic_ip"):
        warnings.append("ESIC IP number missing")
    if not inp.date_of_joining:
        warnings.append("Joining date not entered")

    return {
        "employee_id": inp.employee_id, "emp_code": inp.emp_code, "name": inp.name,
        "department": inp.department, "designation": inp.designation, "month": inp.month,
        "date_of_joining": inp.date_of_joining, "date_of_leaving": inp.date_of_leaving,
        "days_in_month": dim, "days_counted": counted, "paid_days": paid,
        # loss of pay = days on the roll that aren't paid; days before joining /
        # after leaving are "not on roll", not LOP (and not NCP days in the ECR)
        "lop_days": round(max(0.0, counted - paid), 2), "days_not_on_roll": round(max(0.0, dim - counted), 2),
        "attendance": {k: t.get(k) for k in ("present", "half_days", "absent", "leave", "unpaid_leave", "weekly_off",
                                              "holidays", "worked_on_off", "worked_on_holiday", "not_tracked",
                                              "late_days", "ot_hours")},
        "gross_full": st.r(gross_full), "earnings": earnings, "gross": gross,
        "deductions": deductions, "total_deductions": total_ded, "net": net,
        "employer": employer, "employer_cost": gross + sum(e["amount"] for e in employer),
        "pf": pf_info, "esi": esi_info, "pt_state": state or None,
        "payment_mode": p.get("payment_mode", "bank"), "uan": p.get("uan"), "esic_ip": p.get("esic_ip"),
        "warnings": warnings,
    }


def profile_dict(row: EmployeePayroll | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "gender": row.gender, "pt_state": row.pt_state, "pf_enabled": row.pf_enabled,
        "pf_on_full_wage": row.pf_on_full_wage, "eps_eligible": row.eps_eligible, "uan": row.uan,
        "esi_enabled": row.esi_enabled, "esic_ip": row.esic_ip, "ifsc": row.ifsc, "bank_name": row.bank_name,
        "has_bank": bool(row.bank_account_enc), "payment_mode": row.payment_mode, "tax_regime": row.tax_regime,
        "tds_monthly": float(row.tds_monthly or 0), "components": row.components,
    }


def _period_start(month_start: date) -> date | None:
    """First month of the ESI contribution period, None if this is it."""
    if month_start.month in (4, 10):
        return None
    m = 4 if 4 <= month_start.month <= 9 else 10
    y = month_start.year if month_start.month >= m else month_start.year - 1
    return date(y, m, 1)


async def generate_run(db: AsyncSession, month: str, actor: str) -> PayrollRun:
    from app.deps import http_error

    start, end = month_bounds(month)
    cfg = await get_all_settings(db)
    run = (await db.execute(select(PayrollRun).where(PayrollRun.month == month))).scalar_one_or_none()
    if run is not None and run.status == "locked":
        raise http_error(409, "month_locked", f"Payroll for {month} is locked -- unlock it first")
    if run is None:
        run = PayrollRun(month=month)
        db.add(run)
        await db.flush()
    else:
        await db.execute(delete(Payslip).where(Payslip.run_id == run.id))

    ts = await build_timesheet(db, start, end)
    ids = [p.id for p in ts.people]
    profiles = {r.employee_id: r for r in (await db.execute(
        select(EmployeePayroll).where(EmployeePayroll.employee_id.in_(ids)))).scalars().all()} if ids else {}
    adjustments: dict[str, list[dict[str, Any]]] = {}
    for a in (await db.execute(select(PayrollAdjustment).where(PayrollAdjustment.month == month))).scalars().all():
        adjustments.setdefault(a.employee_id, []).append({"kind": a.kind, "label": a.label, "amount": float(a.amount)})
    # ESI continuation: covered in the period's first month -> stays covered
    covered: set[str] = set()
    ps = _period_start(start)
    if ps is not None:
        prev = (await db.execute(select(PayrollRun).where(PayrollRun.month == f"{ps.year:04d}-{ps.month:02d}"))).scalar_one_or_none()
        if prev is not None:
            for prev_slip in (await db.execute(select(Payslip).where(Payslip.run_id == prev.id))).scalars().all():
                if (prev_slip.data or {}).get("esi"):
                    covered.add(prev_slip.employee_id)

    totals = {"people": 0, "gross": 0, "net": 0, "pf_ee": 0, "pf_er": 0, "esi_ee": 0, "esi_er": 0, "pt": 0, "tds": 0,
              "employer_cost": 0, "warnings": 0}
    for p in ts.people:
        t = person_totals(ts, p.id)
        if t["days_in_range"] <= 0:
            continue
        prof = profile_dict(profiles.get(p.id))
        inp = PayslipInput(
            employee_id=p.id, emp_code=p.emp_code, name=p.name, department=p.department, designation=p.designation,
            month=month, full=structure(float(p.monthly_salary or 0) or None, prof.get("components"), cfg),
            totals=t, profile=prof, adjustments=adjustments.get(p.id, []),
            esi_covered_from_period_start=p.id in covered,
            date_of_joining=p.date_of_joining.isoformat() if p.date_of_joining else None,
            date_of_leaving=p.date_of_leaving.isoformat() if p.date_of_leaving else None,
        )
        slip_data = compute_payslip(inp, cfg)
        db.add(Payslip(run_id=run.id, employee_id=p.id, data=slip_data, net_pay=slip_data["net"]))
        d = {x["code"]: x["amount"] for x in slip_data["deductions"] if x["code"] != "adj"}
        e = {x["code"]: x["amount"] for x in slip_data["employer"]}
        totals["people"] += 1
        totals["gross"] += slip_data["gross"]
        totals["net"] += slip_data["net"]
        totals["pf_ee"] += d.get("pf", 0)
        totals["pf_er"] += e.get("eps", 0) + e.get("epf_er", 0)
        totals["esi_ee"] += d.get("esi", 0)
        totals["esi_er"] += e.get("esi_er", 0)
        totals["pt"] += d.get("pt", 0)
        totals["tds"] += d.get("tds", 0)
        totals["employer_cost"] += slip_data["employer_cost"]
        totals["warnings"] += len(slip_data["warnings"])
    run.totals = totals
    run.status = "draft"
    run.generated_at = datetime.now(timezone.utc)
    run.generated_by = actor
    run.settings_snapshot = {k: v for k, v in cfg.items() if k.startswith(("pf_", "esi_", "payroll_", "ot_pay", "pt_", "labour", "eps", "edli"))}
    await db.flush()
    return run


async def employees_by_id(db: AsyncSession, ids: list[str]) -> dict[str, Employee]:
    if not ids:
        return {}
    return {e.id: e for e in (await db.execute(select(Employee).where(Employee.id.in_(ids)))).scalars().all()}
