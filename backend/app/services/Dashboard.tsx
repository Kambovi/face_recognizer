import { useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "../components/DataTable";
import { CorrectionModal } from "../components/CorrectionModal";
import {
  getDashboardToday,
  listEvents,
  mediaUrl,
  toApiError,
} from "../api/client";
import type {
  AbsentRowOut,
  AttendanceEventOut,
  DashboardTodayResponse,
  ExceptionRowOut,
  KnownRowOut,
  UnknownRowOut,
} from "../api/types";
import { formatDateTime, formatHours, formatSimilarity, todayIsoDate } from "../utils/format";

function StatCard({ label, value, tone }: { label: string; value: number; tone: "green" | "amber" | "gray" | "red" }): JSX.Element {
  const toneClasses: Record<typeof tone, string> = {
    green: "text-green-700 bg-green-50",
    amber: "text-amber-700 bg-amber-50",
    gray: "text-gray-700 bg-gray-100",
    red: "text-red-700 bg-red-50",
  };
  return (
    <div className={`rounded-lg p-4 ${toneClasses[tone]}`}>
      <p className="text-xs font-medium uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  );
}

export function Dashboard(): JSX.Element {
  const [data, setData] = useState<DashboardTodayResponse | null>(null);
  const [events, setEvents] = useState<AttendanceEventOut[]>([]);
  const [correctingEvent, setCorrectingEvent] = useState<AttendanceEventOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadDashboard = useCallback(async () => {
    try {
      const dash = await getDashboardToday();
      setData(dash);
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    try {
      const today = todayIsoDate();
      const res = await listEvents({ date_from: today, date_to: today, page: 1, page_size: 100 });
      setEvents(res.items);
    } catch (err) {
      setError(toApiError(err).detail);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadDashboard(), loadEvents()]).finally(() => setLoading(false));
    // Light polling keeps the kiosk-fed dashboard reasonably live without
    // needing a websocket for a single-site, 100-employee deployment.
    const interval = window.setInterval(() => {
      loadDashboard();
      loadEvents();
    }, 30000);
    return () => window.clearInterval(interval);
  }, [loadDashboard, loadEvents]);

  const knownColumns = useMemo<ColumnDef<KnownRowOut>[]>(
    () => [
      {
        header: "Photo",
        cell: ({ row }) => {
          const url = mediaUrl(row.original.best_shot_url);
          return url ? (
            <img src={url} alt="face crop" className="h-10 w-10 rounded object-cover" />
          ) : (
            <div className="h-10 w-10 rounded bg-gray-100" />
          );
        },
      },
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Name", accessorKey: "name" },
      { header: "Department", accessorFn: (row) => row.department ?? "--" },
      { header: "In", accessorFn: (row) => row.in_time ?? "--" },
      { header: "Out", accessorFn: (row) => row.out_time ?? "--" },
      { header: "Hours", accessorFn: (row) => formatHours(row.total_hours) },
      { header: "Status", accessorKey: "status" },
      { header: "Similarity", accessorFn: (row) => formatSimilarity(row.similarity) },
    ],
    [],
  );

  const unknownColumns = useMemo<ColumnDef<UnknownRowOut>[]>(
    () => [
      {
        header: "Photo",
        cell: ({ row }) => {
          const url = mediaUrl(row.original.best_crop_url);
          return url ? (
            <img src={url} alt="face crop" className="h-10 w-10 rounded object-cover" />
          ) : (
            <div className="h-10 w-10 rounded bg-gray-100" />
          );
        },
      },
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Label", accessorFn: (row) => row.label ?? "(unlabeled)" },
      { header: "First seen", accessorKey: "first_seen" },
      { header: "Last seen", accessorKey: "last_seen" },
      { header: "Sightings", accessorKey: "sighting_count" },
      { header: "In", accessorFn: (row) => row.in_time ?? "--" },
      { header: "Out", accessorFn: (row) => row.out_time ?? "--" },
      { header: "Status", accessorKey: "status" },
    ],
    [],
  );

  const absentColumns = useMemo<ColumnDef<AbsentRowOut>[]>(
    () => [
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Name", accessorKey: "name" },
      { header: "Department", accessorFn: (row) => row.department ?? "--" },
      { header: "Shift", accessorFn: (row) => (row.shift_in && row.shift_out ? `${row.shift_in} - ${row.shift_out}` : "--") },
    ],
    [],
  );

  const exceptionColumns = useMemo<ColumnDef<ExceptionRowOut>[]>(
    () => [
      { header: "Kind", accessorKey: "kind" },
      { header: "Face ID", accessorKey: "face_id" },
      { header: "Label", accessorFn: (row) => row.label ?? "--" },
      { header: "Detail", accessorKey: "detail" },
    ],
    [],
  );

  const eventColumns = useMemo<ColumnDef<AttendanceEventOut>[]>(
    () => [
      { header: "Time", accessorFn: (row) => formatDateTime(row.occurred_at) },
      { header: "Type", accessorKey: "event_type" },
      { header: "Subject", accessorFn: (row) => row.subject_type ?? "REJECTED" },
      { header: "Similarity", accessorFn: (row) => formatSimilarity(row.similarity) },
      { header: "Liveness", accessorFn: (row) => formatSimilarity(row.liveness_score) },
      { header: "Reject reason", accessorFn: (row) => row.reject_reason ?? "--" },
      {
        header: "Crop",
        cell: ({ row }) => {
          const url = mediaUrl(row.original.crop_url);
          return url ? <img src={url} alt="face crop" className="h-10 w-10 rounded object-cover" /> : "--";
        },
      },
      {
        header: "Actions",
        cell: ({ row }) => (
          <button
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
    return <p className="text-sm text-gray-500">Loading dashboard...</p>;
  }

  return (
    <div className="space-y-8">
      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {data && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {/* Backend's counts dict key is "present", not "known" (see
              app/services/dashboard.py) -- the `?? data.known.length`
              fallback made the old "known" key harmless (always undefined,
              so the fallback always fired), but read the real key directly
              now for clarity. */}
          <StatCard label="Known present" value={data.counts.present ?? data.known.length} tone="green" />
          <StatCard label="Unknown sightings" value={data.counts.unknown ?? data.unknown.length} tone="amber" />
          <StatCard label="Absent" value={data.counts.absent ?? data.absent.length} tone="gray" />
          <StatCard label="Exceptions" value={data.counts.exceptions ?? data.exceptions.length} tone="red" />
        </div>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Known employees today</h2>
        <DataTable data={data?.known ?? []} columns={knownColumns} emptyMessage="No known employees recognized yet today." />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Unknown visitors today</h2>
        <DataTable data={data?.unknown ?? []} columns={unknownColumns} emptyMessage="No unknown visitors seen today." />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Absent employees</h2>
        <DataTable data={data?.absent ?? []} columns={absentColumns} emptyMessage="Everyone with a shift today has been seen." />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Exceptions</h2>
        <DataTable data={data?.exceptions ?? []} columns={exceptionColumns} emptyMessage="No exceptions today." />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Today's raw events</h2>
        <p className="mb-2 text-xs text-gray-500">
          Every kiosk-recorded event, including rejects. Use "Correct" to fix a misrecognition or a wrong IN/OUT.
        </p>
        <DataTable data={events} columns={eventColumns} emptyMessage="No events recorded yet today." maxBodyHeight={420} />
      </section>

      {correctingEvent && (
        <CorrectionModal
          event={correctingEvent}
          onClose={() => setCorrectingEvent(null)}
          onCorrected={() => {
            loadDashboard();
            loadEvents();
          }}
        />
      )}
    </div>
  );
}
