import { useEffect, useState } from "react";
import { getSettings, updateSettings, toApiError } from "../api/client";
import { NotificationSettings } from "../components/NotificationSettings";
import { ChatbotSettings } from "../components/ChatbotSettings";

type FieldKind = "number" | "boolean" | "string" | "weekdays";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  step?: number;
  hint?: string;
}

// Mirrors backend/app/services/settings_service.py's DEFAULT_SETTINGS keys.
// Grouped for readability; any key the backend adds later that isn't listed
// here still round-trips correctly through the "Advanced (raw JSON)" editor
// below rather than being silently dropped.
const FIELD_GROUPS: { title: string; fields: FieldSpec[] }[] = [
  {
    title: "Recognition",
    fields: [
      { key: "similarity_threshold", label: "Similarity threshold", kind: "number", step: 0.01 },
      { key: "min_face_pixels", label: "Minimum face height (px)", kind: "number", step: 1 },
      { key: "unknown_cluster_threshold", label: "Unknown cluster threshold", kind: "number", step: 0.01 },
      { key: "unknown_max_templates", label: "Max templates per unknown", kind: "number", step: 1 },
      { key: "unknown_auto_ignore_days", label: "Auto-ignore unknowns after (days)", kind: "number", step: 1 },
    ],
  },
  {
    title: "Face quality (kiosk skips bad frames)",
    fields: [
      { key: "quality_gate_enabled", label: "Quality gate enabled", kind: "boolean" },
      { key: "quality_min_score", label: "Minimum quality score (0-1)", kind: "number", step: 0.05, hint: "Hand over the face ~0.35-0.4, clear face ~0.7+. Raise if covered faces still become unknowns." },
      { key: "unknown_min_quality", label: "Unknown person only if quality at least", kind: "number", step: 0.05, hint: "Poorer unmatched faces are logged as 'unclear', never as a new unknown person." },
      { key: "unknown_near_match_similarity", label: "Unknown person only if similarity to every employee below", kind: "number", step: 0.01, hint: "Close to someone but under the match threshold = probably that person with a covered face: logged as unclear." },
      { key: "quality_min_det_score", label: "Minimum detector confidence", kind: "number", step: 0.05 },
      { key: "quality_min_brightness", label: "Minimum brightness (0-255)", kind: "number", step: 1 },
      { key: "quality_min_sharpness", label: "Minimum sharpness", kind: "number", step: 1 },
    ],
  },
  {
    title: "Liveness",
    fields: [
      { key: "liveness_enabled", label: "Liveness check enabled", kind: "boolean" },
      { key: "liveness_threshold", label: "Liveness pass threshold", kind: "number", step: 0.01, hint: "Calibrate per camera: python -m kiosk.liveness_check" },
      { key: "liveness_required", label: "Reject faces if the anti-spoofing model is missing (recommended)", kind: "boolean" },
    ],
  },
  {
    title: "Dedupe & gating",
    fields: [
      { key: "dedupe_window_minutes", label: "Camera ignores the same face again for (minutes)", kind: "number", step: 1 },
      { key: "min_out_gap_minutes", label: "Single gate camera: OUT only after this many minutes from IN (0 = every later sighting)", kind: "number", step: 5 },
      { key: "iou_same_subject", label: "IoU same-subject threshold", kind: "number", step: 0.01 },
      { key: "same_person_threshold", label: "Embedding same-person threshold", kind: "number", step: 0.01 },
      { key: "recent_embedding_buffer", label: "Recent embedding buffer size", kind: "number", step: 1 },
    ],
  },
  {
    title: "Motion gate",
    fields: [
      { key: "motion_pixel_threshold", label: "Motion pixel threshold", kind: "number", step: 1 },
      { key: "motion_area_threshold", label: "Motion area threshold", kind: "number", step: 0.01 },
      { key: "idle_frames_before_sleep", label: "Idle frames before sleep", kind: "number", step: 1 },
      { key: "idle_fps", label: "Idle FPS", kind: "number", step: 1 },
      { key: "reference_refresh_seconds", label: "Reference refresh (seconds)", kind: "number", step: 1 },
    ],
  },
  {
    title: "Device / performance",
    fields: [
      { key: "device_preference", label: "Device preference", kind: "string", hint: "auto | cpu | cuda | tensorrt" },
      { key: "capture_fps", label: "Capture FPS", kind: "number", step: 1 },
      { key: "bestshot_frames", label: "Best-shot buffer frames", kind: "number", step: 1 },
      { key: "ort_intra_op_threads", label: "ONNX Runtime intra-op threads", kind: "number", step: 1 },
      { key: "det_size", label: "Detector input size", kind: "string", hint: "e.g. 640,640" },
    ],
  },
  {
    title: "Payroll & overtime",
    fields: [
      { key: "weekly_off_days", label: "Weekly off", kind: "weekdays" },
      { key: "ot_enabled", label: "Calculate overtime", kind: "boolean" },
      { key: "ot_min_minutes", label: "Minimum OT (minutes)", kind: "number", step: 5, hint: "Less than this after shift end is ignored" },
      { key: "ot_rounding_minutes", label: "Round OT down to (minutes)", kind: "number", step: 5 },
      { key: "full_day_min_hours", label: "Full day needs at least (hours)", kind: "number", step: 0.5, hint: "0 = any sighting is a full day (entry camera only)" },
      { key: "half_day_min_hours", label: "Below this is absent (hours)", kind: "number", step: 0.5, hint: "0 = off" },
      { key: "night_shift_tail_hours", label: "Night shift: count sightings up to N hours after shift end", kind: "number", step: 1 },
      { key: "auto_shift_detect", label: "Auto-detect shift for people without one", kind: "boolean" },
    ],
  },
  {
    title: "Reporting",
    fields: [
      { key: "working_days_per_week", label: "Working days per week", kind: "number", step: 1 },
      { key: "crop_retention_days", label: "Crop retention (days)", kind: "number", step: 1 },
    ],
  },
];


export function Settings(): JSX.Element {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [device, setDevice] = useState<Record<string, unknown> | null>(null);
  const [rawJson, setRawJson] = useState("");
  // untouched: the box mirrors the form. Edited: the box is what gets saved.
  const [rawDirty, setRawDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    getSettings()
      .then((res) => {
        setValues(res.settings);
        setDevice(res.device);
      })
      .catch((err) => setError(toApiError(err).detail))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!rawDirty) setRawJson(JSON.stringify(values, null, 2));
  }, [values, rawDirty]);

  function setField(key: string, kind: FieldKind, raw: string | boolean): void {
    let parsed: unknown = raw;
    if (kind === "number") parsed = raw === "" ? "" : Number(raw);
    setValues((prev) => ({ ...prev, [key]: parsed }));
  }

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      let payloadValues: Record<string, unknown>;
      if (rawDirty) {
        try {
          const parsed: unknown = JSON.parse(rawJson);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
          payloadValues = parsed as Record<string, unknown>;
        } catch {
          setError("Advanced JSON is not valid JSON (it must be one { ... } object).");
          setSaving(false);
          return;
        }
      } else {
        payloadValues = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== undefined && v !== ""));
      }
      const res = await updateSettings({ values: payloadValues });
      setValues(res.settings);
      setRawDirty(false);
      setSavedAt(new Date());
    } catch (err) {
      setError(toApiError(err).detail);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-500">Loading settings...</p>;
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Runtime settings</h1>
        <button onClick={handleSave} disabled={saving} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
          {saving ? "Saving..." : "Save changes"}
        </button>
      </div>
      <p className="text-sm text-gray-500">
        These take effect on the kiosk within its settings-refresh interval, with no restart or redeploy required
        (NON-NEGOTIABLE #1) -- thresholds live here, never in kiosk code or env vars.
      </p>

      {error && <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {savedAt && !error && <p className="rounded-md bg-green-50 p-3 text-sm text-green-700">Saved at {savedAt.toLocaleTimeString()}.</p>}

      <NotificationSettings />

      <ChatbotSettings />

      {device && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500">Kiosk device (last heartbeat)</h2>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            {Object.entries(device).map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs uppercase text-gray-400">{k}</dt>
                <dd className="text-gray-800">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {FIELD_GROUPS.map((group) => (
        <div key={group.title} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">{group.title}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {group.fields.map((field) => {
              const value = values[field.key];
              if (field.kind === "weekdays") {
                const days = Array.isArray(value) ? (value as number[]) : [];
                return (
                  <div key={field.key} className="sm:col-span-2">
                    <span className="mb-1 block text-sm font-medium text-gray-700">{field.label}</span>
                    <div className="flex flex-wrap gap-1.5">
                      {WEEKDAYS.map((d, i) => {
                        const on = days.includes(i);
                        return (
                          <button
                            key={d}
                            type="button"
                            onClick={() =>
                              setValues((prev) => ({
                                ...prev,
                                [field.key]: on ? days.filter((x) => x !== i) : [...days, i].sort(),
                              }))
                            }
                            className={
                              on
                                ? "rounded-md border border-brand-600 bg-brand-600 px-3 py-1.5 text-xs font-medium text-white"
                                : "rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                            }
                          >
                            {d}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              }
              if (field.kind === "boolean") {
                return (
                  <label key={field.key} className="flex items-center gap-2 text-sm text-gray-700">
                    <input type="checkbox" checked={Boolean(value)} onChange={(e) => setField(field.key, "boolean", e.target.checked)} />
                    {field.label}
                  </label>
                );
              }
              return (
                <div key={field.key}>
                  <label className="mb-1 block text-sm font-medium text-gray-700">{field.label}</label>
                  <input
                    type={field.kind === "number" ? "number" : "text"}
                    step={field.step}
                    value={value === undefined || value === null ? "" : String(value)}
                    onChange={(e) => setField(field.key, field.kind, e.target.value)}
                    className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                  {field.hint && <p className="mt-0.5 text-xs text-gray-400">{field.hint}</p>}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      <details className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer select-none text-sm font-semibold uppercase tracking-wide text-gray-500">
          Advanced (raw JSON): all {Object.keys(values).length} settings
        </summary>
        <p className="mb-2 mt-2 text-xs text-gray-500">
          Every current setting, including ones without a field above. It follows the form while you don&apos;t touch it.
          If you edit it, <strong>this box is what gets saved</strong>. Unknown keys are ignored.
          {rawDirty && (
            <button
              type="button"
              onClick={() => setRawDirty(false)}
              className="ml-2 text-brand-700 underline"
            >
              Discard JSON edits
            </button>
          )}
        </p>
        <textarea
          value={rawJson}
          onChange={(e) => {
            setRawJson(e.target.value);
            setRawDirty(true);
          }}
          rows={16}
          spellCheck={false}
          className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-xs"
        />
      </details>
    </div>
  );
}
