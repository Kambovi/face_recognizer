"""Statutory payroll (HR / admin only -- salaries are never shown to viewers).

  GET  /payroll/states                         PT states + slabs in use
  GET  /payroll/profile/{employee_id}          bank / PF / ESI / structure (PAN + account masked)
  PUT  /payroll/profile/{employee_id}
  GET  /payroll/adjustments?month=YYYY-MM      one-off earnings / deductions
  POST /payroll/adjustments
  DELETE /payroll/adjustments/{id}
  GET  /payroll/runs                           all months
  POST /payroll/runs/{month}/generate          (re)calculate a draft
  GET  /payroll/runs/{month}                   summary + every payslip
  POST /payroll/runs/{month}/lock              final: freezes attendance / leave for the month
  POST /payroll/runs/{month}/unlock            admin only, audited
  GET  /payroll/runs/{month}/payslips.pdf[?employee_id=]
  GET  /payroll/runs/{month}/register.csv | bank.csv | ecr.txt | esi.csv | pt.csv
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import http_error, require_admin, require_hr
from app.models.employees import Employee
from app.models.payroll import EmployeePayroll, PayrollAdjustment, PayrollRun, Payslip
from app.models.users import User
from app.security import decrypt_text, encrypt_text
from app.services import payroll_files as files
from app.services.audit import write_audit
from app.services.client_profile import get_profile
from app.services.payroll import COMPONENT_ORDER, generate_run, structure
from app.services.settings_service import get_all_settings
from app.services.statutory import PT_SLABS

router = APIRouter(prefix="/payroll", tags=["payroll"])
Month = Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def _mask(v: str) -> str | None:
    return ("*" * max(0, len(v) - 4) + v[-4:]) if v else None


class ProfileIn(BaseModel):
    gender: Literal["M", "F", "O"] | None = None
    pt_state: str | None = Field(default=None, max_length=5)
    pf_enabled: bool = True
    pf_on_full_wage: bool = False
    eps_eligible: bool = True
    uan: str | None = Field(default=None, pattern=r"^\d{12}$")
    esi_enabled: bool = True
    esic_ip: str | None = Field(default=None, pattern=r"^\d{10}$")
    pan: str | None = Field(default=None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")  # blank = keep
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account: str | None = Field(default=None, pattern=r"^\d{6,20}$")   # blank = keep
    ifsc: str | None = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    payment_mode: Literal["bank", "cash", "cheque"] = "bank"
    tax_regime: Literal["new", "old"] = "new"
    tds_monthly: float = Field(default=0, ge=0, le=10_000_000)
    components: dict[str, float] | None = None

    @field_validator("pan", "ifsc", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) and v.strip() else None

    @field_validator("uan", "esic_ip", "bank_account", "bank_name", "pt_state", mode="before")
    @classmethod
    def _blank(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) and v.strip() else None

    @field_validator("components")
    @classmethod
    def _components(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        if v is None:
            return None
        bad = set(v) - set(COMPONENT_ORDER)
        if bad:
            raise ValueError(f"unknown components {sorted(bad)}; allowed {list(COMPONENT_ORDER)}")
        if any(x < 0 or x > 100_000_000 for x in v.values()):
            raise ValueError("component out of range")
        return {k: float(v.get(k) or 0) for k in COMPONENT_ORDER}


class AdjustmentIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    employee_id: str
    kind: Literal["earning", "deduction"]
    label: str = Field(min_length=1, max_length=80)
    amount: float = Field(gt=0, le=100_000_000)


async def _employee(db: AsyncSession, employee_id: str) -> Employee:
    e = (await db.execute(select(Employee).where(Employee.id == employee_id, Employee.deleted_at.is_(None)))).scalar_one_or_none()
    if e is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "employee_not_found", "Employee not found")
    return e


async def _run(db: AsyncSession, month: str) -> PayrollRun:
    run = (await db.execute(select(PayrollRun).where(PayrollRun.month == month))).scalar_one_or_none()
    if run is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "no_run", f"No payroll generated for {month} yet")
    return run


async def _ensure_month_open(db: AsyncSession, month: str) -> None:
    run = (await db.execute(select(PayrollRun).where(PayrollRun.month == month))).scalar_one_or_none()
    if run is not None and run.status == "locked":
        raise http_error(409, "month_locked", f"Payroll for {month} is locked")


# ------------------------------------------------------------------ setup
@router.get("/states")
async def states(db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> dict[str, Any]:
    cfg = await get_all_settings(db)
    return {"company_state": cfg.get("payroll_state") or "",
            "states": [{"code": k, **v} for k, v in PT_SLABS.items()],
            "custom": cfg.get("pt_slabs_custom") or {}}


@router.get("/profile/{employee_id}")
async def get_profile_(employee_id: str, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> dict[str, Any]:
    emp = await _employee(db, employee_id)
    row = await db.get(EmployeePayroll, emp.id)
    cfg = await get_all_settings(db)
    full = structure(float(emp.monthly_salary or 0) or None, row.components if row else None, cfg)
    base = {
        "employee_id": emp.id, "monthly_salary": float(emp.monthly_salary or 0) or None,
        "structure": full, "structure_from": "components" if row and row.components and sum(row.components.values()) else "template",
    }
    if row is None:
        return {**base, "exists": False, "gender": None, "pt_state": None, "pf_enabled": True, "pf_on_full_wage": False,
                "eps_eligible": True, "uan": None, "esi_enabled": True, "esic_ip": None, "pan_masked": None,
                "bank_name": None, "bank_account_masked": None, "ifsc": None, "payment_mode": "bank",
                "tax_regime": "new", "tds_monthly": 0, "components": None}
    return {**base, "exists": True, "gender": row.gender, "pt_state": row.pt_state, "pf_enabled": row.pf_enabled,
            "pf_on_full_wage": row.pf_on_full_wage, "eps_eligible": row.eps_eligible, "uan": row.uan,
            "esi_enabled": row.esi_enabled, "esic_ip": row.esic_ip, "pan_masked": _mask(decrypt_text(row.pan_enc)),
            "bank_name": row.bank_name, "bank_account_masked": _mask(decrypt_text(row.bank_account_enc)),
            "ifsc": row.ifsc, "payment_mode": row.payment_mode, "tax_regime": row.tax_regime,
            "tds_monthly": float(row.tds_monthly or 0), "components": row.components}


@router.put("/profile/{employee_id}")
async def put_profile(employee_id: str, payload: ProfileIn, db: AsyncSession = Depends(get_db),
                      user: User = Depends(require_hr)) -> dict[str, Any]:
    emp = await _employee(db, employee_id)
    row = await db.get(EmployeePayroll, emp.id)
    if row is None:
        row = EmployeePayroll(employee_id=emp.id)
        db.add(row)
    data = payload.model_dump()
    for k in ("gender", "pt_state", "pf_enabled", "pf_on_full_wage", "eps_eligible", "uan", "esi_enabled", "esic_ip",
              "bank_name", "ifsc", "payment_mode", "tax_regime", "tds_monthly", "components"):
        setattr(row, k, data[k])
    if row.pt_state:
        row.pt_state = row.pt_state.upper()
    if payload.pan:
        row.pan_enc = encrypt_text(payload.pan)
    if payload.bank_account:
        row.bank_account_enc = encrypt_text(payload.bank_account)
    if payload.components:
        emp.monthly_salary = sum(payload.components.values())  # keep gross in sync
    await write_audit(db, user.id, "payroll_profile", "employee", emp.id,
                      after={k: v for k, v in data.items() if k not in ("pan", "bank_account")}
                      | {"pan_changed": bool(payload.pan), "bank_changed": bool(payload.bank_account)})
    await db.commit()
    return await get_profile_(employee_id, db, user)


# ------------------------------------------------------------------ adjustments
@router.get("/adjustments")
async def list_adjustments(month: str, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> list[dict[str, Any]]:
    rows = (await db.execute(select(PayrollAdjustment, Employee).join(Employee, Employee.id == PayrollAdjustment.employee_id)
                             .where(PayrollAdjustment.month == month).order_by(Employee.emp_code))).all()
    return [{"id": a.id, "month": a.month, "employee_id": a.employee_id, "emp_code": e.emp_code, "name": e.name,
             "kind": a.kind, "label": a.label, "amount": float(a.amount)} for a, e in rows]


@router.post("/adjustments", status_code=201)
async def add_adjustment(payload: AdjustmentIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    await _employee(db, payload.employee_id)
    await _ensure_month_open(db, payload.month)
    a = PayrollAdjustment(**payload.model_dump())
    db.add(a)
    await db.flush()
    await write_audit(db, user.id, "payroll_adjustment_add", "employee", payload.employee_id, after=payload.model_dump())
    await db.commit()
    return {"id": a.id}


@router.delete("/adjustments/{adj_id}", status_code=204, response_model=None)
async def delete_adjustment(adj_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> None:
    a = await db.get(PayrollAdjustment, adj_id)
    if a is None:
        raise http_error(404, "not_found", "Adjustment not found")
    await _ensure_month_open(db, a.month)
    await write_audit(db, user.id, "payroll_adjustment_delete", "employee", a.employee_id,
                      before={"month": a.month, "label": a.label, "amount": float(a.amount)})
    await db.delete(a)
    await db.commit()


# ------------------------------------------------------------------ runs
def _run_out(run: PayrollRun) -> dict[str, Any]:
    return {"id": run.id, "month": run.month, "status": run.status, "generated_at": run.generated_at,
            "generated_by": run.generated_by, "locked_at": run.locked_at, "locked_by": run.locked_by,
            "totals": run.totals or {}}


@router.get("/runs")
async def list_runs(db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> list[dict[str, Any]]:
    return [_run_out(r) for r in (await db.execute(select(PayrollRun).order_by(PayrollRun.month.desc()))).scalars().all()]


@router.post("/runs/{month}/generate")
async def generate(month: Month, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    run = await generate_run(db, month, user.email)
    await write_audit(db, user.id, "payroll_generate", "payroll", month, after=run.totals)
    await db.commit()
    return await get_run(month, db, user)


async def _slips(db: AsyncSession, run: PayrollRun, employee_id: str | None = None) -> list[dict[str, Any]]:
    q = select(Payslip).where(Payslip.run_id == run.id)
    if employee_id:
        q = q.where(Payslip.employee_id == employee_id)
    slips = [p.data for p in (await db.execute(q)).scalars().all()]
    return sorted(slips, key=lambda s: str(s.get("emp_code")))


@router.get("/runs/{month}")
async def get_run(month: Month, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> dict[str, Any]:
    run = await _run(db, month)
    return {**_run_out(run), "payslips": await _slips(db, run)}


@router.post("/runs/{month}/lock")
async def lock(month: Month, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> dict[str, Any]:
    run = await _run(db, month)
    run.status = "locked"
    run.locked_at = datetime.now(timezone.utc)
    run.locked_by = user.email
    await write_audit(db, user.id, "payroll_lock", "payroll", month, after=run.totals)
    await db.commit()
    return _run_out(run)


@router.post("/runs/{month}/unlock")
async def unlock(month: Month, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    run = await _run(db, month)
    run.status = "draft"
    await write_audit(db, user.id, "payroll_unlock", "payroll", month, before={"locked_by": run.locked_by})
    run.locked_at = None
    run.locked_by = None
    await db.commit()
    return _run_out(run)


def _download(content: str | bytes, filename: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/runs/{month}/payslips.pdf")
async def payslips_pdf(month: Month, employee_id: str | None = None, db: AsyncSession = Depends(get_db),
                       user: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    slips = await _slips(db, run, employee_id)
    await write_audit(db, user.id, "payslip_download", "payroll", month, after={"employee_id": employee_id, "count": len(slips)})
    await db.commit()
    pdf = files.payslips_pdf(slips, await get_profile(db))
    name = f"payslip_{slips[0]['emp_code']}_{month}.pdf" if employee_id and slips else f"payslips_{month}.pdf"
    return _download(pdf, name, "application/pdf")


@router.get("/runs/{month}/register.csv")
async def register(month: Month, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    return _download(files.salary_register_csv(await _slips(db, run)), f"salary_register_{month}.csv", "text/csv; charset=utf-8")


@router.get("/runs/{month}/bank.csv")
async def bank(month: Month, db: AsyncSession = Depends(get_db), user: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    slips = await _slips(db, run)
    rows = (await db.execute(select(EmployeePayroll).where(
        EmployeePayroll.employee_id.in_([s["employee_id"] for s in slips])))).scalars().all() if slips else []
    accounts = {r.employee_id: {"account": decrypt_text(r.bank_account_enc), "ifsc": r.ifsc or ""} for r in rows}
    await write_audit(db, user.id, "bank_file_download", "payroll", month, after={"rows": len(slips)})
    await db.commit()
    return _download(files.bank_transfer_csv(slips, accounts, month), f"bank_transfer_{month}.csv", "text/csv; charset=utf-8")


@router.get("/runs/{month}/ecr.txt")
async def ecr(month: Month, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    return _download(files.ecr_text(await _slips(db, run)), f"pf_ecr_{month}.txt", "text/plain; charset=utf-8")


@router.get("/runs/{month}/esi.csv")
async def esi(month: Month, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    return _download(files.esi_csv(await _slips(db, run)), f"esi_contribution_{month}.csv", "text/csv; charset=utf-8")


@router.get("/runs/{month}/pt.csv")
async def pt(month: Month, db: AsyncSession = Depends(get_db), _u: User = Depends(require_hr)) -> Response:
    run = await _run(db, month)
    return _download(files.pt_register_csv(await _slips(db, run)), f"professional_tax_{month}.csv", "text/csv; charset=utf-8")
