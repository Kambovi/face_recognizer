import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { Copy, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import {
  addDevice,
  createUser,
  deleteDevice,
  deleteUser,
  listAudit,
  listDevices,
  listUsers,
  resetUserPassword,
  rotateDevice,
  toApiError,
  updateDevice,
  updateUser,
} from "../api/client";
import type { AuditRow, DeviceOut, UserOut, UserRole } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const input = "rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";
const btn = "rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50";
const ROLE_HELP: Record<UserRole, string> = {
  admin: "everything, incl. settings, users, cameras",
  hr: "people, leave, holidays, attendance fixes, payroll",
  viewer: "read-only dashboards and reports, no salaries",
};

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleString() : "never";
}

/** A secret shown exactly once (temporary password / camera token). */
function OneTimeSecret({ label, value, onClose }: { label: string; value: string; onClose: () => void }): JSX.Element {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
      <p className="font-medium text-amber-900">{label} -- shown only now, copy it:</p>
      <div className="mt-2 flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-white px-2 py-1 font-mono text-xs">{value}</code>
        <button
          onClick={() => void navigator.clipboard?.writeText(value).then(() => setCopied(true))}
          className="inline-flex items-center gap-1 rounded-md border border-amber-400 px-2 py-1 text-xs"
        >
          <Copy className="h-3.5 w-3.5" aria-hidden /> {copied ? "Copied" : "Copy"}
        </button>
        <button onClick={onClose} className="text-xs text-amber-900 underline">Done</button>
      </div>
    </div>
  );
}

function Users(): JSX.Element {
  const { user: me } = useAuth();
  const [rows, setRows] = useState<UserOut[]>([]);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>("hr");
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listUsers().then(setRows).catch((e) => setError(toApiError(e).detail));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>): Promise<void> {
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-gray-900">Add a login</h2>
        <div className="flex flex-wrap items-end gap-2">
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email@company.com" type="email" className={`${input} w-64`} />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" className={`${input} w-48`} />
          <select value={role} onChange={(e) => setRole(e.target.value as UserRole)} className={input} aria-label="Role">
            <option value="hr">HR</option>
            <option value="viewer">Viewer</option>
            <option value="admin">Admin</option>
          </select>
          <button
            className={btn}
            disabled={!email.includes("@")}
            onClick={() =>
              void run(async () => {
                const u = await createUser({ email: email.trim(), name: name.trim() || null, role });
                setSecret({ label: `Temporary password for ${u.email}`, value: u.temporary_password ?? "" });
                setEmail("");
                setName("");
              })
            }
          >
            Add
          </button>
        </div>
        <p className="mt-2 text-xs text-gray-500">{role.toUpperCase()}: {ROLE_HELP[role]}. They must set their own password at first sign-in.</p>
      </div>
      {secret && <OneTimeSecret label={secret.label} value={secret.value} onClose={() => setSecret(null)} />}
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">Login</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Last sign-in</th><th className="px-3 py-2" /></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((u) => (
              <tr key={u.id}>
                <td className="px-3 py-2"><div className="font-medium text-gray-900">{u.email}</div><div className="text-xs text-gray-500">{u.name}</div></td>
                <td className="px-3 py-2">
                  <select value={u.role} disabled={u.email === me?.email} onChange={(e) => void run(() => updateUser(u.id, { role: e.target.value as UserRole }))} className={input} aria-label={`Role of ${u.email}`}>
                    <option value="admin">Admin</option><option value="hr">HR</option><option value="viewer">Viewer</option>
                  </select>
                </td>
                <td className="px-3 py-2 text-xs">
                  <span className={clsx("rounded px-1.5 py-0.5", u.is_active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500")}>{u.is_active ? "Active" : "Disabled"}</span>
                  {u.locked && <span className="ml-1 rounded bg-red-50 px-1.5 py-0.5 text-red-700">Locked</span>}
                  {u.must_change_password && <span className="ml-1 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">Temp. password</span>}
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{fmt(u.last_login_at)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {u.email !== me?.email && (
                    <>
                      <button onClick={() => void run(() => updateUser(u.id, { is_active: !u.is_active }))} className="mr-3 text-xs text-gray-600 hover:underline">
                        {u.is_active ? "Disable" : "Enable"}
                      </button>
                      <button
                        onClick={() => void run(async () => {
                          const r = await resetUserPassword(u.id);
                          setSecret({ label: `New temporary password for ${r.email}`, value: r.temporary_password ?? "" });
                        })}
                        className="mr-3 inline-flex items-center gap-1 text-xs text-gray-600 hover:underline"
                      >
                        <KeyRound className="h-3.5 w-3.5" aria-hidden /> Reset password
                      </button>
                      <button onClick={() => { if (window.confirm(`Delete login ${u.email}?`)) void run(() => deleteUser(u.id)); }} className="text-xs text-red-600 hover:underline">
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cameras(): JSX.Element {
  const [rows, setRows] = useState<DeviceOut[]>([]);
  const [kioskId, setKioskId] = useState("");
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    listDevices().then(setRows).catch((e) => setError(toApiError(e).detail));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>): Promise<void> {
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="mb-1 text-sm font-semibold text-gray-900">Register a camera</h2>
        <p className="mb-3 text-xs text-gray-500">
          Each camera gets its own token. Put it in that camera PC&apos;s kiosk settings as KIOSK_SERVICE_TOKEN with the same KIOSK_ID.
          A token only works for its own camera; rotate it if a PC is lost.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <input value={kioskId} onChange={(e) => setKioskId(e.target.value)} placeholder="Camera ID, e.g. main-gate" className={`${input} w-56`} />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (optional)" className={`${input} w-48`} />
          <button
            className={btn}
            disabled={!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(kioskId)}
            onClick={() => void run(async () => {
              const d = await addDevice(kioskId.trim(), name.trim() || null);
              setSecret({ label: `Token for camera ${d.kiosk_id}`, value: d.token ?? "" });
              setKioskId("");
              setName("");
            })}
          >
            Add camera
          </button>
        </div>
      </div>
      {secret && <OneTimeSecret label={secret.label} value={secret.value} onClose={() => setSecret(null)} />}
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">Camera</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Last seen</th><th className="px-3 py-2" /></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-4 text-center text-sm text-gray-500">No cameras registered yet -- cameras still use the shared token.</td></tr>}
            {rows.map((d) => (
              <tr key={d.id}>
                <td className="px-3 py-2"><div className="font-mono text-gray-900">{d.kiosk_id}</div><div className="text-xs text-gray-500">{d.name}</div></td>
                <td className="px-3 py-2 text-xs">
                  <span className={clsx("rounded px-1.5 py-0.5", d.enabled ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500")}>{d.enabled ? "Enabled" : "Disabled"}</span>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{fmt(d.last_used_at)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  <button onClick={() => void run(() => updateDevice(d.id, { enabled: !d.enabled }))} className="mr-3 text-xs text-gray-600 hover:underline">
                    {d.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    onClick={() => void run(async () => {
                      if (!window.confirm(`New token for ${d.kiosk_id}? The old one stops working immediately.`)) return;
                      const r = await rotateDevice(d.id);
                      setSecret({ label: `New token for camera ${r.kiosk_id}`, value: r.token ?? "" });
                    })}
                    className="mr-3 inline-flex items-center gap-1 text-xs text-gray-600 hover:underline"
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden /> New token
                  </button>
                  <button onClick={() => { if (window.confirm(`Remove camera ${d.kiosk_id}?`)) void run(() => deleteDevice(d.id)); }} className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline">
                    <Trash2 className="h-3.5 w-3.5" aria-hidden /> Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Audit(): JSX.Element {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [entity, setEntity] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    listAudit({ entity: entity || undefined, limit: 300 }).then(setRows).catch((e) => setError(toApiError(e).detail));
  }, [entity]);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <select value={entity} onChange={(e) => setEntity(e.target.value)} className={input} aria-label="Filter">
          <option value="">Everything</option>
          <option value="employee">People</option>
          <option value="attendance_event">Attendance fixes</option>
          <option value="payroll">Payroll</option>
          <option value="user">Logins</option>
          <option value="settings">Settings</option>
          <option value="camera">Cameras</option>
          <option value="holiday">Holidays</option>
        </select>
        <span className="text-xs text-gray-500">Latest 300 changes</span>
      </div>
      {error && <p className="rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Who</th><th className="px-3 py-2">What</th><th className="px-3 py-2">Details</th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((a) => (
              <tr key={a.id} className="align-top">
                <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{new Date(a.at).toLocaleString()}</td>
                <td className="px-3 py-2 text-xs">{a.actor}</td>
                <td className="px-3 py-2 text-xs"><span className="font-medium">{a.action}</span> <span className="text-gray-500">{a.entity}</span></td>
                <td className="max-w-md px-3 py-2"><code className="block truncate text-[11px] text-gray-600" title={JSON.stringify(a.after ?? a.before)}>{JSON.stringify(a.after ?? a.before ?? {})}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const TABS = [
  { key: "users", label: "Logins" },
  { key: "cameras", label: "Cameras" },
  { key: "audit", label: "Audit log" },
] as const;

export function Admin(): JSX.Element {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("users");
  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">Admin</h1>
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={clsx("-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-gray-500 hover:text-gray-800")}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === "users" && <Users />}
      {tab === "cameras" && <Cameras />}
      {tab === "audit" && <Audit />}
    </div>
  );
}
