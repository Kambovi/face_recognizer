/**
 * Employee Attendance Dashboard
 * ------------------------------------------------------------------
 * Stack: React 18 + TypeScript + Tailwind CSS + lucide-react
 *
 * Component tree
 *   <AttendanceDashboard>            state owner (filters, sort, paging)
 *     <FilterBar>
 *       <UnitMultiSelect />          multi-unit / entry-point dropdown with "Select All"
 *       <DateRangePicker />          Day | Month | Year | Custom range
 *     <KpiCardGrid>
 *       <KpiCard /> x4               click-to-filter, toggle to clear
 *     <AttendanceTable>
 *       <SortableHeader />           asc -> desc -> default cycle
 *       <Avatar /> <StatusBadge /> <OnTimePill />
 *     <Pagination />
 *
 * Data pipeline (all memoised):
 *   MOCK_RECORDS
 *     -> scopedRecords   (unit + date filter)   => feeds KPI counts
 *     -> kpiRecords      (+ activeKpiFilter)
 *     -> sortedRecords   (+ sort state)
 *     -> pageRecords     (+ pagination)         => rendered rows
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Building2,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  RotateCcw,
  ScanFace,
  UserCheck,
  UserX,
  X,
} from 'lucide-react';

/* ================================================================== */
/*  1. Types                                                           */
/* ================================================================== */

/** The four KPI buckets. Every record belongs to exactly one. */
export type KPIFilterType = 'KNOWN_PRESENT' | 'UNKNOWN_PRESENT' | 'ABSENT' | 'EXCEPTION';

export interface Unit {
  id: string;
  name: string; // e.g. "Doctors"
  entryPoint: string; // camera / gate label, e.g. "OPD Block Entry"
}

export interface AttendanceRecord {
  id: string;
  date: string; // ISO date "YYYY-MM-DD"
  unit_id: string;
  category: KPIFilterType;
  photo: string | null; // avatar URL; null -> initials fallback
  face_id: string;
  name: string;
  designation: string;
  department: string;
  intime: string | null; // 24h "HH:mm" (formatted to 09:00 AM on render)
  outtime: string | null;
  total_hours: number | null;
  is_active: boolean;
  on_time: boolean | null; // null when not applicable (absent / unknown)
  exception_reason?: string;
}

export type DateRangeMode = 'day' | 'month' | 'year' | 'custom';

export interface DateRange {
  mode: DateRangeMode;
  from: string; // inclusive ISO date
  to: string; // inclusive ISO date
}

export interface FilterState {
  unitIds: string[];
  dateRange: DateRange;
  activeKpiFilter: KPIFilterType | null;
}

export type SortKey =
  | 'photo'
  | 'face_id'
  | 'name'
  | 'designation'
  | 'department'
  | 'intime'
  | 'outtime'
  | 'total_hours'
  | 'is_active'
  | 'on_time';

export type SortDirection = 'asc' | 'desc';

export interface SortState {
  key: SortKey | null;
  direction: SortDirection | null;
}

/* ================================================================== */
/*  2. Mock data                                                       */
/* ================================================================== */

/** Anchor date for the mock data set. Swap for `todayISO()` with a real API. */
export const MOCK_TODAY = '2026-09-23';

export const UNITS: Unit[] = [
  { id: 'u-staff', name: 'Staff', entryPoint: 'Main Gate – Cam 01' },
  { id: 'u-security', name: 'Security', entryPoint: 'Gate 2 – Cam 04' },
  { id: 'u-doctors', name: 'Doctors', entryPoint: 'OPD Block Entry – Cam 07' },
  { id: 'u-admin', name: 'Administrative', entryPoint: 'Admin Wing – Cam 10' },
];

const avatar = (n: number) => `https://i.pravatar.cc/80?img=${n}`;

export const MOCK_RECORDS: AttendanceRecord[] = [
  // ---- Known Present --------------------------------------------------
  {
    id: 'r1', date: MOCK_TODAY, unit_id: 'u-doctors', category: 'KNOWN_PRESENT',
    photo: avatar(47), face_id: 'FID-10231', name: 'Dr. Ananya Sharma',
    designation: 'Senior Consultant', department: 'Cardiology',
    intime: '08:52', outtime: '17:40', total_hours: 8.8, is_active: true, on_time: true,
  },
  {
    id: 'r2', date: MOCK_TODAY, unit_id: 'u-staff', category: 'KNOWN_PRESENT',
    photo: avatar(12), face_id: 'FID-10458', name: 'Rahul Verma',
    designation: 'Staff Nurse', department: 'Emergency',
    intime: '09:18', outtime: '17:35', total_hours: 8.3, is_active: true, on_time: false,
  },
  {
    id: 'r3', date: MOCK_TODAY, unit_id: 'u-security', category: 'KNOWN_PRESENT',
    photo: avatar(59), face_id: 'FID-10077', name: 'Imran Qureshi',
    designation: 'Security Supervisor', department: 'Security',
    intime: '07:55', outtime: '16:05', total_hours: 8.2, is_active: true, on_time: true,
  },
  {
    id: 'r4', date: MOCK_TODAY, unit_id: 'u-admin', category: 'KNOWN_PRESENT',
    photo: avatar(44), face_id: 'FID-10902', name: 'Priya Nair',
    designation: 'HR Executive', department: 'Human Resources',
    intime: '09:00', outtime: '17:30', total_hours: 8.5, is_active: true, on_time: true,
  },
  // ---- Unknown Present ------------------------------------------------
  {
    id: 'r5', date: MOCK_TODAY, unit_id: 'u-doctors', category: 'UNKNOWN_PRESENT',
    photo: null, face_id: 'UNK-0141', name: 'Unknown Person',
    designation: 'Unregistered', department: '—',
    intime: '10:12', outtime: '10:48', total_hours: 0.6, is_active: false, on_time: null,
  },
  {
    id: 'r6', date: MOCK_TODAY, unit_id: 'u-staff', category: 'UNKNOWN_PRESENT',
    photo: null, face_id: 'UNK-0142', name: 'Unknown Person',
    designation: 'Unregistered', department: '—',
    intime: '11:05', outtime: null, total_hours: null, is_active: false, on_time: null,
  },
  // ---- Absent ---------------------------------------------------------
  {
    id: 'r7', date: MOCK_TODAY, unit_id: 'u-doctors', category: 'ABSENT',
    photo: avatar(33), face_id: 'FID-10344', name: 'Dr. Karthik Iyer',
    designation: 'Resident Doctor', department: 'Orthopedics',
    intime: null, outtime: null, total_hours: null, is_active: true, on_time: null,
  },
  {
    id: 'r8', date: MOCK_TODAY, unit_id: 'u-security', category: 'ABSENT',
    photo: avatar(68), face_id: 'FID-10019', name: 'Suresh Pal',
    designation: 'Security Guard', department: 'Security',
    intime: null, outtime: null, total_hours: null, is_active: false, on_time: null,
  },
  // ---- Exception ------------------------------------------------------
  {
    id: 'r9', date: MOCK_TODAY, unit_id: 'u-admin', category: 'EXCEPTION',
    photo: avatar(15), face_id: 'FID-10611', name: 'Arjun Mehta',
    designation: 'Accounts Officer', department: 'Finance',
    intime: '09:40', outtime: null, total_hours: null, is_active: true, on_time: false,
    exception_reason: 'Missing out-punch',
  },
  {
    id: 'r10', date: MOCK_TODAY, unit_id: 'u-staff', category: 'EXCEPTION',
    photo: avatar(25), face_id: 'FID-10787', name: 'Fatima Khan',
    designation: 'Pharmacist', department: 'Pharmacy',
    intime: '08:58', outtime: '13:10', total_hours: 4.2, is_active: true, on_time: true,
    exception_reason: 'Early exit',
  },
  // ---- Historical (for date-range testing) ----------------------------
  {
    id: 'r11', date: '2026-09-22', unit_id: 'u-doctors', category: 'KNOWN_PRESENT',
    photo: avatar(47), face_id: 'FID-10231', name: 'Dr. Ananya Sharma',
    designation: 'Senior Consultant', department: 'Cardiology',
    intime: '08:45', outtime: '18:02', total_hours: 9.3, is_active: true, on_time: true,
  },
  {
    id: 'r12', date: '2026-08-14', unit_id: 'u-staff', category: 'EXCEPTION',
    photo: avatar(12), face_id: 'FID-10458', name: 'Rahul Verma',
    designation: 'Staff Nurse', department: 'Emergency',
    intime: '09:05', outtime: '21:30', total_hours: 12.4, is_active: true, on_time: false,
    exception_reason: 'Overtime > 12 hrs',
  },
];

/* ================================================================== */
/*  3. Helpers                                                         */
/* ================================================================== */

const pad = (n: number) => String(n).padStart(2, '0');

/** "HH:mm" -> "09:00 AM" */
export function formatTime(t: string | null): string {
  if (!t) return '—';
  const [h, m] = t.split(':').map(Number);
  const suffix = h >= 12 ? 'PM' : 'AM';
  return `${pad(h % 12 || 12)}:${m.toString().padStart(2, '0')} ${suffix}`;
}

/** Builds an inclusive [from, to] ISO range from a mode + anchor date. */
export function buildRange(mode: DateRangeMode, anchor: string, customTo?: string): DateRange {
  const [y, m] = anchor.split('-').map(Number);
  switch (mode) {
    case 'day':
      return { mode, from: anchor, to: anchor };
    case 'month': {
      const last = new Date(y, m, 0).getDate(); // m is 1-based -> day 0 of next month
      return { mode, from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last)}` };
    }
    case 'year':
      return { mode, from: `${y}-01-01`, to: `${y}-12-31` };
    case 'custom': {
      const to = customTo ?? anchor;
      return anchor <= to ? { mode, from: anchor, to } : { mode, from: to, to: anchor };
    }
  }
}

/** Value used for sorting each column. `null` always sorts last. */
const SORT_ACCESSORS: Record<SortKey, (r: AttendanceRecord) => string | number | null> = {
  photo: (r) => (r.photo ? 1 : 0),
  face_id: (r) => r.face_id,
  name: (r) => r.name,
  designation: (r) => r.designation,
  department: (r) => r.department,
  intime: (r) => r.intime, // "HH:mm" sorts correctly as a string
  outtime: (r) => r.outtime,
  total_hours: (r) => r.total_hours,
  is_active: (r) => (r.is_active ? 1 : 0),
  on_time: (r) => (r.on_time === null ? null : r.on_time ? 1 : 0),
};

function sortRecords(rows: AttendanceRecord[], sort: SortState): AttendanceRecord[] {
  if (!sort.key || !sort.direction) return rows;
  const get = SORT_ACCESSORS[sort.key];
  const dir = sort.direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
    return String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: 'base' }) * dir;
  });
}

const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(' ');

/* ================================================================== */
/*  4. KPI configuration                                               */
/* ================================================================== */

// Tailwind needs complete class strings (no dynamic interpolation) so JIT can see them.
const KPI_CONFIG: Record<
  KPIFilterType,
  { label: string; hint: string; Icon: React.ElementType; iconWrap: string; active: string; bar: string }
> = {
  KNOWN_PRESENT: {
    label: 'Known Present', hint: 'Recognised employees',
    Icon: UserCheck, iconWrap: 'bg-emerald-50 text-emerald-600',
    active: 'border-emerald-500 ring-2 ring-emerald-500/20 shadow-md', bar: 'bg-emerald-500',
  },
  UNKNOWN_PRESENT: {
    label: 'Unknown Present', hint: 'Unregistered faces',
    Icon: ScanFace, iconWrap: 'bg-sky-50 text-sky-600',
    active: 'border-sky-500 ring-2 ring-sky-500/20 shadow-md', bar: 'bg-sky-500',
  },
  ABSENT: {
    label: 'Absent', hint: 'No check-in recorded',
    Icon: UserX, iconWrap: 'bg-rose-50 text-rose-600',
    active: 'border-rose-500 ring-2 ring-rose-500/20 shadow-md', bar: 'bg-rose-500',
  },
  EXCEPTION: {
    label: 'Exception', hint: 'Missed punch, early exit…',
    Icon: AlertTriangle, iconWrap: 'bg-amber-50 text-amber-600',
    active: 'border-amber-500 ring-2 ring-amber-500/20 shadow-md', bar: 'bg-amber-500',
  },
};

const KPI_ORDER: KPIFilterType[] = ['KNOWN_PRESENT', 'UNKNOWN_PRESENT', 'ABSENT', 'EXCEPTION'];

/* ================================================================== */
/*  5. Main component                                                  */
/* ================================================================== */

const DEFAULT_FILTERS: FilterState = {
  unitIds: UNITS.map((u) => u.id),
  dateRange: buildRange('day', MOCK_TODAY),
  activeKpiFilter: null,
};

export default function AttendanceDashboard({
  records = MOCK_RECORDS,
  units = UNITS,
}: {
  records?: AttendanceRecord[];
  units?: Unit[];
}) {
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<SortState>({ key: null, direction: null });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(5);

  // --- Pipeline -------------------------------------------------------
  const scopedRecords = useMemo(() => {
    const unitSet = new Set(filters.unitIds);
    const { from, to } = filters.dateRange;
    return records.filter((r) => unitSet.has(r.unit_id) && r.date >= from && r.date <= to);
  }, [records, filters.unitIds, filters.dateRange]);

  const kpiCounts = useMemo(() => {
    const counts: Record<KPIFilterType, number> = { KNOWN_PRESENT: 0, UNKNOWN_PRESENT: 0, ABSENT: 0, EXCEPTION: 0 };
    scopedRecords.forEach((r) => counts[r.category]++);
    return counts;
  }, [scopedRecords]);

  const kpiRecords = useMemo(
    () => (filters.activeKpiFilter ? scopedRecords.filter((r) => r.category === filters.activeKpiFilter) : scopedRecords),
    [scopedRecords, filters.activeKpiFilter],
  );

  const sortedRecords = useMemo(() => sortRecords(kpiRecords, sort), [kpiRecords, sort]);

  const totalPages = Math.max(1, Math.ceil(sortedRecords.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRecords = useMemo(
    () => sortedRecords.slice((safePage - 1) * pageSize, safePage * pageSize),
    [sortedRecords, safePage, pageSize],
  );

  // Jump back to page 1 whenever the result set changes shape.
  useEffect(() => setPage(1), [filters, sort, pageSize]);

  // --- Handlers -------------------------------------------------------
  const toggleKpi = (kpi: KPIFilterType) =>
    setFilters((f) => ({ ...f, activeKpiFilter: f.activeKpiFilter === kpi ? null : kpi }));

  const cycleSort = (key: SortKey) =>
    setSort((s) => {
      if (s.key !== key) return { key, direction: 'asc' };
      if (s.direction === 'asc') return { key, direction: 'desc' };
      return { key: null, direction: null }; // back to default order
    });

  const resetAll = () => {
    setFilters(DEFAULT_FILTERS);
    setSort({ key: null, direction: null });
  };

  const isDirty =
    filters.activeKpiFilter !== null ||
    filters.unitIds.length !== units.length ||
    filters.dateRange.from !== DEFAULT_FILTERS.dateRange.from ||
    filters.dateRange.to !== DEFAULT_FILTERS.dateRange.to ||
    sort.key !== null;

  return (
    <div className="min-h-screen bg-slate-50 p-4 text-slate-900 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        {/* Header */}
        <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Attendance Dashboard</h1>
            <p className="text-sm text-slate-500">Face-recognition attendance across units and entry points</p>
          </div>
          {isDirty && (
            <button
              onClick={resetAll}
              className="inline-flex items-center gap-1.5 self-start rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-200/60 sm:self-auto"
            >
              <RotateCcw className="h-4 w-4" /> Reset filters
            </button>
          )}
        </header>

        {/* Filter bar */}
        <FilterBar
          units={units}
          unitIds={filters.unitIds}
          onUnitIdsChange={(unitIds) => setFilters((f) => ({ ...f, unitIds }))}
          dateRange={filters.dateRange}
          onDateRangeChange={(dateRange) => setFilters((f) => ({ ...f, dateRange }))}
        />

        {/* KPI cards */}
        <KpiCardGrid counts={kpiCounts} active={filters.activeKpiFilter} onToggle={toggleKpi} />

        {/* Table */}
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-700">Attendance records</h2>
            {filters.activeKpiFilter && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 py-1 pl-3 pr-1 text-xs font-medium text-slate-700">
                <span className={cx('h-1.5 w-1.5 rounded-full', KPI_CONFIG[filters.activeKpiFilter].bar)} />
                {KPI_CONFIG[filters.activeKpiFilter].label}
                <button
                  onClick={() => setFilters((f) => ({ ...f, activeKpiFilter: null }))}
                  className="rounded-full p-0.5 hover:bg-slate-200"
                  aria-label="Clear KPI filter"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            )}
          </div>

          <AttendanceTable rows={pageRecords} sort={sort} onSort={cycleSort} noUnits={filters.unitIds.length === 0} />

          <Pagination
            page={safePage}
            totalPages={totalPages}
            pageSize={pageSize}
            totalRows={sortedRecords.length}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </section>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  6. Filter bar                                                      */
/* ================================================================== */

function FilterBar(props: {
  units: Unit[];
  unitIds: string[];
  onUnitIdsChange: (ids: string[]) => void;
  dateRange: DateRange;
  onDateRangeChange: (r: DateRange) => void;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm md:flex-row md:items-center">
      <UnitMultiSelect units={props.units} value={props.unitIds} onChange={props.onUnitIdsChange} />
      <div className="hidden h-6 w-px bg-slate-200 md:block" />
      <DateRangePicker value={props.dateRange} onChange={props.onDateRangeChange} />
    </div>
  );
}

/* ---------------- Unit / entry-point multi-select ---------------- */

function UnitMultiSelect({ units, value, onChange }: { units: Unit[]; value: string[]; onChange: (ids: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const allSelected = value.length === units.length;
  const someSelected = value.length > 0 && !allSelected;

  // Native checkboxes only expose `indeterminate` as a DOM property.
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected, open]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !rootRef.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggleOne = (id: string) =>
    onChange(value.includes(id) ? value.filter((v) => v !== id) : units.filter((u) => u.id === id || value.includes(u.id)).map((u) => u.id));

  const toggleAll = () => onChange(allSelected ? [] : units.map((u) => u.id));

  const label = allSelected
    ? 'All units'
    : value.length === 0
      ? 'No units selected'
      : value.length <= 2
        ? units.filter((u) => value.includes(u.id)).map((u) => u.name).join(', ')
        : `${value.length} of ${units.length} units`;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm hover:border-slate-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40 md:w-64"
      >
        <Building2 className="h-4 w-4 shrink-0 text-slate-400" />
        <span className={cx('flex-1 truncate text-left', value.length === 0 && 'text-rose-600')}>{label}</span>
        <ChevronDown className={cx('h-4 w-4 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute left-0 z-30 mt-2 w-full min-w-[18rem] rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg md:w-72">
          <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium hover:bg-slate-50">
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            Select all
            <span className="ml-auto text-xs font-normal text-slate-400">{value.length}/{units.length}</span>
          </label>
          <div className="my-1 h-px bg-slate-100" />
          <ul role="listbox" aria-multiselectable="true" className="max-h-64 overflow-y-auto">
            {units.map((u) => {
              const checked = value.includes(u.id);
              return (
                <li key={u.id} role="option" aria-selected={checked}>
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOne(u.id)}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <span className="flex flex-col">
                      <span className="font-medium text-slate-800">{u.name}</span>
                      <span className="text-xs text-slate-500">{u.entryPoint}</span>
                    </span>
                    {checked && <Check className="ml-auto mt-0.5 h-4 w-4 text-indigo-600" />}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ---------------- Date range picker ---------------- */

const MODES: { id: DateRangeMode; label: string }[] = [
  { id: 'day', label: 'Day' },
  { id: 'month', label: 'Month' },
  { id: 'year', label: 'Year' },
  { id: 'custom', label: 'Range' },
];

const YEAR_OPTIONS = Array.from({ length: 6 }, (_, i) => Number(MOCK_TODAY.slice(0, 4)) - i);

function DateRangePicker({ value, onChange }: { value: DateRange; onChange: (r: DateRange) => void }) {
  const inputCls =
    'rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20';

  const switchMode = (mode: DateRangeMode) =>
    onChange(buildRange(mode, value.from, mode === 'custom' ? value.to : undefined));

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="flex items-center gap-2">
        <CalendarDays className="h-4 w-4 text-slate-400" />
        <div role="tablist" className="inline-flex rounded-lg bg-slate-100 p-0.5">
          {MODES.map((m) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={value.mode === m.id}
              onClick={() => switchMode(m.id)}
              className={cx(
                'rounded-md px-3 py-1.5 text-xs font-medium transition',
                value.mode === m.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {value.mode === 'day' && (
          <input
            type="date"
            value={value.from}
            max={MOCK_TODAY}
            onChange={(e) => e.target.value && onChange(buildRange('day', e.target.value))}
            className={inputCls}
          />
        )}
        {value.mode === 'month' && (
          <input
            type="month"
            value={value.from.slice(0, 7)}
            max={MOCK_TODAY.slice(0, 7)}
            onChange={(e) => e.target.value && onChange(buildRange('month', `${e.target.value}-01`))}
            className={inputCls}
          />
        )}
        {value.mode === 'year' && (
          <select
            value={value.from.slice(0, 4)}
            onChange={(e) => onChange(buildRange('year', `${e.target.value}-01-01`))}
            className={inputCls}
          >
            {YEAR_OPTIONS.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        )}
        {value.mode === 'custom' && (
          <>
            <input
              type="date"
              value={value.from}
              max={value.to}
              onChange={(e) => e.target.value && onChange(buildRange('custom', e.target.value, value.to))}
              className={inputCls}
              aria-label="From date"
            />
            <span className="text-sm text-slate-400">to</span>
            <input
              type="date"
              value={value.to}
              min={value.from}
              max={MOCK_TODAY}
              onChange={(e) => e.target.value && onChange(buildRange('custom', value.from, e.target.value))}
              className={inputCls}
              aria-label="To date"
            />
          </>
        )}
      </div>
    </div>
  );
}

/* ================================================================== */
/*  7. KPI cards                                                       */
/* ================================================================== */

function KpiCardGrid({
  counts,
  active,
  onToggle,
}: {
  counts: Record<KPIFilterType, number>;
  active: KPIFilterType | null;
  onToggle: (k: KPIFilterType) => void;
}) {
  const total = KPI_ORDER.reduce((s, k) => s + counts[k], 0);
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {KPI_ORDER.map((k) => (
        <KpiCard key={k} kpi={k} count={counts[k]} total={total} isActive={active === k} dimmed={active !== null && active !== k} onClick={() => onToggle(k)} />
      ))}
    </div>
  );
}

function KpiCard({
  kpi, count, total, isActive, dimmed, onClick,
}: {
  kpi: KPIFilterType; count: number; total: number; isActive: boolean; dimmed: boolean; onClick: () => void;
}) {
  const cfg = KPI_CONFIG[kpi];
  const pct = total ? Math.round((count / total) * 100) : 0;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      title={isActive ? 'Click to show all records' : `Show only ${cfg.label}`}
      className={cx(
        'group relative flex flex-col gap-4 rounded-xl border bg-white p-4 text-left transition-all',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
        isActive ? cfg.active : 'border-slate-200 shadow-sm hover:-translate-y-0.5 hover:shadow-md',
        dimmed && 'opacity-60 hover:opacity-100',
      )}
    >
      <div className="flex items-start justify-between">
        <span className={cx('rounded-lg p-2', cfg.iconWrap)}>
          <cfg.Icon className="h-5 w-5" />
        </span>
        {isActive ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white">
            Filtering <X className="h-3 w-3" />
          </span>
        ) : (
          <span className="text-xs text-slate-400">{pct}%</span>
        )}
      </div>
      <div>
        <p className="text-3xl font-semibold tabular-nums tracking-tight">{count}</p>
        <p className="mt-0.5 text-sm font-medium text-slate-700">{cfg.label}</p>
        <p className="text-xs text-slate-500">{cfg.hint}</p>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={cx('h-full rounded-full transition-all', cfg.bar)} style={{ width: `${pct}%` }} />
      </div>
    </button>
  );
}

/* ================================================================== */
/*  8. Table                                                           */
/* ================================================================== */

const COLUMNS: { key: SortKey; label: string; align?: 'right' | 'center' }[] = [
  { key: 'photo', label: 'Photo' },
  { key: 'face_id', label: 'Face ID' },
  { key: 'name', label: 'Name' },
  { key: 'designation', label: 'Designation' },
  { key: 'department', label: 'Department' },
  { key: 'intime', label: 'In Time' },
  { key: 'outtime', label: 'Out Time' },
  { key: 'total_hours', label: 'Total Hours', align: 'right' },
  { key: 'is_active', label: 'Status' },
  { key: 'on_time', label: 'On Time' },
];

function AttendanceTable({
  rows, sort, onSort, noUnits,
}: {
  rows: AttendanceRecord[]; sort: SortState; onSort: (k: SortKey) => void; noUnits: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            {COLUMNS.map((c) => (
              <SortableHeader key={c.key} column={c} sort={sort} onSort={onSort} />
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length} className="px-4 py-16 text-center text-sm text-slate-500">
                {noUnits ? 'Select at least one unit to view attendance.' : 'No records match the current filters.'}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r.id} className="transition-colors hover:bg-slate-50/70">
                <td className="px-4 py-3"><Avatar record={r} /></td>
                <td className="whitespace-nowrap px-4 py-3">
                  <span
                    className={cx(
                      'rounded-md px-2 py-0.5 font-mono text-xs',
                      r.category === 'UNKNOWN_PRESENT' ? 'bg-sky-50 text-sky-700' : 'bg-slate-100 text-slate-700',
                    )}
                  >
                    {r.face_id}
                  </span>
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <div className="font-medium text-slate-900">{r.name}</div>
                  {r.exception_reason && (
                    <div className="mt-0.5 inline-flex items-center gap-1 text-xs text-amber-700">
                      <AlertTriangle className="h-3 w-3" /> {r.exception_reason}
                    </div>
                  )}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{r.designation}</td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{r.department}</td>
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-slate-700">{formatTime(r.intime)}</td>
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-slate-700">{formatTime(r.outtime)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-700">
                  {r.total_hours !== null ? `${r.total_hours.toFixed(1)} hrs` : '—'}
                </td>
                <td className="px-4 py-3"><StatusBadge active={r.is_active} /></td>
                <td className="px-4 py-3"><OnTimePill value={r.on_time} /></td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function SortableHeader({
  column, sort, onSort,
}: {
  column: (typeof COLUMNS)[number]; sort: SortState; onSort: (k: SortKey) => void;
}) {
  const isSorted = sort.key === column.key && sort.direction !== null;
  const Icon = !isSorted ? ArrowUpDown : sort.direction === 'asc' ? ArrowUp : ArrowDown;
  return (
    <th
      scope="col"
      aria-sort={isSorted ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cx('whitespace-nowrap px-4 py-3 font-medium', column.align === 'right' ? 'text-right' : 'text-left')}
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className={cx(
          'group inline-flex items-center gap-1.5 text-xs uppercase tracking-wide',
          isSorted ? 'text-slate-900' : 'text-slate-500 hover:text-slate-800',
        )}
      >
        {column.label}
        <Icon className={cx('h-3.5 w-3.5', isSorted ? 'text-indigo-600' : 'text-slate-300 group-hover:text-slate-500')} />
      </button>
    </th>
  );
}

function Avatar({ record }: { record: AttendanceRecord }) {
  const [broken, setBroken] = useState(false);
  if (record.photo && !broken) {
    return (
      <img
        src={record.photo}
        alt={record.name}
        onError={() => setBroken(true)}
        className="h-9 w-9 rounded-full object-cover ring-2 ring-white shadow-sm"
      />
    );
  }
  if (record.category === 'UNKNOWN_PRESENT') {
    return (
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-sky-50 text-sky-600 ring-1 ring-sky-200">
        <ScanFace className="h-4 w-4" />
      </span>
    );
  }
  const initials = record.name.replace(/^Dr\.?\s*/i, '').split(' ').map((p) => p[0]).slice(0, 2).join('');
  return (
    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-600">
      {initials}
    </span>
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        active ? 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' : 'bg-slate-50 text-slate-500 ring-slate-500/20',
      )}
    >
      <span className={cx('h-1.5 w-1.5 rounded-full', active ? 'bg-emerald-500' : 'bg-slate-400')} />
      {active ? 'Active' : 'Inactive'}
    </span>
  );
}

function OnTimePill({ value }: { value: boolean | null }) {
  if (value === null) return <span className="text-slate-400">—</span>;
  return (
    <span
      className={cx(
        'inline-flex min-w-[2.75rem] justify-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        value ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
      )}
    >
      {value ? 'Yes' : 'No'}
    </span>
  );
}

/* ================================================================== */
/*  9. Pagination                                                      */
/* ================================================================== */

function Pagination({
  page, totalPages, pageSize, totalRows, onPageChange, onPageSizeChange,
}: {
  page: number; totalPages: number; pageSize: number; totalRows: number;
  onPageChange: (p: number) => void; onPageSizeChange: (s: number) => void;
}) {
  const start = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalRows);

  // Compact page list: 1 … 4 5 6 … 20
  const pages = useMemo(() => {
    const out: (number | '…')[] = [];
    for (let p = 1; p <= totalPages; p++) {
      if (p === 1 || p === totalPages || Math.abs(p - page) <= 1) out.push(p);
      else if (out[out.length - 1] !== '…') out.push('…');
    }
    return out;
  }, [page, totalPages]);

  const btn =
    'inline-flex h-8 min-w-[2rem] items-center justify-center rounded-md px-2 text-sm text-slate-600 hover:bg-slate-100 disabled:pointer-events-none disabled:opacity-40';

  return (
    <div className="flex flex-col gap-3 border-t border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span>
          Showing <span className="font-medium text-slate-700">{start}–{end}</span> of{' '}
          <span className="font-medium text-slate-700">{totalRows}</span> records
        </span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          aria-label="Rows per page"
        >
          {[5, 10, 25, 50].map((n) => (
            <option key={n} value={n}>{n} / page</option>
          ))}
        </select>
      </div>

      <nav className="flex items-center gap-1" aria-label="Pagination">
        <button className={btn} onClick={() => onPageChange(1)} disabled={page === 1} aria-label="First page">
          <ChevronsLeft className="h-4 w-4" />
        </button>
        <button className={btn} onClick={() => onPageChange(page - 1)} disabled={page === 1} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </button>
        {pages.map((p, i) =>
          p === '…' ? (
            <span key={`gap-${i}`} className="px-1 text-slate-400">…</span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p)}
              aria-current={p === page ? 'page' : undefined}
              className={cx(btn, p === page && 'bg-indigo-600 font-medium text-white hover:bg-indigo-600')}
            >
              {p}
            </button>
          ),
        )}
        <button className={btn} onClick={() => onPageChange(page + 1)} disabled={page === totalPages} aria-label="Next page">
          <ChevronRight className="h-4 w-4" />
        </button>
        <button className={btn} onClick={() => onPageChange(totalPages)} disabled={page === totalPages} aria-label="Last page">
          <ChevronsRight className="h-4 w-4" />
        </button>
      </nav>
    </div>
  );
}
