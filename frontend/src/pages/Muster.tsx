import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Printer, RefreshCw, Siren, UserX } from "lucide-react";
import clsx from "clsx";
import { downloadFile, getMuster, setCameraRole, toApiError } from "../api/client";
import type { CameraRole, MusterResponse } from "../api/types";
import { AuthImage } from "../components/AuthImage";
import { useAuth } from "../auth/AuthContext";
import { useProfile } from "../profile/ProfileContext";
import { formatTime } from "../utils/format";

const ROLE_LABEL: Record<CameraRole, string> = { entry: "Entry", exit: "Exit", both: "Entry + exit" };

export function Muster(): JSX.Element {
  const { user } = useAuth();
  const profile = useProfile();
  const isAdmin = user?.role === "admin";
  const [data, setData] = useState<MusterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [safe, setSafe] = useState<Set<string>>(new Set());
  const [dept, setDept] = useState("");
  const [onlyMissing, setOnlyMissing] = useState(false);

  const load = useCallback(() => {
    getMuster()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(toApiError(e).detail));
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  const inside = useMemo(() => data?.inside ?? [], [data]);
  const visitors = useMemo(() => data?.visitors_inside ?? [], [data]);
  const departments = useMemo(() => Array.from(new Set(inside.map((p) => p.department ?? "Unassigned"))).sort(), [inside]);
  const shown = inside.filter(
    (p) => (!dept || (p.department ?? "Unassigned") === dept) && (!onlyMissing || !safe.has(p.employee_id)),
  );
  const unaccounted = inside.filter((p) => !safe.has(p.employee_id)).length + visitors.filter((v) => !safe.has(v.unknown_id)).length;

  function toggle(id: string): void {
    setSafe((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function changeRole(kioskId: string, role: CameraRole): Promise<void> {
    try {
      await setCameraRole(kioskId, role);
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
            <Siren className="h-5 w-5 text-red-600" aria-hidden /> Emergency muster
          </h1>
          <p className="text-sm text-gray-500">
            Who is inside right now, from the cameras. Tick people as they reach the assembly point.
            {data && <> Updated {formatTime(data.generated_at)} · refreshes every 30 s.</>}
          </p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button onClick={load} className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm hover:bg-gray-50">
            <RefreshCw className="h-4 w-4" aria-hidden /> Refresh
          </button>
          <button onClick={() => window.print()} className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm hover:bg-gray-50">
            <Printer className="h-4 w-4" aria-hidden /> Print
          </button>
          <button
            onClick={() => void downloadFile("/muster.csv", {}, "muster.csv")}
            className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm hover:bg-gray-50"
          >
            <Download className="h-4 w-4" aria-hidden /> CSV
          </button>
        </div>
      </header>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={`${profile.person_label_plural} inside`} value={inside.length} tone="neutral" />
        <Stat label="Visitors inside" value={visitors.length} tone="neutral" />
        <Stat label="Marked safe" value={safe.size} tone="good" />
        <Stat label="Not yet accounted for" value={unaccounted} tone={unaccounted > 0 ? "bad" : "good"} />
      </div>

      {data && !data.has_exit_camera && (
        <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          No camera is marked as an exit. With one camera for both ways, anyone seen a second time counts as having left,
          so this list can miss people. For a reliable muster, put a camera on the way out and mark it Exit below.
        </p>
      )}

      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 p-3 print:hidden">
          <select className="rounded-md border border-gray-300 px-2 py-1.5 text-sm" value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">All {profile.department_label_plural.toLowerCase()}</option>
            {departments.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-sm text-gray-700">
            <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
            Only not accounted for
          </label>
          {safe.size > 0 && (
            <button onClick={() => setSafe(new Set())} className="ml-auto text-xs text-gray-500 hover:text-gray-800">
              Reset ticks
            </button>
          )}
        </div>
        {shown.length === 0 ? (
          <p className="p-6 text-center text-sm text-gray-400">{inside.length === 0 ? "Nobody is inside." : "Everyone here is accounted for."}</p>
        ) : (
          <ul className="grid grid-cols-1 divide-y divide-gray-100 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-3">
            {shown.map((p) => {
              const ok = safe.has(p.employee_id);
              return (
                <li key={p.employee_id}>
                  <button
                    onClick={() => toggle(p.employee_id)}
                    className={clsx("flex w-full items-center gap-3 p-3 text-left transition-colors", ok ? "bg-emerald-50" : "hover:bg-gray-50")}
                  >
                    <AuthImage
                      path={p.photo_url}
                      alt=""
                      className="h-11 w-11 shrink-0 rounded-full object-cover"
                      fallback={<span className="h-11 w-11 shrink-0 rounded-full bg-gray-200" />}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-gray-900">{p.name}</span>
                      <span className="block truncate text-xs text-gray-500">
                        {p.emp_code} · {p.department ?? "—"}
                        {p.contractor ? ` · ${p.contractor}` : ""}
                      </span>
                      <span className="block text-[11px] text-gray-400">
                        Last seen {formatTime(p.last_seen_at)} at {p.last_camera}
                      </span>
                    </span>
                    {ok ? (
                      <CheckCircle2 className="h-6 w-6 shrink-0 text-emerald-600" aria-label="Safe" />
                    ) : (
                      <span className="h-6 w-6 shrink-0 rounded-full border-2 border-gray-300" aria-label="Not yet safe" />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {visitors.length > 0 && (
        <section className="rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-gray-800">
            <UserX className="h-4 w-4 text-gray-500" aria-hidden /> Visitors / unidentified inside
          </h2>
          <div className="flex flex-wrap gap-3">
            {visitors.map((v) => {
              const ok = safe.has(v.unknown_id);
              return (
                <button
                  key={v.unknown_id}
                  onClick={() => toggle(v.unknown_id)}
                  className={clsx("flex w-36 flex-col items-center rounded-lg border p-2 text-center", ok ? "border-emerald-300 bg-emerald-50" : "border-gray-200")}
                >
                  <AuthImage path={v.photo_url} alt="" className="h-20 w-20 rounded-md object-cover" fallback={<span className="h-20 w-20 rounded-md bg-gray-200" />} />
                  <span className="mt-1 text-xs font-medium text-gray-800">{v.label ?? v.face_id}</span>
                  <span className="text-[11px] text-gray-400">
                    {formatTime(v.last_seen_at)} · {v.last_camera}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {isAdmin && data && data.cameras.length > 0 && (
        <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm print:hidden">
          <h2 className="text-sm font-semibold text-gray-800">Camera directions</h2>
          <p className="mb-3 text-xs text-gray-500">Tell the system which way people walk past each camera.</p>
          <ul className="divide-y divide-gray-100">
            {data.cameras.map((c) => (
              <li key={c.kiosk_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="font-medium text-gray-800">{c.kiosk_id}</span>
                <select
                  value={c.role}
                  onChange={(e) => void changeRole(c.kiosk_id, e.target.value as CameraRole)}
                  className="rounded-md border border-gray-300 px-2 py-1 text-sm"
                >
                  {(Object.keys(ROLE_LABEL) as CameraRole[]).map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </select>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "neutral" | "good" | "bad" }): JSX.Element {
  return (
    <div
      className={clsx(
        "rounded-xl border p-4",
        tone === "bad" ? "border-red-200 bg-red-50" : tone === "good" ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-white",
      )}
    >
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={clsx("mt-1 text-3xl font-semibold tabular-nums", tone === "bad" ? "text-red-700" : tone === "good" ? "text-emerald-700" : "text-gray-900")}>
        {value}
      </p>
    </div>
  );
}
