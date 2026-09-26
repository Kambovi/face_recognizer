# Face Attendance

> **Start here:** [`docs/PROJECT_BIBLE.md`](docs/PROJECT_BIBLE.md) (how everything works, runs and deploys) · [`docs/CLIENT_DEPLOYMENT.md`](docs/CLIENT_DEPLOYMENT.md) (installing at a client) · [`docs/BUSINESS_PLAYBOOK.md`](docs/BUSINESS_PLAYBOOK.md) · [`docs/FORMS_AND_TEMPLATES.md`](docs/FORMS_AND_TEMPLATES.md) · [`docs/PRODUCT_REPORT.md`](docs/PRODUCT_REPORT.md) (features + client pitch)

A production-grade, single-site kiosk face-recognition attendance system
for a ~100-employee office: a camera-facing kiosk process that detects,
liveness-checks, and recognizes faces locally; a FastAPI + Postgres/pgvector
backend that owns matching, the attendance state machine, and biometric
data protection; and a React admin dashboard for HR to review, correct, and
report on attendance.

```
┌─────────┐  synthetic/RTSP frame   ┌─────────────┐  HTTP (bearer token)   ┌─────────────┐   HTTP (JWT)   ┌──────────┐
│ Camera  │ ───────────────────▶   │   kiosk     │ ─────────────────────▶ │     api     │ ◀───────────── │   web    │
│ / synth │                        │ (steps 1-6) │  POST /kiosk/event      │ (steps 7-11)│                │ (React)  │
└─────────┘                        └─────────────┘                        └──────┬──────┘                └──────────┘
                                                                                   │
                                                                            ┌──────▼──────┐
                                                                            │  Postgres   │
                                                                            │  + pgvector │
                                                                            └─────────────┘
```

See `docs/ARCHITECTURE.md` for the full module-by-module tour,
`docs/DECISIONS.md` for every design call and its reasoning,
`docs/TUNING.md` for what every runtime-tunable setting does,
`docs/RUNBOOK.md` for operating it, and `docs/DPDP_COMPLIANCE.md` for how
its data-protection controls map onto India's DPDP Act.

## Quickstart

Requires Docker and Docker Compose. No local Python/Node install needed to
run the system (only for local development against it — see below).

```
cp .env.example .env          # defaults work for a demo; see docs/RUNBOOK.md before production
make up                       # docker compose up -d --build; waits for GET /health
make seed                     # 100 synthetic employees, ~12 days of attendance history, 5 unknown visitors
make smoke                    # end-to-end proof: login, enroll, recognize, dedupe, correct, cluster
```

Then open `http://localhost:3000` (default admin credentials are seeded by
`make seed` — see its output) and `http://localhost:8000/api/v1/health`
directly if you just want the raw status JSON.

`make down` stops everything; `make clean` also removes local dev
virtualenvs, `node_modules`, and the frontend build output.

## What each piece is

- **`kiosk/`** — the recognition-pipeline process. Runs motion detection,
  face detection, best-shot frame selection, liveness (anti-spoofing), and
  embedding entirely locally; posts only a finished event (an embedding,
  quality/liveness scores, and a small crop — never a raw camera frame) to
  the API. Never touches Postgres directly. See `kiosk/kiosk/main.py`.
- **`backend/`** — FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + Alembic.
  Owns the 1:N similarity search (pgvector), the unknown-visitor clustering,
  the IN/OUT attendance state machine with dedupe, envelope encryption of
  biometric data, JWT auth for admins/viewers, and the full REST surface
  under `/api/v1`. See `backend/app/main.py`.
- **`frontend/`** — React 18 + TypeScript + Vite. Five pages: Dashboard
  (today's attendance + a correction workflow), Analytics, Unknowns
  (review/link/split/promote unrecognized visitors), Employees, Settings
  (every runtime-tunable value in `docs/TUNING.md`, editable live).

## Local development (without Docker, per service)

**Backend:**
```
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install onnxruntime==1.19.2        # or onnxruntime-gpu, see "Upgrading to GPU"
DATABASE_URL_SYNC=sqlite:///./dev.db DATABASE_URL=sqlite+aiosqlite:///./dev.db \
  EMBEDDING_ENCRYPTION_KEY=<generate one, see docs/RUNBOOK.md> \
  JWT_SECRET=dev_secret KIOSK_SERVICE_TOKEN=dev_token \
  alembic upgrade head
uvicorn app.main:app --reload
```

**Kiosk** (against a running API, `CAMERA_SOURCE=synthetic` needs no camera
hardware):
```
cd kiosk
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install onnxruntime==1.19.2
API_BASE_URL=http://localhost:8000 KIOSK_SERVICE_TOKEN=dev_token python -m kiosk.main
```

**Frontend:**
```
cd frontend
npm install
npm run dev
```

## Testing

```
make test              # all three suites, in throwaway venvs / node_modules
make test-backend      # backend/: pytest, incl. one dedicated proof test per NON-NEGOTIABLE
make test-kiosk        # kiosk/: pytest, incl. the near-zero-idle-CPU proof tests
make test-frontend     # frontend/: tsc -b && vite build && vitest run
make lint              # ruff + mypy (backend, kiosk) + eslint (frontend), all must be clean
make bench             # kiosk/kiosk/bench.py -- per-stage recognition-pipeline latency
```

Every one of the spec's 8 NON-NEGOTIABLES has a dedicated test proving it,
named for what it proves (e.g. `backend/tests/test_nn2_biometric_protection.py`,
`kiosk/tests/test_pipeline.py`'s idle-CPU tests for NON-NEGOTIABLE #6, the
source-scan test for NON-NEGOTIABLE #8) — see `docs/ARCHITECTURE.md` and
the test files themselves for what each one actually checks.

## Upgrading to GPU

The kiosk (and the backend's own enrollment-time inference) run on CPU by
default. Moving either to GPU is a two-file, two-line change — deliberately
small, because `kiosk/kiosk/device.py` (byte-identical in
`backend/app/device.py`; see `docs/DECISIONS.md`) is the *only* place in
the entire codebase that ever chooses an ONNX Runtime execution provider.
Nothing else needs to change.

1. **Confirm host GPU support.** The Docker host needs an NVIDIA GPU, the
   NVIDIA driver, and the NVIDIA Container Toolkit installed (`nvidia-smi`
   should work both on the host and inside a test container run with
   `--gpus all`).

2. **Set `ORT_FLAVOR=gpu`** in `.env` (or export it before `make up`).
   This is a Docker build arg (`docker-compose.yml` -> both Dockerfiles)
   that switches which ONNX Runtime wheel gets installed:
   `onnxruntime-gpu==1.19.2` instead of `onnxruntime==1.19.2`. No other
   dependency changes.

3. **Uncomment the GPU reservation block** for both `kiosk` and `api` in
   `docker-compose.yml` (each service already has a commented-out
   `deploy.resources.reservations.devices` block with `driver: nvidia`
   ready to go — just remove the leading `#`s).

4. **Set `DEVICE_PREFERENCE=auto`** (the default) or explicitly `gpu` in
   `.env`. `auto` tries GPU-capable providers first (in priority order:
   TensorRT, then CUDA, then CoreML) and falls back to CPU automatically —
   see `device.py`'s module docstring for exactly why a *reported*-available
   provider can still silently fail, and how this module catches that
   (it builds a real session and runs real inference before trusting a
   provider, rather than trusting `onnxruntime.get_available_providers()`
   at face value).

5. **Rebuild and restart:**
   ```
   docker compose build kiosk api
   docker compose up -d
   ```

6. **Verify it actually took.** `GET /api/v1/health`'s `device` block
   reports the resolved provider and profile:
   ```json
   { "device": { "provider": "CUDAExecutionProvider", "profile": "gpu", "status": "ok", "fallback_from": null, ... } }
   ```
   If `provider` still says `CPUExecutionProvider`, check `fallback_from`
   (non-null means it tried a GPU provider and fell back — check container
   logs for the specific failure) and confirm step 1's toolkit is correctly
   wired into the Docker daemon.

7. **Re-tune, don't assume the CPU defaults still apply.** The first kiosk
   heartbeat after a fresh `device_preference`/profile change seeds
   `capture_fps`, `bestshot_frames`, `ort_intra_op_threads`, and `det_size`
   from the GPU tuning defaults automatically (see `docs/TUNING.md`), but
   only if those settings have never been manually overridden before —
   if you'd already hand-tuned CPU values, revisit them for the new
   profile explicitly via the Settings page. Run `make bench` before and
   after to confirm the expected latency improvement actually materialized.

Reverting to CPU is the same procedure in reverse: `ORT_FLAVOR=cpu`,
re-comment the GPU blocks, rebuild.

## Repository layout

```
backend/     FastAPI + Postgres/pgvector backend (see backend's own app/ tree)
kiosk/       Recognition-pipeline kiosk process
frontend/    React + TypeScript admin dashboard
docs/        ARCHITECTURE, DECISIONS, DPDP_COMPLIANCE, TUNING, RUNBOOK (this tree)
docker-compose.yml   The four services: db, api, kiosk, web
Makefile             up/down/seed/smoke/test/bench/lint — see targets above
.env.example         Every environment variable, with working defaults
```
