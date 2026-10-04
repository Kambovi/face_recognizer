import { useCallback, useEffect, useState } from "react";
import { addHoliday, addHolidaysBulk, deleteHoliday, indiaHolidayPreset, listHolidays, toApiError } from "../api/client";
import type { HolidayOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const input = "rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";
const KIND_LABEL: Record<HolidayOut["kind"], string> = {
  national: "National",
  festival: "Festival",
  optional: "Optional (take as leave)",
};

/** Company holiday calendar: a holiday is a paid day off (H) for everyone;
 *  people who work on it get the whole day as overtime (HP). */
export function Holidays(): JSX.Element {
  const { isHr } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const [rows, setRows] = useState<HolidayOut[]>([]);
  const [day, setDay] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<HolidayOut["kind"]>("festival");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const load = useCallback(() => {
    listHolidays(year).then(setRows).catch((e) => setError(toApiError(e).detail));
  }, [year]);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>): Promise<void> {
    setError(null);
    setInfo(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  const paidCount = rows.filter((r) => r.kind !== "optional").length;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-gray-900">Holidays</h1>
        <div className="flex items-center gap-2">
          <button onClick={() => setYear((y) => y - 1)} className={input} aria-label="Previous year">&lt;</button>
          <span className="w-14 text-center text-sm font-medium">{year}</span>
          <button onClick={() => setYear((y) => y + 1)} className={input} aria-label="Next year">&gt;</button>
        </div>
      </div>
      <p className="text-sm text-gray-500">
        {paidCount} paid holiday{paidCount === 1 ? "" : "s"} in {year}. Holidays are paid days off in attendance and payroll;
        working on one counts as overtime. Festival dates change every year and differ by state -- add them from your state
        government&apos;s list.
      </p>

      {isHr && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-end gap-2">
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className={input} aria-label="Date" />
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name, e.g. Diwali" className={`${input} min-w-0 flex-1`} />
            <select value={kind} onChange={(e) => setKind(e.target.value as HolidayOut["kind"])} className={input} aria-label="Kind">
              {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button
              disabled={!day || !name.trim()}
              onClick={() => void run(async () => {
                await addHoliday({ day, name: name.trim(), kind });
                setName("");
              })}
              className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
          <button
            onClick={() => void run(async () => {
              const preset = await indiaHolidayPreset(year);
              const r = await addHolidaysBulk(preset);
              setInfo(`Added ${r.saved} national holidays (26 Jan, 15 Aug, 2 Oct).`);
            })}
            className="mt-2 text-xs text-brand-700 underline"
          >
            Add the 3 national holidays for {year}
          </button>
        </div>
      )}
      {info && <p className="rounded-md bg-emerald-50 p-2 text-sm text-emerald-700">{info}</p>}
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}

      <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white shadow-sm">
        {rows.length === 0 && <li className="px-4 py-6 text-center text-sm text-gray-500">No holidays for {year} yet.</li>}
        {rows.map((h) => (
          <li key={h.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
            <span className="w-28 shrink-0 font-mono text-gray-700">{h.day} <span className="text-xs text-gray-400">{h.weekday}</span></span>
            <span className="min-w-0 flex-1 font-medium text-gray-900">{h.name}</span>
            <span className={h.kind === "optional" ? "text-xs text-gray-500" : "text-xs text-emerald-700"}>{KIND_LABEL[h.kind]}</span>
            {isHr && (
              <button onClick={() => { if (window.confirm(`Remove ${h.name}?`)) void run(() => deleteHoliday(h.id)); }} className="text-xs text-red-600 hover:underline">
                Remove
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
