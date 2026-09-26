import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

// The backend stores every timestamp as UTC and only ever hands the frontend
// either a raw UTC ISO datetime (e.g. AttendanceEventOut.occurred_at) or an
// already-localized "HH:mm" string it computed server-side (dashboard/
// analytics rows). This module is the one place the frontend converts the
// former for display -- never re-implement timezone math in a component.
export const APP_TIMEZONE = "Asia/Kolkata";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return formatInTimeZone(new Date(iso), APP_TIMEZONE, "dd MMM yyyy, HH:mm:ss");
  } catch {
    return iso;
  }
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return formatInTimeZone(new Date(iso), APP_TIMEZONE, "HH:mm:ss");
  } catch {
    return iso;
  }
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  try {
    return formatInTimeZone(new Date(iso), APP_TIMEZONE, "dd MMM yyyy");
  } catch {
    return iso;
  }
}

export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "--";
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${value.toFixed(1)}%`;
}

export function formatSimilarity(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  return `${(value * 100).toFixed(1)}%`;
}

export function todayIsoDate(): string {
  return formatInTimeZone(new Date(), APP_TIMEZONE, "yyyy-MM-dd");
}

/** "2026-09-25" + "09:30" (wall-clock in APP_TIMEZONE) -> UTC ISO string for the API. */
export function localDateTimeToIso(isoDate: string, hhmm: string): string {
  return fromZonedTime(`${isoDate}T${hhmm}:00`, APP_TIMEZONE).toISOString();
}
