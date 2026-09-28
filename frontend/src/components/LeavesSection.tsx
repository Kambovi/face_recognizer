import { useCallback, useEffect, useState } from "react";
import { addLeave, deleteLeave, listLeaves, toApiError } from "../api/client";
import type { LeaveOut } from "../api/types";

const input = "rounded-md border border-gray-300 px-2 py-1.5 text-sm";

function todayIso(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** Leave register for one person (Employees -> detail panel). A leave day
 *  shows as L / LWP instead of Absent in reports, payroll and the chatbot. */
export function LeavesSection({ employeeId }: { employeeId: string }): JSX.Element {
  const [rows, setRows] = useState<LeaveOut[]>([]);
  const [from, setFrom] = useState(todayIso());
  const [to, setTo] = useState(todayIso());
  const [kind, setKind] = useState<"paid" | "unpaid">("paid");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    listLeaves(employeeId).then(setRows).catch((e) => setError(toApiError(e).detail));
  }, [employeeId]);
  useEffect(load, [load]);

  async function add(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await addLeave({ employee_id: employeeId, date_from: from, date_to: to < from ? from : to, kind, note: note.trim() || null });
      setNote("");
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-5">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Leave</h3>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-gray-600">
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={`${input} mt-1 block`} />
        </label>
        <label className="text-xs text-gray-600">
          To
          <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} className={`${input} mt-1 block`} />
        </label>
        <select value={kind} onChange={(e) => setKind(e.target.value as "paid" | "unpaid")} className={input} aria-label="Leave type">
          <option value="paid">Paid leave</option>
          <option value="unpaid">Without pay</option>
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className={`${input} min-w-0 flex-1`} />
        <button onClick={add} disabled={busy} className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
          Mark leave
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      {rows.length > 0 && (
        <ul className="mt-3 max-h-40 divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-200 text-sm">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>
                {r.day} ·{" "}
                <span className={r.kind === "paid" ? "text-emerald-700" : "text-amber-700"}>{r.kind === "paid" ? "Paid" : "Without pay"}</span>
                {r.note && <span className="text-gray-500"> · {r.note}</span>}
              </span>
              <button
                onClick={() => deleteLeave(r.id).then(load).catch((e) => setError(toApiError(e).detail))}
                className="text-xs text-red-600 hover:underline"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
