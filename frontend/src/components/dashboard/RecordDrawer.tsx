import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Clock, EyeOff, Link2, Loader2, ScanFace, ShieldAlert, Trash2, UserPen, UserPlus, UserRoundX, X } from "lucide-react";
import clsx from "clsx";
import {
  createManualEvent,
  deleteUnknown,
  linkUnknown,
  listEmployees,
  manualOverrideEvent,
  promoteUnknown,
  reassignEvent,
  toApiError,
  updateEmployee,
  updateUnknown,
} from "../../api/client";
import type { EmployeeOut } from "../../api/types";
import { AuthImage } from "../AuthImage";
import { PersonFields } from "../PersonFields";
import { EMPTY_PERSON, personPayload, useCameras, type PersonValues } from "../person";
import { useProfile } from "../../profile/ProfileContext";
import { localDateTimeToIso } from "../../utils/format";
import { formatClock, formatDay, humanizeKind, type AttendanceRecord } from "./model";

// Everything an admin needs to fix a row WITHOUT leaving the dashboard:
//   unknown face  -> register as a new person / it's an existing person / ignore / delete
//   known person  -> edit details / fix IN-OUT time / "this wasn't them"
//   absent person -> edit details / mark present by hand (camera missed them)
// Each action maps 1:1 onto an existing audited backend endpoint.

type Tab =
  | "register"
  | "link"
  | "ignore"
  | "details"
  | "time"
  | "wrong"
  | "watch";

const DEFAULT_REASON = "Corrected from dashboard";

interface RecordDrawerProps {
  record: AttendanceRecord;
  onClose: () => void;
  onChanged: (message: string) => void;
}

export function RecordDrawer({ record, onClose, onChanged }: RecordDrawerProps): JSX.Element {
  const profile = useProfile();
  const isUnknown = record.category === "UNKNOWN_PRESENT";
  const isAbsent = record.category === "ABSENT";
  const tabs: { id: Tab; label: string; Icon: typeof UserPlus }[] = isUnknown
    ? [
        { id: "register", label: `New ${profile.person_label.toLowerCase()}`, Icon: UserPlus },
        { id: "link", label: `Existing ${profile.person_label.toLowerCase()}`, Icon: Link2 },
        { id: "ignore", label: "Ignore / delete", Icon: EyeOff },
        { id: "watch", label: "Watchlist", Icon: ShieldAlert },
      ]
    : [
        { id: "details", label: "Details", Icon: UserPen },
        { id: "time", label: isAbsent ? "Mark present" : "Fix time", Icon: Clock },
        ...(isAbsent ? [] : [{ id: "wrong" as Tab, label: "Wrong person", Icon: UserRoundX }]),
        { id: "watch" as Tab, label: "Watchlist", Icon: ShieldAlert },
      ];
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? "details");

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={`Edit ${record.name}`}>
      <button type="button" className="absolute inset-0 bg-gray-900/30" aria-label="Close" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        {/* header */}
        <div className="flex items-start gap-4 border-b border-gray-200 p-5">
          <AuthImage
            path={record.photo}
            alt={`${record.name} face`}
            className="h-20 w-20 shrink-0 rounded-xl object-cover ring-1 ring-gray-200"
            fallback={
              <span className="flex h-20 w-20 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-gray-400">
                <ScanFace className="h-8 w-8" aria-hidden />
              </span>
            }
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-lg font-semibold text-gray-900">{record.name}</p>
            <p className="mt-0.5 text-sm text-gray-500">
              <span className="font-mono">{record.face_id}</span>
              {record.emp_code && <> · {profile.id_label} {record.emp_code}</>}
            </p>
            <p className="mt-1 text-xs text-gray-500">
              {formatDay(record.date)} · In {formatClock(record.intime)} · Out {formatClock(record.outtime)}
              {record.kiosk_ids.length > 0 && <> · {record.kiosk_ids.join(", ")}</>}
            </p>
            {record.exceptions.length > 0 && (
              <p className="mt-1 text-xs text-amber-700">{record.exceptions.map((x) => humanizeKind(x.kind)).join(" · ")}</p>
            )}
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600" aria-label="Close">
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        {/* tabs */}
        <div role="tablist" className="flex gap-1 border-b border-gray-200 px-5">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-3 text-sm font-medium",
                tab === t.id ? "border-brand-600 text-brand-700" : "border-transparent text-gray-500 hover:text-gray-800",
              )}
            >
              <t.Icon className="h-4 w-4" aria-hidden /> {t.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {tab === "register" && <RegisterPanel record={record} onDone={onChanged} />}
          {tab === "link" && <LinkPanel record={record} onDone={onChanged} />}
          {tab === "ignore" && <IgnorePanel record={record} onDone={onChanged} />}
          {tab === "details" && <DetailsPanel record={record} onDone={onChanged} />}
          {tab === "time" && <TimePanel record={record} onDone={onChanged} />}
          {tab === "wrong" && <WrongPersonPanel record={record} onDone={onChanged} />}
          {tab === "watch" && <WatchlistPanel record={record} onDone={onChanged} />}
        </div>
      </aside>
    </div>,
    document.body,
  );
}

// ------------------------------------------------------------------ shared ---

function useSubmit(onDone: (msg: string) => void): {
  busy: boolean;
  error: string | null;
  run: (fn: () => Promise<string>) => Promise<void>;
  setError: (e: string | null) => void;
} {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(fn: () => Promise<string>): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      onDone(await fn());
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run, setError };
}

function Footer({
  busy,
  error,
  label,
  onClick,
  danger,
  disabled,
}: {
  busy: boolean;
  error: string | null;
  label: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}): JSX.Element {
  return (
    <div className="mt-6 space-y-3">
      {error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      <button
        type="button"
        onClick={onClick}
        disabled={busy || disabled}
        className={clsx(
          "inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50",
          danger ? "bg-rose-600 hover:bg-rose-700" : "bg-brand-600 hover:bg-brand-700",
        )}
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} {label}
      </button>
    </div>
  );
}

function Note({ children }: { children: ReactNode }): JSX.Element {
  return <p className="mb-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-600">{children}</p>;
}

function ReasonInput({ value, onChange }: { value: string; onChange: (v: string) => void }): JSX.Element {
  return (
    <label className="mt-4 block">
      <span className="mb-1 block text-xs font-medium text-gray-700">Note (saved in the audit log)</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      />
    </label>
  );
}

function useEmployees(): EmployeeOut[] {
  const [items, setItems] = useState<EmployeeOut[]>([]);
  useEffect(() => {
    listEmployees({ page_size: 1000, is_active: true })
      .then((r) => setItems(r.items))
      .catch(() => setItems([]));
  }, []);
  return items;
}

function EmployeePicker({
  value,
  onChange,
  exclude,
}: {
  value: string;
  onChange: (id: string) => void;
  exclude?: string;
}): JSX.Element {
  const profile = useProfile();
  const employees = useEmployees();
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return employees
      .filter((e) => e.id !== exclude)
      .filter((e) => !needle || `${e.name} ${e.emp_code} ${e.face_id} ${e.department ?? ""}`.toLowerCase().includes(needle))
      .slice(0, 50);
  }, [employees, q, exclude]);
  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={`Search ${profile.person_label_plural.toLowerCase()} by name, ${profile.id_label}…`}
        className="mb-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      />
      <ul className="max-h-64 divide-y divide-gray-100 overflow-y-auto rounded-lg border border-gray-200">
        {shown.length === 0 && <li className="p-3 text-sm text-gray-500">No match.</li>}
        {shown.map((e) => (
          <li key={e.id}>
            <button
              type="button"
              onClick={() => onChange(e.id)}
              className={clsx(
                "flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm",
                value === e.id ? "bg-brand-50" : "hover:bg-gray-50",
              )}
            >
              <span>
                <span className="font-medium text-gray-900">{e.name}</span>
                <span className="ml-2 text-xs text-gray-500">
                  {e.emp_code}
                  {e.department && ` · ${e.department}`}
                </span>
              </span>
              {value === e.id && <CheckCircle2 className="h-4 w-4 text-brand-600" aria-hidden />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------ unknown face ---

function RegisterPanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const profile = useProfile();
  const cameras = useCameras();
  const [values, setValues] = useState<PersonValues>({ ...EMPTY_PERSON, home_kiosk_id: record.kiosk_ids[0] ?? "" });
  const [consent, setConsent] = useState(false);
  const { busy, error, run, setError } = useSubmit(onDone);

  function submit(): void {
    if (!values.name.trim() || !values.emp_code.trim()) {
      setError(`Name and ${profile.id_label} are required.`);
      return;
    }
    if (!consent) {
      setError("Please confirm the person has agreed to face attendance.");
      return;
    }
    void run(async () => {
      await promoteUnknown(record.subject_id, {
        name: values.name.trim(),
        emp_code: values.emp_code.trim(),
        ...personPayload(values),
        consent: { policy_version: "v1", purpose_text: "Biometric attendance" },
        reason: "Registered from dashboard",
      });
      return `${values.name.trim()} registered — past sightings now count as their attendance.`;
    });
  }

  return (
    <>
      <Note>
        This face isn&apos;t registered yet. Fill in the details to add them as a {profile.person_label.toLowerCase()}. Their
        face photos and today&apos;s attendance move over automatically.
      </Note>
      <PersonFields value={values} onChange={setValues} cameras={cameras} />
      <label className="mt-4 flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
        The person has agreed to their face being used for attendance.
      </label>
      <Footer busy={busy} error={error} label={`Register ${profile.person_label.toLowerCase()}`} onClick={submit} />
    </>
  );
}

function LinkPanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const profile = useProfile();
  const [target, setTarget] = useState("");
  const [learn, setLearn] = useState(true);
  const { busy, error, run, setError } = useSubmit(onDone);
  function submit(): void {
    if (!target) {
      setError(`Choose the ${profile.person_label.toLowerCase()} this face belongs to.`);
      return;
    }
    void run(async () => {
      await linkUnknown(record.subject_id, { employee_id: target, reason: "Linked from dashboard", adopt_templates: learn });
      return "Linked — these sightings now count as their attendance.";
    });
  }
  return (
    <>
      <Note>Already registered, but the camera didn&apos;t recognise them? Pick who it is.</Note>
      <EmployeePicker value={target} onChange={setTarget} />
      <label className="mt-4 flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} className="mt-0.5" />
        Also learn this face angle, so they&apos;re recognised better next time (recommended)
      </label>
      <Footer busy={busy} error={error} label="Link to this person" onClick={submit} />
    </>
  );
}

function IgnorePanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const ignore = useSubmit(onDone);
  const del = useSubmit(onDone);
  const [confirm, setConfirm] = useState(false);
  return (
    <>
      <Note>
        <b>Ignore</b> hides a visitor you don&apos;t care about (delivery, guest) — they won&apos;t be asked about again.
        <br />
        <b>Delete</b> permanently removes the face data and its sightings (use for test entries).
      </Note>
      <Footer
        busy={ignore.busy}
        error={ignore.error}
        label="Ignore this visitor"
        onClick={() =>
          void ignore.run(async () => {
            await updateUnknown(record.subject_id, { status: "IGNORED" });
            return "Visitor ignored.";
          })
        }
      />
      <div className="mt-8 rounded-lg border border-rose-200 p-4">
        <label className="flex items-start gap-2 text-sm text-rose-800">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5" />
          I understand this permanently deletes this face and all its sightings.
        </label>
        <Footer
          busy={del.busy}
          error={del.error}
          danger
          disabled={!confirm}
          label="Delete permanently"
          onClick={() =>
            void del.run(async () => {
              await deleteUnknown(record.subject_id);
              return "Deleted.";
            })
          }
        />
      </div>
    </>
  );
}

function WatchlistPanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const [reason, setReason] = useState("");
  const { busy, error, run } = useSubmit(onDone);
  const isUnknown = record.category === "UNKNOWN_PRESENT";
  return (
    <>
      <Note>
        Every time {isUnknown ? "this face" : record.name} is seen by any camera, an alert pops up on the dashboard bell
        (and on WhatsApp, if set up). Use it for dismissed staff, banned visitors or anyone security must watch for.
        Remove people from the list on the Alerts page.
      </Note>
      <label className="mt-4 block text-xs font-medium text-gray-700">
        Reason (shown with every alert)
        <textarea
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Dismissed on 1 Sep, not allowed on premises"
          className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
      </label>
      <Footer
        busy={busy}
        error={error}
        danger
        disabled={reason.trim().length < 3}
        label="Add to watchlist"
        onClick={() =>
          void run(async () => {
            if (isUnknown) await updateUnknown(record.subject_id, { watchlist_reason: reason.trim() });
            else await updateEmployee(record.subject_id, { watchlist_reason: reason.trim() });
            return "Added to the watchlist.";
          })
        }
      />
    </>
  );
}

// ---------------------------------------------------------- known / absent ---

function DetailsPanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const cameras = useCameras();
  const [values, setValues] = useState<PersonValues>({
    name: record.name,
    emp_code: record.emp_code ?? "",
    department: record.department ?? "",
    designation: record.designation ?? "",
    home_kiosk_id: record.home_kiosk_id ?? "",
  });
  const [active, setActive] = useState(record.is_active !== false);
  const { busy, error, run, setError } = useSubmit(onDone);
  function submit(): void {
    if (!values.name.trim()) {
      setError("Name is required.");
      return;
    }
    void run(async () => {
      await updateEmployee(record.subject_id, { name: values.name.trim(), ...personPayload(values), is_active: active });
      return "Details saved.";
    });
  }
  return (
    <>
      <PersonFields
        value={values}
        onChange={setValues}
        show={{ emp_code: false }}
        cameras={cameras}
        currentCamera={record.home_kiosk_id}
      />
      <label className="mt-4 flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
        Active (counted in attendance; untick when someone leaves)
      </label>
      <Footer busy={busy} error={error} label="Save details" onClick={submit} />
    </>
  );
}

function TimePanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const [inTime, setInTime] = useState(record.intime ?? "");
  const [outTime, setOutTime] = useState(record.outtime ?? "");
  const [reason, setReason] = useState(record.category === "ABSENT" ? "Camera missed them" : DEFAULT_REASON);
  const { busy, error, run, setError } = useSubmit(onDone);

  function submit(): void {
    if (reason.trim().length < 3) {
      setError("Please add a short note (3+ characters).");
      return;
    }
    if (inTime && outTime && outTime <= inTime) {
      setError("OUT time must be after IN time.");
      return;
    }
    void run(async () => {
      const r = reason.trim();
      let changed = 0;
      if (inTime && inTime !== (record.intime ?? "")) {
        const at = localDateTimeToIso(record.date, inTime);
        if (record.in_event_id) await manualOverrideEvent(record.in_event_id, { occurred_at: at, reason: r });
        else await createManualEvent({ employee_id: record.subject_id, event_type: "IN", occurred_at: at, reason: r });
        changed += 1;
      }
      if (outTime && outTime !== (record.outtime ?? "")) {
        const at = localDateTimeToIso(record.date, outTime);
        if (record.out_event_id) await manualOverrideEvent(record.out_event_id, { occurred_at: at, reason: r });
        else await createManualEvent({ employee_id: record.subject_id, event_type: "OUT", occurred_at: at, reason: r });
        changed += 1;
      }
      if (changed === 0) throw new Error("Nothing changed.");
      return "Attendance time updated.";
    }).catch(() => undefined);
  }

  return (
    <>
      <Note>
        {record.category === "ABSENT"
          ? "Was this person actually here (camera off, face not captured)? Enter the times to mark them present."
          : "Correct the IN / OUT time, or add a missing OUT (e.g. they forgot to face the camera while leaving)."}{" "}
        Every change is marked as manual and kept in the audit log.
      </Note>
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-700">IN time ({formatDay(record.date)})</span>
          <input type="time" value={inTime} onChange={(e) => setInTime(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-700">OUT time</span>
          <input type="time" value={outTime} onChange={(e) => setOutTime(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        </label>
      </div>
      <ReasonInput value={reason} onChange={setReason} />
      <Footer busy={busy} error={error} label={record.category === "ABSENT" ? "Mark present" : "Save time"} onClick={submit} />
    </>
  );
}

function WrongPersonPanel({ record, onDone }: { record: AttendanceRecord; onDone: (m: string) => void }): JSX.Element {
  const profile = useProfile();
  const [mode, setMode] = useState<"other" | "unknown">("other");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("Wrong person recognised");
  const { busy, error, run, setError } = useSubmit(onDone);
  const eventIds = [record.in_event_id, record.out_event_id].filter((x): x is string => Boolean(x));

  function submit(): void {
    if (mode === "other" && !target) {
      setError(`Choose who it actually was.`);
      return;
    }
    if (eventIds.length === 0) {
      setError("No camera entries to move for this day.");
      return;
    }
    void run(async () => {
      for (const id of eventIds) {
        await reassignEvent(id, {
          target_type: mode === "other" ? "EMPLOYEE" : "NEW_UNKNOWN",
          target_id: mode === "other" ? target : null,
          reason: reason.trim() || "Wrong person recognised",
        });
      }
      return "Entry moved to the right person.";
    });
  }

  return (
    <>
      <Note>
        The camera marked <b>{record.name}</b> but it was someone else? Move today&apos;s entry to the right person.
      </Note>
      <div className="mb-4 inline-flex rounded-lg bg-gray-100 p-0.5 text-sm">
        {(["other", "unknown"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={clsx("rounded-md px-3 py-1.5 font-medium", mode === m ? "bg-white shadow-sm" : "text-gray-500")}
          >
            {m === "other" ? `Another ${profile.person_label.toLowerCase()}` : "Someone not registered"}
          </button>
        ))}
      </div>
      {mode === "other" && <EmployeePicker value={target} onChange={setTarget} exclude={record.subject_id} />}
      <ReasonInput value={reason} onChange={setReason} />
      <Footer busy={busy} error={error} label="Move entry" onClick={submit} danger />
      <p className="mt-3 flex items-center gap-1 text-xs text-gray-400">
        <Trash2 className="h-3 w-3" aria-hidden /> Nothing is deleted — the original is kept in the audit log.
      </p>
    </>
  );
}
