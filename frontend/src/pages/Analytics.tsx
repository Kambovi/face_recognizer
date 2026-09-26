import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Area,
  AreaChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  Cctv,
  Clock,
  Download,
  Loader2,
  Minus,
  ScanFace,
  Timer,
  TriangleAlert,
  UserCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import clsx from "clsx";
import { DataTable } from "../components/DataTable";
import { downloadAnalyticsCsv, getAnalyticsOverview, getAnalyticsSummary, toApiError } from "../api/client";
import type { AnalyticsOverview, LocationStat, PersonStat, SummaryRowOut } from "../api/types";
import { useProfile } from "../profile/ProfileContext";
import { formatHours, formatPercent, todayIsoDate } from "../utils/format";
import { formatDay } from "../components/dashboard/model";

// Analytics = "how are we doing, where, and who needs attention" for a
// period. Layout follows the usual pattern of HR / access-control dashboards
// (Keka, greytHR, Darwinbox, Zoho People): one filter row -> headline KPIs
// with change vs the previous period -> per-location headcount -> trend ->
// breakdowns -> people lists -> full table. Charts follow the dataviz rules:
// one y-axis per chart, one hue for one series, thin marks, hairline grid.

type Preset = "today" | "week" | "month" | "30d" | "year" | "custom";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "week", label: "This week" },
  { id: "month", label: "This month" },
  { id: "30d", label: "Last 30 days" },
  { id: "year", label: "This year" },
  { id: "custom", label: "Custom" },
];

function shift(iso: string, days: number): string {
  const [y = 1970, m = 1, d = 1] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

function presetRange(preset: Preset, today: string): { from: string; to: string } {
  const [y = 1970, m = 1, d = 1] = today.split("-").map(Number);
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // Monday = 0
  switch (preset) {
    case "today":
      return { from: today, to: today };
    case "week":
      return { from: shift(today, -weekday), to: today };
    case "month":
      return { from: `${today.slice(0, 7)}-01`, to: today };
    case "30d":
      return { from: shift(today, -29), to: today };
    case "year":
      return { from: `${today.slice(0, 4)}-01-01`, to: today };
    default:
      return { from: shift(today, -6), to: today };
  }
}

function useBrandColor(step = 600): string {
  const [color, setColor] = useState("rgb(79 70 229)");
  const profile = useProfile();
  useEffect(() => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(`--brand-${step}`).trim();
    if (v) setColor(`rgb(${v.split(/\s+/).join(",")})`);
  }, [profile.org_type, step]);
  return color;
}

function minutesToClock(m: number): string {
  if (m < 0) return "--";
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${String(h % 12 || 12).padStart(2, "0")}:${String(mm).padStart(2, "0")} ${h >= 12 ? "PM" : "AM"}`;
}

const INK = { axis: "#898781", grid: "#e1e0d9" };

// ---------------------------------------------------------------- page ----

export function Analytics(): JSX.Element {
  const profile = useProfile();
  const today = todayIsoDate();
  const [preset, setPreset] = useState<Preset>("week");
  const [custom, setCustom] = useState(() => presetRange("custom", today));
  const range = preset === "custom" ? custom : presetRange(preset, today);

  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [rows, setRows] = useState<SummaryRowOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = { date_from: range.from, date_to: range.to };
    Promise.all([getAnalyticsOverview(params), getAnalyticsSummary({ period: "daily", ...params })])
      .then(([ov, summary]) => {
        if (cancelled) return;
        setData(ov);
        setRows(summary.rows);
      })
      .catch((err) => !cancelled && setError(toApiError(err).detail))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [range.from, range.to]);

  const people = profile.person_label_plural.toLowerCase();
  const singleDay = range.from === range.to;
  const latestLabel = data ? (data.kpis.latest_day === today ? "today" : formatDay(data.kpis.latest_day)) : "today";

  return (
    <div className="space-y-6">
      {/* header + the one filter row */}
      <header className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900">Attendance analytics</h1>
          <p className="text-sm text-gray-500">
            {formatDay(range.from)}
            {!singleDay && <> → {formatDay(range.to)}</>}
            {data && <> · {data.working_days} working day{data.working_days === 1 ? "" : "s"}</>}
            {loading && data && <Loader2 className="ml-2 inline h-3.5 w-3.5 animate-spin" aria-label="Refreshing" />}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="Period" className="inline-flex flex-wrap rounded-lg bg-gray-100 p-0.5">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                role="tab"
                type="button"
                aria-selected={preset === p.id}
                onClick={() => setPreset(p.id)}
                className={clsx(
                  "rounded-md px-3 py-1.5 text-xs font-medium",
                  preset === p.id ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-800",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          {preset === "custom" && (
            <span className="inline-flex items-center gap-1.5 text-sm">
              <CalendarDays className="h-4 w-4 text-gray-400" aria-hidden />
              <input
                type="date"
                value={custom.from}
                max={custom.to}
                onChange={(e) => e.target.value && setCustom((c) => ({ ...c, from: e.target.value }))}
                className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm"
                aria-label="From"
              />
              <span className="text-gray-400">to</span>
              <input
                type="date"
                value={custom.to}
                min={custom.from}
                max={today}
                onChange={(e) => e.target.value && setCustom((c) => ({ ...c, to: e.target.value }))}
                className="rounded-lg border border-gray-200 px-2 py-1.5 text-sm"
                aria-label="To"
              />
            </span>
          )}
          <button
            type="button"
            onClick={() =>
              void downloadAnalyticsCsv({ period: "daily", date_from: range.from, date_to: range.to }).catch((err) =>
                setError(toApiError(err).detail),
              )
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            <Download className="h-4 w-4" aria-hidden /> Export CSV
          </button>
        </div>
      </header>

      {error && <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}

      {!data ? (
        <p className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading analytics…
        </p>
      ) : (
        <div className={clsx("space-y-6 transition-opacity", loading && "opacity-60")}>
          <KpiSection data={data} people={people} latestLabel={latestLabel} />
          <LocationsSection locations={data.locations} people={people} latestLabel={latestLabel} />
          {!singleDay && <TrendSection data={data} />}
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <DepartmentSection data={data} />
            <ArrivalSection data={data} />
          </div>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <PeopleList
              title="Lowest attendance"
              subtitle={`${profile.person_label_plural} who missed the most working days in this period`}
              rows={data.lowest_attendance.filter((r) => r.attendance_pct < 100)}
              metric={(r) => `${r.attendance_pct.toFixed(0)}%`}
              detail={(r) => `${r.present_days}/${r.expected_days} days`}
              meter={(r) => r.attendance_pct}
              empty="Everyone attended every working day."
            />
            <PeopleList
              title="Most late arrivals"
              subtitle="Arrived after shift start + grace, most often"
              rows={data.most_late}
              metric={(r) => `${r.late_days}×`}
              detail={(r) => `late on ${r.late_days} of ${r.present_days} days present`}
              meter={(r) => (r.present_days ? (r.late_days / r.present_days) * 100 : 0)}
              meterTone="warning"
              empty="No late arrivals in this period."
            />
          </div>

          <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
            <button
              type="button"
              onClick={() => setShowTable((s) => !s)}
              className="flex w-full items-center justify-between px-5 py-4 text-left"
              aria-expanded={showTable}
            >
              <span>
                <span className="text-sm font-semibold text-gray-800">Everyone — full table</span>
                <span className="ml-2 text-xs text-gray-500">{rows.length} rows · same numbers as the CSV export</span>
              </span>
              <span className="text-xs font-medium text-brand-700">{showTable ? "Hide" : "Show"}</span>
            </button>
            {showTable && (
              <div className="border-t border-gray-200 p-3">
                <SummaryTable rows={rows} />
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ KPIs ----

function Delta({ now, before, unit, goodWhenUp = true }: { now: number; before: number; unit: "pp" | "%" | "min" | "h" | ""; goodWhenUp?: boolean }): JSX.Element | null {
  if (!Number.isFinite(before) || before < 0) return null;
  const diff = now - before;
  if (Math.abs(diff) < 0.05) {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-gray-500">
        <Minus className="h-3 w-3" aria-hidden /> same as previous
      </span>
    );
  }
  const up = diff > 0;
  const good = up === goodWhenUp;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  const value =
    unit === "min" ? `${Math.abs(Math.round(diff))} min` : unit === "h" ? formatHours(Math.abs(diff)) : `${Math.abs(diff).toFixed(unit === "" ? 0 : 1)}${unit === "pp" ? " pts" : unit}`;
  return (
    <span className={clsx("inline-flex items-center gap-0.5 text-xs font-medium", good ? "text-emerald-700" : "text-rose-700")}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {value} {unit === "min" ? (up ? "later" : "earlier") : ""} vs previous
    </span>
  );
}

function Tile({ Icon, label, value, sub, delta }: { Icon: LucideIcon; label: string; value: ReactNode; sub?: ReactNode; delta?: ReactNode }): JSX.Element {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <span className="flex items-center gap-2 text-xs font-medium text-gray-500">
        <Icon className="h-4 w-4 text-gray-400" aria-hidden /> {label}
      </span>
      <span className="text-2xl font-semibold tracking-tight text-gray-900">{value}</span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
      {delta}
    </div>
  );
}

function KpiSection({ data, people, latestLabel }: { data: AnalyticsOverview; people: string; latestLabel: string }): JSX.Element {
  const k = data.kpis;
  const p = k.previous;
  // No attendance at all last period (new install / system was off) -> a delta would just echo the current value.
  const hasPrev = p.present_person_days > 0;
  const presentPct = k.roster ? Math.round((k.present_latest_day / k.roster) * 100) : 0;
  return (
    <section className="grid grid-cols-1 gap-4 md:grid-cols-3 xl:grid-cols-6">
      {/* hero */}
      <div className="flex flex-col justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50 p-5 md:col-span-3 xl:col-span-2">
        <span className="text-sm font-medium text-brand-800">Attendance rate</span>
        <span className="text-5xl font-semibold tracking-tight text-gray-900">{formatPercent(k.attendance_pct)}</span>
        <span className="text-sm text-gray-600">
          of expected attendance days were present
          {data.working_days === 0 && " (no working days in range)"}
        </span>
        {hasPrev && <Delta now={k.attendance_pct} before={p.attendance_pct} unit="pp" />}
      </div>
      <Tile
        Icon={UserCheck}
        label={`Present ${latestLabel}`}
        value={
          <>
            {k.present_latest_day}
            <span className="text-base font-normal text-gray-400"> / {k.roster}</span>
          </>
        }
        sub={
          <span className="block">
            <span className="mb-1 block h-1.5 w-full overflow-hidden rounded-full bg-brand-100">
              <span className="block h-full rounded-full bg-brand-600" style={{ width: `${presentPct}%` }} />
            </span>
            {presentPct}% of active {people}
          </span>
        }
      />
      <Tile
        Icon={Clock}
        label="On-time rate"
        value={formatPercent(k.on_time_pct)}
        sub={`${k.late_count} late arrival${k.late_count === 1 ? "" : "s"}`}
        delta={hasPrev ? <Delta now={k.on_time_pct} before={p.on_time_pct} unit="pp" /> : undefined}
      />
      <Tile
        Icon={Timer}
        label="Avg arrival · hours"
        value={minutesToClock(k.avg_arrival_minutes)}
        sub={`${formatHours(k.avg_hours)} average day`}
        delta={
          hasPrev && k.avg_arrival_minutes >= 0 && p.avg_arrival_minutes >= 0 ? (
            <Delta now={k.avg_arrival_minutes} before={p.avg_arrival_minutes} unit="min" goodWhenUp={false} />
          ) : undefined
        }
      />
      <Tile
        Icon={ScanFace}
        label="Unknown visitors"
        value={k.unknown_visitors}
        sub="distinct unregistered faces"
        delta={hasPrev ? <Delta now={k.unknown_visitors} before={p.unknown_visitors} unit="" goodWhenUp={false} /> : undefined}
      />
    </section>
  );
}

// ------------------------------------------------------------- locations ----

function LocationsSection({ locations, people, latestLabel }: { locations: LocationStat[]; people: string; latestLabel: string }): JSX.Element {
  return (
    <section>
      <SectionTitle
        title="By camera / entry point"
        subtitle={`How many ${people} belong to each camera and how many are in ${latestLabel}. "Belong" = assigned home camera, else the camera they use most.`}
      />
      {locations.length === 0 ? (
        <Empty>No cameras have reported yet.</Empty>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {locations.map((l) => {
            const pct = l.roster ? Math.round((l.present_latest_day / l.roster) * 100) : 0;
            return (
              <div key={l.kiosk_id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2 text-sm font-semibold text-gray-800">
                    <Cctv className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                    <span className="truncate">{l.kiosk_id}</span>
                  </span>
                  <span className={clsx("inline-flex items-center gap-1 text-[11px] font-medium", l.online ? "text-emerald-700" : "text-gray-400")}>
                    <span className={clsx("h-1.5 w-1.5 rounded-full", l.online ? "bg-emerald-500" : "bg-gray-300")} />
                    {l.online ? "Online" : "Offline"}
                  </span>
                </div>
                <p className="mt-3 text-3xl font-semibold tracking-tight text-gray-900">
                  {l.present_latest_day}
                  <span className="text-lg font-normal text-gray-400"> / {l.roster}</span>
                </p>
                <p className="text-xs text-gray-500">present {latestLabel}</p>
                <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-brand-100" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={`${l.kiosk_id} present`}>
                  <div className="h-full rounded-full bg-brand-600" style={{ width: `${pct}%` }} />
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt className="text-gray-500">Absent</dt>
                    <dd className="font-semibold text-gray-800">{l.absent_latest_day}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Visitors</dt>
                    <dd className="font-semibold text-gray-800">{l.unknown_visitors_latest_day}</dd>
                  </div>
                  <div>
                    <dt className="text-gray-500">Period</dt>
                    <dd className="font-semibold text-gray-800">{formatPercent(l.attendance_pct)}</dd>
                  </div>
                </dl>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------- trend ----

function ChartTip({ active, payload, render }: TooltipProps<number, string> & { render: (row: Record<string, unknown>) => ReactNode }): JSX.Element | null {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as Record<string, unknown>;
  return <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">{render(row)}</div>;
}

function TrendSection({ data }: { data: AnalyticsOverview }): JSX.Element {
  const brand = useBrandColor(600);
  const points = data.trend.map((t) => ({ ...t, label: formatDay(t.date).slice(0, 6), rate: t.working_day ? t.attendance_pct : null }));
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <SectionTitle title="Daily attendance rate" subtitle="% of active people present each working day (weekends / off-days left blank)" />
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid vertical={false} stroke={INK.grid} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: INK.axis }} tickLine={false} axisLine={{ stroke: INK.grid }} minTickGap={16} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11, fill: INK.axis }} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ stroke: INK.axis, strokeWidth: 1 }}
              content={
                <ChartTip
                  render={(r) => (
                    <>
                      <p className="text-sm font-semibold text-gray-900">{r.working_day ? `${Number(r.attendance_pct).toFixed(1)}%` : "Off day"}</p>
                      <p className="text-gray-500">{formatDay(String(r.date))}</p>
                      <p className="text-gray-600">
                        {String(r.present)} of {String(r.roster)} present · {String(r.late)} late
                      </p>
                    </>
                  )}
                />
              }
            />
            <Area isAnimationActive={false} type="linear" dataKey="rate" stroke={brand} strokeWidth={2} fill={brand} fillOpacity={0.1} connectNulls={false} dot={{ r: 3, fill: brand, stroke: "#fff", strokeWidth: 2 }} activeDot={{ r: 5 }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

// ----------------------------------------------------- departments / arrival ----

function DepartmentSection({ data }: { data: AnalyticsOverview }): JSX.Element {
  const profile = useProfile();
  const brand = useBrandColor(600);
  const rows = data.departments.slice(0, 12);
  const height = Math.max(140, rows.length * 34 + 30);
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <SectionTitle title={`Attendance by ${profile.department_label.toLowerCase()}`} subtitle="Lowest first — the ones to follow up on" />
      {rows.length === 0 ? (
        <Empty>No data.</Empty>
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 44, bottom: 0, left: 0 }} barCategoryGap={8}>
              <CartesianGrid horizontal={false} stroke={INK.grid} />
              <XAxis type="number" domain={[0, 100]} ticks={[0, 50, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11, fill: INK.axis }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="department" width={120} tick={{ fontSize: 12, fill: "#52514e" }} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ fill: "rgba(0,0,0,0.03)" }}
                content={
                  <ChartTip
                    render={(r) => (
                      <>
                        <p className="text-sm font-semibold text-gray-900">{Number(r.attendance_pct).toFixed(1)}%</p>
                        <p className="text-gray-500">{String(r.department)}</p>
                        <p className="text-gray-600">
                          {String(r.roster)} people · {String(r.present_latest_day)} in latest day · {String(r.late_count)} late
                        </p>
                      </>
                    )}
                  />
                }
              />
              <Bar isAnimationActive={false} dataKey="attendance_pct" fill={brand} barSize={16} radius={[0, 4, 4, 0]}>
                <LabelList dataKey="attendance_pct" position="right" formatter={(v: number) => `${Math.round(v)}%`} style={{ fontSize: 11, fill: "#52514e" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function ArrivalSection({ data }: { data: AnalyticsOverview }): JSX.Element {
  const brand = useBrandColor(600);
  const total = data.arrivals.reduce((s, b) => s + b.count, 0);
  const peak = data.arrivals.reduce((best, b) => (b.count > best.count ? b : best), data.arrivals[0] ?? { bucket: "", count: 0, start_minutes: 0 });
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <SectionTitle
        title="When people arrive"
        subtitle={total ? `First entry of the day, 30-min slots · busiest ${peak.bucket} (${peak.count})` : "First entry of the day, 30-min slots"}
      />
      {total === 0 ? (
        <Empty>No arrivals recorded on working days in this period.</Empty>
      ) : (
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.arrivals} margin={{ top: 16, right: 8, bottom: 0, left: -20 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke={INK.grid} />
              <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: INK.axis }} tickLine={false} axisLine={{ stroke: INK.grid }} interval={1} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: INK.axis }} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ fill: "rgba(0,0,0,0.03)" }}
                content={
                  <ChartTip
                    render={(r) => (
                      <>
                        <p className="text-sm font-semibold text-gray-900">{String(r.count)} arrivals</p>
                        <p className="text-gray-500">{String(r.bucket)}</p>
                      </>
                    )}
                  />
                }
              />
              <Bar isAnimationActive={false} dataKey="count" fill={brand} maxBarSize={24} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- people ----

function PeopleList({
  title,
  subtitle,
  rows,
  metric,
  detail,
  meter,
  meterTone = "brand",
  empty,
}: {
  title: string;
  subtitle: string;
  rows: PersonStat[];
  metric: (r: PersonStat) => string;
  detail: (r: PersonStat) => string;
  meter: (r: PersonStat) => number;
  meterTone?: "brand" | "warning";
  empty: string;
}): JSX.Element {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <SectionTitle title={title} subtitle={subtitle} Icon={meterTone === "warning" ? TriangleAlert : Users} />
      {rows.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <ul className="divide-y divide-gray-100">
          {rows.map((r) => (
            <li key={r.employee_id} className="flex items-center gap-4 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">{r.name}</p>
                <p className="truncate text-xs text-gray-500">
                  {r.emp_code}
                  {r.department && ` · ${r.department}`}
                  {r.home_kiosk_id && ` · ${r.home_kiosk_id}`}
                </p>
              </div>
              <div className="hidden w-32 sm:block">
                <div className={clsx("h-1.5 w-full overflow-hidden rounded-full", meterTone === "warning" ? "bg-amber-100" : "bg-brand-100")}>
                  <div className={clsx("h-full rounded-full", meterTone === "warning" ? "bg-amber-500" : "bg-brand-600")} style={{ width: `${Math.min(100, meter(r))}%` }} />
                </div>
                <p className="mt-1 text-[11px] text-gray-500">{detail(r)}</p>
              </div>
              <span className="w-12 text-right text-sm font-semibold tabular-nums text-gray-900">{metric(r)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SummaryTable({ rows }: { rows: SummaryRowOut[] }): JSX.Element {
  const profile = useProfile();
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const n = q.trim().toLowerCase();
    return n ? rows.filter((r) => `${r.name ?? ""} ${r.face_id} ${r.department ?? ""}`.toLowerCase().includes(n)) : rows;
  }, [rows, q]);
  const columns = useMemo<ColumnDef<SummaryRowOut>[]>(
    () => [
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Name", accessorFn: (row) => row.name ?? row.label ?? "(unlabeled)" },
      { header: profile.department_label, accessorFn: (row) => row.department ?? "--" },
      { header: "Avg in", accessorFn: (row) => row.avg_in_time ?? "--" },
      { header: "Avg out", accessorFn: (row) => row.avg_out_time ?? "--" },
      { header: "Total hours", accessorFn: (row) => formatHours(row.total_hours) },
      { header: "Present", accessorKey: "present_days" },
      { header: "Absent", accessorKey: "absent_days" },
      { header: "Late", accessorKey: "late_count" },
      { header: "Early exit", accessorKey: "early_exit_count" },
      { header: "Attendance", accessorFn: (row) => formatPercent(row.attendance_pct) },
    ],
    [profile],
  );
  return (
    <>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search name, ID, department…"
        className="mb-3 w-full max-w-sm rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      />
      <DataTable data={shown} columns={columns} emptyMessage="No attendance data for this period." maxBodyHeight={480} />
    </>
  );
}

// ------------------------------------------------------------------ bits ----

function SectionTitle({ title, subtitle, Icon }: { title: string; subtitle?: string; Icon?: LucideIcon }): JSX.Element {
  return (
    <div className="mb-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-800">
        {Icon && <Icon className="h-4 w-4 text-gray-400" aria-hidden />}
        {title}
      </h2>
      {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}
    </div>
  );
}

function Empty({ children }: { children: ReactNode }): JSX.Element {
  return <p className="rounded-lg border border-dashed border-gray-200 p-6 text-center text-sm text-gray-500">{children}</p>;
}
