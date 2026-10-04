import { useEffect, useState } from "react";
import { getPayrollProfile, getPayrollStates, savePayrollProfile, toApiError } from "../api/client";
import type { PayrollProfile, PayrollProfileIn, PtState, SalaryComponents } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const input = "w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-sm";
const COMPONENTS: [keyof SalaryComponents, string][] = [
  ["basic", "Basic"], ["da", "DA"], ["hra", "HRA"], ["conveyance", "Conveyance"], ["special", "Special allowance"], ["other", "Other"],
];

function toForm(p: PayrollProfile): PayrollProfileIn & { pan: string; bank_account: string } {
  return {
    gender: p.gender, pt_state: p.pt_state, pf_enabled: p.pf_enabled, pf_on_full_wage: p.pf_on_full_wage,
    eps_eligible: p.eps_eligible, uan: p.uan, esi_enabled: p.esi_enabled, esic_ip: p.esic_ip, pan: "",
    bank_name: p.bank_name, bank_account: "", ifsc: p.ifsc, payment_mode: p.payment_mode, tax_regime: p.tax_regime,
    tds_monthly: p.tds_monthly, components: p.components,
  };
}

/** Bank, PF / ESI / PT and salary structure of one person (HR / admin). */
export function PayrollSection({ employeeId, onSaved }: { employeeId: string; onSaved?: () => void }): JSX.Element | null {
  const { isHr } = useAuth();
  const [profile, setProfile] = useState<PayrollProfile | null>(null);
  const [form, setForm] = useState<ReturnType<typeof toForm> | null>(null);
  const [states, setStates] = useState<PtState[]>([]);
  const [useStructure, setUseStructure] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!isHr) return;
    getPayrollProfile(employeeId)
      .then((p) => {
        setProfile(p);
        setForm(toForm(p));
        setUseStructure(p.structure_from === "components");
      })
      .catch((e) => setError(toApiError(e).detail));
    getPayrollStates().then((r) => setStates(r.states)).catch(() => setStates([]));
  }, [employeeId, isHr]);

  if (!isHr) return null;
  if (!form || !profile) {
    return error ? <p className="mb-5 text-sm text-red-600">{error}</p> : null;
  }

  const set = (patch: Partial<typeof form>): void => {
    setSaved(false);
    setForm({ ...form, ...patch });
  };
  const comps: SalaryComponents = form.components ?? profile.structure;
  const gross = Object.values(comps).reduce((a, b) => a + (Number(b) || 0), 0);

  async function save(): Promise<void> {
    if (!form) return;
    setError(null);
    try {
      const payload: PayrollProfileIn = {
        ...form,
        pan: form.pan.trim() || null,
        bank_account: form.bank_account.trim() || null,
        components: useStructure ? comps : null,
      };
      const p = await savePayrollProfile(employeeId, payload);
      setProfile(p);
      setForm(toForm(p));
      setSaved(true);
      onSaved?.();
    } catch (e) {
      setError(toApiError(e).detail);
    }
  }

  return (
    <details className="mb-5 rounded-lg border border-gray-200 p-3">
      <summary className="cursor-pointer select-none text-sm font-semibold uppercase tracking-wide text-gray-500">
        Payroll (bank, PF, ESI, salary structure)
      </summary>
      <div className="mt-3 space-y-4 text-sm">
        <div>
          <label className="flex items-center gap-2 text-xs text-gray-700">
            <input type="checkbox" checked={useStructure} onChange={(e) => { setUseStructure(e.target.checked); setSaved(false); if (e.target.checked && !form.components) set({ components: profile.structure }); }} />
            Own salary structure (otherwise split from the monthly salary with the company template)
          </label>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {COMPONENTS.map(([k, label]) => (
              <label key={k} className="text-xs text-gray-600">
                {label}
                <input className={`${input} mt-0.5`} type="number" min={0} disabled={!useStructure}
                  value={comps[k] ?? 0} onChange={(e) => set({ components: { ...comps, [k]: Number(e.target.value) || 0 } })} />
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Gross per month: <strong>₹{gross.toLocaleString("en-IN")}</strong>. Labour codes: keep Basic + DA at least 50% of gross.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <label className="text-xs text-gray-600">Gender (PT)
            <select className={`${input} mt-0.5`} value={form.gender ?? ""} onChange={(e) => set({ gender: (e.target.value || null) as PayrollProfileIn["gender"] })}>
              <option value="">--</option><option value="M">Male</option><option value="F">Female</option><option value="O">Other</option>
            </select>
          </label>
          <label className="text-xs text-gray-600">PT state
            <select className={`${input} mt-0.5`} value={form.pt_state ?? ""} onChange={(e) => set({ pt_state: e.target.value || null })}>
              <option value="">Company default</option>
              {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-600">TDS per month (₹)
            <input className={`${input} mt-0.5`} type="number" min={0} value={form.tds_monthly} onChange={(e) => set({ tds_monthly: Number(e.target.value) || 0 })} />
          </label>
          <label className="text-xs text-gray-600">UAN (PF)
            <input className={`${input} mt-0.5`} inputMode="numeric" maxLength={12} value={form.uan ?? ""} onChange={(e) => set({ uan: e.target.value || null })} />
          </label>
          <label className="text-xs text-gray-600">ESIC IP number
            <input className={`${input} mt-0.5`} inputMode="numeric" maxLength={10} value={form.esic_ip ?? ""} onChange={(e) => set({ esic_ip: e.target.value || null })} />
          </label>
          <label className="text-xs text-gray-600">PAN {profile.pan_masked && <span className="text-gray-400">({profile.pan_masked})</span>}
            <input className={`${input} mt-0.5 uppercase`} maxLength={10} placeholder={profile.pan_masked ? "leave blank to keep" : "ABCDE1234F"} value={form.pan} onChange={(e) => set({ pan: e.target.value })} />
          </label>
        </div>

        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-700">
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.pf_enabled} onChange={(e) => set({ pf_enabled: e.target.checked })} /> PF</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.pf_on_full_wage} onChange={(e) => set({ pf_on_full_wage: e.target.checked })} /> PF on full wage (above ceiling)</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.eps_eligible} onChange={(e) => set({ eps_eligible: e.target.checked })} /> Pension (EPS)</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={form.esi_enabled} onChange={(e) => set({ esi_enabled: e.target.checked })} /> ESI (if wage within limit)</label>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <label className="text-xs text-gray-600">Pay by
            <select className={`${input} mt-0.5`} value={form.payment_mode} onChange={(e) => set({ payment_mode: e.target.value as PayrollProfileIn["payment_mode"] })}>
              <option value="bank">Bank transfer</option><option value="cash">Cash</option><option value="cheque">Cheque</option>
            </select>
          </label>
          <label className="text-xs text-gray-600">Bank
            <input className={`${input} mt-0.5`} value={form.bank_name ?? ""} onChange={(e) => set({ bank_name: e.target.value || null })} />
          </label>
          <label className="text-xs text-gray-600">Account no. {profile.bank_account_masked && <span className="text-gray-400">({profile.bank_account_masked})</span>}
            <input className={`${input} mt-0.5`} inputMode="numeric" placeholder={profile.bank_account_masked ? "blank = keep" : ""} value={form.bank_account} onChange={(e) => set({ bank_account: e.target.value })} />
          </label>
          <label className="text-xs text-gray-600">IFSC
            <input className={`${input} mt-0.5 uppercase`} maxLength={11} value={form.ifsc ?? ""} onChange={(e) => set({ ifsc: e.target.value.toUpperCase() || null })} />
          </label>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex items-center gap-3">
          <button onClick={() => void save()} className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700">Save payroll details</button>
          {saved && <span className="text-xs text-emerald-700">Saved</span>}
          <span className="text-xs text-gray-400">PAN and account number are stored encrypted.</span>
        </div>
      </div>
    </details>
  );
}
