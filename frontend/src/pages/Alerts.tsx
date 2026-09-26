import { useEffect, useState } from "react";
import { ShieldAlert, Smartphone } from "lucide-react";
import clsx from "clsx";
import { ackAlert, getWatchlist, listAlerts, toApiError, updateEmployee, updateUnknown } from "../api/client";
import type { AlertOut, WatchlistEntry } from "../api/types";
import { AuthImage } from "../components/AuthImage";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../utils/format";

export function Alerts(): JSX.Element {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [alerts, setAlerts] = useState<AlertOut[]>([]);
  const [watch, setWatch] = useState<WatchlistEntry[]>([]);
  const [openOnly, setOpenOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = (): void => {
    listAlerts(openOnly, 200)
      .then(setAlerts)
      .catch((e) => setError(toApiError(e).detail));
    getWatchlist()
      .then(setWatch)
      .catch(() => setWatch([]));
  };
  useEffect(load, [openOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  async function unwatch(w: WatchlistEntry): Promise<void> {
    try {
      if (w.type === "person") await updateEmployee(w.id, { watchlist_reason: "" });
      else await updateUnknown(w.id, { watchlist_reason: "" });
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">Alerts &amp; watchlist</h1>
        <p className="text-sm text-gray-500">
          An alert is raised when someone on the watchlist is seen, or when a photo / phone screen is held up to a camera.
        </p>
      </header>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-800">Watchlist ({watch.length})</h2>
          <span className="text-xs text-gray-500">Add people from their profile, or faces from the dashboard drawer.</span>
        </div>
        {watch.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400">Nobody is on the watchlist.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {watch.map((w) => (
              <li key={`${w.type}-${w.id}`} className="flex items-center gap-3 px-4 py-2.5">
                <AuthImage path={w.photo_url} alt="" className="h-9 w-9 rounded-md object-cover" fallback={<span className="h-9 w-9 rounded-md bg-gray-200" />} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">
                    {w.name} <span className="text-gray-400">{w.code}</span>
                    {w.type === "face" && <span className="ml-1 rounded bg-gray-100 px-1 text-[10px] text-gray-600">unregistered face</span>}
                  </p>
                  <p className="truncate text-xs text-gray-500">{w.reason}</p>
                </div>
                {isAdmin && (
                  <button onClick={() => void unwatch(w)} className="text-xs font-medium text-gray-500 hover:text-red-600">
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-800">Alert history</h2>
          <label className="flex items-center gap-1.5 text-sm text-gray-600">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> Open only
          </label>
        </div>
        {alerts.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400">No alerts.</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {alerts.map((a) => (
              <li key={a.id} className={clsx("flex items-center gap-3 px-4 py-2.5", !a.acknowledged_at && "bg-red-50/40")}>
                <AuthImage
                  path={a.photo_url}
                  alt=""
                  className="h-10 w-10 rounded-md object-cover"
                  fallback={
                    <span className="flex h-10 w-10 items-center justify-center rounded-md bg-red-50 text-red-600">
                      {a.kind === "spoof" ? <Smartphone className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}
                    </span>
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">{a.title}</p>
                  <p className="truncate text-xs text-gray-500">
                    {formatDateTime(a.created_at)}
                    {a.detail ? ` · ${a.detail}` : ""}
                  </p>
                </div>
                {a.acknowledged_at ? (
                  <span className="text-xs text-gray-400">Seen by {a.acknowledged_by}</span>
                ) : (
                  <button
                    onClick={() => void ackAlert(a.id).then(load)}
                    className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-white"
                  >
                    Acknowledge
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
