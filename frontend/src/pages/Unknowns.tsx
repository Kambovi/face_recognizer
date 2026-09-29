import { useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "../components/DataTable";
import { AuthImage } from "../components/AuthImage";
import { PersonFields } from "../components/PersonFields";
import { EMPTY_PERSON, personPayload, useCameras, type PersonValues } from "../components/person";
import { useProfile } from "../profile/ProfileContext";
import {
  deleteUnknown,
  linkUnknown,
  listEmployees,
  listUnknownTemplates,
  listUnknowns,
  promoteUnknown,
  splitUnknown,
  toApiError,
  updateUnknown,
} from "../api/client";
import type { EmployeeOut, FaceTemplateOut, UnknownIdentityOut } from "../api/types";
import { formatDateTime } from "../utils/format";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "OPEN", label: "Open" },
  { value: "LINKED", label: "Linked" },
  { value: "PROMOTED", label: "Promoted" },
  { value: "IGNORED", label: "Ignored" },
];

function LinkModal({
  unknown,
  onClose,
  onDone,
}: {
  unknown: UnknownIdentityOut;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const [employees, setEmployees] = useState<EmployeeOut[]>([]);
  const [employeeId, setEmployeeId] = useState("");
  const [adoptTemplates, setAdoptTemplates] = useState(true);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listEmployees({ page_size: 200 }).then((res) => setEmployees(res.items)).catch(() => setEmployees([]));
  }, []);

  async function handleSubmit(): Promise<void> {
    if (!employeeId) {
      setError("Choose an employee.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Reason must be at least 3 characters.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await linkUnknown(unknown.id, { employee_id: employeeId, reason, adopt_templates: adoptTemplates });
      onDone();
      onClose();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title={`Link ${unknown.face_id} to an employee`} onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">Employee</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
            <option value="">Select an employee...</option>
            {employees.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.face_id} &mdash; {emp.name}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input type="checkbox" checked={adoptTemplates} onChange={(e) => setAdoptTemplates(e.target.checked)} />
          Adopt this identity's face templates into the employee's profile
        </label>
        <ReasonField value={reason} onChange={setReason} />
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
      <ModalActions onCancel={onClose} onConfirm={handleSubmit} confirmLabel="Link" submitting={submitting} />
    </ModalShell>
  );
}

function PromoteModal({
  unknown,
  onClose,
  onDone,
}: {
  unknown: UnknownIdentityOut;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const profile = useProfile();
  const cameras = useCameras();
  const [values, setValues] = useState<PersonValues>(EMPTY_PERSON);
  const [policyVersion, setPolicyVersion] = useState("v1");
  const [purposeText, setPurposeText] = useState("Biometric attendance enrollment");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(): Promise<void> {
    if (!values.name.trim() || !values.emp_code.trim()) {
      setError(`Name and ${profile.id_label} are required.`);
      return;
    }
    if (reason.trim().length < 3) {
      setError("Reason must be at least 3 characters.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await promoteUnknown(unknown.id, {
        name: values.name.trim(),
        emp_code: values.emp_code.trim(),
        ...personPayload(values),
        consent: { policy_version: policyVersion, purpose_text: purposeText },
        reason,
      });
      onDone();
      onClose();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title={`Register ${unknown.face_id} as a new ${profile.person_label.toLowerCase()}`} onClose={onClose}>
      <div className="space-y-3">
        <PersonFields value={values} onChange={setValues} cameras={cameras} />
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Consent (required to promote)</p>
        <TextField label="Policy version" value={policyVersion} onChange={setPolicyVersion} />
        <TextField label="Purpose" value={purposeText} onChange={setPurposeText} />
        <ReasonField value={reason} onChange={setReason} />
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
      <ModalActions onCancel={onClose} onConfirm={handleSubmit} confirmLabel="Promote" submitting={submitting} />
    </ModalShell>
  );
}

function SplitModal({
  unknown,
  onClose,
  onDone,
}: {
  unknown: UnknownIdentityOut;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const [templates, setTemplates] = useState<FaceTemplateOut[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingTemplates, setLoadingTemplates] = useState(true);

  useEffect(() => {
    listUnknownTemplates(unknown.id)
      .then(setTemplates)
      .catch((err) => setError(toApiError(err).detail))
      .finally(() => setLoadingTemplates(false));
  }, [unknown.id]);

  function toggle(id: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSubmit(): Promise<void> {
    if (selected.size === 0) {
      setError("Choose at least one sighting to split off.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Reason must be at least 3 characters.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await splitUnknown(unknown.id, { template_ids: Array.from(selected), reason });
      onDone();
      onClose();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title={`Split sightings out of ${unknown.face_id}`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-gray-500">
          Historical events stay attributed to {unknown.face_id}; only the selected face templates move to a brand-new
          identity. Use "Reassign to new unknown" on a specific event (from the Dashboard) if a past sighting also
          needs to move.
        </p>
        {loadingTemplates ? (
          <p className="text-sm text-gray-500">Loading sightings...</p>
        ) : templates.length === 0 ? (
          <p className="text-sm text-gray-500">No face templates stored for this identity.</p>
        ) : (
          <div className="grid max-h-64 grid-cols-3 gap-2 overflow-y-auto">
            {templates.map((t) => {
              const isSelected = selected.has(t.id);
              return (
                <button
                  key={t.id}
                  onClick={() => toggle(t.id)}
                  className={`rounded-md border p-1 text-xs ${isSelected ? "border-brand-600 ring-2 ring-brand-500" : "border-gray-200"}`}
                >
                  <AuthImage
                    path={t.crop_url}
                    alt="sighting"
                    className="h-16 w-full rounded object-cover"
                    fallback={
                      <div className="flex h-16 w-full items-center justify-center rounded bg-gray-100 text-gray-400">no image</div>
                    }
                  />
                  <p className="mt-1 truncate">{t.id.slice(0, 8)}</p>
                </button>
              );
            })}
          </div>
        )}
        <ReasonField value={reason} onChange={setReason} />
        {error && <p className="text-sm text-red-600">{error}</p>}
      </div>
      <ModalActions onCancel={onClose} onConfirm={handleSubmit} confirmLabel="Split" submitting={submitting} />
    </ModalShell>
  );
}

function ModalShell({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }): JSX.Element {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalActions({
  onCancel,
  onConfirm,
  confirmLabel,
  submitting,
}: {
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  submitting: boolean;
}): JSX.Element {
  return (
    <div className="mt-6 flex justify-end gap-2">
      <button onClick={onCancel} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700">
        Cancel
      </button>
      <button
        onClick={onConfirm}
        disabled={submitting}
        className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
      >
        {submitting ? "Saving..." : confirmLabel}
      </button>
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }): JSX.Element {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
    </div>
  );
}

function ReasonField({ value, onChange }: { value: string; onChange: (v: string) => void }): JSX.Element {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">Reason (required)</label>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={2} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
    </div>
  );
}

export function Unknowns(): JSX.Element {
  const [items, setItems] = useState<UnknownIdentityOut[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [linking, setLinking] = useState<UnknownIdentityOut | null>(null);
  const [promoting, setPromoting] = useState<UnknownIdentityOut | null>(null);
  const [splitting, setSplitting] = useState<UnknownIdentityOut | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listUnknowns({ status: status || undefined, page_size: 200 });
      setItems(res.items);
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  const handleIgnore = useCallback(
    async (u: UnknownIdentityOut): Promise<void> => {
      try {
        await updateUnknown(u.id, { status: "IGNORED" });
        load();
      } catch (err) {
        setError(toApiError(err).detail);
      }
    },
    [load],
  );

  const handleDelete = useCallback(
    async (u: UnknownIdentityOut): Promise<void> => {
      if (!window.confirm(`Permanently delete ${u.face_id} and all of its biometric templates?`)) return;
      try {
        await deleteUnknown(u.id);
        load();
      } catch (err) {
        setError(toApiError(err).detail);
      }
    },
    [load],
  );

  const columns = useMemo<ColumnDef<UnknownIdentityOut>[]>(
    () => [
      {
        header: "Best shot",
        cell: ({ row }) => (
          <AuthImage
            path={row.original.best_crop_url}
            alt="best sighting"
            className="h-10 w-10 rounded object-cover"
            fallback={<div className="h-10 w-10 rounded bg-gray-100" />}
          />
        ),
      },
      { id: "face_id", header: "Face ID", accessorKey: "face_id", sortingFn: "alphanumeric" },
      { id: "label", header: "Label", accessorFn: (row) => row.label ?? "(unlabeled)" },
      // sort on the raw ISO timestamp, show it formatted
      { id: "first_seen", header: "First seen", accessorFn: (row) => row.first_seen_at, cell: ({ row }) => formatDateTime(row.original.first_seen_at) },
      { id: "last_seen", header: "Last seen", accessorFn: (row) => row.last_seen_at, cell: ({ row }) => formatDateTime(row.original.last_seen_at) },
      { id: "sightings", header: "Sightings", accessorKey: "sighting_count" },
      { id: "status", header: "Status", accessorKey: "status" },
      {
        header: "Actions",
        cell: ({ row }) => {
          const u = row.original;
          const disabled = u.status !== "OPEN";
          return (
            <div className="flex flex-wrap gap-1.5">
              <button disabled={disabled} onClick={() => setLinking(u)} className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                Link
              </button>
              <button disabled={disabled} onClick={() => setPromoting(u)} className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                Promote
              </button>
              <button disabled={disabled} onClick={() => setSplitting(u)} className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                Split
              </button>
              <button disabled={disabled} onClick={() => handleIgnore(u)} className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">
                Ignore
              </button>
              <button onClick={() => handleDelete(u)} className="rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                Delete
              </button>
            </div>
          );
        },
      },
    ],
    [handleIgnore, handleDelete],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Unknown faces</h1>
          <p className="text-sm text-gray-500">Tip: you can also identify faces straight from the Dashboard (click a row).</p>
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-gray-300 px-3 py-2 text-sm">
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {loading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <DataTable
          data={items}
          columns={columns}
          getRowId={(row) => row.id}
          emptyMessage="No unknown identities match this filter."
          maxBodyHeight={560}
          initialSort={[{ id: "last_seen", desc: true }]}
        />
      )}

      {linking && <LinkModal unknown={linking} onClose={() => setLinking(null)} onDone={load} />}
      {promoting && <PromoteModal unknown={promoting} onClose={() => setPromoting(null)} onDone={load} />}
      {splitting && <SplitModal unknown={splitting} onClose={() => setSplitting(null)} onDone={load} />}
    </div>
  );
}
