import { useEffect, useState } from "react";
import type { AttendanceEventOut, EmployeeOut, EventType, UnknownIdentityOut } from "../api/types";
import { listEmployees, listUnknowns, manualOverrideEvent, reassignEvent, toApiError } from "../api/client";
import { formatDateTime } from "../utils/format";

interface CorrectionModalProps {
  event: AttendanceEventOut;
  onClose: () => void;
  onCorrected: (updated: AttendanceEventOut) => void;
}

// The dashboard's "Correction Modal": four actions HR can take on a single
// recognized/rejected attendance event, chosen because they map 1:1 onto the
// backend's two correction endpoints (manual override, and reassign with its
// three target-type variants) -- see docs/DECISIONS.md ("dashboard
// correction modal scope").
type CorrectionAction = "override" | "reassign_employee" | "reassign_unknown" | "reassign_new_unknown";

const ACTIONS: { id: CorrectionAction; label: string }[] = [
  { id: "override", label: "Fix time / type" },
  { id: "reassign_employee", label: "Reassign to employee" },
  { id: "reassign_unknown", label: "Reassign to unknown" },
  { id: "reassign_new_unknown", label: "Split into new unknown" },
];

export function CorrectionModal({ event, onClose, onCorrected }: CorrectionModalProps): JSX.Element {
  const [action, setAction] = useState<CorrectionAction>("override");
  const [reason, setReason] = useState("");
  const [eventType, setEventType] = useState<EventType>((event.event_type as EventType) ?? "IN");
  const [occurredAt, setOccurredAt] = useState(event.occurred_at.slice(0, 16));
  const [employees, setEmployees] = useState<EmployeeOut[]>([]);
  const [unknowns, setUnknowns] = useState<UnknownIdentityOut[]>([]);
  const [targetId, setTargetId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (action === "reassign_employee" && employees.length === 0) {
      listEmployees({ page_size: 200 })
        .then((res) => setEmployees(res.items))
        .catch(() => setEmployees([]));
    }
    if (action === "reassign_unknown" && unknowns.length === 0) {
      listUnknowns({ page_size: 200 })
        .then((res) => setUnknowns(res.items))
        .catch(() => setUnknowns([]));
    }
  }, [action, employees.length, unknowns.length]);

  async function handleSubmit(): Promise<void> {
    if (reason.trim().length < 3) {
      setError("Reason must be at least 3 characters.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      let updated: AttendanceEventOut;
      if (action === "override") {
        updated = await manualOverrideEvent(event.id, {
          event_type: eventType,
          occurred_at: new Date(occurredAt).toISOString(),
          reason,
        });
      } else if (action === "reassign_employee") {
        if (!targetId) {
          setError("Choose an employee to reassign to.");
          setSubmitting(false);
          return;
        }
        updated = await reassignEvent(event.id, { target_type: "EMPLOYEE", target_id: targetId, reason });
      } else if (action === "reassign_unknown") {
        if (!targetId) {
          setError("Choose an unknown identity to reassign to.");
          setSubmitting(false);
          return;
        }
        updated = await reassignEvent(event.id, { target_type: "UNKNOWN", target_id: targetId, reason });
      } else {
        updated = await reassignEvent(event.id, { target_type: "NEW_UNKNOWN", reason });
      }
      onCorrected(updated);
      onClose();
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Correct attendance event</h2>
            <p className="text-sm text-gray-500">
              {event.event_type} at {formatDateTime(event.occurred_at)} &middot; kiosk {event.kiosk_id}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          {ACTIONS.map((a) => (
            <button
              key={a.id}
              onClick={() => setAction(a.id)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium ${
                action === a.id ? "bg-brand-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {action === "override" && (
            <>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Event type</label>
                <select
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value as EventType)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="IN">IN</option>
                  <option value="OUT">OUT</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">Occurred at</label>
                <input
                  type="datetime-local"
                  value={occurredAt}
                  onChange={(e) => setOccurredAt(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </>
          )}

          {action === "reassign_employee" && (
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Employee</label>
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select an employee...</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {emp.face_id} &mdash; {emp.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {action === "reassign_unknown" && (
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Unknown identity</label>
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="">Select an unknown identity...</option>
                {unknowns.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.face_id} {u.label ? `(${u.label})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {action === "reassign_new_unknown" && (
            <p className="rounded-md bg-gray-50 p-3 text-sm text-gray-600">
              This event will be detached and given a brand-new unknown identity, separate from whatever it was
              previously matched to.
            </p>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Reason (required)</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              placeholder="e.g. Camera glare caused a mismatch"
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {submitting ? "Saving..." : "Apply correction"}
          </button>
        </div>
      </div>
    </div>
  );
}
