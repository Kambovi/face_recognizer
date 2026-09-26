#!/usr/bin/env python
"""`make smoke` -- a real, black-box end-to-end test against a LIVE
`docker compose up` deployment, run via
`docker compose exec -T api python scripts/smoke.py`.

Exercises the actual HTTP surface exactly as a real admin + a real kiosk
would: health, login, employee creation + consent + enrollment, a kiosk
recognition event producing an IN then an OUT, the dashboard reflecting it,
a manual correction, and the unknown-visitor path. Prints exactly "SMOKE
PASS" and exits 0 on success; prints "SMOKE FAIL: <reason>" and exits 1 on
the first failed assertion.

Enrollment image (see docs/DECISIONS.md, "smoke test enrollment image"):
uses insightface's own bundled `data/images/t1.jpg` sample photo (a real,
already-installed package asset -- nothing is fetched over the network by
this script, and nothing new is added to this repo) rather than a
procedurally drawn portrait, because a real face detector cannot find a
face in simple synthetic line art. If the real buffalo_l model can't be
loaded (no network to fetch weights on first run), this script computes the
exact same deterministic placeholder embedding
(app.services.embedding._placeholder_embedding) that the live server's own
enrollment endpoint falls back to for the identical image bytes -- so the
kiosk-recognition assertions below hold under either scenario without the
script needing to know which one it's in.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_BASE = os.environ.get("SMOKE_API_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ.get("SMOKE_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "ChangeMe123!")
KIOSK_TOKEN = os.environ.get("KIOSK_SERVICE_TOKEN", "dev_only_kiosk_service_token")
KIOSK_ID = "smoke-kiosk"

_step_n = 0


def die(reason: str) -> None:
    print(f"SMOKE FAIL: {reason}")
    sys.exit(1)


def step(label: str) -> None:
    global _step_n
    _step_n += 1
    print(f"[{_step_n:02d}] {label}")


def wait_for_health(client: httpx.Client, timeout_s: float = 90.0) -> None:
    step("waiting for GET /health")
    deadline = time.monotonic() + timeout_s
    last_error: str = "never reached"
    while time.monotonic() < deadline:
        try:
            resp = client.get("/api/v1/health", timeout=5.0)
            if resp.status_code == 200 and resp.json().get("status") in ("ok", "degraded"):
                print(f"     -> {resp.json()['status']}")
                return
            last_error = f"status={resp.status_code} body={resp.text[:200]}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(2.0)
    die(f"API never became healthy within {timeout_s}s (last: {last_error})")


def _placeholder_compatible_embedding(image_bytes: bytes) -> list[float]:
    from app.services.embedding import _placeholder_embedding

    return _placeholder_embedding(image_bytes)


def prepare_enrollment_photo() -> tuple[bytes, list[float]]:
    """Returns (jpeg_bytes_to_upload, the_embedding_the_live_server_will_
    compute_for_it). See module docstring for why this can be computed
    ahead of time rather than read back from the API (which never exposes
    raw embeddings, by design -- NON-NEGOTIABLE #2)."""
    step("preparing a real, single-face enrollment photo")
    import insightface

    img_path = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
    img = cv2.imread(str(img_path))
    if img is None:
        die(f"could not read bundled sample image at {img_path}")

    try:
        from app.config import get_settings
        from app.device import resolve_providers
        from insightface.app import FaceAnalysis

        settings = get_settings()
        providers, info = resolve_providers(settings.device_preference)
        app = FaceAnalysis(name=settings.insightface_model_name, root=settings.model_cache_dir, providers=providers)
        app.prepare(ctx_id=-1 if providers[0] == "CPUExecutionProvider" else 0, det_size=tuple(info["tuning"]["det_size"]))
        faces = app.get(img)
        if faces:
            face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            pad_x, pad_y = int((x2 - x1) * 0.4), int((y2 - y1) * 0.4)
            h, w = img.shape[:2]
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(w, x2 + pad_x), min(h, y2 + pad_y)
            crop = img[y1:y2, x1:x2]
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if ok:
                jpeg_bytes = buf.tobytes()
                print("     -> real detection succeeded; using a real single-face crop + its real embedding")
                return jpeg_bytes, np.asarray(face.normed_embedding, dtype=np.float64).tolist()
    except Exception as exc:  # noqa: BLE001 -- fall through to the placeholder-safe path below
        print(f"     -> real detection unavailable ({type(exc).__name__}); falling back to placeholder-compatible mode")

    # Real detection unavailable (e.g. no network to fetch buffalo_l on
    # first run) -- ship the whole bundled photo as-is. The live server, in
    # the same situation, computes a deterministic hash-of-bytes embedding
    # for it (see app/services/embedding.py); reproduce that exact
    # computation here so the kiosk-event assertions below still hold.
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        die("failed to re-encode the bundled sample image")
    jpeg_bytes = buf.tobytes()
    return jpeg_bytes, _placeholder_compatible_embedding(jpeg_bytes)


def main() -> None:
    client = httpx.Client(base_url=API_BASE, timeout=30.0)

    wait_for_health(client)

    step("logging in as the default admin")
    login_resp = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if login_resp.status_code != 200:
        die(f"admin login failed: {login_resp.status_code} {login_resp.text[:300]}")
    token = login_resp.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {token}"}
    kiosk_headers = {"Authorization": f"Bearer {KIOSK_TOKEN}"}

    # A previous run of this script that died between enrollment and cleanup
    # (e.g. a failed assertion) can leave a still-active "Smoke Test *"
    # employee behind, enrolled against the same bundled photo this run also
    # uses. Since the same photo always yields the same embedding, that
    # leftover would recognize-match ahead of the employee this run is about
    # to create. Deactivate any such leftovers first so each run starts clean
    # regardless of whether the previous one finished.
    step("deactivating any leftover smoke-test employees from a previous failed run")
    stale_resp = client.get("/api/v1/employees", params={"department": "QA", "page_size": 500}, headers=admin_headers)
    if stale_resp.status_code == 200:
        stale = [e for e in stale_resp.json()["items"] if e["name"].startswith("Smoke Test") and e["is_active"]]
        for e in stale:
            client.delete(f"/api/v1/employees/{e['id']}", headers=admin_headers)
        print(f"     -> deactivated {len(stale)} leftover employee(s)")
    # (Leftover UNKNOWN identities from a previous aborted run use random
    # embeddings and never collide with this run's own random embedding, so
    # they're left alone here -- they don't affect correctness.)

    step("GET /shifts")
    shifts_resp = client.get("/api/v1/shifts", headers=admin_headers)
    if shifts_resp.status_code != 200:
        die(f"listing shifts failed: {shifts_resp.status_code} {shifts_resp.text[:300]}")
    shifts = shifts_resp.json()
    shift_id = shifts[0]["id"] if shifts else None

    unique_suffix = uuid.uuid4().hex[:8]
    step(f"creating a temporary employee (SMOKE-{unique_suffix})")
    create_resp = client.post(
        "/api/v1/employees",
        json={"name": f"Smoke Test {unique_suffix}", "emp_code": f"SMOKE-{unique_suffix}", "department": "QA", "shift_id": shift_id},
        headers=admin_headers,
    )
    if create_resp.status_code != 201:
        die(f"employee creation failed: {create_resp.status_code} {create_resp.text[:300]}")
    employee = create_resp.json()
    employee_id, face_id = employee["id"], employee["face_id"]
    print(f"     -> {face_id} ({employee_id})")

    step("granting consent")
    consent_resp = client.post(
        f"/api/v1/employees/{employee_id}/consent",
        json={"policy_version": "v1", "purpose_text": "Smoke test enrollment"},
        headers=admin_headers,
    )
    if consent_resp.status_code != 201:
        die(f"consent grant failed: {consent_resp.status_code} {consent_resp.text[:300]}")

    jpeg_bytes, expected_embedding = prepare_enrollment_photo()

    step("enrolling the photo via POST /employees/{id}/enroll")
    enroll_resp = client.post(
        f"/api/v1/employees/{employee_id}/enroll",
        files=[("files", ("smoke.jpg", jpeg_bytes, "image/jpeg"))],
        headers=admin_headers,
    )
    if enroll_resp.status_code != 200:
        die(f"enrollment failed: {enroll_resp.status_code} {enroll_resp.text[:300]}")
    enroll_body = enroll_resp.json()
    if enroll_body["accepted_count"] < 1:
        die(f"enrollment accepted 0 images: {enroll_body}")
    print(f"     -> accepted {enroll_body['accepted_count']} image(s), {enroll_body['template_count']} template(s) total")

    step("posting a kiosk recognition event (expect IN)")
    occurred_at_in = datetime.now(timezone.utc)
    in_resp = client.post(
        "/api/v1/kiosk/event",
        json={
            "client_event_id": str(uuid.uuid4()),
            "kiosk_id": KIOSK_ID,
            "occurred_at": occurred_at_in.isoformat(),
            "embedding": expected_embedding,
            "quality_score": 0.9,
            "liveness_score": 0.95,
        },
        headers=kiosk_headers,
    )
    if in_resp.status_code != 200:
        die(f"kiosk IN event failed: {in_resp.status_code} {in_resp.text[:300]}")
    in_body = in_resp.json()
    if in_body.get("face_id") != face_id:
        die(f"kiosk event matched the wrong subject: expected {face_id}, got {in_body.get('face_id')} (similarity={in_body.get('similarity')})")
    if in_body.get("event_type") != "IN":
        die(f"expected the first event of the day to be IN, got {in_body.get('event_type')}")
    print(f"     -> recognized as {face_id}, event_type=IN, similarity={in_body.get('similarity'):.4f}")

    step("posting a second event 6 minutes later (past the dedupe window; expect OUT)")
    occurred_at_out = occurred_at_in + timedelta(minutes=6)
    out_resp = client.post(
        "/api/v1/kiosk/event",
        json={
            "client_event_id": str(uuid.uuid4()),
            "kiosk_id": KIOSK_ID,
            "occurred_at": occurred_at_out.isoformat(),
            "embedding": expected_embedding,
            "quality_score": 0.9,
            "liveness_score": 0.95,
        },
        headers=kiosk_headers,
    )
    if out_resp.status_code != 200:
        die(f"kiosk OUT event failed: {out_resp.status_code} {out_resp.text[:300]}")
    out_body = out_resp.json()
    if out_body.get("event_type") != "OUT":
        die(f"expected the second (post-dedupe-window) event to be OUT, got {out_body.get('event_type')}")
    print("     -> event_type=OUT")

    # Idempotent offline-queue replay against the real client_event_id unique
    # constraint is already covered exhaustively by
    # backend/tests/test_nn5_offline_replay.py; not repeated here.

    step("GET /attendance/events?date_from=today (expect one IN row and one OUT row for this run)")
    today = occurred_at_in.astimezone().date().isoformat()
    events_resp = client.get(
        "/api/v1/attendance/events", params={"date_from": today, "date_to": today, "page_size": 500}, headers=admin_headers
    )
    if events_resp.status_code != 200:
        die(f"listing events failed: {events_resp.status_code} {events_resp.text[:300]}")
    our_events = sorted(
        (e for e in events_resp.json()["items"] if e["employee_id"] == employee_id),
        key=lambda e: e["occurred_at"],
    )
    # The IN and OUT events posted above are more than dedupe_window_minutes
    # apart (6 minutes), so upsert_attendance_event() creates a NEW row for
    # the OUT transition rather than merging it into the IN row -- two rows
    # is the correct, intended state-machine behavior here, not a dedupe bug.
    if len(our_events) != 2:
        die(f"expected exactly 2 attendance rows (IN + OUT) for {face_id} today, found {len(our_events)}")
    if our_events[0]["event_type"] != "IN" or our_events[1]["event_type"] != "OUT":
        die(f"expected [IN, OUT] event_type ordering, got {[e['event_type'] for e in our_events]}")
    event_id = our_events[1]["id"]  # the OUT row; used by the manual-override step below
    print(f"     -> 2 rows (IN, OUT), overriding id={event_id}")

    step("GET /dashboard/today (expect this employee present with hours > 0)")
    dash_resp = client.get("/api/v1/dashboard/today", headers=admin_headers)
    if dash_resp.status_code != 200:
        die(f"dashboard fetch failed: {dash_resp.status_code} {dash_resp.text[:300]}")
    dash_body = dash_resp.json()
    known_row = next((r for r in dash_body["known"] if r["face_id"] == face_id), None)
    if known_row is None:
        die(f"{face_id} did not appear in today's dashboard 'known' section")
    if known_row["total_hours"] <= 0:
        die(f"expected positive total_hours for {face_id}, got {known_row['total_hours']}")
    print(f"     -> present, in={known_row['in_time']}, out={known_row['out_time']}, hours={known_row['total_hours']}")

    step("applying a manual correction (PATCH /attendance/events/{id})")
    override_resp = client.patch(
        f"/api/v1/attendance/events/{event_id}",
        json={"event_type": "OUT", "reason": "smoke test manual override"},
        headers=admin_headers,
    )
    if override_resp.status_code != 200:
        die(f"manual override failed: {override_resp.status_code} {override_resp.text[:300]}")
    if not override_resp.json()["is_manual_override"]:
        die("manual override did not set is_manual_override=true")
    print("     -> override applied")

    step("posting a kiosk event with a genuinely novel embedding (expect UNKNOWN)")
    rng = np.random.default_rng()
    novel_embedding = rng.normal(size=512)
    novel_embedding = (novel_embedding / np.linalg.norm(novel_embedding)).tolist()
    unknown_resp = client.post(
        "/api/v1/kiosk/event",
        json={
            "client_event_id": str(uuid.uuid4()),
            "kiosk_id": KIOSK_ID,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "embedding": novel_embedding,
            "quality_score": 0.8,
            "liveness_score": 0.9,
        },
        headers=kiosk_headers,
    )
    if unknown_resp.status_code != 200:
        die(f"kiosk unknown-path event failed: {unknown_resp.status_code} {unknown_resp.text[:300]}")
    unknown_body = unknown_resp.json()
    if unknown_body.get("subject_type") != "UNKNOWN":
        die(f"expected a novel embedding to create/match an UNKNOWN identity, got subject_type={unknown_body.get('subject_type')}")
    unknown_face_id = unknown_body["face_id"]
    print(f"     -> {unknown_face_id}")

    step("GET /unknowns (expect the new identity present)")
    unknowns_resp = client.get("/api/v1/unknowns", headers=admin_headers)
    if unknowns_resp.status_code != 200:
        die(f"listing unknowns failed: {unknowns_resp.status_code} {unknowns_resp.text[:300]}")
    if not any(u["face_id"] == unknown_face_id for u in unknowns_resp.json()["items"]):
        die(f"{unknown_face_id} not found in GET /unknowns")

    step("GET /analytics/summary and /settings sanity checks")
    analytics_resp = client.get("/api/v1/analytics/summary", params={"period": "daily"}, headers=admin_headers)
    if analytics_resp.status_code != 200:
        die(f"analytics summary failed: {analytics_resp.status_code} {analytics_resp.text[:300]}")
    settings_resp = client.get("/api/v1/settings", headers=admin_headers)
    if settings_resp.status_code != 200 or "similarity_threshold" not in settings_resp.json()["settings"]:
        die("settings endpoint did not return expected runtime settings")

    step("cleaning up (deactivating the smoke-test employee, deleting the smoke-test unknown)")
    delete_emp_resp = client.delete(f"/api/v1/employees/{employee_id}", headers=admin_headers)
    if delete_emp_resp.status_code != 204:
        die(f"cleanup: deactivating smoke employee failed: {delete_emp_resp.status_code}")
    unknown_id = next(u["id"] for u in unknowns_resp.json()["items"] if u["face_id"] == unknown_face_id)
    delete_unk_resp = client.delete(f"/api/v1/unknowns/{unknown_id}", headers=admin_headers)
    if delete_unk_resp.status_code != 204:
        die(f"cleanup: deleting smoke unknown failed: {delete_unk_resp.status_code}")

    client.close()
    print("SMOKE PASS")


if __name__ == "__main__":
    main()
