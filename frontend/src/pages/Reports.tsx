import { Fragment, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Download, FileSpreadsheet, FileText, HardHat, Wallet } from "lucide-react";
import clsx from "clsx";
import { downloadFile, getContractorReport, listContractorNames, toApiError } from "../api/client";
import type { ContractorReport, PayrollFormat } from "../api/types";
import { useProfile } from "../profile/ProfileContext";
import { todayIsoDate } from "../utils/format";

type Tab = "contractors" | "payroll" | "muster" | "monthly";

const input =
  "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

function prevMonth(iso: string): string {
  const [y = 2000, m = 1] = iso.slice(0, 7).split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 2, 1)); // UTC: no timezone day-shift
  return d.toISOString().slice(0, 7);
}

function monthEnd(ym: string): string {
  const [y = 2000, m = 1] = ym.split("-").map(Number);
  return `${ym}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
}

export function Reports(): JSX.Element {
  const [tab, setTab] = useState<Tab>("contractors");
  const tabs: { id: Tab; label: string; icon: typeof HardHat }[] = [
    { id: "contractors", label: "Contractor bill check", icon: HardHat },
    { id: "payroll", label: "Payroll export", icon: Wallet },
    { id: "muster", label: "Muster roll", icon: FileSpreadsheet },
    { id: "monthly", label: "Monthly PDF", icon: FileText },
  ];
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500">Attendance turned into man-days, paid days and overtime, ready for billing and payroll.</p>
      </header>
      <div className="flex flex-wrap gap-1 rounded-lg bg-gray-100 p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
              tab === t.id ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900",
            )}
          >
            <t.icon className="h-4 w-4" aria-hidden />
            {t.label}
          </button>
        ))}
      </div>
      {tab === "contractors" && <Contractors />}
      {tab === "payroll" && <Payroll />}
      {tab === "muster" && <Muster />}
      {tab === "monthly" && <MonthlyPdf />}
    </div>
  );
}

function useContractors(): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    listContractorNames()
      .then(setNames)
      .catch(() => setNames([]));
  }, []);
  return names;
}

function RangePicker({
  from,
  to,
  onChange,
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}): JSX.Element {
  const today = todayIsoDate();
  const last = prevMonth(today);
  const presets: [string, string, string][] = [
    ["This month", monthStart(today), today],
    ["Last month", `${last}-01`, monthEnd(last)],
  ];
  return (
    <div className="flex flex-wrap items-end gap-2">
      {presets.map(([label, f, t]) => (
        <button
          key={label}
          onClick={() => onChange(f, t)}
          className={clsx(
            "rounded-md border px-3 py-2 text-sm",
            from === f && to === t ? "border-brand-600 bg-brand-50 text-brand-700" : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
          )}
        >
          {label}
        </button>
      ))}
      <label className="text-xs font-medium text-gray-600">
        From
        <input type="date" className={clsx(input, "block")} value={from} onChange={(e) => onChange(e.target.value, to)} />
      </label>
      <label className="text-xs font-medium text-gray-600">
        To
        <input type="date" className={clsx(input, "block")} value={to} min={from} onChange={(e) => onChange(from, e.target.value)} />
      </label>
    </div>
  );
}

// ---------------------------------------------------------------- contractors
function Contractors(): JSX.Element {
  const today = todayIsoDate();
  const [from, setFrom] = useState(monthStart(today));
  const [to, setTo] = useState(today);
  const [data, setData] = useState<ContractorReport | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getContractorReport(from, to)
      .then(setData)
      .catch((e) => setError(toApiError(e).detail))
      .finally(() => setLoading(false));
  }, [from, to]);

  const rows = data?.contractors ?? [];
  const totalManDays = rows.reduce((s, r) => s + r.man_days, 0);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <RangePicker
          from={from}
          to={to}
          onChange={(f, t) => {
            setFrom(f);
            setTo(t);
          }}
        />
        <button
          onClick={() => void downloadFile("/reports/contractors.csv", { date_from: from, date_to: to }, `contractors_${from}_${to}.csv`)}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <Download className="h-4 w-4" aria-hidden /> Day-wise CSV
        </button>
      </div>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <p className="text-sm text-gray-600">
        Compare <strong>man-days</strong> below with the contractor&apos;s bill. A man-day is one person present for one day
        (half day = 0.5). Total: <strong className="tabular-nums">{totalManDays.toFixed(1)}</strong>.
      </p>
      <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-3">Contractor</th>
              <th className="px-4 py-3 text-right">On roll</th>
              <th className="px-4 py-3 text-right">Avg present / day</th>
              <th className="px-4 py-3 text-right">Man-days</th>
              <th className="px-4 py-3 text-right">OT hours</th>
              <th className="px-4 py-3 text-right">Late days</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-400">
                  Loading...
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-400">
                  No data for these dates.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <Fragment key={r.contractor}>
                <tr className="cursor-pointer hover:bg-gray-50" onClick={() => setOpen(open === r.contractor ? null : r.contractor)}>
                  <td className="px-4 py-2.5 font-medium text-gray-900">
                    <span className="inline-flex items-center gap-1">
                      {open === r.contractor ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      {r.contractor}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{r.headcount}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{r.avg_daily_present}</td>
                  <td className="px-4 py-2.5 text-right font-semibold tabular-nums">{r.man_days.toFixed(1)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{r.ot_hours}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{r.late_days}</td>
                </tr>
                {open === r.contractor && (
                  <tr>
                    <td colSpan={6} className="bg-gray-50 px-4 py-3">
                      <ContractorDetail row={r} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ContractorDetail({ row }: { row: ContractorReport["contractors"][number] }): JSX.Element {
  const max = Math.max(1, ...row.daily.map((d) => d.on_roll));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Present per day</h4>
        <ul className="space-y-1">
          {row.daily.map((d) => (
            <li key={d.date} className="flex items-center gap-2 text-xs">
              <span className="w-20 shrink-0 tabular-nums text-gray-500">{d.date.slice(5)}</span>
              <span className="relative h-3 flex-1 rounded bg-gray-200">
                <span className="absolute inset-y-0 left-0 rounded bg-brand-500" style={{ width: `${(d.present / max) * 100}%` }} />
              </span>
              <span className="w-16 shrink-0 text-right tabular-nums text-gray-700">
                {d.present}/{d.on_roll}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">People</h4>
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500">
              <tr>
                <th className="py-1 text-left">Name</th>
                <th className="py-1 text-right">Present</th>
                <th className="py-1 text-right">Absent</th>
                <th className="py-1 text-right">OT h</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {row.people.map((p) => (
                <tr key={p.employee_id}>
                  <td className="py-1">
                    {p.name} <span className="text-gray-400">{p.emp_code}</span>
                  </td>
                  <td className="py-1 text-right tabular-nums">{p.present + p.half_days * 0.5}</td>
                  <td className="py-1 text-right tabular-nums">{p.absent}</td>
                  <td className="py-1 text-right tabular-nums">{p.ot_hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- payroll
const FORMATS: { id: PayrollFormat; label: string; note: string }[] = [
  { id: "generic", label: "Excel / CSV (all columns)", note: "Every figure: present, half days, absent, weekly off, paid days, LOP, late, OT." },
  { id: "tally", label: "Tally Prime (XML)", note: "Import in Tally: Gateway → Import → Vouchers. Names must match the employee names in Tally." },
  { id: "zoho", label: "Zoho Payroll (CSV)", note: "Paid days, LOP days and OT hours per Employee ID." },
  { id: "greythr", label: "greytHR (CSV)", note: "Paid days, LOP days and OT hours per Employee No." },
  { id: "keka", label: "Keka (CSV)", note: "Payable days, loss-of-pay days and overtime per Employee Number." },
];

function Payroll(): JSX.Element {
  const today = todayIsoDate();
  const [month, setMonth] = useState(prevMonth(today));
  const [format, setFormat] = useState<PayrollFormat>("generic");
  const [contractor, setContractor] = useState("");
  const [company, setCompany] = useState("");
  const [presentType, setPresentType] = useState("Present");
  const [otType, setOtType] = useState("Overtime");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contractors = useContractors();
  const profile = useProfile();
  const fmt = FORMATS.find((f) => f.id === format);

  async function download(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await downloadFile(
        "/reports/payroll",
        {
          month,
          format,
          contractor: contractor || undefined,
          tally_company: format === "tally" ? company || profile.org_name : undefined,
          tally_present_type: format === "tally" ? presentType : undefined,
          tally_ot_type: format === "tally" ? otType : undefined,
        },
        `payroll_${format}_${month}.${format === "tally" ? "xml" : "csv"}`,
      );
    } catch (e) {
      setError(toApiError(e).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-2xl space-y-4 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-gray-700">
          Month
          <input type="month" className={clsx(input, "block w-full")} value={month} max={today.slice(0, 7)} onChange={(e) => setMonth(e.target.value)} />
        </label>
        <label className="text-xs font-medium text-gray-700">
          Who
          <select className={clsx(input, "block w-full")} value={contractor} onChange={(e) => setContractor(e.target.value)}>
            <option value="">Everyone</option>
            <option value="Own staff">Own staff only</option>
            {contractors.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
      </div>
      <fieldset>
        <legend className="mb-2 text-xs font-medium text-gray-700">Format</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {FORMATS.map((f) => (
            <label
              key={f.id}
              className={clsx(
                "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                format === f.id ? "border-brand-600 bg-brand-50 text-brand-800" : "border-gray-200 hover:bg-gray-50",
              )}
            >
              <input type="radio" name="fmt" checked={format === f.id} onChange={() => setFormat(f.id)} />
              {f.label}
            </label>
          ))}
        </div>
        {fmt && <p className="mt-2 text-xs text-gray-500">{fmt.note}</p>}
      </fieldset>
      {format === "tally" && (
        <div className="grid gap-3 rounded-lg bg-gray-50 p-3 sm:grid-cols-3">
          <label className="text-xs font-medium text-gray-700">
            Tally company name
            <input className={clsx(input, "block w-full")} value={company} placeholder={profile.org_name} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-gray-700">
            Attendance type
            <input className={clsx(input, "block w-full")} value={presentType} onChange={(e) => setPresentType(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-gray-700">
            Overtime type
            <input className={clsx(input, "block w-full")} value={otType} onChange={(e) => setOtType(e.target.value)} />
          </label>
        </div>
      )}
      <p className="text-xs text-gray-500">
        Paid days = days in month − loss-of-pay days. Weekly offs are paid; overtime and half-day rules are in Settings →
        Payroll &amp; overtime.
      </p>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button
        onClick={() => void download()}
        disabled={busy || !month}
        className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
      >
        <Download className="h-4 w-4" aria-hidden /> {busy ? "Preparing..." : "Download"}
      </button>
    </section>
  );
}

// ---------------------------------------------------------------- muster roll
function Muster(): JSX.Element {
  const today = todayIsoDate();
  const [from, setFrom] = useState(monthStart(today));
  const [to, setTo] = useState(today);
  const [contractor, setContractor] = useState("");
  const [error, setError] = useState<string | null>(null);
  const contractors = useContractors();

  return (
    <section className="max-w-3xl space-y-4 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-gray-600">
        A register-style sheet: one row per person, one column per day with <strong>P</strong> (present),{" "}
        <strong>HD</strong> (half day), <strong>A</strong> (absent), <strong>WO</strong> (weekly off),{" "}
        <strong>WOP</strong> (worked on weekly off), then totals. Opens in Excel.
      </p>
      <RangePicker
        from={from}
        to={to}
        onChange={(f, t) => {
          setFrom(f);
          setTo(t);
        }}
      />
      <label className="block max-w-xs text-xs font-medium text-gray-700">
        Who
        <select className={clsx(input, "block w-full")} value={contractor} onChange={(e) => setContractor(e.target.value)}>
          <option value="">Everyone</option>
          <option value="Own staff">Own staff only</option>
          {contractors.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </label>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button
        onClick={() =>
          void downloadFile(
            "/reports/muster-roll.csv",
            { date_from: from, date_to: to, contractor: contractor || undefined },
            `muster_roll_${from}_${to}.csv`,
          ).catch((e) => setError(toApiError(e).detail))
        }
        className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
      >
        <Download className="h-4 w-4" aria-hidden /> Download muster roll
      </button>
    </section>
  );
}

// ---------------------------------------------------------------- monthly PDF
function MonthlyPdf(): JSX.Element {
  const today = todayIsoDate();
  const [month, setMonth] = useState(prevMonth(today));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <section className="max-w-2xl space-y-4 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-gray-600">
        A 2-page report for the owner or management review: attendance %, man-days, late arrivals, overtime, a day-by-day
        chart, department and contractor tables, and who needs attention.
      </p>
      <label className="block max-w-xs text-xs font-medium text-gray-700">
        Month
        <input type="month" className={clsx(input, "block w-full")} value={month} max={today.slice(0, 7)} onChange={(e) => setMonth(e.target.value)} />
      </label>
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <button
        disabled={busy || !month}
        onClick={() => {
          setBusy(true);
          setError(null);
          void downloadFile("/reports/monthly.pdf", { month }, `attendance_${month}.pdf`)
            .catch((e) => setError(toApiError(e).detail))
            .finally(() => setBusy(false));
        }}
        className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
      >
        <Download className="h-4 w-4" aria-hidden /> {busy ? "Preparing..." : "Download PDF"}
      </button>
    </section>
  );
}
