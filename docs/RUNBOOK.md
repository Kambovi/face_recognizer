# RUNBOOK.md

Operational reference for running this system day to day: first deploy,
health checks, common failures and what to do about them, backup/restore,
and the production-hardening checklist a `docker compose up` dev setup
does not give you for free.

## First deploy

```
cp .env.example .env        # edit JWT_SECRET, EMBEDDING_ENCRYPTION_KEY, POSTGRES_PASSWORD for anything beyond a demo
make up                     # docker compose up -d --build, waits for /health
make seed                   # 100 synthetic employees, ~12 days of attendance history, 5 unknowns
make smoke                  # full E2E proof: login, enroll, recognize, dedupe, correct, unknown-cluster
```

Generate real values rather than keeping the `.env.example` defaults for
anything beyond a local demo:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # EMBEDDING_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"                                 # JWT_SECRET
```

**`EMBEDDING_ENCRYPTION_KEY` cannot be rotated by simply changing it** —
every already-encrypted embedding's wrapped DEK is wrapped with the OLD
master key, and swapping the key without a re-wrap migration makes every
existing biometric record undecryptable. If real key rotation is ever
needed: decrypt every `embedding_encrypted` row with the old key, re-wrap
under the new key, write it back, in one transaction per row — there is no
tool for this in the repo today; treat it as a one-off migration script to
write when the need arises, not a routine operation.

## Health checks

`GET /api/v1/health` is the single source of truth for "is this deployment
OK":

```json
{
  "status": "ok" | "degraded",
  "db": "ok" | "error",
  "model": "buffalo_l (kiosk-side; see device block)",
  "device": { "provider": "...", "profile": "cpu|gpu", "status": "...", "stale": false, ... },
  "time": "..."
}
```

- `db: error` — Postgres is unreachable from the API container. Check
  `docker compose ps db`'s health status and `docker compose logs db`.
- `device.stale: true` — no kiosk heartbeat in the last 5 minutes
  (`HEARTBEAT_STALE_AFTER` in `app/routers/health.py`). The kiosk container
  is down, can't reach the API, or is stuck — check `docker compose logs
  kiosk`.
- `device` is the literal string `{"status": "unknown", "detail": "no kiosk
  has reported in yet"}` — completely fresh deployment, no kiosk has ever
  successfully posted a heartbeat. Expected right after first boot; check
  `kiosk` logs if it persists past a minute or two.
- `status: degraded` overall — either of the above, surfaced as one
  top-level flag for a monitoring check to alert on. Still returns HTTP 200
  (deliberately — "degraded" is a valid, meaningful health state, not a
  transport-level error; a monitor should read the JSON body, not just the
  status code).

## Common failures

**Kiosk logs `face_engine_unavailable` / `liveness_unavailable`.** The
buffalo_l or MiniFASNet weights couldn't be downloaded into the shared
`models` volume (no network egress from the container, or a registry/CDN
outage). The kiosk keeps running — `detect()`/`embed()` return empty
results and liveness fails open (see `docs/DECISIONS.md`) — but recognition
effectively does nothing useful until weights land. Fix: confirm the
container can reach `github.com`/the insightface release CDN, or
pre-populate the `models` named volume out of band (download once, `docker
cp` the files into the volume) for an air-gapped site.

**Liveness (anti-spoofing).** Fixed 2026-09-26: the kiosk now downloads
two pinned MiniFASNet ONNX models (V2 + V1SE, SHA-256 verified) into
`{MODEL_CACHE_DIR}/minifasnet/` and averages them. For an offline site, copy
`MiniFASNetV2.onnx` and `MiniFASNetV1SE.onnx` there by hand. If they can't
load, the camera card on Analytics shows "Anti-spoofing OFF" and, with
`liveness_required` = true (default), faces are rejected rather than
accepted -- fix the model files, don't just turn the setting off.
Calibrate `liveness_threshold` per camera at install:
`python -m kiosk.liveness_check --label real`, then `--label spoof`
(phone photo held up), then `--recommend`.

**`GET /health` shows `device.stale: true` but the kiosk container is
clearly running.** Check `KIOSK_SERVICE_TOKEN` matches between `api` and
`kiosk` — a mismatched token makes every kiosk call (including the
heartbeat) fail auth silently from the kiosk's perspective (it just logs
and retries later; it doesn't crash). Check `docker compose logs kiosk` for
401s.

**`make smoke` fails with a 422 on enrollment.** Check the multipart field
name used by whatever client hit the endpoint — `POST /employees/{id}/
enroll` expects the field name `files`, not `images` (a real bug caught and
fixed in both `scripts/smoke.py` and `frontend/src/api/client.ts` during
this build — see `docs/DECISIONS.md`). If you're scripting against this API
yourself, use `files`.

**`make smoke` recognizes the wrong employee, or fails claiming a stale
employee already exists.** `scripts/smoke.py` uses a fixed bundled photo
(`insightface`'s own `t1.jpg`), so every run's embedding is bit-for-bit
identical. The script self-heals this at the start of every run by
deactivating any previously-leftover `Smoke Test *` employee (see
`docs/DECISIONS.md`) — if you see this anyway, check whether something
else (a manual test, a half-finished migration) left an active employee
named `Smoke Test *` outside the `QA` department, which the self-heal step
won't catch.

**Recognition accuracy is poor / too many false unknowns / too many wrong
matches.** This is a tuning problem, not a bug — see `docs/TUNING.md`,
specifically `similarity_threshold` and `unknown_cluster_threshold`. Also
check `GET /health`'s `device.profile`: CPU vs GPU tuning defaults (det
size, capture fps) differ, and an unexpected fallback to CPU (check
`device.fallback_from` and `device.status`) can silently change effective
accuracy/latency tradeoffs from what was tuned for.

**A specific employee can never be recognized after `DELETE /employees/
{id}/consent`.** This is correct, intended behavior, not a bug — see
`docs/DECISIONS.md` ("consent revocation must actually stop matching").
Re-granting consent and re-enrolling is required to make them matchable
again.

## Backup / restore

Everything that matters lives in two named Docker volumes plus one
database:

- `pgdata` — the entire relational database (employees, consents,
  attendance, encrypted embeddings, audit log, settings). Back up with
  standard Postgres tooling: `docker compose exec db pg_dump -U
  <POSTGRES_USER> <POSTGRES_DB> | gzip > backup.sql.gz`. Restore into a
  fresh `pgdata` volume with `psql` before starting `api`.
- `media` — saved face crops referenced by `crop_path` columns in the DB.
  Back these up together with `pgdata`, from the same point in time — a
  crop path in a restored DB pointing at a file that doesn't exist in a
  mismatched `media` backup is a broken (but non-fatal — `media.py`'s
  serving endpoint 404s cleanly) reference, not a corruption risk.
- `models` — not backup-worthy. It's a cache of publicly re-downloadable
  ONNX weights; losing it just means the next boot re-downloads (or fails
  open per the decisions above if there's no network at restore time —
  worth pre-seeding at a DR site if network access can't be guaranteed).
- `kiosk_queue` — the offline-events SQLite file. Losing it loses only
  events that haven't yet reached the API; by design, everything that
  successfully reached the API is durable in `pgdata` already. Not worth a
  dedicated backup strategy for most sites, but don't casually delete it
  while a kiosk might be mid-outage.

`EMBEDDING_ENCRYPTION_KEY` and `JWT_SECRET` must be backed up (a password
manager / secrets vault, not the repo) alongside the database — restoring
`pgdata` without the matching `EMBEDDING_ENCRYPTION_KEY` makes every
biometric record permanently undecryptable, with no recovery path.

## Production hardening checklist

The shipped `docker-compose.yml` is honestly a development/demo
configuration in a few specific ways; before a real deployment:

- [ ] Put a real reverse proxy (nginx, Caddy, a cloud load balancer) in
      front of `api` and `web` with TLS termination — the compose file
      serves plain HTTP on `8000`/`3000`/`5432` bound to all interfaces
      except `db` (already bound to `127.0.0.1` only).
- [ ] Change every `change_me`/`dev_only` default in `.env` — the compose
      file's inline defaults are meant to make a first `docker compose up`
      "just work," not to be production values.
- [ ] Put the Postgres data directory (and, per `docs/DECISIONS.md`, the
      plaintext-embedding pgvector column it contains) on an
      encrypted-at-rest volume — LUKS, or your cloud provider's disk
      encryption.
- [ ] Fix the MiniFASNet SHA-256 placeholder (above) if liveness matters for
      your threat model.
- [ ] Decide and implement the retention automation `docs/DPDP_COMPLIANCE.md`
      flags as not yet built (`crop_retention_days`,
      `unknown_auto_ignore_days` are read by nothing today).
- [ ] Restrict `CORS_ORIGINS` from the default `*` to your actual frontend
      origin.
- [ ] Point `DATABASE_URL`/`DATABASE_URL_SYNC` at a Postgres instance with
      its own backup/HA story if a single co-located container isn't
      sufficient for your uptime requirements.
- [ ] Review `JWT_EXPIRE_MINUTES` (default 480 = 8h) against your session
      policy.

## Upgrading to GPU

See the README's "Upgrading to GPU" section for the full procedure — it's
a two-line change (`ORT_FLAVOR=gpu` + uncommenting one `deploy.resources`
block per service in `docker-compose.yml`), by design: `kiosk/kiosk/
device.py` (and its byte-identical backend copy) is the only place that
ever chooses an ONNX Runtime execution provider, so there is no
CPU-specific code path anywhere else to find and change.

## Log format

Every service logs structured JSON (`structlog`, ISO timestamps, explicit
level field) — pipe to your log aggregator of choice; there's no
plain-text log format to parse. Key event names to alert on: `
device_probe_skipped` / `face_engine_unavailable` / `liveness_unavailable`
(degraded capability, not necessarily an outage), `kiosk_shutdown_
requested` (expected on a deploy/restart, unexpected otherwise),
`offline_queue_replayed` (informational — confirms the kiosk recovered
from an outage and is catching up).
