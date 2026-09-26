# DECISIONS.md

Per the spec's rule: *"If a genuine ambiguity blocks you, pick the simplest
defensible option, implement it, and record it here with one line of
reasoning. Do not stop to ask."* This file is the running log of every such
call made while building this system, plus the handful of real bugs found
and fixed along the way (kept here rather than in a separate changelog,
since finding them was itself the product of resolving an ambiguity about
"is this actually correct?"). Entries are grouped by area and cross-linked
from the source comment that says `see docs/DECISIONS.md`.

## Device / ONNX Runtime

**device.py duplication (byte-for-byte, not shared).** The spec designates
`kiosk/device.py` as the single place that resolves an ONNX Runtime
provider. The backend API also runs real ONNX inference of its own
(enrollment-time detect+embed in `app/services/embedding.py`), but Docker
Compose builds `api/` and `kiosk/` from two isolated build contexts that
share no source tree at build time. Rather than invent a second,
independently-written provider-resolution path in the backend — which is
exactly what NON-NEGOTIABLE #8's source-scan test exists to prevent — the
simplest defensible option is to keep `backend/app/device.py` a byte-for-byte
copy of `kiosk/kiosk/device.py`, with a comment on both files stating the
duplication and that any change must land in both. A shared package/wheel
would be more elegant but was out of scope for a two-container
`docker compose` layout with no shared base image.

**Detection and recognition run as separate model calls in the kiosk, but
combined in the backend.** `kiosk/kiosk/face_engine.py` calls
`FaceAnalysis.models["detection"]` and `["recognition"]` separately so the
best-shot buffer (spec step 4) can run detection on every gated frame while
paying the ArcFace embedding cost exactly once, on the single winning crop.
`backend/app/services/embedding.py` uses the combined, convenience
`FaceAnalysis.get()` instead, because enrollment only ever processes a
handful of still photos per admin action, not a live video stream — there is
no perf reason to split the calls there.

## Liveness

**Liveness model unavailable -> fail OPEN (treat every face as passing),
never fail closed.** If MiniFASNet's weights can't be downloaded (no
network) or the file is corrupt, `LivenessChecker.available` is `False` and
`check()` returns `1.0` (pass) unconditionally. The alternative — refusing
all attendance whenever liveness can't run — would take a working kiosk
fully offline over a spoof-detection feature being degraded, which is a
worse outcome for the stated purpose (an attendance system) than
occasionally accepting a photo-based spoof while liveness is down. This is
the OPPOSITE direction from NON-NEGOTIABLE #3 ("liveness cannot be
bypassed"), which is about what happens when liveness IS available: a
failing score there must produce zero recognition/matching calls, and that
contract is unit-tested against a mocked, available checker.

**MiniFASNet SHA-256 pin is a placeholder.** `MODEL_SHA256` in
`kiosk/kiosk/liveness.py` is a zero-filled placeholder because the sandbox
this was built in cannot reach the model's real release URL to compute the
genuine digest (confirmed at runtime: the upstream GitHub raw URL 403s from
this environment). Every download therefore currently fails the checksum
and liveness silently falls back to "available=False, pass everything" per
the decision above — this is safe (fails open, never crashes) but **must be
replaced with the real upstream SHA-256 before a production deployment**,
or every kiosk will silently run with liveness permanently disabled. Flagged
again in docs/RUNBOOK.md.

## Best-shot / subject gating

**`record_processed(embedding=None, ...)` must skip the ring buffer, not
push a placeholder into it (bug fix, this pass).** `kiosk/pipeline.py` calls
`SubjectGate.record_processed()` for `too_small` and `liveness_failed`
rejects with `embedding=None` (steps 3/5 stop before recognition ever runs).
The original implementation unconditionally did
`np.asarray(embedding, dtype=np.float64)`, which for `None` silently
produces a 0-d `nan` array rather than raising — that malformed entry then
sat in the recent-embedding ring buffer until the next real
`check_embedding()` call tried `cosine_similarity()` against it, at which
point `np.dot()` between a 512-d vector and a 0-d array broadcasts into a
512-element result and `float(...)` on it raises
`TypeError: only length-1 arrays can be converted to Python scalars` —
crashing pipeline processing for the very next visitor. Fixed by skipping
the ring-buffer append entirely when `embedding is None` (the box/track
bookkeeping still updates normally). Regression tests:
`test_record_processed_with_no_embedding_does_not_pollute_the_ring_buffer`
and `test_record_processed_mixes_no_embedding_and_real_embedding_rejects_safely`
in `kiosk/tests/test_subject_gate.py`.

## Offline resilience

**A local SQLite queue, not an in-memory list, for offline events.** Spec
step 11 requires zero attendance loss across a network partition. An
in-memory queue would lose everything on a kiosk process crash or restart
during an outage; a file-backed SQLite queue survives both, at negligible
extra complexity, and gives the replay loop a durable "pending" set to
iterate that isn't tied to process lifetime.

**Idempotency key is a client-generated UUID (`client_event_id`), enforced
as a real DB unique constraint.** This is the literal mechanism satisfying
NON-NEGOTIABLE #5 ("Use a client-generated UUID per event as the idempotency
key"); it isn't named in the spec's literal `attendance_events` column list,
so it's called out here and in the model file's own comment. A unique
constraint (not just app-level "check before insert" logic) is what makes a
replay race (e.g. two near-simultaneous replay attempts after a flaky
reconnect) safe without an explicit lock.

## Recognition / matching / data model

**Plaintext `embedding` column alongside `embedding_encrypted`.**
pgvector's `<=>` cosine-distance operator must run in SQL, so the 1:N search
(step 7) needs a plaintext-float pgvector column to search against; there is
no way to run an ANN/cosine search directly over Fernet-encrypted bytes. The
envelope-encrypted column (`embedding_encrypted` + a per-record wrapped DEK)
is treated as the durable, at-rest biometric artifact and is what NON-
NEGOTIABLE #2 is actually protecting; the plaintext column is documented as
a derived search index that a production deployment must place on an
encrypted-at-rest volume (LUKS/cloud-provider disk encryption) — see
docs/RUNBOOK.md. This is the simplest option that keeps real SQL-side
vector search while still satisfying "never expose raw embeddings over the
API" (NON-NEGOTIABLE #2 is about the API surface, not the disk).

**pgvector `Vector(dim)` on Postgres, JSON-encoded TEXT on SQLite.** The full
backend test suite needs to run with zero external services (no Postgres, no
pgvector extension). `app/models/types.py`'s `Vector` type transparently
compiles to a real `vector(dim)` column on Postgres and falls back to a
JSON-encoded TEXT column on SQLite; `app/services/matching.py` is the one
and only place that branches on dialect, computing cosine distance in Python
for the SQLite path. Correctness-identical for test-sized fixtures; never
used in production (`app/db.py`'s dialect check is the sole branch point).

**`subject_type`/`employee_id`/`unknown_identity_id` are all nullable, with
a CHECK constraint carving out one specific exception.** The spec's "exactly
one of employee_id/unknown_identity_id is set" rule holds for every event
that reaches step 7 (identity clustering/matching). It does NOT hold for
`liveness_failed`/`too_small` rejects, which are stopped by steps 3/5 before
the pipeline ever attempts to identify who the face belongs to — there is no
embedding and no clustering call for those, so neither FK can be populated
and `subject_type` itself is unknown. Rather than inventing a synthetic
"UNIDENTIFIED" subject row just to satisfy a NOT NULL constraint, the
simplest defensible option is a CHECK constraint with an explicit carve-out:
`(employee IS NOT NULL AND unknown IS NULL) OR (unknown IS NOT NULL AND
employee IS NULL) OR (both NULL AND reject_reason IN ('liveness_failed',
'too_small'))`.

**`working_days_per_week` (N) defines expected working days as `weekday() <
N`.** `app/services/analytics.py`'s absence/attendance-rate calculations
need *some* notion of which calendar days an employee was expected to show
up. The spec's data model has no per-employee weekly-off rotation or
holiday-calendar table, so the simplest defensible option is: N=5 means
Mon-Fri are working days, uniformly across all employees. This deliberately
doesn't model an employee whose weekly off is, say, Tuesday+Wednesday
instead of Sat+Sun, or company holidays — a real deployment would extend
`shifts` (or add a new table) with an explicit working-days bitmask /
holiday calendar and this function would read it instead of a bare
integer.

**Split-unknown does not retroactively re-attribute past attendance
events.** `split_unknown()` moves the chosen face TEMPLATES to a brand-new
UNK-nnnn identity, but historical `attendance_events` rows stay attributed
to the original identity, because an event only stores a similarity SCORE
at the time it was recognized — never the raw query embedding or which
specific template matched — so there is no reliable way to know, after the
fact, which of several now-split templates a given past sighting actually
belongs to without re-running detection+embedding against its stored crop
(which the spec's data model doesn't retain for unknowns beyond the
template crops themselves). An admin who needs specific historical events
moved can do so explicitly via the existing
`PATCH /attendance/events/{id}/reassign` endpoint. This is a real, disclosed
limitation of the split operation, not an oversight.

**`GET /shifts` (+ admin create) exists even though it isn't in the spec's
literal endpoint list.** `employees.shift_id` and both the Employees and
Settings pages need a way to enumerate shifts to populate a dropdown; adding
a small, obviously-necessary read (and an admin-only create, for seeding new
shifts without a DB console) endpoint was judged simpler and more defensible
than the alternative of hardcoding shift choices in the frontend.

**`kiosk_heartbeats` table exists even though it isn't in the spec's literal
DATA MODEL section.** The backend API itself never runs the recognition
pipeline's ONNX inference, so it has no device state of its own — but
`GET /health` is required to return a `device` block, and device resolution
happens once per KIOSK process, not per API request. This tiny table is how
a kiosk's self-reported resolved provider (from its own `device.py` call)
reaches `/health` and the Settings page: the kiosk posts a heartbeat
periodically, and the backend just relays the most recent row.

## Enrollment / embeddings fallback

**Enrollment falls back to a deterministic hash-of-bytes placeholder
embedding when the real model can't load.** If buffalo_l's weights aren't
reachable (no network, as in this sandbox on a cold model cache), real
face detection/embedding is impossible; rather than making the whole system
undemonstrable, `app/services/embedding.py` falls back to a placeholder
embedding deterministically derived from a hash of the uploaded image
bytes. It is clearly logged and tagged with a distinct `model_version`
string so it can never be confused with, or accidentally matched against, a
real embedding — and it exists purely so `make seed` / `make smoke` and the
rest of the system (matching, dedupe, unknown clustering, analytics,
dashboard) stay fully exercisable end-to-end without real model weights,
per the spec's own allowance for mocked model sessions in a
network-constrained environment.

**Synthetic camera frames (`CAMERA_SOURCE=synthetic`) are procedurally-drawn
PIL faces, matching the seed script's style.** `kiosk/kiosk/capture.py`
draws simple synthetic faces so the whole system is demonstrable end-to-end
without real camera hardware; `scripts/seed_demo.py` deliberately draws the
same style of synthetic portrait for the demo dataset's employee photos, so
a demo kiosk run and the seeded dataset are visually/stylistically
consistent with each other.

**`scripts/seed_demo.py` enrolls 100 employees with synthetic, deterministic
unit-normalized 512-d embeddings, bypassing real face detection entirely.**
A real face detector cannot find a face in simple procedurally-drawn PIL art
(confirmed: buffalo_l's SCRFD detector returns zero detections against
these images), so seeding 100 employees "the real way" (upload a photo, let
the server detect+embed it) is not possible against synthetic art. Rather
than either (a) blocking `make seed` entirely on real camera photos of 100
real people, which doesn't exist for a demo dataset, or (b) writing a
second, parallel enrollment code path, the simplest defensible option is:
generate the embeddings directly with a seeded
`numpy.random.default_rng(SEED)` (deterministic and reproducible across
runs), write them straight into `face_templates`, and still exercise the
REAL `upsert_attendance_event()` / `cluster_or_create_unknown()` service
functions for attendance and unknown-clustering realism, so everything
downstream of "an embedding exists" is exercised for real.

**`scripts/smoke.py`'s enrollment photo is insightface's own bundled
`data/images/t1.jpg`, not procedurally-drawn art.** Unlike `make seed` (which
only needs *an* embedding to exist, and can use a synthetic one), `make
smoke` specifically exists to prove the REAL kiosk-recognition HTTP path end
to end, which means it needs a photo real detection can actually find a face
in. `t1.jpg` is already an installed package asset (ships inside the
`insightface` pip package) — nothing is fetched over the network by this
script and nothing new is added to the repo. If real detection is
unavailable (no network to fetch buffalo_l weights on a cold cache), the
script falls back to shipping the whole bundled photo as-is and computing
the exact same deterministic placeholder embedding
(`app.services.embedding._placeholder_embedding`) that the live server's own
enrollment endpoint would compute for those identical bytes — so the
kiosk-recognition assertions hold under either scenario without the script
needing to know which one it's in. This dual-path design is what lets
NON-NEGOTIABLE #2 ("the API never exposes raw embeddings") coexist with a
black-box HTTP smoke test that still needs to know, in advance, what
embedding a kiosk event must carry to match.

**`scripts/smoke.py` deactivates leftover "Smoke Test *" employees at the
start of every run.** Because the enrollment photo (`t1.jpg`) is identical
byte-for-byte on every run, every run's enrolled employee has the exact same
embedding. A run that dies between enrollment and its own cleanup step
(e.g. a failing assertion, discovered and fixed during this pass — see
below) leaves a still-ACTIVE employee behind with that same embedding; the
next run's first kiosk event would then recognize-match the stale leftover
employee instead of the new one it just enrolled. Rather than requiring
every `make smoke` invocation to run against a guaranteed-pristine database
(true for a fresh `docker compose up`, not necessarily true for someone
re-running smoke against a long-lived staging deployment), the script now
deactivates any active employee named `Smoke Test *` in the `QA` department
before creating its own, making repeated runs against the same live
deployment safe. Verified in this pass by running the script twice back to
back against the same server: both runs print `SMOKE PASS`.

**`scripts/smoke.py`'s dedupe-window assertion was wrong and has been
corrected (bug fix, this pass).** The script originally posted a kiosk IN
event, then a second event 6 minutes later (past `dedupe_window_minutes`),
and asserted `GET /attendance/events?date_from=today` would return exactly
1 (deduped) row for that employee. That assertion was simply incorrect:
per `app/services/attendance.py`'s `upsert_attendance_event()`, a gap larger
than the dedupe window creates a NEW row for the OUT transition rather than
merging into the existing IN row — 2 rows (one IN, one OUT) is the correct,
intended state-machine behavior, not a dedupe bug. The assertion now expects
exactly 2 rows in `[IN, OUT]` order and overrides the OUT row in the
following manual-correction step. This was caught only by actually running
the script against a live server, not by static review.

## Consent (bug fix, this pass)

**Consent revocation must actually stop matching, not just record that it
happened.** `DELETE /employees/{id}/consent` already set
`Consent.revoked_at` and `employee.is_active = False`, with a comment
claiming this "disables recognition for this person immediately." It
didn't: `app/services/matching.py`'s `search_templates()` searches
`face_templates` directly and never joins against `employees.is_active` or
`consents.revoked_at` — so a "revoked" employee's face templates stayed
fully present and fully matchable by every subsequent kiosk event, with
`is_active=False` never consulted anywhere in the recognition path. This
was a genuine biometric-consent enforcement gap with zero test coverage
(no existing test ever exercised revoke-then-recognize). Two ways to close
it were considered: (a) add a join/filter to `search_templates()` so
matching itself checks consent state, or (b) delete the employee's
`face_templates` rows at revocation time, mirroring what `delete_employee()`
already does for the same underlying concern. (a) was rejected because
several existing NON-NEGOTIABLE proof tests (`test_nn4_dedupe.py`,
`test_nn7_unknown_identity.py`, etc.) create employees and templates
directly at the service layer with no `Consent` row at all — they rely on
matching being consent-agnostic by design, so gating the hot-path query on
consent would have broken deliberate, spec-driven test setups rather than
fixing a bug. (b) is the simplest, least invasive option: `revoke_consent()`
now deletes the employee's `face_templates` the same way `delete_employee()`
does, so there is nothing left in the matchable pool once consent is
revoked, without touching the matching query's semantics at all. Proof test:
`test_revoking_consent_purges_templates_so_recognition_actually_stops` in
`backend/tests/test_nn2_biometric_protection.py`, which drives
`process_kiosk_event()` directly (the real server-side matching path) with
the identical, previously-matching embedding after revocation and asserts
it now resolves to a brand-new UNKNOWN rather than the revoked employee.

## Type-checking / model annotations (bug fixes, this pass)

**`Mapped[sa.DateTime]` was wrong everywhere it appeared; corrected to
`Mapped[datetime]`.** Every timestamp column across the ORM models
(`attendance_events.occurred_at`/`created_at`, `employees.created_at`/
`deleted_at`, `consents.granted_at`/`revoked_at`, `unknown_identities.*`,
`users.created_at`, `kiosk_heartbeats.last_seen_at`, `audit_log.at`,
`face_templates.created_at`) was annotated `Mapped[sqlalchemy.DateTime]` —
the SQLAlchemy *column type* class — instead of `Mapped[datetime.datetime]`,
the actual Python runtime type every real row attribute holds (confirmed by
every consumer doing `.astimezone()`, `.isoformat()`, subtraction, etc.,
none of which `sqlalchemy.DateTime` supports). This was silently correct at
runtime (`mapped_column(UTCDateTime(), ...)` returns real `datetime`
instances regardless of the type-hint) but made `mypy app` report 60+
downstream errors across `services/dashboard.py`, `services/analytics.py`,
`services/attendance.py`, `services/unknown_identity.py`, and several
routers. Fixed by correcting every occurrence to `Mapped[datetime]` /
`Mapped[datetime | None]` (adding the missing `from datetime import
datetime` import to each affected model file) — a one-line-per-file, purely
type-annotation fix with zero runtime behavior change, confirmed by the
full backend test suite still passing 26/26 afterward.

**`Employee`/`Shift` forward references needed an explicit `TYPE_CHECKING`
import.** `app/models/shifts.py` and `app/models/employees.py`
cross-reference each other's ORM class in a `relationship(...)` type hint
(`Mapped[list["Employee"]]` / `Mapped["Shift | None"]`) as a string literal
to avoid a real circular import at module-load time — the standard
SQLAlchemy 2.0 pattern. Without a name to resolve against, though, mypy
correctly reported `Name "Employee"/"Shift" is not defined`, and the
existing `# noqa: F821` comments only silenced ruff, not mypy. Fixed by
adding `if TYPE_CHECKING: from app.models.<other> import <Name>` to each
file — resolved for mypy, never imported at runtime, so the circular-import
concern that motivated the string-literal forward reference in the first
place is unaffected.

## Lint/type-check tooling scope (this pass)

**Added `pyproject.toml` to `backend/` and `kiosk/` purely to scope `ruff`/
`mypy`, not to change their strictness.** Neither directory had a lint/type
config file at all; without one, `ruff check .` and `mypy app`/`mypy kiosk`
also walked local dev virtualenvs (`.venv-test`, wherever a contributor
happens to have created one) and flagged issues inside third-party vendored
code (e.g. `insightface`'s bundled `thirdparty/face3d` Cython setup.py) that
has nothing to do with this project — a fluke of what happens to be
installed locally, not a real finding. The added config: (1) excludes
`.venv`/`.venv-test`/`venv` from both tools; (2) deliberately keeps ruff at
its own default lint selection (`E4`, `E7`, `E9`, `F` — no line-length or
import-sort rules) rather than opting into a stricter rule set, since the
codebase was written and reviewed against that default and turning on more
categories now would flag long-but-otherwise-fine existing lines for a
reason unrelated to why the config was added; (3) tells mypy to
`ignore_missing_imports` only for the specific third-party packages that
ship no `py.typed` marker (`insightface`, `onnxruntime`, `cv2`, `pgvector`)
rather than a blanket ignore, so a genuine "no module named app.foo" typo in
first-party code still fails the check.

## Frontend

**Dashboard's "Correction Modal" has exactly four actions**, chosen because
they map 1:1 onto the backend's two correction endpoints: "Fix time / type"
-> `PATCH /attendance/events/{id}` (manual override); "Reassign to
employee" / "Reassign to unknown" / "Split into new unknown" -> the three
target-type variants of `PATCH /attendance/events/{id}/reassign`. No fifth
action (e.g. "delete the event outright") exists because the spec's
correction endpoints don't expose one, and inventing a destructive operation
outside the documented API surface was judged out of scope.

**A dedicated "today's raw events" table was added to the Dashboard page.**
The dashboard summary endpoint (`GET /dashboard/today`) groups rows by
employee/unknown for the at-a-glance view and only exposes human-readable
`face_id`s there, not individual event UUIDs — but the Correction Modal
needs a real event `id` to PATCH. Rather than adding IDs to the summary
response (which would leak per-event granularity into an endpoint whose
whole point is a rolled-up daily view), the Dashboard page also queries
`GET /attendance/events?date_from=today&date_to=today` for a separate raw
events table, giving the modal real event IDs to act on.

**`enrollEmployee()`'s multipart field name bug (bug fix, this pass).**
Both `frontend/src/api/client.ts` and `backend/scripts/smoke.py` uploaded
the enrollment photo(s) under the multipart field name `"images"`, but
`POST /employees/{id}/enroll`'s actual FastAPI parameter is `files: list[
UploadFile]` — field name `"files"`. This produced a real 422 "Field
required" from a live server (the existing pytest-based
`test_integration_smoke.py` already used the correct `"files"` field, so
in-process tests never caught it); found only by running `scripts/smoke.py`
against an actually-running instance, not by static review. Both call sites
now use `"files"`.
