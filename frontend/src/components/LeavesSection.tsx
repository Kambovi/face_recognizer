import { useCallback, useEffect, useState } from "react";
import { addLeave, deleteLeave, getLeaveBalance, listLeaves, listLeaveTypes, toApiError } from "../api/client";
import type { LeaveBalance, LeaveOut, LeaveType } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const input = "rounded-md border border-gray-300 px-2 py-1.5 text-sm";

function todayIso(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function label(r: LeaveOut): string {
  if (r.kind === "off") return "Off day";
  const base = r.leave_type ?? (r.kind === "paid" ? "Paid" : "Without pay");
  return r.portion < 1 ? `${base} (half day)` : base;
}

/** Leave register + balances for one person (Employees -> detail panel).
 *  A leave day shows as L / LWP / HL instead of Absent in reports, payroll
 *  and the chatbot; "Off day" is a rostered weekly off (WO). */
export function LeavesSection({ employeeId }: { employeeId: string }): JSX.Element {
  const { isHr } = useAuth();
  const [rows, setRows] = useState<LeaveOut[]>([]);
  const [types, setTypes] = useState<LeaveType[]>([]);
  const [balance, setBalance] = useState<LeaveBalance[]>([]);
  const [from, setFrom] = useState(todayIso());
  const [to, setTo] = useState(todayIso());
  const [choice, setChoice] = useState("CL"); // a leave type code, or "__off"
  const [half, setHalf] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needsForce, setNeedsForce] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listLeaves(employeeId).then(setRows).catch((e) => setError(toApiError(e).detail));
    getLeaveBalance(employeeId).then(setBalance).catch(() => setBalance([]));
  }, [employeeId]);
  useEffect(load, [load]);
  useEffect(() => {
    listLeaveTypes()
      .then((t) => {
        setTypes(t);
        const first = t[0];
        if (first && !t.some((x) => x.code === "CL")) setChoice(first.code);
      })
      .catch(() => setTypes([]));
  }, []);

  async function add(force = false): Promise<void> {
    setBusy(true);
    setError(null);
    setNeedsForce(false);
    try {
      const off = choice === "__off";
      await addLeave({
        employee_id: employeeId,
        date_from: from,
        date_to: half ? from : to < from ? from : to,
        ...(off ? { kind: "off" as const } : { leave_type: choice }),
        portion: half && !off ? 0.5 : 1,
        note: note.trim() || null,
        force,
      });
      setNote("");
      load();
    } catch (e) {
      const err = toApiError(e);
      setError(err.detail);
      setNeedsForce(err.code === "insufficient_balance");
    } finally {
      setBusy(false);
    }
  }

  const paidBalances = balance.filter((b) => b.paid);

  return (
    <section className="mb-5">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Leave</h3>
      {paidBalances.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {paidBalances.map((b) => (
            <span key={b.code} className="rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs text-gray-700"
              title={`Opening ${b.opening} + credited ${b.credited} - used ${b.used} (${b.year_from} to ${b.year_to})`}>
              <strong>{b.code}</strong> {b.balance ?? 0} left
            </span>
          ))}
        </div>
      )}
      {isHr && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-gray-600">
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={`${input} mt-1 block`} />
          </label>
          {!half && (
            <label className="text-xs text-gray-600">
              To
              <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} className={`${input} mt-1 block`} />
            </label>
          )}
          <select value={choice} onChange={(e) => setChoice(e.target.value)} className={input} aria-label="Leave type">
            {types.map((t) => (
              <option key={t.code} value={t.code}>{t.name}{t.paid ? "" : " (unpaid)"}</option>
            ))}
            <option value="__off">Off day (rotating weekly off)</option>
          </select>
          {choice !== "__off" && (
            <label className="flex items-center gap-1 text-xs text-gray-600">
              <input type="checkbox" checked={half} onChange={(e) => setHalf(e.target.checked)} /> Half day
            </label>
          )}
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className={`${input} min-w-0 flex-1`} />
          <button onClick={() => void add()} disabled={busy} className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
            Mark
          </button>
        </div>
      )}
      {isHr && <p className="mt-1 text-xs text-gray-400">Weekly offs and holidays inside the range are skipped automatically.</p>}
      {error && (
        <p className="mt-2 text-sm text-red-600">
          {error}
          {needsForce && (
            <button onClick={() => void add(true)} className="ml-2 text-xs text-red-700 underline">Mark anyway (goes negative)</button>
          )}
        </p>
      )}
      {rows.length > 0 && (
        <ul className="mt-3 max-h-40 divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-200 text-sm">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>
                {r.day} ·{" "}
                <span className={r.kind === "paid" ? "text-emerald-700" : r.kind === "off" ? "text-gray-600" : "text-amber-700"}>{label(r)}</span>
                {r.note && <span className="text-gray-500"> · {r.note}</span>}
              </span>
              {isHr && (
                <button
                  onClick={() => deleteLeave(r.id).then(load).catch((e) => setError(toApiError(e).detail))}
                  className="text-xs text-red-600 hover:underline"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
