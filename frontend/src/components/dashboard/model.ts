// Types + pure helpers for the Dashboard page. No React in here, so
// everything is unit-testable and the component files stay export-clean for
// react-refresh.
import type { DashboardTodayResponse, ExceptionRowOut } from "../../api/types";

// ---------------------------------------------------------------- types ----

/** The four KPI buckets. Known/Unknown/Absent are disjoint; Exception is a
 *  flag that overlaps (a Late employee is both Known Present and Exception). */
export type KPIFilterType = "KNOWN_PRESENT" | "UNKNOWN_PRESENT" | "ABSENT" | "EXCEPTION";

export const KPI_ORDER: KPIFilterType[] = ["KNOWN_PRESENT", "UNKNOWN_PRESENT", "ABSENT", "EXCEPTION"];

export const KPI_LABELS: Record<KPIFilterType, string> = {
  KNOWN_PRESENT: "Known Present",
  UNKNOWN_PRESENT: "Unknown Present",
  ABSENT: "Absent",
  EXCEPTION: "Exception",
};

/** Primary bucket of a row. "EXCEPTION" only for rows that exist purely as an
 *  exception (e.g. a liveness failure at a kiosk, which has no person). */
export type RecordCategory = KPIFilterType;

export interface RecordException {
  kind: string;
  detail: string;
}

export interface AttendanceRecord {
  key: string;
  date: string; // "YYYY-MM-DD" (local)
  category: RecordCategory;
  photo: string | null; // API path; wrap with mediaUrl() to render
  face_id: string;
  /** Employee code (e.g. "EMP-102"), null for unknown visitors / kiosk exceptions. */
  emp_code: string | null;
  name: string;
  designation: string | null;
  department: string | null;
  intime: string | null; // "HH:mm" (local, from backend)
  outtime: string | null;
  total_hours: number | null;
  /** Employees: true/false. Unknown visitors / kiosk exceptions: null. */
  is_active: boolean | null;
  /** Shown instead of Active/Inactive when is_active is null, e.g. "OPEN". */
  subject_status: string | null;
  on_time: boolean | null;
  kiosk_ids: string[];
  exceptions: RecordException[];
  /** employee id (known/absent) or unknown-identity id (unknown); "" for kiosk-only exception rows */
  subject_id: string;
  in_event_id: string | null;
  out_event_id: string | null;
  home_kiosk_id: string | null;
}

export type DateRangeMode = "day" | "month" | "year" | "custom";

export interface DateRange {
  mode: DateRangeMode;
  from: string; // inclusive "YYYY-MM-DD"
  to: string; // inclusive "YYYY-MM-DD"
}

export interface FilterState {
  /** null = all entry points (including ones that appear later). */
  kioskIds: string[] | null;
  dateRange: DateRange;
  activeKpiFilter: KPIFilterType | null;
  /** Case-insensitive substring match against emp_code. "" = no filter. */
  empCode: string;
}

export type SortKey =
  | "date"
  | "photo"
  | "face_id"
  | "emp_code"
  | "name"
  | "designation"
  | "department"
  | "intime"
  | "outtime"
  | "total_hours"
  | "is_active"
  | "on_time";

export interface SortState {
  key: SortKey | null;
  direction: "asc" | "desc" | null;
}

// ------------------------------------------------------- API -> records ----

export function humanizeKind(kind: string): string {
  const s = kind.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Flattens the four dashboard lists into one table-ready list, attaching
 *  each exception to the person/day it belongs to. */
export function buildRecords(res: DashboardTodayResponse): AttendanceRecord[] {
  const records: AttendanceRecord[] = [];
  const byFaceDay = new Map<string, AttendanceRecord>();
  const index = (r: AttendanceRecord): void => {
    records.push(r);
    byFaceDay.set(`${r.face_id}|${r.date}`, r);
  };

  for (const k of res.known) {
    index({
      key: `K|${k.face_id}|${k.date}`,
      date: k.date,
      category: "KNOWN_PRESENT",
      photo: k.best_shot_url ?? k.thumb_url,
      face_id: k.face_id,
      emp_code: k.emp_code,
      name: k.name,
      designation: k.designation,
      department: k.department,
      intime: k.in_time,
      outtime: k.out_time,
      // Backend now returns elapsed-so-far hours (now - first IN) when
      // there's no OUT yet, so no need to null this out client-side.
      total_hours: k.total_hours,
      is_active: k.is_active,
      subject_status: null,
      on_time: k.on_time,
      kiosk_ids: k.kiosk_ids,
      exceptions: [],
      subject_id: k.subject_id ?? "",
      in_event_id: k.in_event_id ?? null,
      out_event_id: k.out_event_id ?? null,
      home_kiosk_id: k.home_kiosk_id ?? null,
    });
  }

  for (const u of res.unknown) {
    index({
      key: `U|${u.face_id}|${u.date}`,
      date: u.date,
      category: "UNKNOWN_PRESENT",
      photo: u.best_crop_url,
      face_id: u.face_id,
      emp_code: null,
      name: u.label ?? "Unknown visitor",
      designation: "Unregistered",
      department: null,
      intime: u.in_time,
      outtime: u.out_time,
      total_hours: u.total_hours,
      is_active: null,
      subject_status: u.status,
      on_time: null,
      kiosk_ids: u.kiosk_ids,
      exceptions: [],
      subject_id: u.subject_id ?? "",
      in_event_id: u.in_event_id ?? null,
      out_event_id: u.out_event_id ?? null,
      home_kiosk_id: null,
    });
  }

  for (const a of res.absent) {
    index({
      key: `A|${a.face_id}|${a.date}`,
      date: a.date,
      category: "ABSENT",
      photo: a.thumb_url,
      face_id: a.face_id,
      emp_code: a.emp_code,
      name: a.name,
      designation: a.designation,
      department: a.department,
      intime: null,
      outtime: null,
      total_hours: null,
      is_active: a.is_active,
      subject_status: null,
      on_time: null,
      kiosk_ids: [],
      exceptions: [],
      subject_id: a.subject_id ?? "",
      in_event_id: null,
      out_event_id: null,
      home_kiosk_id: a.home_kiosk_id ?? null,
    });
  }

  res.exceptions.forEach((x: ExceptionRowOut, i) => {
    const owner = byFaceDay.get(`${x.face_id}|${x.date}`);
    if (owner) {
      owner.exceptions.push({ kind: x.kind, detail: x.detail });
      return;
    }
    // No person/day row to attach to (e.g. liveness failure: face_id is the kiosk id).
    records.push({
      key: `X|${x.kind}|${x.face_id}|${x.date}|${i}`,
      date: x.date,
      category: "EXCEPTION",
      photo: null,
      face_id: x.face_id,
      emp_code: null,
      name: x.label ?? humanizeKind(x.kind),
      designation: null,
      department: null,
      intime: null,
      outtime: null,
      total_hours: null,
      is_active: null,
      subject_status: null,
      on_time: null,
      kiosk_ids: x.kiosk_ids,
      exceptions: [{ kind: x.kind, detail: x.detail }],
      subject_id: "",
      in_event_id: null,
      out_event_id: null,
      home_kiosk_id: null,
    });
  });

  return records;
}

export function matchesKpi(r: AttendanceRecord, kpi: KPIFilterType | null): boolean {
  if (kpi === null) return true;
  if (kpi === "EXCEPTION") return r.exceptions.length > 0;
  return r.category === kpi;
}

/** Absent rows have no entry point, so they are kept whenever at least one
 *  entry point is selected. */
export function matchesKiosks(r: AttendanceRecord, kioskIds: string[] | null): boolean {
  if (kioskIds === null) return true;
  if (kioskIds.length === 0) return false;
  if (r.kiosk_ids.length === 0) return true;
  return r.kiosk_ids.some((k) => kioskIds.includes(k));
}

/** Case-insensitive substring match on emp_code. Blank query = no filter.
 *  Rows with no emp_code (unknown visitors, kiosk exceptions) are excluded
 *  once a query is typed, same as an entry-point filter would exclude them. */
export function matchesEmpCode(r: AttendanceRecord, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (r.emp_code ?? "").toLowerCase().includes(q);
}

export function countKpis(records: AttendanceRecord[]): Record<KPIFilterType, number> {
  const counts: Record<KPIFilterType, number> = { KNOWN_PRESENT: 0, UNKNOWN_PRESENT: 0, ABSENT: 0, EXCEPTION: 0 };
  for (const r of records) {
    if (r.category !== "EXCEPTION") counts[r.category] += 1;
    if (r.exceptions.length > 0) counts.EXCEPTION += 1;
  }
  return counts;
}

// ---------------------------------------------------------------- sort -----

const SORT_ACCESSORS: Record<SortKey, (r: AttendanceRecord) => string | number | null> = {
  date: (r) => r.date,
  photo: (r) => (r.photo ? 1 : 0),
  face_id: (r) => r.face_id,
  emp_code: (r) => r.emp_code,
  name: (r) => r.name,
  designation: (r) => r.designation,
  department: (r) => r.department,
  intime: (r) => r.intime, // "HH:mm" sorts correctly as text
  outtime: (r) => r.outtime,
  total_hours: (r) => r.total_hours,
  is_active: (r) => (r.is_active === null ? null : r.is_active ? 1 : 0),
  on_time: (r) => (r.on_time === null ? null : r.on_time ? 1 : 0),
};

/** Stable sort; nulls always last regardless of direction. */
export function sortRecords(rows: AttendanceRecord[], sort: SortState): AttendanceRecord[] {
  const { key, direction } = sort;
  if (!key || !direction) return rows;
  const get = SORT_ACCESSORS[key];
  const dir = direction === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
    return String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: "base" }) * dir;
  });
}

export function nextSort(current: SortState, key: SortKey): SortState {
  if (current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return { key: null, direction: null };
}

// ---------------------------------------------------------------- dates ----

const pad = (n: number): string => String(n).padStart(2, "0");

/** Inclusive [from, to] for a mode, anchored on any date inside it. */
export function buildRange(mode: DateRangeMode, anchor: string, customTo?: string): DateRange {
  const [y = 1970, m = 1] = anchor.split("-").map(Number);
  switch (mode) {
    case "day":
      return { mode, from: anchor, to: anchor };
    case "month": {
      const last = new Date(y, m, 0).getDate(); // day 0 of next month
      return { mode, from: `${y}-${pad(m)}-01`, to: `${y}-${pad(m)}-${pad(last)}` };
    }
    case "year":
      return { mode, from: `${y}-01-01`, to: `${y}-12-31` };
    case "custom": {
      const to = customTo ?? anchor;
      return anchor <= to ? { mode, from: anchor, to } : { mode, from: to, to: anchor };
    }
  }
}

/** Clamp a range's end to today so we never ask the API for the future. */
export function clampToToday(range: DateRange, today: string): { date_from: string; date_to: string } {
  const to = range.to > today ? today : range.to;
  const from = range.from > to ? to : range.from;
  return { date_from: from, date_to: to };
}

/** "09:05" -> "09:05 AM" */
export function formatClock(hhmm: string | null): string {
  if (!hhmm) return "--";
  const [h = 0, m = 0] = hhmm.split(":").map(Number);
  return `${pad(h % 12 || 12)}:${pad(m)} ${h >= 12 ? "PM" : "AM"}`;
}

export function formatDay(iso: string): string {
  const [y = 1970, m = 1, d = 1] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
