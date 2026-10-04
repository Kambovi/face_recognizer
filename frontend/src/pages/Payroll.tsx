import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Download, Lock, Play, Unlock } from "lucide-react";
import {
  addAdjustment,
  deleteAdjustment,
  downloadFile,
  generatePayroll,
  getPayrollRun,
  listAdjustments,
  listEmployees,
  lockPayroll,
  toApiError,
  unlockPayroll,
} from "../api/client";
import type { EmployeeOut, PayrollAdjustment, PayrollRunOut, Payslip } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const input = "rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";
const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const money = (n: number | undefined | null): string => inr.format(n ?? 0);

function previousMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function sumCode(lines: { code: string; amount: number }[], code: string): number {
  return lines.filter((l) => l.code === code).reduce((a, l) => a + l.amount, 0);
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }): JSX.Element {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-500">{sub}</p>}
    </div>
  );
}

function SlipDetail({ s }: { s: Payslip }): JSX.Element {
  const a = s.attendance;
  return (
    <div className="grid gap-4 bg-gray-50 px-4 py-3 text-xs sm:grid-cols-3">
      <div>
        <p className="mb-1 font-semibold text-gray-700">Attendance</p>
        <p>Present {a.present ?? 0}, half days {a.half_days ?? 0}, absent {a.absent ?? 0}</p>
        <p>Leave {a.leave ?? 0}, unpaid {a.unpaid_leave ?? 0}, holidays {a.holidays ?? 0}, weekly off {a.weekly_off ?? 0}</p>
        <p>Paid {s.paid_days} of {s.days_in_month}, LOP {s.lop_days}, OT {a.ot_hours ?? 0} h</p>
      </div>
      <div>
        <p className="mb-1 font-semibold text-gray-700">Earnings</p>
        {s.earnings.map((e, i) => <p key={i} className="flex justify-between gap-2"><span>{e.label}</span><span className="tabular-nums">{money(e.amount)}</span></p>)}
      </div>
      <div>
        <p className="mb-1 font-semibold text-gray-700">Deductions</p>
        {s.deductions.length === 0 && <p className="text-gray-400">none</p>}
        {s.deductions.map((d, i) => <p key={i} className="flex justify-between gap-2"><span>{d.label}</span><span className="tabular-nums">{money(d.amount)}</span></p>)}
        <p className="mt-2 font-semibold text-gray-700">Employer cost {money(s.employer_cost)}</p>
      </div>
      {s.warnings.length > 0 && (
        <p className="sm:col-span-3 text-amber-700">{s.warnings.join(" · ")}</p>
      )}
    </div>
  );
}

function Adjustments({ month, locked, onChange }: { month: string; locked: boolean; onChange: () => void }): JSX.Element {
  const [rows, setRows] = useState<PayrollAdjustment[]>([]);
  const [people, setPeople] = useState<EmployeeOut[]>([]);
  const [employeeId, setEmployeeId] = useState("");
  const [kind, setKind] = useState<"earning" | "deduction">("deduction");
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listAdjustments(month).then(setRows).catch((e) => setError(toApiError(e).detail));
  }, [month]);
  useEffect(load, [load]);
  useEffect(() => {
    listEmployees({ page_size: 10000 }).then((r) => setPeople(r.items)).catch(() => setPeople([]));
  }, []);

  async function add(): Promise<void> {
    setError(null);
    try {
      await addAdjustment({ month, employee_id: employeeId, kind, label: label.trim(), amount: Number(amount) });
      setLabel("");
      setAmount("");
      load();
      onChange();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <details className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <summary className="cursor-pointer select-none text-sm font-semibold text-gray-900">
        One-off earnings / deductions for {month} ({rows.length})
      </summary>
      <p className="mt-2 text-xs text-gray-500">Arrears, bonus, incentive, advance or loan recovery, canteen, LWF ... Regenerate the payroll after changes.</p>
      {!locked && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className={`${input} w-56`} aria-label="Person">
            <option value="">Person...</option>
            {people.map((p) => <option key={p.id} value={p.id}>{p.emp_code} -- {p.name}</option>)}
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value as "earning" | "deduction")} className={input} aria-label="Type">
            <option value="deduction">Deduction</option>
            <option value="earning">Earning</option>
          </select>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label, e.g. Advance recovery" className={`${input} w-56`} />
          <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount" type="number" min={1} className={`${input} w-28`} />
          <button onClick={() => void add()} disabled={!employeeId || !label.trim() || !(Number(amount) > 0)}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
            Add
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {rows.length > 0 && (
        <ul className="mt-3 divide-y divide-gray-100 rounded-md border border-gray-200 text-sm">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>{r.emp_code} {r.name} · {r.label}</span>
              <span className={clsx("tabular-nums", r.kind === "earning" ? "text-emerald-700" : "text-red-700")}>
                {r.kind === "earning" ? "+" : "-"}{money(r.amount)}
                {!locked && (
                  <button onClick={() => void deleteAdjustment(r.id).then(() => { load(); onChange(); }).catch((e) => setError(toApiError(e).detail))}
                    className="ml-3 text-xs text-red-600 hover:underline">Remove</button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

/** Monthly payroll: generate a draft from attendance, check, download the
 *  files, then lock (attendance and leave for the month are frozen). */
export function Payroll(): JSX.Element {
  const { isAdmin } = useAuth();
  const [month, setMonth] = useState(previousMonth());
  const [run, setRun] = useState<PayrollRunOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [stale, setStale] = useState(false);

  const load = useCallback(() => {
    setError(null);
    getPayrollRun(month)
      .then((r) => { setRun(r); setStale(false); })
      .catch((e) => {
        const err = toApiError(e);
        setRun(null);
        if (err.code !== "no_run") setError(err.detail);
      });
  }, [month]);
  useEffect(load, [load]);

  async function act(fn: () => Promise<PayrollRunOut>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    } finally {
      setBusy(false);
    }
  }

  const slips = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (run?.payslips ?? []).filter((s) => !q || `${s.emp_code} ${s.name} ${s.department ?? ""}`.toLowerCase().includes(q));
  }, [run, filter]);
  const locked = run?.status === "locked";
  const t = run?.totals;
  const dl = (path: string, name: string): void => {
    downloadFile(`/payroll/runs/${month}/${path}`, {}, name).catch((e) => setError(toApiError(e).detail));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Payroll</h1>
          <p className="text-sm text-gray-500">From attendance, leave and holidays. Check, download, then lock the month.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className={input} aria-label="Month" />
          {!locked && (
            <button disabled={busy} onClick={() => void act(() => generatePayroll(month))}
              className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
              <Play className="h-4 w-4" aria-hidden /> {run ? "Recalculate" : "Generate"}
            </button>
          )}
          {run && !locked && (
            <button disabled={busy} onClick={() => { if (window.confirm(`Lock ${month}? Attendance, leave and holidays for the month can't be changed afterwards.`)) void act(() => lockPayroll(month)); }}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
              <Lock className="h-4 w-4" aria-hidden /> Lock month
            </button>
          )}
          {locked && isAdmin && (
            <button disabled={busy} onClick={() => { if (window.confirm(`Unlock ${month}? Payslips may change when recalculated.`)) void act(() => unlockPayroll(month)); }}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
              <Unlock className="h-4 w-4" aria-hidden /> Unlock
            </button>
          )}
        </div>
      </div>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {!run && !error && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center text-sm text-gray-500">
          No payroll for {month} yet. Set salaries (Staff &rarr; person &rarr; Payroll), holidays and leave, then press Generate.
        </div>
      )}

      {run && t && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span className={clsx("rounded px-2 py-0.5 font-medium", locked ? "bg-gray-900 text-white" : "bg-amber-100 text-amber-800")}>
              {locked ? `Locked by ${run.locked_by ?? ""}` : "Draft"}
            </span>
            <span>Calculated {new Date(run.generated_at).toLocaleString()} by {run.generated_by}</span>
            {stale && <span className="text-amber-700">Adjustments changed -- recalculate</span>}
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
            <Tile label="People" value={String(t.people)} />
            <Tile label="Gross" value={money(t.gross)} />
            <Tile label="Net pay" value={money(t.net)} />
            <Tile label="PF" value={money(t.pf_ee + t.pf_er)} sub={`EE ${money(t.pf_ee)} · ER ${money(t.pf_er)}`} />
            <Tile label="ESI" value={money(t.esi_ee + t.esi_er)} sub={`EE ${money(t.esi_ee)} · ER ${money(t.esi_er)}`} />
            <Tile label="Employer cost" value={money(t.employer_cost)} sub={`PT ${money(t.pt)} · TDS ${money(t.tds)}`} />
          </div>
          {t.warnings > 0 && (
            <p className="flex items-center gap-2 rounded-md bg-amber-50 p-2 text-sm text-amber-800">
              <AlertTriangle className="h-4 w-4" aria-hidden /> {t.warnings} thing(s) to check -- missing bank details, UAN, joining dates ... (marked in the table)
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {[
              ["payslips.pdf", `payslips_${month}.pdf`, "All payslips (PDF)"],
              ["register.csv", `salary_register_${month}.csv`, "Salary register"],
              ["bank.csv", `bank_transfer_${month}.csv`, "Bank transfer sheet"],
              ["ecr.txt", `pf_ecr_${month}.txt`, "PF ECR (EPFO)"],
              ["esi.csv", `esi_contribution_${month}.csv`, "ESI contribution"],
              ["pt.csv", `professional_tax_${month}.csv`, "PT register"],
            ].map(([path = "", name = "", label]) => (
              <button key={path} onClick={() => dl(path, name)}
                className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
                <Download className="h-4 w-4" aria-hidden /> {label}
              </button>
            ))}
          </div>

          <Adjustments month={month} locked={locked} onChange={() => setStale(true)} />

          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search name / ID / department" className={`${input} w-72`} />
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-3 py-2">Person</th>
                  <th className="px-3 py-2 text-right">Paid days</th>
                  <th className="px-3 py-2 text-right">Gross</th>
                  <th className="px-3 py-2 text-right">PF</th>
                  <th className="px-3 py-2 text-right">ESI</th>
                  <th className="px-3 py-2 text-right">PT</th>
                  <th className="px-3 py-2 text-right">TDS</th>
                  <th className="px-3 py-2 text-right">Other</th>
                  <th className="px-3 py-2 text-right">Net pay</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {slips.map((s) => (
                  <Fragment key={s.employee_id}>
                    <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setOpen(open === s.employee_id ? null : s.employee_id)}>
                      <td className="px-3 py-2">
                        <div className="font-medium text-gray-900">{s.name}</div>
                        <div className="text-xs text-gray-500">{s.emp_code}{s.department ? ` · ${s.department}` : ""}</div>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.paid_days}/{s.days_in_month}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(s.gross)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(sumCode(s.deductions, "pf"))}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(sumCode(s.deductions, "esi"))}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(sumCode(s.deductions, "pt"))}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(sumCode(s.deductions, "tds"))}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(sumCode(s.deductions, "adj"))}</td>
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{money(s.net)}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        {s.warnings.length > 0 && <AlertTriangle className="mr-2 inline h-4 w-4 text-amber-500" aria-label={s.warnings.join(", ")} />}
                        <button
                          onClick={(e) => { e.stopPropagation(); downloadFile(`/payroll/runs/${month}/payslips.pdf`, { employee_id: s.employee_id }, `payslip_${s.emp_code}_${month}.pdf`).catch((er) => setError(toApiError(er).detail)); }}
                          className="text-xs text-brand-700 hover:underline"
                        >
                          Payslip
                        </button>
                      </td>
                    </tr>
                    {open === s.employee_id && (
                      <tr><td colSpan={10} className="p-0"><SlipDetail s={s} /></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-gray-500">
            PF on the Rs 25,000 ceiling (from 17-Sep-2026), labour-code 50% wage rule, ESI up to Rs 21,000, PT by state slabs.
            TDS is the monthly amount entered per person. Check rates with your CA in Settings -&gt; Payroll.
          </p>
        </>
      )}
    </div>
  );
}
