import { useEffect, useMemo, useState } from "react";
import { Moon, Plus, Sun, Trash2 } from "lucide-react";
import clsx from "clsx";
import {
  assignRoster,
  createShift,
  deleteRosterRow,
  deleteShift,
  listEmployees,
  listRoster,
  listShifts,
  toApiError,
  updateShift,
} from "../api/client";
import type { EmployeeOut, RosterRow, ShiftOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useProfile } from "../profile/ProfileContext";
import { todayIsoDate } from "../utils/format";

const input =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

function isNight(s: ShiftOut): boolean {
  return s.out_time <= s.in_time;
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`); // UTC: no timezone day-shift
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function Shifts(): JSX.Element {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "hr"; // HR may edit people + attendance too
  const [shifts, setShifts] = useState<ShiftOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const reload = (): void => {
    listShifts()
      .then(setShifts)
      .catch((e) => setError(toApiError(e).detail));
  };
  useEffect(reload, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">Shifts &amp; roster</h1>
        <p className="text-sm text-gray-500">
          Shift timings decide late marks and overtime. Use the roster for rotating or night shifts.
        </p>
      </header>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {notice && <p className="rounded-md bg-green-50 p-3 text-sm text-green-700">{notice}</p>}

      <ShiftList shifts={shifts} isAdmin={isAdmin} onChanged={reload} onError={setError} />
      <Roster shifts={shifts} isAdmin={isAdmin} onError={setError} onNotice={setNotice} />
    </div>
  );
}

// ---------------------------------------------------------------- shifts
function ShiftList({
  shifts,
  isAdmin,
  onChanged,
  onError,
}: {
  shifts: ShiftOut[];
  isAdmin: boolean;
  onChanged: () => void;
  onError: (m: string | null) => void;
}): JSX.Element {
  const [editing, setEditing] = useState<ShiftOut | "new" | null>(null);

  async function remove(s: ShiftOut): Promise<void> {
    if (!window.confirm(`Delete shift "${s.name}"? People on it fall back to the default shift.`)) return;
    try {
      await deleteShift(s.id);
      onChanged();
    } catch (e) {
      onError(toApiError(e).detail);
    }
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-800">Shifts</h2>
        {isAdmin && (
          <button
            onClick={() => setEditing("new")}
            className="inline-flex items-center gap-1 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
          >
            <Plus className="h-4 w-4" aria-hidden /> Add shift
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shifts.map((s) => (
          <div key={s.id} className="rounded-lg border border-gray-200 p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="flex items-center gap-2 font-medium text-gray-900">
                {isNight(s) ? (
                  <Moon className="h-4 w-4 text-indigo-500" aria-label="Night shift" />
                ) : (
                  <Sun className="h-4 w-4 text-amber-500" aria-label="Day shift" />
                )}
                {s.name}
              </span>
              {s.is_default && <span className="rounded bg-brand-50 px-1.5 py-0.5 text-[11px] font-medium text-brand-700">Default</span>}
            </div>
            <p className="mt-1 text-2xl font-semibold tracking-tight text-gray-900">
              {s.in_time} <span className="text-gray-400">→</span> {s.out_time}
            </p>
            <p className="text-xs text-gray-500">
              {s.grace_minutes} min grace{isNight(s) ? " · ends next morning" : ""}
            </p>
            {isAdmin && (
              <div className="mt-2 flex gap-2 text-xs">
                <button onClick={() => setEditing(s)} className="font-medium text-brand-700 hover:underline">
                  Edit
                </button>
                {!s.is_default && (
                  <button onClick={() => void remove(s)} className="font-medium text-red-600 hover:underline">
                    Delete
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      {editing && (
        <ShiftForm
          shift={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onChanged();
          }}
        />
      )}
    </section>
  );
}

function ShiftForm({ shift, onClose, onSaved }: { shift: ShiftOut | null; onClose: () => void; onSaved: () => void }): JSX.Element {
  const [name, setName] = useState(shift?.name ?? "");
  const [inTime, setInTime] = useState(shift?.in_time ?? "09:00");
  const [outTime, setOutTime] = useState(shift?.out_time ?? "18:00");
  const [grace, setGrace] = useState(shift?.grace_minutes ?? 15);
  const [isDefault, setIsDefault] = useState(shift?.is_default ?? false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function save(): Promise<void> {
    setBusy(true);
    setErr(null);
    const payload = { name: name.trim(), in_time: inTime, out_time: outTime, grace_minutes: grace, is_default: isDefault };
    try {
      if (shift) await updateShift(shift.id, payload);
      else await createShift(payload);
      onSaved();
    } catch (e) {
      setErr(toApiError(e).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-brand-200 bg-brand-50/40 p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-800">{shift ? `Edit ${shift.name}` : "New shift"}</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="col-span-2 block text-xs font-medium text-gray-700 sm:col-span-1">
          Name
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Night" />
        </label>
        <label className="block text-xs font-medium text-gray-700">
          Starts
          <input type="time" className={input} value={inTime} onChange={(e) => setInTime(e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-gray-700">
          Ends
          <input type="time" className={input} value={outTime} onChange={(e) => setOutTime(e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-gray-700">
          Grace (min)
          <input type="number" min={0} className={input} value={grace} onChange={(e) => setGrace(Number(e.target.value))} />
        </label>
      </div>
      {outTime <= inTime && <p className="mt-2 text-xs text-indigo-700">Ends the next morning (night shift).</p>}
      <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        Default shift (for people without a shift or roster entry)
      </label>
      {err && <p className="mt-2 text-sm text-red-700">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button
          disabled={busy || !name.trim()}
          onClick={() => void save()}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {busy ? "Saving..." : "Save"}
        </button>
        <button onClick={onClose} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-white">
          Cancel
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- roster
function Roster({
  shifts,
  isAdmin,
  onError,
  onNotice,
}: {
  shifts: ShiftOut[];
  isAdmin: boolean;
  onError: (m: string | null) => void;
  onNotice: (m: string | null) => void;
}): JSX.Element {
  const profile = useProfile();
  const today = todayIsoDate();
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(addDays(today, 6));
  const [rows, setRows] = useState<RosterRow[]>([]);
  const [people, setPeople] = useState<EmployeeOut[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [dept, setDept] = useState("");
  const [shiftId, setShiftId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = (): void => {
    listRoster(from, to)
      .then(setRows)
      .catch((e) => onError(toApiError(e).detail));
  };
  useEffect(load, [from, to]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    listEmployees({ is_active: true, page_size: 5000 })
      .then((r) => setPeople(r.items))
      .catch(() => setPeople([]));
  }, []);

  const departments = useMemo(() => Array.from(new Set(people.map((p) => p.department).filter(Boolean))) as string[], [people]);
  const visible = people.filter(
    (p) =>
      (!dept || p.department === dept) &&
      (!search || `${p.name} ${p.emp_code}`.toLowerCase().includes(search.toLowerCase())),
  );

  async function assign(): Promise<void> {
    setBusy(true);
    onError(null);
    try {
      const r = await assignRoster({ employee_ids: Array.from(picked), shift_id: shiftId, start_date: from, end_date: to });
      onNotice(`Shift assigned to ${r.assigned} ${profile.person_label_plural.toLowerCase()} for ${from} → ${to}.`);
      setPicked(new Set());
      load();
    } catch (e) {
      onError(toApiError(e).detail);
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string): void {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-800">Roster</h2>
      <p className="mb-3 text-xs text-gray-500">
        Pick dates, people and a shift. It replaces whatever they had on those dates. Everyone else uses their own shift, or
        the default.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="block text-xs font-medium text-gray-700">
          From
          <input type="date" className={input} value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="block text-xs font-medium text-gray-700">
          To
          <input type="date" className={input} value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </label>
        {isAdmin && (
          <label className="col-span-2 block text-xs font-medium text-gray-700">
            Shift
            <select className={input} value={shiftId} onChange={(e) => setShiftId(e.target.value)}>
              <option value="">— Choose shift —</option>
              {shifts.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.in_time}–{s.out_time})
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {isAdmin && (
        <div className="mt-4 rounded-lg border border-gray-200">
          <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 bg-gray-50 p-2">
            <input
              className="min-w-[10rem] flex-1 rounded-md border border-gray-300 px-2 py-1 text-sm"
              placeholder={`Search ${profile.person_label_plural.toLowerCase()}`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select className="rounded-md border border-gray-300 px-2 py-1 text-sm" value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">All {profile.department_label_plural.toLowerCase()}</option>
              {departments.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
            <button
              className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs"
              onClick={() => setPicked(new Set([...picked, ...visible.map((p) => p.id)]))}
            >
              Select all shown
            </button>
            <button className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs" onClick={() => setPicked(new Set())}>
              Clear
            </button>
            <span className="text-xs text-gray-500">{picked.size} selected</span>
          </div>
          <ul className="max-h-60 divide-y divide-gray-100 overflow-y-auto">
            {visible.map((p) => (
              <li key={p.id}>
                <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50">
                  <input type="checkbox" checked={picked.has(p.id)} onChange={() => toggle(p.id)} />
                  <span className="font-medium text-gray-800">{p.name}</span>
                  <span className="text-gray-400">{p.emp_code}</span>
                  <span className="ml-auto text-xs text-gray-400">{p.department ?? ""}</span>
                </label>
              </li>
            ))}
            {visible.length === 0 && <li className="px-3 py-4 text-center text-sm text-gray-400">Nobody matches.</li>}
          </ul>
          <div className="border-t border-gray-200 p-2">
            <button
              disabled={busy || !shiftId || picked.size === 0 || to < from}
              onClick={() => void assign()}
              className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {busy ? "Assigning..." : `Assign shift to ${picked.size}`}
            </button>
          </div>
        </div>
      )}

      <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-gray-500">Rostered in this range</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-400">No roster entries. Everyone works their own shift.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="py-1.5 pr-3">{profile.person_label}</th>
                <th className="py-1.5 pr-3">Shift</th>
                <th className="py-1.5 pr-3">Dates</th>
                {isAdmin && <th />}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="py-1.5 pr-3">
                    {r.name} <span className="text-gray-400">{r.emp_code}</span>
                  </td>
                  <td className={clsx("py-1.5 pr-3", shifts.find((s) => s.id === r.shift_id && isNight(s)) && "text-indigo-700")}>
                    {r.shift_name}
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums">
                    {r.start_date} → {r.end_date}
                  </td>
                  {isAdmin && (
                    <td className="py-1.5 text-right">
                      <button
                        aria-label="Remove roster entry"
                        onClick={() =>
                          void deleteRosterRow(r.id)
                            .then(load)
                            .catch((e) => onError(toApiError(e).detail))
                        }
                        className="text-gray-400 hover:text-red-600"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
