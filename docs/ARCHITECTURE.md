# ARCHITECTURE.md

A tour of how the pieces fit together. For *why* a given design was chosen
over an alternative, see `docs/DECISIONS.md` — this file describes what
exists, not why it looks the way it does.

## The four services

`docker compose up` runs four containers, wired by `docker-compose.yml`:

- **`db`** — `pgvector/pgvector:pg16`, a stock Postgres 16 image with the
  `pgvector` extension pre-installed. Holds every table. A named volume
  (`pgdata`) persists it across restarts.
- **`api`** — the FastAPI backend (`backend/`). Owns the database, the REST
  surface under `/api/v1`, biometric encryption, the recognition-matching
  and attendance state machine, and (only for enrollment photos) its own
  ONNX inference. Runs `alembic upgrade head` before `uvicorn` starts
  (see its Dockerfile's runtime-stage `CMD`).
- **`kiosk`** — the recognition-pipeline process (`kiosk/`). Runs the
  camera-facing half of the pipeline (motion gate through best-shot
  buffering, liveness, embedding) and posts finished events to the API over
  HTTP. Never touches Postgres directly.
- **`web`** — the React admin/HR dashboard (`frontend/`), built to a static
  bundle and served by nginx.

Two named volumes cross the api/kiosk boundary: `models` (shared ONNX model
cache — whichever container downloads `buffalo_l` first, the other reuses
it) and `media` (api-only, holds saved face crops); `kiosk_queue` is the
kiosk's private offline-events SQLite file.

## Why the kiosk never talks to Postgres

The kiosk is a single-purpose, possibly-many-of-them process (one per
physical kiosk device) that should be safe to run on hardware an operator
doesn't fully trust with database credentials, and safe to lose without
losing data. It only ever calls the API's HTTP surface
(`POST /api/v1/kiosk/event`, `GET /api/v1/kiosk/config`,
`POST /api/v1/kiosk/heartbeat`) using a shared static bearer token
(`KIOSK_SERVICE_TOKEN`) — a deliberately simpler auth model than the
JWT-based admin/viewer auth, since a kiosk is a service identity, not a
human session. If the API is unreachable, events queue locally
(`kiosk/kiosk/offline_queue.py`) and replay once it's back — see
`docs/DECISIONS.md`.

## The recognition pipeline, split across two processes

The spec's 11-step pipeline is split at the embedding boundary:

**Kiosk-side (`kiosk/kiosk/pipeline.py`), steps 1-6, all local, all CPU (or
GPU) inference with no network round-trip per frame:**

1. **Motion gate** (`motion_gate.py`) — cheap frame-diff check; the
   expensive detector is never called on a static scene (NON-NEGOTIABLE #6).
2. **Detect** (`face_engine.py`'s `.detect()`) — SCRFD face detection.
   1b. **Subject gate, pre-embedding** (`subject_gate.py`'s
   `check_pre_embedding()`) — track continuity + bounding-box IoU dedupe,
   run on the box alone, before anything more expensive.
3. **Size reject** — a detected face below `min_face_pixels` is reported as
   a `too_small` reject and short-circuits before liveness/embedding.
4. **Best-shot buffering** (`bestshot.py`) — buffers up to
   `bestshot_frames` candidates over `bestshot_window_seconds` and scores
   each by sharpness x frontality x face-area; only the single best crop
   proceeds.
5. **Liveness** (`liveness.py`) — MiniFASNet anti-spoofing on the winning
   crop; a failing score reports a `liveness_failed` reject and stops
   before any embedding is computed (NON-NEGOTIABLE #3).
6. **Embed** (`face_engine.py`'s `.embed()`) — ArcFace embedding of the
   winning crop. 1b. **Subject gate, post-embedding**
   (`check_embedding()`) — cosine similarity against a short recent-embedding
   ring buffer, the safety net for when track continuity breaks (e.g. a
   brief occlusion assigns a new track id) but it's actually the same
   recently-seen person.

The result of steps 1-6 is a payload (`embedding`, `quality_score`,
`liveness_score`, a base64 JPEG crop, or a reject reason with no embedding)
posted to `POST /api/v1/kiosk/event`, or queued offline on failure.

**Backend-side (`backend/app/services/recognition.py`), steps 7-11, all
inside one request/DB transaction:**

7. **1:N similarity search** (`services/matching.py`) — pgvector `<=>`
   cosine search on Postgres; a Python fallback for SQLite (tests only).
8. **Threshold decision** — match above `similarity_threshold` -> known
   employee; below -> unknown-identity clustering
   (`services/unknown_identity.py`'s `cluster_or_create_unknown()`, a
   looser 1:N search against UNKNOWN-owned templates).
9. **Attendance state machine** (`services/attendance.py`'s
   `upsert_attendance_event()`) — IN/OUT with a sliding dedupe window: a
   repeat sighting within `dedupe_window_minutes` updates the existing row
   ("latest wins"); a sighting past the window creates a new row, flipping
   IN/OUT.
10. **Persistence** — the event row, envelope-encrypted embedding
    (`app/security.py`), and crop are written together.
11. **Response** — `face_id`, `subject_type`, `event_type`, `similarity`
    are returned to the kiosk (never the raw embedding — NON-NEGOTIABLE #2);
    the kiosk logs it and moves on.

## Backend module map

```
backend/app/
  main.py            FastAPI app, middleware, router registration
  config.py           Settings (env-backed, pydantic-settings)
  device.py            ONNX provider resolution (byte-identical copy of kiosk/kiosk/device.py)
  db.py                 Async engine/session, dialect detection (Postgres vs SQLite)
  deps.py                FastAPI dependencies: get_db, require_admin, get_current_user
  security.py             Password hashing, JWT, envelope encryption
  models/                 SQLAlchemy 2.0 ORM (one file per table, see the 9-table list below)
  schemas/                Pydantic v2 request/response models, one file per router
  routers/                One file per resource: auth, employees, dashboard, attendance,
                             unknowns, analytics, settings, kiosk, media, shifts, health
  services/               Business logic, framework-agnostic: attendance, matching,
                             unknown_identity, embedding, quality, analytics, dashboard,
                             audit, settings_service, media, ids
  migrations/            Alembic env + hand-written versioned migrations
```

**The 9 tables** (`app/models/`): `employees`, `shifts`, `consents`,
`face_templates`, `attendance_events`, `unknown_identities`,
`kiosk_heartbeats` (not in the spec's literal list — see
`docs/DECISIONS.md`), `users`, `audit_log`, plus a `settings` key/value
table for runtime tuning (10 total tables; "9-table data model" in the spec
predates `kiosk_heartbeats` and `settings` being called out separately).

## Kiosk module map

```
kiosk/kiosk/
  main.py            Process entrypoint: wires everything together, the run loop
  config.py           KioskConfig (env-backed)
  device.py             ONNX provider resolution (THE canonical copy; see docs/DECISIONS.md)
  capture.py              Frame source: synthetic PIL faces, a cv2.VideoCapture index, or an rtsp:// URL
  face_engine.py            SCRFD detect() + ArcFace embed(), as two separate model calls
  liveness.py                 MiniFASNet anti-spoofing
  motion_gate.py                Step 1: cheap frame-diff gate
  subject_gate.py                 Step 1b: track continuity + IoU + embedding-similarity dedupe
  bestshot.py                       Step 4: buffering + sharpness/frontality/area scoring
  offline_queue.py                    Step 11: local SQLite durable queue + idempotent replay
  api_client.py                         Thin HTTP client for the three kiosk-facing endpoints
  pipeline.py                             Orchestrates steps 1-6 end to end
  bench.py                                  `make bench` -- per-stage latency microbenchmark
```

## Frontend module map

```
frontend/src/
  api/                client.ts (axios + every typed API call), types.ts (mirrors backend schemas)
  auth/                AuthContext.tsx: JWT storage, AuthProvider/useAuth()
  components/           DataTable, Layout, ProtectedRoute, CorrectionModal
  pages/                 Login, Dashboard, Analytics, Unknowns, Employees, Settings
  utils/                  format.ts: the one place UTC timestamps become Asia/Kolkata display strings
```

Routing: `react-router-dom`, gated by `ProtectedRoute` (redirects to
`/login` if no valid token). Data fetching is plain `useEffect` + the typed
`api/client.ts` functions (no query-caching library) — five pages was
judged too small a surface to justify one.

## Auth model

Two schemes, deliberately different, because they protect different things:

- **Admin/viewer (human users, the web app):** JWT (HS256), issued by
  `POST /api/v1/auth/login`, bcrypt-hashed passwords
  (`app/security.py`). `require_admin` / `get_current_user` FastAPI
  dependencies gate each router.
- **Kiosk (service identity, the kiosk process):** a single static bearer
  token (`KIOSK_SERVICE_TOKEN`), the same for every kiosk in this
  single-site deployment. Checked by a lightweight dependency in
  `routers/kiosk.py`, entirely separate from the JWT path.

## Data flow at a glance

```
 [kiosk process]                                    [api process]
  camera/synthetic frame
       |
       v
  motion gate --(no motion)--> idle, no detector call
       |
       v (motion)
  detect --(no face)--> reset, wait
       |
       v
  subject gate (pre-embed) --(dedup hit)--> gated, no further work
       |
       v
  size check --(too small)-----------------------> POST /kiosk/event (reject_reason=too_small, no embedding)
       |
       v
  best-shot buffer (accumulate up to N frames / T seconds)
       |
       v
  liveness --(fail)-------------------------------> POST /kiosk/event (reject_reason=liveness_failed, no embedding)
       |
       v
  embed
       |
       v
  subject gate (post-embed) --(dedup hit)--> gated, no further work
       |
       v
  POST /kiosk/event (embedding, quality, liveness, crop)  ---->  1:N pgvector search
                                                                       |
                                                    match >= threshold | below threshold
                                                                 v                 v
                                                          known employee    cluster_or_create_unknown
                                                                 |                 |
                                                                 v                 v
                                                          upsert_attendance_event (IN/OUT + dedupe)
                                                                 |
                                                                 v
                                                          encrypt + persist + respond
```

If the `POST /kiosk/event` call itself fails (network partition, API down),
the payload is written to the kiosk's local offline queue instead and
replayed later — everything above the wire, and everything below it, is
unaffected by that failure mode.
