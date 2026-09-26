import { useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "../components/DataTable";
import { AuthImage } from "../components/AuthImage";
import { PersonFields } from "../components/PersonFields";
import { EMPTY_PERSON, personPayload, useCameras, type PersonValues } from "../components/person";
import { useProfile } from "../profile/ProfileContext";
import {
  createEmployee,
  deleteEmployee,
  deleteTemplate,
  enrollEmployee,
  grantConsent,
  listEmployees,
  listShifts,
  listTemplates,
  revokeConsent,
  toApiError,
  updateEmployee,
} from "../api/client";
import type { EmployeeOut, FaceTemplateOut, ShiftOut } from "../api/types";
import { formatDate } from "../utils/format";

function CreateEmployeeForm({ shifts, onCreated }: { shifts: ShiftOut[]; onCreated: () => void }): JSX.Element {
  const profile = useProfile();
  const cameras = useCameras();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<PersonValues>(EMPTY_PERSON);
  const [shiftId, setShiftId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(): Promise<void> {
    if (!values.name.trim() || !values.emp_code.trim()) {
      setError(`Name and ${profile.id_label} are required.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createEmployee({
        name: values.name.trim(),
        emp_code: values.emp_code.trim(),
        ...personPayload(values),
        shift_id: shiftId || null,
      });
      setValues(EMPTY_PERSON);
      setShiftId("");
      setOpen(false);
      onCreated();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
        + New {profile.person_label.toLowerCase()}
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">New {profile.person_label.toLowerCase()}</h2>
        <PersonFields value={values} onChange={setValues} cameras={cameras} />
        <label className="mt-3 block">
          <span className="mb-1 block text-xs font-medium text-gray-700">Shift</span>
          <select value={shiftId} onChange={(e) => setShiftId(e.target.value)} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
            <option value="">No shift</option>
            {shifts.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.in_time}-{s.out_time})
              </option>
            ))}
          </select>
        </label>
        <p className="mt-3 text-xs text-gray-500">After creating, open &ldquo;Manage&rdquo; to upload 3-5 clear face photos.</p>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setOpen(false)} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700">
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={submitting} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
            {submitting ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EmployeeDetailPanel({
  employee,
  shifts,
  onClose,
  onChanged,
}: {
  employee: EmployeeOut;
  shifts: ShiftOut[];
  onClose: () => void;
  onChanged: () => void;
}): JSX.Element {
  const [templates, setTemplates] = useState<FaceTemplateOut[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cameras = useCameras();
  const [values, setValues] = useState<PersonValues>({
    name: employee.name,
    emp_code: employee.emp_code,
    department: employee.department ?? "",
    designation: employee.designation ?? "",
    home_kiosk_id: employee.home_kiosk_id ?? "",
    contractor: employee.contractor ?? "",
  });
  const [shiftId, setShiftId] = useState(employee.shift_id ?? "");
  const [enrolling, setEnrolling] = useState(false);
  const [consentPolicy, setConsentPolicy] = useState("v1");
  const [consentPurpose, setConsentPurpose] = useState("Biometric attendance enrollment");

  const loadTemplates = useCallback(() => {
    setLoadingTemplates(true);
    listTemplates(employee.id)
      .then(setTemplates)
      .catch((err) => setError(toApiError(err).detail))
      .finally(() => setLoadingTemplates(false));
  }, [employee.id]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  async function handleSaveDetails(): Promise<void> {
    try {
      await updateEmployee(employee.id, {
        name: values.name.trim() || employee.name,
        ...personPayload(values),
        shift_id: shiftId || null,
      });
      onChanged();
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }

  async function handleToggleActive(): Promise<void> {
    try {
      await updateEmployee(employee.id, { is_active: !employee.is_active });
      onChanged();
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }

  async function handleEnroll(fileList: FileList | null): Promise<void> {
    if (!fileList || fileList.length === 0) return;
    setEnrolling(true);
    setError(null);
    try {
      const result = await enrollEmployee(employee.id, Array.from(fileList));
      if (result.accepted_count === 0) {
        setError("No images were accepted -- check face size, quality, and lighting.");
      }
      loadTemplates();
      onChanged();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setEnrolling(false);
    }
  }

  async function handleDeleteTemplate(templateId: string): Promise<void> {
    try {
      await deleteTemplate(employee.id, templateId);
      loadTemplates();
      onChanged();
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }

  async function handleGrantConsent(): Promise<void> {
    try {
      await grantConsent(employee.id, { policy_version: consentPolicy, purpose_text: consentPurpose });
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }

  async function handleRevokeConsent(): Promise<void> {
    try {
      await revokeConsent(employee.id);
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              {employee.name} <span className="text-sm font-normal text-gray-500">({employee.face_id})</span>
            </h2>
            <p className="text-sm text-gray-500">Enrolled {formatDate(employee.created_at)}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            ✕
          </button>
        </div>

        {error && <p className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

        <section className="mb-5 grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <PersonFields value={values} onChange={setValues} show={{ emp_code: false }} cameras={cameras} currentCamera={employee.home_kiosk_id} />
          </div>
          <select value={shiftId} onChange={(e) => setShiftId(e.target.value)} className="col-span-2 rounded-md border border-gray-300 px-3 py-2 text-sm">
            <option value="">No shift</option>
            {shifts.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.in_time}-{s.out_time})
              </option>
            ))}
          </select>
          <div className="col-span-2 flex gap-2">
            <button onClick={handleSaveDetails} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700">
              Save details
            </button>
            <button onClick={handleToggleActive} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700">
              {employee.is_active ? "Deactivate" : "Reactivate"}
            </button>
          </div>
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Consent</h3>
          <div className="grid grid-cols-2 gap-2">
            <input placeholder="Policy version" value={consentPolicy} onChange={(e) => setConsentPolicy(e.target.value)} className="rounded-md border border-gray-300 px-3 py-2 text-sm" />
            <input placeholder="Purpose" value={consentPurpose} onChange={(e) => setConsentPurpose(e.target.value)} className="rounded-md border border-gray-300 px-3 py-2 text-sm" />
          </div>
          <div className="mt-2 flex gap-2">
            <button onClick={handleGrantConsent} className="rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              Grant consent
            </button>
            <button onClick={handleRevokeConsent} className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50">
              Revoke consent
            </button>
          </div>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-gray-500">Face templates ({templates.length})</h3>
            <label className="cursor-pointer rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50">
              {enrolling ? "Uploading..." : "+ Enroll photos"}
              <input type="file" accept="image/*" multiple hidden disabled={enrolling} onChange={(e) => handleEnroll(e.target.files)} />
            </label>
          </div>
          {loadingTemplates ? (
            <p className="text-sm text-gray-500">Loading templates...</p>
          ) : templates.length === 0 ? (
            <p className="text-sm text-gray-500">No face templates enrolled yet.</p>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              {templates.map((t) => (
                <div key={t.id} className="rounded-md border border-gray-200 p-1 text-xs">
                  <AuthImage
                    path={t.crop_url}
                    alt="template"
                    className="h-20 w-full rounded object-cover"
                    fallback={
                      <div className="flex h-20 w-full items-center justify-center rounded bg-gray-100 text-gray-400">no image</div>
                    }
                  />
                  <p className="mt-1 truncate">{t.is_primary ? "primary" : "alt"} &middot; q={t.quality_score.toFixed(2)}</p>
                  <button onClick={() => handleDeleteTemplate(t.id)} className="mt-1 w-full rounded border border-red-200 py-0.5 text-red-600 hover:bg-red-50">
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export function Employees(): JSX.Element {
  const profile = useProfile();
  const [employees, setEmployees] = useState<EmployeeOut[]>([]);
  const [shifts, setShifts] = useState<ShiftOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<EmployeeOut | null>(null);
  const [showInactive, setShowInactive] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [empRes, shiftRes] = await Promise.all([
        listEmployees({ page_size: 500, is_active: showInactive ? undefined : true }),
        listShifts(),
      ]);
      setEmployees(empRes.items);
      setShifts(shiftRes);
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setLoading(false);
    }
  }, [showInactive]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = useCallback(async (emp: EmployeeOut): Promise<void> => {
    if (!window.confirm(`Deactivate ${emp.name} and hard-purge their biometric templates? This cannot be undone.`)) return;
    try {
      await deleteEmployee(emp.id);
      load();
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }, [load]);

  const columns = useMemo<ColumnDef<EmployeeOut>[]>(
    () => [
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Name", accessorKey: "name" },
      { header: profile.id_label, accessorKey: "emp_code" },
      { header: profile.department_label, accessorFn: (row) => row.department ?? "--" },
      { header: profile.designation_label, accessorFn: (row) => row.designation ?? "--" },
      { header: "Home camera", accessorFn: (row) => row.home_kiosk_id ?? "--" },
      { header: "Contractor", accessorFn: (row) => row.contractor ?? "Own staff" },
      { header: "Templates", accessorKey: "template_count" },
      {
        header: "Status",
        cell: ({ row }) => (
          <span className={row.original.is_active ? "text-green-700" : "text-gray-400"}>
            {row.original.is_active ? "Active" : "Inactive"}
          </span>
        ),
      },
      {
        header: "Actions",
        cell: ({ row }) => (
          <div className="flex gap-1.5">
            <button onClick={() => setSelected(row.original)} className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50">
              Manage
            </button>
            {row.original.is_active && (
              <button onClick={() => handleDelete(row.original)} className="rounded-md border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">
                Deactivate
              </button>
            )}
          </div>
        ),
      },
    ],
    [handleDelete, profile],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">{profile.person_label_plural}</h1>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            Show inactive
          </label>
          <CreateEmployeeForm shifts={shifts} onCreated={load} />
        </div>
      </div>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {loading ? (
        <p className="text-sm text-gray-500">Loading employees...</p>
      ) : (
        <DataTable data={employees} columns={columns} getRowId={(row) => row.id} emptyMessage={`No ${profile.person_label_plural.toLowerCase()} yet -- add one above.`} maxBodyHeight={560} />
      )}

      {selected && (
        <EmployeeDetailPanel
          employee={selected}
          shifts={shifts}
          onClose={() => setSelected(null)}
          onChanged={() => {
            load();
          }}
        />
      )}
    </div>
  );
}
