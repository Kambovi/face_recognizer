# TUNING.md

Every value in this file lives in the `settings` table (`app/models/
settings.py`), editable from the Settings page or `PATCH /api/v1/settings`,
never hardcoded (NON-NEGOTIABLE #1). `app/services/settings_service.py`'s
`DEFAULT_SETTINGS` is what a fresh install starts with, before an operator
changes anything; once a row exists for a key, the DB value always wins.
The kiosk polls `GET /kiosk/config` (a read-only projection of this same
table) every `settings_refresh_seconds` and applies changes to its
already-running gates in place — no kiosk restart needed for a tuning
change to take effect.

## Recognition thresholds

| Key | Default | What it controls |
|---|---|---|
| `similarity_threshold` | `0.38` | Minimum cosine similarity for a 1:N match (step 7-8) to count as "this is employee X" rather than falling through to unknown-identity clustering. Lower = more false accepts (different people matched as the same); higher = more false rejects (the same person's own face not recognized, especially across lighting/angle variation). `0.38` is a conservative-permissive middle value for ArcFace-family embeddings; a real deployment should tune this against its own enrolled population's false-accept/false-reject tradeoff, not trust the default blindly. |
| `unknown_cluster_threshold` | `0.55` | Minimum similarity for a below-`similarity_threshold` face to be clustered onto an *existing* UNKNOWN identity rather than creating a brand-new one. Deliberately looser than `similarity_threshold` isn't required — it's a separate population (unknown visitors, not enrolled employees) with its own tolerance; the specific value controls how "clumpy" repeat-unknown-visitor tracking is. |
| `same_person_threshold` | `0.90` | Kiosk-side subject-gate check 3 (`subject_gate.py`'s `check_embedding`): how similar a new embedding must be to a recently-processed one to be treated as "still the same person standing there" and skipped rather than re-sent. Intentionally much higher than `similarity_threshold` — this is a dedupe check against a known-recent sighting, not an identity search, so it can afford to be strict without risking missed recognitions. |
| `min_face_pixels` | `80` | Faces detected smaller than this (in bounding-box height) never reach liveness/embedding — reported as a `too_small` reject instead. Too low and the detector wastes cycles on faces too small to embed reliably; too high and a legitimately-distant-but-real visitor gets rejected. |

## Liveness

| Key | Default | What it controls |
|---|---|---|
| `liveness_enabled` | `true` | Master on/off switch for spoof detection (step 5). Disabling it entirely is a real security tradeoff an operator explicitly opts into (e.g. a controlled environment with no spoof risk) — never disabled implicitly by a missing model. |
| `liveness_threshold` | `0.75` | Minimum "real face" probability from MiniFASNet to pass. Below this: `liveness_failed`, and — per NON-NEGOTIABLE #3 — zero recognition/matching calls happen for that frame. |

## Dedupe / attendance state machine

| Key | Default | What it controls |
|---|---|---|
| `dedupe_window_minutes` | `5` | The sliding window `upsert_attendance_event()` (`app/services/attendance.py`) uses to decide "is this a continuation of the last sighting (merge into the existing row) or a genuinely new event (create a new IN/OUT row)". Set this to roughly your shortest plausible real in-then-out gap (e.g. a quick break) so genuine separate visits aren't merged, but repeated frames of one doorway pass aren't split into spurious duplicate rows. |
| `iou_same_subject` | `0.85` | Kiosk-side subject-gate check 2: bounding-box IoU threshold for "this detection is the same physical person still standing in roughly the same spot" — high because it's guarding against re-processing the same still-present face, not tracking motion. |
| `recent_embedding_buffer` | `5` | Size of the kiosk-side ring buffer subject-gate check 3 compares new embeddings against. Larger = better dedupe recall across brief occlusions/track breaks, at the cost of a few more `cosine_similarity` calls per frame (cheap; this is pure numpy, no model inference). |

## Motion gate / idle-cost (NON-NEGOTIABLE #6)

| Key | Default | What it controls |
|---|---|---|
| `motion_pixel_threshold` | `25` | Per-pixel grayscale intensity delta (0-255) above which a pixel counts as "changed" between consecutive frames. |
| `motion_area_threshold` | `0.02` | Fraction of the frame's pixels that must have "changed" (per the threshold above) for the frame to count as motion at all. Together these two are the entire cost of an idle frame: two cheap array operations, no model call. |
| `idle_frames_before_sleep` | `60` | Consecutive no-motion frames before the kiosk drops from `capture_fps` down to `idle_fps`. |
| `idle_fps` | `1` | Capture rate once idle — this (not `capture_fps`) is what actually determines steady-state idle CPU cost on an empty kiosk. |
| `reference_refresh_seconds` | `30` | How often the motion gate's "reference" (baseline, no-motion) frame is refreshed, so gradual lighting drift over the course of a day doesn't get misread as permanent motion. |

## Best-shot buffering (step 4)

| Key | Default (CPU) | Default (GPU) | What it controls |
|---|---|---|---|
| `bestshot_frames` | `5` | `8` | Max candidate frames buffered per visit before forcing a decision even if the time window hasn't elapsed. More candidates = better odds of catching a genuinely sharp, frontal frame, at the cost of a slightly longer per-visit latency and (CPU) more detector calls per visit. |
| `bestshot_window_seconds` | `1.5` | `1.5` | Max wall-clock time to keep buffering before picking the best candidate seen so far, even if fewer than `bestshot_frames` were captured — bounds worst-case per-visit latency. |

## Device-dependent tuning (auto-applied once, then operator-owned)

`capture_fps`, `bestshot_frames`, `ort_intra_op_threads`, and `det_size` are
each seeded from the resolved device profile (CPU vs GPU — see
`kiosk/kiosk/device.py`'s `_TUNING_DEFAULTS`) the *first* time a kiosk
reports its heartbeat, and never silently overwritten again afterward, even
if the device profile later changes (e.g. a GPU driver starts failing and
the kiosk falls back to CPU) — an operator who has since hand-tuned these
values should not have them clobbered by a later automatic re-seed.

| Key | CPU default | GPU default | Why they differ |
|---|---|---|---|
| `capture_fps` | `6` | `15` | GPU inference is fast enough to usefully sample more frames per second without the detector becoming the bottleneck; on CPU, higher fps mostly means more wasted detector calls on frames that get discarded by the best-shot buffer anyway. |
| `bestshot_frames` | `5` | `8` | More GPU headroom means affording more candidates per visit for a better best-shot pick, without materially increasing per-visit latency. |
| `ort_intra_op_threads` | `min(4, cpu_count)` | `1` | On CPU, ONNX Runtime benefits from multiple intra-op threads for a single inference call. On GPU, the actual compute happens on the device; extra CPU threads mostly add contention/overhead around dispatching to it. |
| `det_size` | `640,640` | `640,640` | Currently identical — det_size primarily trades detector accuracy for compute cost, and 640x640 was judged a reasonable default for both profiles; a deployment with either much smaller subjects-in-frame (increase) or much tighter GPU latency budgets (decrease) can override it directly. |

## Retention (see also `docs/DPDP_COMPLIANCE.md`)

| Key | Default | What it controls |
|---|---|---|
| `crop_retention_days` | `90` | Intended lifetime of saved face crops before deletion. **Not currently auto-enforced** — see `docs/DPDP_COMPLIANCE.md`'s "Retention" section for why (no scheduler in the fixed tech stack) and what an operator needs to do about it today. |
| `unknown_auto_ignore_days` | `30` | Intended age at which a never-resolved UNKNOWN identity should be auto-marked ignored. Same caveat: the setting exists and is read by nothing yet. |

## Business/reporting

| Key | Default | What it controls |
|---|---|---|
| `working_days_per_week` | `5` | Used by `app/services/analytics.py` to compute expected working days for absence/attendance-rate calculations — see `docs/DECISIONS.md` for the documented simplification this implies (uniform Mon-Fri across all employees, no per-employee weekly-off rotation or holiday calendar). |
| `device_preference` | `"auto"` | Passed straight through to `device.resolve_providers()` — `"auto"`, `"cpu"`, or a specific provider name. See `docs/RUNBOOK.md`'s "Upgrading to GPU" for when to change this. |

## How to actually tune these in practice

1. Change one setting at a time via `PATCH /api/v1/settings` (or the
   Settings page) and watch `make bench`'s per-stage latency output plus a
   short live observation period — this system deliberately has no
   automatic threshold-tuning; every value here is a judgment call an
   operator makes against their own site's lighting, camera placement, and
   population.
2. `similarity_threshold` and `unknown_cluster_threshold` are the two most
   consequential values for real-world accuracy and should be tuned against
   a labeled sample of real enrolled employees' faces under real kiosk
   lighting before go-live, not left at their defaults.
3. Motion-gate and best-shot values matter for CPU cost and latency, not
   accuracy — tune these against `make bench`'s numbers and observed idle
   CPU usage, not against recognition quality.
