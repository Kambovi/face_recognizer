# Face Attendance — current status (2026-09-23)

## Environment
Running natively on Windows (no Docker — laptop's BIOS has no virtualization option). SQLite instead of Postgres. Package manager: `uv` (must pin `--python 3.11`, else it grabs 3.13 and wheels break).

Project path on user's PC: `D:\DS PROJECTS\face-attendance\`

## How to run (3 terminals, in this order)
1. **Backend** — `cd backend`, activate venv, then just:
   ```
   uvicorn app.main:app --reload
   ```
   Do NOT override `JWT_SECRET` / `KIOSK_SERVICE_TOKEN` — use the built-in defaults (`dev_only_change_me_to_a_long_random_string` / `dev_only_kiosk_service_token`). Overriding them on some restarts and not others caused a chain of 401 bugs.
2. **Frontend** — `cd frontend`, `npm install` (needed once after the 2026-09-23 dashboard redesign added `lucide-react`), then `npm run dev` → opens at **http://localhost:5173** (NOT 3000 — that's only the Docker/nginx port).
3. **Kiosk** — `cd kiosk`, activate its own venv, then:
   ```
   $env:CAMERA_SOURCE="0"
   $env:API_BASE_URL="http://localhost:8000"
   $env:KIOSK_SERVICE_TOKEN="dev_only_kiosk_service_token"
   uv run python -m kiosk.main
   ```
   `CAMERA_SOURCE=0` = laptop webcam. Env vars are per-terminal-session — must be re-set every time a new PowerShell window is opened (kiosk has no `.env` auto-load, unlike backend).

Login: `admin@example.com` / `ChangeMe123!`. If dashboard ever 401s after a backend restart, it's a stale JWT — log out and back in.

## Dashboard redesign (DONE 2026-09-23, written into the project)
User asked for an enterprise-style attendance dashboard: 4 clickable KPI cards (Known Present / Unknown Present / Absent / Exception) that filter one unified table; table columns Photo, Face ID, Name, Designation, Department, In, Out, Total Hours, Status (Active/Inactive), On Time (Yes/No pill); every column sortable (asc → desc → default); pagination + row count; filter bar with multi-select "Unit / Entry point" (Select All) and a Day / Month / Year / Range date picker for history.

**Backend** (backward compatible — `/dashboard/today` still works, all fields additive):
- New `GET /api/v1/dashboard?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` (inclusive, IST, max 366 days → 422 otherwise). `services/dashboard.py::get_dashboard()`; `/today` now delegates to it.
- One row per subject per local day. New row fields: `date`, `kiosk_ids` (entry points seen that day), `is_active`, `on_time` (known); `date`, `kiosk_ids` (unknown/exceptions); `date`, `is_active` (absent). Response adds `date_from`, `date_to`, `kiosks` (heartbeats ∪ event kiosks).
- Constant query count (was N+1 per employee and per unknown); template thumbnails fetched without embedding columns.
- Absences: only active employees, only days ≥ enrollment date, never future days. Inactive employees still show as Known if seen.
- **Fixed** the flagged "Unknown sightings = all-time OPEN" inconsistency: unknowns now = identities actually seen in the range.
- New test `backend/tests/test_dashboard_range.py` (2 tests). Full suite 22 passed (test_device needs onnxruntime, not run in sandbox); ruff + mypy clean.

**Frontend**:
- `pages/Dashboard.tsx` rewritten; new `components/dashboard/` (`model.ts` types + pure helpers, `KpiCards.tsx`, `FilterControls.tsx` = UnitMultiSelect + DateRangePicker, `AttendanceTable.tsx` = table + Pagination, `model.test.ts` 8 tests).
- "Unit / entry point" = **kiosk_id** (camera). There is no employee→unit mapping in the data model, so Absent rows (no camera) stay visible whenever ≥1 entry point is selected. If the user actually means department-style units (Doctors/Staff/Security/Admin), that's a different filter (employees.department) — not built.
- Exceptions attach to their person/day row (amber chips under the name); orphans (liveness failure, face_id = kiosk id) get their own row. Exception KPI counts rows with ≥1 exception, so it overlaps Known/Unknown.
- Raw kiosk events + Correct modal kept, now range-aware, collapsed by default, with an Entry point column.
- Polls every 30s only while the range includes today. tsc -b, eslint (0 warnings), vitest (22), vite build all green. Verified in headless Chromium against a live backend with seeded data.
- Added dependency `lucide-react@1.47.0` (package.json + lock updated) — user must run `npm install`.

Stray file noticed: `backend/app/services/Dashboard.tsx` (a copy of the old frontend page sitting in the backend services folder) — harmless, safe to delete.

## Earlier code changes this session
- `frontend/src/pages/Dashboard.tsx` — added a "Photo" column (face crop thumbnail) to both the Known and Unknown tables (superseded by the redesign above).
- `backend/app/services/recognition.py` — crop storage path changed from `events/{kiosk_id}/` to `events/{local_date}/{kiosk_id}/`, so crops land in one folder per calendar day. Decided AGAINST adding an explicit `batch_id` (UUID) column — redundant with `occurred_at`.

## Testing findings / known non-bugs
- Seeded 100 demo employees have **synthetic/fake face embeddings** — the user's real face will never match them. Real webcam detections will always land in "Unknown" until the user enrolls their own face as an employee via the Employees page.
- Confirmed working end-to-end: webcam capture → face detect/align → embed → event posted → offline queue replay.

## Analytics/UI redesign (separate, paused thread)
User pasted a large GPT-written redesign brief for the Analytics page. `/analytics/summary` returns one aggregated row per employee for the whole period (no day-by-day granularity), so a true multi-day trend chart needs a backend change or client-side aggregation of `/attendance/events` (or the new per-day `GET /dashboard` rows). **Not implemented.**

## Open/pending items
- Analytics page redesign (see above) — not started.
- MiniFASNet liveness model still fails to download (404 upstream); liveness fails open.
- Decide whether "units" should be entry points (built) or departments.