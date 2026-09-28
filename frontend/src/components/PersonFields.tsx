import type { CameraOut } from "../api/types";
import { useContractorNames, type PersonValues } from "./person";
import { useProfile } from "../profile/ProfileContext";

// One set of "who is this person" inputs, shared by: register-from-dashboard,
// Unknown faces -> Promote, and the People page create/edit forms -- so the
// department list (vendor-locked) and the per-camera cap look and behave the
// same everywhere.

const input =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-gray-50 disabled:text-gray-500";

interface PersonFieldsProps {
  value: PersonValues;
  onChange: (next: PersonValues) => void;
  /** Hide name / ID (e.g. editing an existing person whose ID can't change). */
  show?: { name?: boolean; emp_code?: boolean };
  /** Camera the person is currently on (so it doesn't count as "full" for them). */
  currentCamera?: string | null;
  cameras: CameraOut[];
}

export function PersonFields({ value, onChange, show = {}, currentCamera, cameras }: PersonFieldsProps): JSX.Element {
  const profile = useProfile();
  const set = (patch: Partial<PersonValues>): void => onChange({ ...value, ...patch });
  const showName = show.name ?? true;
  const showCode = show.emp_code ?? true;
  const departments = profile.departments;
  const contractors = useContractorNames();
  const legacyDept = value.department && departments.length > 0 && !departments.includes(value.department);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {showName && (
        <Field label="Full name" required>
          <input className={input} value={value.name} onChange={(e) => set({ name: e.target.value })} autoFocus />
        </Field>
      )}
      {showCode && (
        <Field label={profile.id_label} required>
          <input className={input} value={value.emp_code} onChange={(e) => set({ emp_code: e.target.value })} />
        </Field>
      )}
      <Field label={profile.department_label}>
        {departments.length > 0 ? (
          <select className={input} value={value.department} onChange={(e) => set({ department: e.target.value })}>
            <option value="">— Select {profile.department_label.toLowerCase()} —</option>
            {legacyDept && <option value={value.department}>{value.department} (old)</option>}
            {departments.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        ) : (
          <input className={input} value={value.department} onChange={(e) => set({ department: e.target.value })} />
        )}
      </Field>
      <Field label={profile.designation_label}>
        <input className={input} value={value.designation} onChange={(e) => set({ designation: e.target.value })} />
      </Field>
      {value.contractor !== undefined && (
        <Field label="Contractor / agency" hint="Blank = own staff" wide>
          <input
            className={input}
            list="contractor-names"
            value={value.contractor}
            placeholder="e.g. Sharma Manpower Services"
            onChange={(e) => set({ contractor: e.target.value })}
          />
          <datalist id="contractor-names">
            {contractors.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </Field>
      )}
      {value.monthly_salary !== undefined && (
        <Field label="Monthly salary (₹)" hint="Gross; used for payable salary" wide>
          <input
            className={input}
            inputMode="decimal"
            value={value.monthly_salary}
            placeholder="e.g. 18000"
            onChange={(e) => set({ monthly_salary: e.target.value })}
          />
        </Field>
      )}
      <Field label="Home camera" hint={`Max ${profile.max_enrolled_per_camera} per camera`} wide>
        <select className={input} value={value.home_kiosk_id} onChange={(e) => set({ home_kiosk_id: e.target.value })}>
          <option value="">— Not assigned —</option>
          {cameras.map((c) => {
            const full = c.cap > 0 && c.enrolled >= c.cap && c.kiosk_id !== currentCamera;
            return (
              <option key={c.kiosk_id} value={c.kiosk_id} disabled={full}>
                {c.kiosk_id} · {c.enrolled}/{c.cap || "∞"} enrolled{full ? " · FULL" : ""}
                {c.online ? "" : " · offline"}
              </option>
            );
          })}
        </select>
      </Field>
    </div>
  );
}

function Field({
  label,
  hint,
  required,
  wide,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  wide?: boolean;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <label className={wide ? "block sm:col-span-2" : "block"}>
      <span className="mb-1 flex items-baseline justify-between text-xs font-medium text-gray-700">
        <span>
          {label}
          {required && <span className="text-rose-500"> *</span>}
        </span>
        {hint && <span className="font-normal text-gray-400">{hint}</span>}
      </span>
      {children}
    </label>
  );
}
