import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle2, ChevronDown, Loader2, RotateCcw, X } from "lucide-react";
import clsx from "clsx";
import { DataTable } from "../components/DataTable";
import { CorrectionModal } from "../components/CorrectionModal";
import { getDashboard, listEvents, toApiError } from "../api/client";
import { AuthImage } from "../components/AuthImage";
import type { AttendanceEventOut, DashboardTodayResponse } from "../api/types";
import { formatDateTime, formatSimilarity, todayIsoDate } from "../utils/format";
import { KpiCards } from "../components/dashboard/KpiCards";
import { DateRangePicker, EmpCodeFilter, UnitMultiSelect } from "../components/dashboard/FilterControls";
import { AttendanceTable, Pagination } from "../components/dashboard/AttendanceTable";
import { RecordDrawer } from "../components/dashboard/RecordDrawer";
import { useAuth } from "../auth/AuthContext";
import {
  KPI_LABELS,
  buildRange,
  buildRecords,
  clampToToday,
  countKpis,
  matchesEmpCode,
  matchesKiosks,
  matchesKpi,
  nextSort,
  sortRecords,
  type FilterState,
  type KPIFilterType,
  type SortKey,
  type AttendanceRecord,
  type SortState,
} from "../components/dashboard/model";

// Light polling keeps the kiosk-fed dashboard reasonably live without a
// websocket (single-site, ~100-employee deployment). Only while the selected
// range includes today -- historical ranges don't change.
const POLL_MS = 30_000;
const EVENTS_PAGE_SIZE = 100;

const KPI_DOT: Record<KPIFilterType, string> = {
  KNOWN_PRESENT: "bg-emerald-500",
  UNKNOWN_PRESENT: "bg-sky-500",
  ABSENT: "bg-rose-500",
  EXCEPTION: "bg-amber-500",
};

function defaultFilters(today: string): FilterState {
  return { kioskIds: null, dateRange: buildRange("day", today), activeKpiFilter: null, empCode: "" };
}

export function Dashboard(): JSX.Element {
  const today = todayIsoDate();

  const [filters, setFilters] = useState<FilterState>(() => defaultFilters(today));
  const [sort, setSort] = useState<SortState>({ key: null, direction: null });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const [data, setData] = useState<DashboardTodayResponse | null>(null);
  const [events, setEvents] = useState<AttendanceEventOut[]>([]);
  const [eventsTotal, setEventsTotal] = useState(0);
  const [showEvents, setShowEvents] = useState(false);
  const [correctingEvent, setCorrectingEvent] = useState<AttendanceEventOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [editing, setEditing] = useState<AttendanceRecord | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return undefined;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast]);

  // A dashboard left open overnight follows the calendar: if it was showing
  // the current day / month / year, move it to the new one after midnight.
  const shownToday = useRef(today);
  useEffect(() => {
    const prev = shownToday.current;
    if (prev === today) return;
    shownToday.current = today;
    setFilters((f) => {
      const r = f.dateRange;
      const wasCurrent = r.mode !== "custom" && r.from <= prev && prev <= r.to;
      return wasCurrent ? { ...f, dateRange: buildRange(r.mode, today) } : f;
    });
  }, [today]);

  // --- data loading --------------------------------------------------------
  const { date_from, date_to } = clampToToday(filters.dateRange, today);
  const rangeIncludesToday = date_from <= today && today <= filters.dateRange.to;
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setRefreshing(true);
    try {
      const [dash, ev] = await Promise.all([
        getDashboard({ date_from, date_to }),
        listEvents({ date_from, date_to, page: 1, page_size: EVENTS_PAGE_SIZE }),
      ]);
      if (seq !== requestSeq.current) return; // a newer range was requested meanwhile
      setData(dash);
      setEvents(ev.items);
      setEventsTotal(ev.total);
      setError(null);
    } catch (err) {
      if (seq === requestSeq.current) setError(toApiError(err).detail);
    } finally {
      if (seq === requestSeq.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [date_from, date_to]);

  useEffect(() => {
    void load();
    if (!rangeIncludesToday) return undefined;
    const interval = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(interval);
  }, [load, rangeIncludesToday]);

  // --- pipeline: records -> entry point -> KPI -> sort -> page -------------
  const allRecords = useMemo(() => (data ? buildRecords(data) : []), [data]);
  const scoped = useMemo(
    () =>
      allRecords.filter((r) => matchesKiosks(r, filters.kioskIds) && matchesEmpCode(r, filters.empCode)),
    [allRecords, filters.kioskIds, filters.empCode],
  );
  const kpiCounts = useMemo(() => countKpis(scoped), [scoped]);
  const filtered = useMemo(
    () => scoped.filter((r) => matchesKpi(r, filters.activeKpiFilter)),
    [scoped, filters.activeKpiFilter],
  );
  const sorted = useMemo(() => sortRecords(filtered, sort), [filtered, sort]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageRows = useMemo(
    () => sorted.slice((safePage - 1) * pageSize, safePage * pageSize),
    [sorted, safePage, pageSize],
  );

  const visibleEvents = useMemo(
    () => (filters.kioskIds === null ? events : events.filter((e) => filters.kioskIds?.includes(e.kiosk_id))),
    [events, filters.kioskIds],
  );

  // --- handlers (each resets to page 1) ------------------------------------
  const updateFilters = (patch: Partial<FilterState>): void => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };
  const toggleKpi = (kpi: KPIFilterType): void =>
    updateFilters({ activeKpiFilter: filters.activeKpiFilter === kpi ? null : kpi });
  const onSort = (key: SortKey): void => {
    setSort((s) => nextSort(s, key));
    setPage(1);
  };
  const resetAll = (): void => {
    setFilters(defaultFilters(today));
    setSort({ key: null, direction: null });
    setPage(1);
  };

  const isDirty =
    filters.activeKpiFilter !== null ||
    filters.kioskIds !== null ||
    filters.empCode !== "" ||
    filters.dateRange.mode !== "day" ||
    filters.dateRange.from !== today ||
    sort.key !== null;

  const multiDay = date_from !== date_to;

  const emptyMessage =
    filters.kioskIds?.length === 0
      ? "Select at least one entry point to view attendance."
      : filters.empCode
        ? `No records match emp ID "${filters.empCode}".`
        : filters.activeKpiFilter
          ? `No ${KPI_LABELS[filters.activeKpiFilter].toLowerCase()} records for this period.`
          : "No attendance records for this period.";

  // --- raw events table (unchanged behaviour, now range-aware) -------------
  const eventColumns = useMemo<ColumnDef<AttendanceEventOut>[]>(
    () => [
      { header: "Time", accessorFn: (row) => formatDateTime(row.occurred_at) },
      { header: "Entry point", accessorKey: "kiosk_id" },
      { header: "Type", accessorKey: "event_type" },
      { header: "Subject", accessorFn: (row) => row.subject_type ?? "REJECTED" },
      { header: "Similarity", accessorFn: (row) => formatSimilarity(row.similarity) },
      { header: "Liveness", accessorFn: (row) => formatSimilarity(row.liveness_score) },
      { header: "Reject reason", accessorFn: (row) => row.reject_reason ?? "--" },
      {
        header: "Crop",
        cell: ({ row }) => (
          <AuthImage
            path={row.original.crop_url}
            alt="face crop"
            className="h-10 w-10 rounded object-cover"
            fallback="--"
          />
        ),
      },
      {
        header: "Actions",
        cell: ({ row }) => (
          <button
            type="button"
            onClick={() => setCorrectingEvent(row.original)}
            className="rounded-md border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            Correct
          </button>
        ),
      },
    ],
    [],
  );

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-gray-500">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading dashboard...
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900">Attendance</h1>
          <p className="text-sm text-gray-500">
            {multiDay ? `${date_from} → ${date_to}` : date_from === today ? "Today" : date_from}
            {rangeIncludesToday && " · refreshes every 30s"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {refreshing && <Loader2 className="h-4 w-4 animate-spin text-gray-400" aria-label="Refreshing" />}
          {isDirty && (
            <button
              type="button"
              onClick={resetAll}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-100"
            >
              <RotateCcw className="h-4 w-4" aria-hidden /> Reset filters
            </button>
          )}
        </div>
      </header>

      {/* Filter bar */}
      <div className="flex flex-col gap-3 rounded-xl border border-gray-200 bg-white p-3 shadow-sm md:flex-row md:items-center">
        <UnitMultiSelect
          options={data?.kiosks ?? []}
          value={filters.kioskIds}
          onChange={(kioskIds) => updateFilters({ kioskIds })}
        />
        <EmpCodeFilter value={filters.empCode} onChange={(empCode) => updateFilters({ empCode })} />
        <div className="hidden h-6 w-px bg-gray-200 md:block" />
        <DateRangePicker value={filters.dateRange} onChange={(dateRange) => updateFilters({ dateRange })} today={today} />
      </div>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {/* KPI cards */}
      <KpiCards counts={kpiCounts} active={filters.activeKpiFilter} onToggle={toggleKpi} />

      {/* Attendance table */}
      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-gray-700">Attendance records</h2>
          {filters.activeKpiFilter && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 py-1 pl-3 pr-1 text-xs font-medium text-gray-700">
              <span className={clsx("h-1.5 w-1.5 rounded-full", KPI_DOT[filters.activeKpiFilter])} />
              {KPI_LABELS[filters.activeKpiFilter]}
              <button
                type="button"
                onClick={() => updateFilters({ activeKpiFilter: null })}
                className="rounded-full p-0.5 hover:bg-gray-200"
                aria-label="Clear KPI filter"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </span>
          )}
        </div>
        <AttendanceTable
          rows={pageRows}
          sort={sort}
          onSort={onSort}
          showDate={multiDay}
          emptyMessage={emptyMessage}
          onEdit={isAdmin ? setEditing : undefined}
        />
        <Pagination
          page={safePage}
          totalPages={totalPages}
          pageSize={pageSize}
          totalRows={sorted.length}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n);
            setPage(1);
          }}
        />
      </section>

      {/* Raw events + corrections */}
      <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <button
          type="button"
          onClick={() => setShowEvents((s) => !s)}
          aria-expanded={showEvents}
          className="flex w-full items-center justify-between px-4 py-3 text-left"
        >
          <span>
            <span className="text-sm font-semibold text-gray-700">Raw kiosk events</span>
            <span className="ml-2 text-xs text-gray-500">
              {visibleEvents.length}
              {eventsTotal > events.length && ` of ${eventsTotal} (latest ${EVENTS_PAGE_SIZE})`} · includes rejects ·
              use &ldquo;Correct&rdquo; to fix a misrecognition or wrong IN/OUT
            </span>
          </span>
          <ChevronDown className={clsx("h-4 w-4 text-gray-400 transition-transform", showEvents && "rotate-180")} aria-hidden />
        </button>
        {showEvents && (
          <div className="border-t border-gray-200 p-3">
            <DataTable
              data={visibleEvents}
              columns={eventColumns}
              emptyMessage="No events recorded for this period."
              maxBodyHeight={420}
              getRowId={(row) => row.id}
            />
          </div>
        )}
      </section>

      {editing && (
        <RecordDrawer
          record={editing}
          onClose={() => setEditing(null)}
          onChanged={(message) => {
            setEditing(null);
            setToast(message);
            void load();
          }}
        />
      )}

      {toast && (
        <div role="status" className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-gray-900 px-4 py-3 text-sm text-white shadow-lg">
          <span className="inline-flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden /> {toast}
          </span>
        </div>
      )}

      {correctingEvent && (
        <CorrectionModal
          event={correctingEvent}
          onClose={() => setCorrectingEvent(null)}
          onCorrected={() => {
            void load();
          }}
        />
      )}
    </div>
  );
}
