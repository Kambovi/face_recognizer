# DPDP_COMPLIANCE.md

This system processes facial biometric data of employees, which India's
Digital Personal Data Protection Act, 2023 (DPDP Act) treats as personal
data requiring consent, purpose limitation, and security safeguards (it
does not carve out a separate "sensitive personal data" category the way
some other privacy regimes do, but a face embedding is squarely "personal
data" under its definition, and the Act's general obligations apply in
full). This document maps the Act's obligations, as they'd apply to a
single-site employee-attendance deployment, onto what this codebase
actually implements — and is explicit about what it does not automate,
because a compliance document that overstates what the software does is
worse than no document at all.

**This is not legal advice.** The deploying organization is the Data
Fiduciary under the Act and is responsible for its own compliance
determination; this document describes the technical controls this
software provides toward that, not a legal conclusion that deploying it
makes an organization compliant.

## Consent

- **Explicit, purpose-bound, recorded consent is required before
  enrollment.** `POST /employees/{id}/enroll` refuses (422
  `consent_required`) unless an active `Consent` row exists
  (`app/routers/employees.py`). A consent record captures
  `policy_version`, free-text `purpose_text`, `granted_at`, and the granting
  admin's `ip_address` (`app/models/consents.py`) — an audit-grade record of
  what the employee (or their authorized representative, for an
  admin-mediated enrollment) was told, not just a boolean flag.
- **Consent can be withdrawn, and withdrawal has a real effect.**
  `DELETE /employees/{id}/consent` marks the consent record revoked,
  deactivates the employee, and — this was a real gap found and fixed
  during this build, see `docs/DECISIONS.md` ("consent revocation must
  actually stop matching") — deletes the employee's face templates outright,
  so a revoked employee is no longer in the matchable pool for any
  subsequent kiosk recognition event, not just marked revoked in a table
  nobody reads at match time.
- **What this does not automate:** the Act expects consent requests to be
  in clear, plain language and (per the Rules) in any of the languages in
  the Eighth Schedule when requested. `purpose_text` is a free-text field —
  the deploying organization is responsible for the actual wording shown to
  employees, this system just stores and enforces its presence.

## Purpose limitation & data minimization

- **Only a derived embedding and a small JPEG crop are ever persisted**,
  never the raw enrollment photo or raw camera frame — `app/services/
  media.py`'s module docstring states this as NON-NEGOTIABLE #2, and
  `kiosk/kiosk/pipeline.py` only ever sends the winning best-shot crop
  (already downscaled to 224x224) over the wire, never a full frame.
- **The embedding itself is envelope-encrypted at rest** (`app/security.py`):
  a fresh random Data Encryption Key per record, wrapped by a long-lived
  master key from `EMBEDDING_ENCRYPTION_KEY`. A plaintext-float copy also
  exists in the same table, because pgvector's similarity search has to run
  in SQL over real floats — this is a deliberate, disclosed tradeoff (see
  `docs/DECISIONS.md`), and the plaintext column is documented as requiring
  an encrypted-at-rest volume in production (`docs/RUNBOOK.md`).
- **The API never returns raw embeddings to any client**, kiosk or
  frontend — enforced structurally (no response schema anywhere exposes an
  `embedding` field) and covered by NON-NEGOTIABLE #2's dedicated test.
- **Recognition results carry a similarity score, not "what it compared
  against."** No response, log line, or stored record exposes one
  employee's biometric data to another employee's recognition event.

## Security safeguards

- **Encryption at rest** for the biometric artifact (above), and TLS is
  expected to terminate at the deployment's reverse proxy /
  `docker-compose.yml`'s `web`/`api` boundary in production (not itself
  configured by this repo, which ships a dev-oriented plain-HTTP compose
  file — see `docs/RUNBOOK.md`'s production checklist).
- **Access control**: JWT-based admin/viewer roles for every human-facing
  endpoint (`app/deps.py`'s `require_admin`/`get_current_user`), bcrypt
  password hashing (`app/security.py`), and a separate, narrowly-scoped
  static bearer token for the kiosk's own service identity — a kiosk device
  can post attendance events but cannot read employee records, list
  consents, or call any admin endpoint.
- **Audit trail**: every consent grant/revoke, employee create/update/
  delete, and manual attendance correction writes an `AuditLog` row
  (`app/services/audit.py`) recording the actor, action, entity, and a
  before/after diff — the record a DPDP breach investigation or a Data
  Principal's grievance would need to reconstruct what happened to their
  data and who did it.
- **Reasonable security practices** (Rule requirement): dependency-pinned
  requirements files, no secrets committed to the repo (all read from
  environment variables with dev-only defaults clearly marked
  `change_me`/`dev_only` in `.env.example`), and the source-scan test
  (NON-NEGOTIABLE #8) that prevents a hardcoded, unreviewed ONNX provider
  path from silently reintroducing an unvetted dependency.

## Data Principal rights

- **Right to access / correction**: the Employees page lets an admin view
  and update an employee's own record; the Dashboard's Correction Modal
  lets an admin correct a misattributed or mistimed attendance event on the
  Data Principal's behalf (a face-recognition system's Data Principal — the
  employee — is not expected to self-serve corrections to a biometric
  matching decision the way they might a name or address field).
- **Right to erasure**: `DELETE /employees/{id}` hard-purges the employee's
  face templates, consent records, and deactivates the employee record
  (attendance history is retained for legitimate business/legal
  record-keeping — the Act permits retention beyond the stated purpose
  where another law requires it, e.g. labour/wage-record statutes; a
  deployment operating somewhere without such a requirement should decide
  its own retention policy for `attendance_events` rows tied to a deleted
  employee).
- **Right to withdraw consent**: covered above.
- **Grievance redressal**: the Act requires a mechanism for Data Principals
  to raise grievances; this is an organizational process, not a system
  feature — this software provides the audit trail and correction tools a
  grievance-handling process would need, not a grievance-intake UI itself.

## Retention — a disclosed, unautomated gap

`crop_retention_days` (default 90) and `unknown_auto_ignore_days` (default
30) exist as runtime settings (`app/services/settings_service.py`) and are
exposed on the Settings page, but **no scheduled job currently reads and
acts on them.** The spec's fixed tech stack is FastAPI + BackgroundTasks
only (explicitly, no Celery/cron worker), and BackgroundTasks only runs
attached to an HTTP request/response cycle — there is no natural "the
90-day mark just passed" trigger in that model without adding a scheduler
dependency the spec didn't call for. Rather than bolt on an unrequested
scheduling subsystem, this is disclosed here as the honest state of the
system: **an operator wanting DPDP-aligned storage-limitation in practice
today must run an external, periodic script or admin action** (a `cron`
entry calling a small script against the `crop_path`/`created_at` columns
directly, or a manually-triggered admin endpoint written for this purpose)
until a scheduler is added. This is flagged again in `docs/RUNBOOK.md`'s
operational checklist so it isn't missed at deployment time.

## Cross-border transfer / data localization

The spec is an explicitly single-site, on-premises-style deployment (one
Postgres instance, local Docker volumes for media — no managed cloud
storage or third-party API in the pipeline). Nothing in this codebase
transmits biometric data outside the deployment's own Docker network. If a
deployment adds cloud backups, log aggregation, or a managed database, the
organization is responsible for evaluating that transfer against the Act's
(currently permissive, blacklist-based) cross-border transfer rules —
outside this software's scope.

## Summary table

| Obligation | Status |
|---|---|
| Consent before processing | Implemented, enforced at enrollment |
| Consent withdrawal stops processing | Implemented (fixed this pass) |
| Purpose recorded per consent | Implemented (`purpose_text`, `policy_version`) |
| Data minimization (no raw photos retained) | Implemented |
| Encryption at rest for biometric data | Implemented (envelope encryption) |
| API never exposes raw embeddings | Implemented, tested |
| Access control (RBAC) | Implemented (admin/viewer JWT + kiosk token) |
| Audit trail | Implemented |
| Right to erasure | Implemented (`DELETE /employees/{id}`) |
| Right to access/correction | Implemented (Employees page, Correction Modal) |
| Automated storage-limitation / retention purge | **Not automated** — operator action required, see above |
| Grievance redressal process | Organizational, outside software scope |
| TLS in transit | Deployment responsibility, see `docs/RUNBOOK.md` |
