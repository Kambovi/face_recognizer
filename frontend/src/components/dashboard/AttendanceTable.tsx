import { useMemo } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Pencil,
  ScanFace,
  TriangleAlert,
} from "lucide-react";
import clsx from "clsx";
import { AuthImage } from "../AuthImage";
import { useProfile } from "../../profile/ProfileContext";
import { formatClock, formatDay, humanizeKind, type AttendanceRecord, type SortKey, type SortState } from "./model";

interface Column {
  key: SortKey;
  label: string;
  align?: "right";
}

const BASE_COLUMNS: Column[] = [
  { key: "photo", label: "Photo" },
  { key: "face_id", label: "Face ID" },
  { key: "emp_code", label: "ID" },
  { key: "name", label: "Name" },
  { key: "department", label: "Department" },
  { key: "intime", label: "In Time" },
  { key: "outtime", label: "Out Time" },
  { key: "total_hours", label: "Total Hours", align: "right" },
  { key: "is_active", label: "Status" },
  { key: "on_time", label: "On Time" },
];

interface AttendanceTableProps {
  rows: AttendanceRecord[]; // current page only
  sort: SortState;
  onSort: (key: SortKey) => void;
  /** Adds a Date column when the range spans more than one day. */
  showDate: boolean;
  emptyMessage: string;
  /** Admins get an Edit button per row (opens the dashboard edit drawer). */
  onEdit?: (row: AttendanceRecord) => void;
}

export function AttendanceTable({ rows, sort, onSort, showDate, emptyMessage, onEdit }: AttendanceTableProps): JSX.Element {
  const profile = useProfile();
  const columns = useMemo<Column[]>(() => {
    const base = BASE_COLUMNS.map((c) =>
      c.key === "emp_code"
        ? { ...c, label: profile.id_label }
        : c.key === "department"
          ? { ...c, label: profile.department_label }
          : c,
    );
    return showDate ? [{ key: "date" as SortKey, label: "Date" }, ...base] : base;
  }, [showDate, profile]);
  const colCount = columns.length + (onEdit ? 1 : 0);

  return (
    <>
      {/* Phones: one card per person instead of a 10-column table. */}
      <ul className="divide-y divide-gray-100 md:hidden">
        {rows.length === 0 && <li className="px-4 py-12 text-center text-sm text-gray-500">{emptyMessage}</li>}
        {rows.map((r) => (
          <li key={r.key}>
            <button
              type="button"
              disabled={!(onEdit && r.subject_id)}
              onClick={onEdit && r.subject_id ? () => onEdit(r) : undefined}
              className="flex w-full items-start gap-3 px-4 py-3 text-left enabled:active:bg-gray-50"
            >
              <Avatar record={r} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-gray-900">{r.name}</span>
                  <span className="shrink-0 tabular-nums text-xs text-gray-500">
                    {formatClock(r.intime)}
                    {r.outtime ? ` – ${formatClock(r.outtime)}` : ""}
                  </span>
                </span>
                <span className="block truncate text-xs text-gray-500">
                  {showDate ? `${formatDay(r.date)} · ` : ""}
                  {r.emp_code ?? r.face_id}
                  {r.department ? ` · ${r.department}` : ""}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-1">
                  <StatusBadge record={r} />
                  <OnTimePill value={r.on_time} />
                  {r.exceptions.map((x, i) => (
                    <span
                      key={`${x.kind}-${i}`}
                      className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800"
                    >
                      <TriangleAlert className="h-3 w-3" aria-hidden />
                      {humanizeKind(x.kind)}
                    </span>
                  ))}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    <div className="hidden overflow-x-auto md:block">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((c) => (
              <SortableHeader key={c.key} column={c} sort={sort} onSort={onSort} />
            ))}
            {onEdit && <th scope="col" className="sticky right-0 bg-gray-50 px-3 py-3" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={colCount} className="px-4 py-16 text-center text-sm text-gray-500">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr
                key={r.key}
                className={clsx("transition-colors hover:bg-gray-50/70", onEdit && r.subject_id && "cursor-pointer")}
                onClick={onEdit && r.subject_id ? () => onEdit(r) : undefined}
              >
                {showDate && <td className="whitespace-nowrap px-3 py-3 text-gray-600">{formatDay(r.date)}</td>}
                <td className="px-3 py-3">
                  <Avatar record={r} />
                </td>
                <td className="whitespace-nowrap px-3 py-3">
                  <span
                    className={clsx(
                      "rounded-md px-2 py-0.5 font-mono text-xs",
                      r.category === "UNKNOWN_PRESENT" ? "bg-sky-50 text-sky-700" : "bg-gray-100 text-gray-700",
                    )}
                  >
                    {r.face_id}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-gray-600">{r.emp_code ?? "--"}</td>
                <td className="px-3 py-3">
                  <div className="whitespace-nowrap font-medium text-gray-900">{r.name}</div>
                  {r.designation && <div className="whitespace-nowrap text-xs text-gray-500">{r.designation}</div>}
                  {r.exceptions.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {r.exceptions.map((x, i) => (
                        <span
                          key={`${x.kind}-${i}`}
                          title={x.detail}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800"
                        >
                          <TriangleAlert className="h-3 w-3" aria-hidden />
                          {humanizeKind(x.kind)}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-gray-600">{r.department ?? "--"}</td>
                <td className="whitespace-nowrap px-3 py-3 tabular-nums text-gray-700">{formatClock(r.intime)}</td>
                <td className="whitespace-nowrap px-3 py-3 tabular-nums text-gray-700">{formatClock(r.outtime)}</td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums text-gray-700">
                  {r.total_hours !== null ? `${r.total_hours.toFixed(1)} hrs` : "--"}
                </td>
                <td className="px-3 py-3">
                  <StatusBadge record={r} />
                </td>
                <td className="px-3 py-3">
                  <OnTimePill value={r.on_time} />
                </td>
                {onEdit && (
                  <td className="sticky right-0 bg-white px-3 py-3 text-right shadow-[-8px_0_8px_-8px_rgba(0,0,0,0.08)]">
                    {r.subject_id && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit(r);
                        }}
                        className={clsx(
                          "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold",
                          r.category === "UNKNOWN_PRESENT"
                            ? "bg-brand-600 text-white hover:bg-brand-700"
                            : "border border-gray-300 text-gray-700 hover:bg-gray-50",
                        )}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                        {r.category === "UNKNOWN_PRESENT" ? "Identify" : "Edit"}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
    </>
  );
}

function SortableHeader({ column, sort, onSort }: { column: Column; sort: SortState; onSort: (k: SortKey) => void }): JSX.Element {
  const isSorted = sort.key === column.key && sort.direction !== null;
  const Icon = !isSorted ? ArrowUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      scope="col"
      aria-sort={isSorted ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
      className={clsx("whitespace-nowrap px-3 py-3 font-medium", column.align === "right" ? "text-right" : "text-left")}
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className={clsx(
          "group inline-flex items-center gap-1.5 text-xs uppercase tracking-wide",
          isSorted ? "text-gray-900" : "text-gray-500 hover:text-gray-800",
        )}
      >
        {column.label}
        <Icon
          className={clsx("h-3.5 w-3.5", isSorted ? "text-brand-600" : "text-gray-300 group-hover:text-gray-500")}
          aria-hidden
        />
      </button>
    </th>
  );
}

function Avatar({ record }: { record: AttendanceRecord }): JSX.Element {
  const fallback =
    record.category === "UNKNOWN_PRESENT" || record.category === "EXCEPTION" ? (
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 text-gray-400">
        <ScanFace className="h-4 w-4" aria-hidden />
      </span>
    ) : (
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-600">
        {record.name
          .replace(/^Dr\.?\s*/i, "")
          .split(/\s+/)
          .map((p) => p.charAt(0))
          .slice(0, 2)
          .join("")
          .toUpperCase()}
      </span>
    );
  return (
    <AuthImage
      path={record.photo}
      alt={`${record.name} face crop`}
      className="h-10 w-10 rounded-full object-cover shadow-sm ring-2 ring-white"
      fallback={fallback}
    />
  );
}

function StatusBadge({ record }: { record: AttendanceRecord }): JSX.Element {
  if (record.is_active === null) {
    if (!record.subject_status) return <span className="text-gray-400">--</span>;
    return (
      <span className="inline-flex items-center rounded-md bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700 ring-1 ring-inset ring-sky-600/20">
        {humanizeKind(record.subject_status.toLowerCase())}
      </span>
    );
  }
  const active = record.is_active;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        active ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-gray-50 text-gray-500 ring-gray-500/20",
      )}
    >
      <span className={clsx("h-1.5 w-1.5 rounded-full", active ? "bg-emerald-500" : "bg-gray-400")} />
      {active ? "Active" : "Inactive"}
    </span>
  );
}

function OnTimePill({ value }: { value: boolean | null }): JSX.Element {
  if (value === null) return <span className="text-gray-400">--</span>;
  return (
    <span
      className={clsx(
        "inline-flex min-w-[2.75rem] justify-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        value ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700",
      )}
    >
      {value ? "Yes" : "No"}
    </span>
  );
}

// ------------------------------------------------------------- pagination ----

interface PaginationProps {
  page: number;
  totalPages: number;
  pageSize: number;
  totalRows: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}

export function Pagination({ page, totalPages, pageSize, totalRows, onPageChange, onPageSizeChange }: PaginationProps): JSX.Element {
  const start = totalRows === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalRows);

  // 1 … 4 5 6 … 20
  const pages = useMemo(() => {
    const out: (number | "gap")[] = [];
    for (let p = 1; p <= totalPages; p += 1) {
      if (p === 1 || p === totalPages || Math.abs(p - page) <= 1) out.push(p);
      else if (out[out.length - 1] !== "gap") out.push("gap");
    }
    return out;
  }, [page, totalPages]);

  const btn =
    "inline-flex h-8 min-w-[2rem] items-center justify-center rounded-md px-2 text-sm text-gray-600 hover:bg-gray-100 disabled:pointer-events-none disabled:opacity-40";

  return (
    <div className="flex flex-col gap-3 border-t border-gray-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3 text-sm text-gray-500">
        <span>
          Showing{" "}
          <span className="font-medium text-gray-700">
            {start}–{end}
          </span>{" "}
          of <span className="font-medium text-gray-700">{totalRows}</span> records
        </span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-gray-200 bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          aria-label="Rows per page"
        >
          {[10, 25, 50, 100].map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </select>
      </div>

      <nav className="flex items-center gap-1" aria-label="Pagination">
        <button type="button" className={btn} onClick={() => onPageChange(1)} disabled={page === 1} aria-label="First page">
          <ChevronsLeft className="h-4 w-4" aria-hidden />
        </button>
        <button type="button" className={btn} onClick={() => onPageChange(page - 1)} disabled={page === 1} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </button>
        {pages.map((p, i) =>
          p === "gap" ? (
            <span key={`gap-${i}`} className="px-1 text-gray-400">
              …
            </span>
          ) : (
            <button
              type="button"
              key={p}
              onClick={() => onPageChange(p)}
              aria-current={p === page ? "page" : undefined}
              className={clsx(btn, p === page && "bg-brand-600 font-medium text-white hover:bg-brand-600")}
            >
              {p}
            </button>
          ),
        )}
        <button
          type="button"
          className={btn}
          onClick={() => onPageChange(page + 1)}
          disabled={page === totalPages}
          aria-label="Next page"
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </button>
        <button
          type="button"
          className={btn}
          onClick={() => onPageChange(totalPages)}
          disabled={page === totalPages}
          aria-label="Last page"
        >
          <ChevronsRight className="h-4 w-4" aria-hidden />
        </button>
      </nav>
    </div>
  );
}
