import { useEffect, useState } from "react";
import { Bell, Building, Copy, Plus, Trash2, Video, Wifi, WifiOff } from "lucide-react";
import clsx from "clsx";
import { createSite, deleteSite, getHqLink, listSites, setHqLink, testHqLink, toApiError } from "../api/client";
import type { HqLink, SiteOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../utils/format";

const STALE_MINUTES = 15;
const input =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

function minutesAgo(iso: string | null): number | null {
  if (!iso) return null;
  return Math.round((Date.now() - new Date(iso).getTime()) / 60000);
}

export function Sites(): JSX.Element {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [sites, setSites] = useState<SiteOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [created, setCreated] = useState<SiteOut | null>(null);

  const load = (): void => {
    listSites()
      .then(setSites)
      .catch((e) => setError(toApiError(e).detail));
  };
  useEffect(() => {
    load();
    const t = window.setInterval(load, 60_000);
    return () => window.clearInterval(t);
  }, []);

  const totals = sites.reduce(
    (acc, s) => {
      const snap = s.snapshot ?? {};
      acc.roster += snap.roster ?? 0;
      acc.present += snap.present ?? 0;
      acc.late += snap.late ?? 0;
      acc.inside += snap.inside_now ?? 0;
      acc.alerts += snap.open_alerts ?? 0;
      return acc;
    },
    { roster: 0, present: 0, late: 0, inside: 0, alerts: 0 },
  );

  async function add(): Promise<void> {
    try {
      const s = await createSite(newName.trim());
      setCreated(s);
      setNewName("");
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">All sites</h1>
        <p className="text-sm text-gray-500">
          Every factory / branch in one place. Each site keeps running on its own; it sends only today&apos;s counts here
          every 5 minutes.
        </p>
      </header>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {sites.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Total label="Sites" value={sites.length} />
          <Total label="Present now" value={`${totals.present} / ${totals.roster}`} />
          <Total label="Late today" value={totals.late} />
          <Total label="Inside now" value={totals.inside} />
          <Total label="Open alerts" value={totals.alerts} bad={totals.alerts > 0} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {sites.map((s) => {
          const snap = s.snapshot ?? {};
          const ago = minutesAgo(s.last_push_at);
          const stale = ago === null || ago > STALE_MINUTES;
          const pct = snap.roster ? Math.round(((snap.present ?? 0) / snap.roster) * 100) : 0;
          return (
            <div key={s.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="flex items-center gap-1.5 truncate font-semibold text-gray-900">
                    <Building className="h-4 w-4 shrink-0 text-gray-400" aria-hidden /> {s.name}
                  </p>
                  <p className={clsx("mt-0.5 flex items-center gap-1 text-xs", stale ? "text-red-600" : "text-gray-500")}>
                    {stale ? <WifiOff className="h-3.5 w-3.5" /> : <Wifi className="h-3.5 w-3.5" />}
                    {ago === null ? "Never reported" : stale ? `No update for ${ago} min` : `Updated ${ago} min ago`}
                  </p>
                </div>
                {isAdmin && (
                  <button
                    aria-label={`Remove ${s.name}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${s.name}? It will stop showing here.`)) void deleteSite(s.id).then(load);
                    }}
                    className="text-gray-300 hover:text-red-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              <p className="mt-3 text-3xl font-semibold tracking-tight text-gray-900">
                {snap.present ?? 0}
                <span className="text-lg font-normal text-gray-400"> / {snap.roster ?? 0} present</span>
              </p>
              <div className="mt-2 h-1.5 rounded-full bg-gray-100">
                <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <Mini label="Late" value={snap.late ?? 0} />
                <Mini label="Inside now" value={snap.inside_now ?? 0} />
                <Mini label="Visitors" value={snap.unknown_visitors ?? 0} />
              </dl>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
                    (snap.cameras_online ?? 0) < (snap.cameras_total ?? 0) ? "bg-amber-50 text-amber-800" : "bg-gray-100 text-gray-700",
                  )}
                >
                  <Video className="h-3.5 w-3.5" /> {snap.cameras_online ?? 0}/{snap.cameras_total ?? 0} cameras online
                </span>
                {(snap.open_alerts ?? 0) > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-red-700">
                    <Bell className="h-3.5 w-3.5" /> {snap.open_alerts} open alerts
                  </span>
                )}
                {(snap.cameras_liveness_off ?? 0) > 0 && (
                  <span className="rounded-full bg-red-50 px-2 py-0.5 text-red-700">Anti-spoofing off on {snap.cameras_liveness_off}</span>
                )}
              </div>
            </div>
          );
        })}
        {sites.length === 0 && (
          <div className="rounded-xl border border-dashed border-gray-300 p-6 text-sm text-gray-500 md:col-span-2 xl:col-span-3">
            No other sites report here yet. If this is the head-office dashboard, add each factory / branch below and enter the
            token at that site. If this install IS a site, connect it to head office in the box at the bottom.
          </div>
        )}
      </div>

      {isAdmin && (
        <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-800">Add a site (head office)</h2>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <input className={input} placeholder="e.g. Plant 2 — Chakan" value={newName} onChange={(e) => setNewName(e.target.value)} />
            <button
              disabled={!newName.trim()}
              onClick={() => void add()}
              className="inline-flex shrink-0 items-center justify-center gap-1 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" aria-hidden /> Add site
            </button>
          </div>
          {created?.token && (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
              <p className="font-medium text-amber-900">Token for {created.name} (shown only once — copy it now)</p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded bg-white px-2 py-1 font-mono text-xs">{created.token}</code>
                <button
                  onClick={() => void navigator.clipboard?.writeText(created.token ?? "")}
                  className="rounded-md border border-amber-300 bg-white p-1.5"
                  aria-label="Copy token"
                >
                  <Copy className="h-4 w-4" />
                </button>
              </div>
              <p className="mt-2 text-xs text-amber-900">
                At that site: Sites → Connect to head office → paste this page&apos;s address and the token.
              </p>
            </div>
          )}
        </section>
      )}

      {isAdmin && <HqLinkBox />}
    </div>
  );
}

function HqLinkBox(): JSX.Element {
  const [link, setLink] = useState<HqLink | null>(null);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    getHqLink()
      .then((l) => {
        setLink(l);
        setUrl(l.url);
      })
      .catch(() => setLink(null));
  }, []);

  async function save(): Promise<void> {
    try {
      const l = await setHqLink(url, token);
      setLink(l);
      setToken("");
      if (l.url) {
        const r = await testHqLink();
        setMsg(r.pushed ? "Connected: head office received this site's numbers." : `Could not reach head office: ${r.reason ?? ""}`);
        setLink(await getHqLink());
      } else setMsg("Disconnected from head office.");
    } catch (e) {
      setMsg(toApiError(e).detail);
    }
  }

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-800">Connect this site to head office</h2>
      <p className="text-xs text-gray-500">Only counts are sent (present, late, cameras online, alerts) — never photos or names.</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <input className={input} placeholder="Head-office address, e.g. https://hq.example.com" value={url} onChange={(e) => setUrl(e.target.value)} />
        <input
          className={input}
          placeholder={link?.token_set ? "Token saved (leave blank to keep)" : "Site token from head office"}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button onClick={() => void save()} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
          Save &amp; test
        </button>
        {link?.last_push_at && <span className="text-xs text-gray-500">Last sent {formatDateTime(link.last_push_at)}</span>}
        {link?.last_error && <span className="text-xs text-red-600">Last error: {link.last_error}</span>}
      </div>
      {msg && <p className="mt-2 text-sm text-gray-700">{msg}</p>}
    </section>
  );
}

function Total({ label, value, bad }: { label: string; value: number | string; bad?: boolean }): JSX.Element {
  return (
    <div className={clsx("rounded-xl border p-3", bad ? "border-red-200 bg-red-50" : "border-gray-200 bg-white")}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={clsx("mt-0.5 text-2xl font-semibold tabular-nums", bad ? "text-red-700" : "text-gray-900")}>{value}</p>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: number }): JSX.Element {
  return (
    <div className="rounded-lg bg-gray-50 py-1.5">
      <dd className="text-base font-semibold tabular-nums text-gray-900">{value}</dd>
      <dt className="text-[11px] text-gray-500">{label}</dt>
    </div>
  );
}
