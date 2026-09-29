"""NON-NEGOTIABLE #1 -- thresholds are runtime config, never hardcoded.

Every tunable in the spec's "Runtime-tunable settings" table lives here as a
default, used only when the `settings` table has no row for that key yet
(first boot) or when explicitly asked for a fallback. Once a row exists,
the DB value always wins. The Settings page (PATCH /settings) writes rows
here; the kiosk polls GET /kiosk/config (a read-only projection of the same
table) every `settings_refresh_seconds`.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting

DEFAULT_SETTINGS: dict[str, Any] = {
    "similarity_threshold": 0.38,
    "liveness_enabled": True,
    "liveness_threshold": 0.5,  # calibrate per camera: python -m kiosk.liveness_check
    # Fail-closed: if the anti-spoofing model can't load, reject faces
    # instead of silently accepting photos (see kiosk/kiosk/liveness.py).
    "liveness_required": True,
    "dedupe_window_minutes": 5,
    # one-camera gate: a detection this long after IN (or later) becomes OUT;
    # earlier ones are only counted (services/attendance.py)
    "min_out_gap_minutes": 120,
    "min_face_pixels": 80,
    "crop_retention_days": 90,
    "motion_pixel_threshold": 25,
    "motion_area_threshold": 0.02,
    "idle_frames_before_sleep": 60,
    "idle_fps": 1,
    "reference_refresh_seconds": 30,
    "iou_same_subject": 0.85,
    # Kiosk-side "same person as a moment ago -> don't send again". 0.90 was
    # far above what one real person scores across frames (~0.5-0.8), so it
    # never fired and every few seconds produced another event.
    "same_person_threshold": 0.55,
    "recent_embedding_buffer": 5,
    # Grouping repeat sightings of the same stranger. Must be LOOSER (lower)
    # than or near the employee threshold -- 0.55 was stricter and, measured
    # on a real deployment, split one person into dozens of UNK- ids.
    "unknown_cluster_threshold": 0.40,
    # More stored angles per stranger = better chance the next sighting
    # matches one of them. Near-identical templates are skipped (see
    # services/unknown_identity.py) so these slots hold genuinely different views.
    "unknown_max_templates": 15,
    # Same camera, seen again within this many seconds -> almost certainly the
    # same person still standing there; accept a lower similarity.
    "unknown_recent_window_seconds": 120,
    "unknown_recent_threshold": 0.30,
    "unknown_auto_ignore_days": 30,
    "working_days_per_week": 5,
    # --- Timesheet / payroll (services/timesheet.py) ---
    # Weekly off days, Mon=0 .. Sun=6. Used by timesheets and payroll exports.
    "weekly_off_days": [6],
    # A night shift's sightings up to this many hours after the shift ends
    # count toward the shift's start date.
    "night_shift_tail_hours": 4,
    # Overtime = time after shift end, if at least `ot_min_minutes`, rounded
    # DOWN to `ot_rounding_minutes`. On a weekly off, all worked time is OT.
    "ot_enabled": True,
    "ot_min_minutes": 30,
    "ot_rounding_minutes": 15,
    # Day status by hours worked (first to last sighting). 0 = off: any
    # sighting is a full day (right for sites with only an entry camera).
    "full_day_min_hours": 0,
    "half_day_min_hours": 0,
    # People with no roster row and no fixed shift: pick the shift whose
    # start is nearest their first sighting (for late / OT maths).
    "auto_shift_detect": True,
    # Emergency muster: how far back a sighting still counts (covers a night shift).
    "muster_window_hours": 16,
    # kiosk_id -> "entry" | "exit" | "both" (set from the Muster page).
    "camera_roles": {},
    # --- Alerts ---
    "alert_cooldown_minutes": 30,
    "alert_on_spoof": True,
    "spoof_alert_cooldown_minutes": 10,
    "device_preference": "auto",
    # Device-dependent: seeded from the resolved device profile at first
    # kiosk heartbeat (see routers/kiosk.py); these are the CPU-baseline
    # defaults used until then.
    "capture_fps": 6,
    "bestshot_frames": 5,
    "ort_intra_op_threads": 4,
    "det_size": "640,640",
    # Kiosk face-quality gate (kiosk/quality.py): bad frames are never
    # embedded, because a bad embedding can't be matched by any threshold.
    "quality_gate_enabled": True,
    "quality_min_det_score": 0.60,
    "quality_min_frontality": 0.50,
    "quality_min_pitch_ratio": 0.28,
    "quality_max_pitch_ratio": 0.75,
    "quality_min_brightness": 40.0,
    "quality_min_sharpness": 20.0,
    # combined quality score (0-1): below this the kiosk drops the frame, and
    # the server never learns a face template from it (hand over the face
    # ~0.35-0.4, clear face ~0.7+)
    "quality_min_score": 0.50,
}

# Keys whose *default* depends on the resolved device profile (see spec's
# DEVICE-DEPENDENT TUNING table). Applied once, the first time a kiosk
# heartbeat reports its resolved profile, and never overwritten again if the
# operator has since changed them by hand.
DEVICE_DEPENDENT_KEYS = {"capture_fps", "bestshot_frames", "ort_intra_op_threads", "det_size"}

GPU_TUNING_DEFAULTS: dict[str, Any] = {
    "capture_fps": 15,
    "bestshot_frames": 8,
    "ort_intra_op_threads": 1,
    "det_size": "640,640",
}


async def get_all_settings(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(select(Setting))
    # Rows that aren't runtime tunables (the vendor-locked client profile, see
    # services/client_profile.py) are not settings and must never round-trip
    # through the Settings page.
    rows = {row.key: row.value_json for row in result.scalars().all() if not row.key.startswith("client_")}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(rows)
    return merged


async def get_setting(db: AsyncSession, key: str) -> Any:
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row is not None:
        return row.value_json
    if key in DEFAULT_SETTINGS:
        return DEFAULT_SETTINGS[key]
    raise KeyError(key)


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        db.add(Setting(key=key, value_json=value))
    else:
        row.value_json = value
    await db.flush()


async def apply_device_profile_defaults_if_unset(db: AsyncSession, profile: str) -> None:
    """Called once per kiosk heartbeat. Only fills in device-dependent keys
    that have NEVER been explicitly set by an operator -- an existing row
    always wins, so a hand-tuned value survives a device change."""
    if profile not in ("cpu", "gpu"):
        return
    defaults = GPU_TUNING_DEFAULTS if profile == "gpu" else {k: DEFAULT_SETTINGS[k] for k in DEVICE_DEPENDENT_KEYS}
    for key, value in defaults.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        if result.scalar_one_or_none() is None:
            db.add(Setting(key=key, value_json=value))
    await db.flush()
