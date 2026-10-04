"""End-to-end: SaaS cloud + one edge box as real processes.

  vendor creates tenant (scripts/tenants.py) -> cloud API + edge box start ->
  box connects (tunnel) -> admin logs in on the cloud -> a camera event at
  the box becomes attendance in the cloud -> photo shown through the tunnel
  -> unknown person mirrored -> policy search answered by the box -> delete
  erases the templates on the box -> suspend locks the dashboard.

Faces never reach the cloud: the test checks the cloud tenant database has
no face templates and the cloud media folder stays empty.
"""
from __future__ import annotations

import base64
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.licence import keygen

BACKEND = Path(__file__).resolve().parents[1]
JPEG = b"\xff\xd8\xff\xe0" + b"JFIF-test-photo" * 20


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait(fn, timeout=30.0, what="condition"):  # type: ignore[no-untyped-def]
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for {what} ({last})")


def _emb(seed: int) -> list[float]:
    v = np.random.default_rng(seed).standard_normal(512)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def saas(tmp_path):  # type: ignore[no-untyped-def]
    priv, pub = keygen()
    common = {
        "PYTHONPATH": str(BACKEND), "APP_ENV": "development", "JWT_SECRET": "j" * 48,
        "PATH": os.environ.get("PATH", ""),
    }
    cloud_env = {**common, "APP_ROLE": "cloud",
                 "CONTROL_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/control.db",
                 "TENANT_DATABASE_URL_TEMPLATE": f"sqlite+aiosqlite:///{tmp_path}/{{db}}.db",
                 "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/unused.db",
                 "DATABASE_URL_SYNC": f"sqlite:///{tmp_path}/unused.db",
                 "LICENCE_PRIVATE_KEY": priv, "KIOSK_SERVICE_TOKEN": "",
                 "EMBEDDING_ENCRYPTION_KEY": "Q2xvdWRLZXlDbG91ZEtleUNsb3VkS2V5Q2xvdWRLZXk=",
                 "MEDIA_ROOT": str(tmp_path / "cloud_media")}
    out = subprocess.run([sys.executable, "scripts/tenants.py", "create", "--slug", "acme", "--name", "Acme Ltd",
                          "--admin-email", "owner@acme.in", "--departments", "Ops", "--max-cameras", "2"],
                         cwd=BACKEND, env=cloud_env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr + out.stdout
    temp_pw = out.stdout.split("temporary password: ")[1].split()[0]
    site_token = out.stdout.split("EDGE_SITE_TOKEN=")[1].split()[0]

    cport, eport = _port(), _port()
    policy = tmp_path / "policy"
    policy.mkdir()
    (policy / "leave.md").write_text("# Leave\n\nEvery employee gets 12 casual leave days per year.")
    edge_env = {**common, "APP_ROLE": "edge",
                "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/edge.db",
                "DATABASE_URL_SYNC": f"sqlite:///{tmp_path}/edge.db",
                "MEDIA_ROOT": str(tmp_path / "edge_media"), "POLICY_DIR": str(policy),
                "CLOUD_URL": f"http://127.0.0.1:{cport}", "EDGE_SITE_TOKEN": site_token, "LICENCE_PUBLIC_KEY": pub,
                "EMBEDDING_ENCRYPTION_KEY": "RWRnZUtleUVkZ2VLZXlFZGdlS2V5RWRnZUtleTEyMzQ=",
                "KIOSK_SERVICE_TOKEN": "shared-edge-token-0123456789abcdef"}
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(cport), "--log-level", "warning"],
                         cwd=BACKEND, env=cloud_env),
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.edge.main:app", "--port", str(eport), "--log-level", "warning"],
                         cwd=BACKEND, env=edge_env),
    ]
    try:
        yield {"cloud": f"http://127.0.0.1:{cport}", "edge": f"http://127.0.0.1:{eport}", "pw": temp_pw,
               "tmp": tmp_path, "cloud_env": cloud_env}
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


def test_cloud_and_edge_box_end_to_end(saas):  # type: ignore[no-untyped-def]
    cloud, edge, tmp = saas["cloud"], saas["edge"], saas["tmp"]
    t = {"X-Tenant": "acme"}
    _wait(lambda: httpx.get(f"{cloud}/api/v1/health").json()["edges_online"] == 1, what="edge tunnel")
    st = httpx.get(f"{edge}/api/v1/edge/status").json()
    assert st["licence"] == "ok" and st["tenant"] == "Acme Ltd"

    # unknown tenant / no tenant
    assert httpx.get(f"{cloud}/api/v1/profile", headers={"X-Tenant": "nobody"}).status_code == 404

    # first login: temporary password must be changed
    r = httpx.post(f"{cloud}/api/v1/auth/login", headers=t, json={"email": "owner@acme.in", "password": saas["pw"]})
    assert r.status_code == 200 and r.json()["must_change_password"]
    h = {**t, "Authorization": f"Bearer {r.json()['access_token']}"}
    r = httpx.post(f"{cloud}/api/v1/auth/change-password", headers=h,
                   json={"current_password": saas["pw"], "new_password": "Blue-Train-4821"})
    h = {**t, "Authorization": f"Bearer {r.json()['access_token']}"}
    assert httpx.get(f"{cloud}/api/v1/profile", headers=t).json()["org_name"] == "Acme Ltd"

    # a person on the cloud; their face template enrolled on the box (direct
    # insert here: the real enrol path needs the InsightFace model)
    emp = httpx.post(f"{cloud}/api/v1/employees", headers=h,
                     json={"emp_code": "A1", "name": "Asha", "department": "Ops"}).json()
    from app.security import encrypt_embedding  # noqa: F401  (key differs per process; blob only stored)

    vec = _emb(1)
    con = sqlite3.connect(tmp / "edge.db")
    import json
    import uuid

    con.execute("INSERT INTO face_templates (id, owner_type, owner_id, embedding, embedding_encrypted, quality_score,"
                " model_version, source_image_path, created_at, is_primary) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), "EMPLOYEE", emp["id"], json.dumps(vec), b"x", 0.9, "test", None,
                 datetime.now(timezone.utc).isoformat(), 1))
    con.commit()
    con.close()
    tpl = httpx.get(f"{cloud}/api/v1/employees/{emp['id']}/templates", headers=h)
    assert tpl.status_code == 200 and len(tpl.json()) == 1  # answered by the box

    # camera event at the box -> attendance in the cloud, photo via tunnel
    kh = {"Authorization": "Bearer shared-edge-token-0123456789abcdef"}
    ev = {"client_event_id": "cam-1", "kiosk_id": "gate", "occurred_at": datetime.now(timezone.utc).isoformat(),
          "embedding": vec, "quality_score": 0.9, "liveness_score": 0.95,
          "crop_jpeg_base64": base64.b64encode(JPEG).decode()}
    r = httpx.post(f"{edge}/api/v1/kiosk/event", headers=kh, json=ev)
    assert r.status_code == 200 and r.json()["subject_type"] == "EMPLOYEE"
    events = _wait(lambda: httpx.get(f"{cloud}/api/v1/attendance/events", headers=h).json()["items"], what="event in cloud")
    e0 = events[0]
    assert e0["employee_id"] == emp["id"] and e0["crop_url"]
    img = httpx.get(f"{cloud}{e0['crop_url']}", headers=h)
    assert img.status_code == 200 and img.content == JPEG

    # a stranger -> unknown person on the box, mirrored (no face data) in the cloud
    ev2 = {**ev, "client_event_id": "cam-2", "embedding": _emb(2)}
    assert httpx.post(f"{edge}/api/v1/kiosk/event", headers=kh, json=ev2).json()["subject_type"] == "UNKNOWN"
    unk = _wait(lambda: httpx.get(f"{cloud}/api/v1/unknowns", headers=h).json()["items"], what="unknown in cloud")
    assert unk[0]["face_id"].startswith("UNK-") and unk[0]["best_crop_url"]
    assert httpx.get(f"{cloud}{unk[0]['best_crop_url']}", headers=h).content == JPEG

    # a retried kiosk event is not double counted
    httpx.post(f"{edge}/api/v1/kiosk/event", headers=kh, json=ev)
    time.sleep(1.5)
    assert len(httpx.get(f"{cloud}/api/v1/attendance/events", headers=h).json()["items"]) == 2

    # policy documents stay on the box; the cloud chatbot can still search them
    st = httpx.get(f"{cloud}/api/v1/chat/status", headers=h).json()
    assert st["policy"]["chunks"] >= 1
    ans = httpx.post(f"{cloud}/api/v1/chat", headers=h, json={"message": "casual leave kitni hai"}).json()
    assert "12 casual leave" in ans["text"]

    # nothing biometric in the cloud
    tdb = sqlite3.connect(tmp / "fa_acme.db")
    assert tdb.execute("SELECT COUNT(*) FROM face_templates").fetchone()[0] == 0
    tdb.close()
    assert not any((tmp / "cloud_media").rglob("*.jpg"))

    # delete on the cloud erases the face data on the box
    assert httpx.delete(f"{cloud}/api/v1/employees/{emp['id']}", headers=h).status_code == 204
    con = sqlite3.connect(tmp / "edge.db")
    assert con.execute("SELECT COUNT(*) FROM face_templates WHERE owner_type='EMPLOYEE'").fetchone()[0] == 0
    con.close()

    # vendor suspends the account -> dashboard locked
    out = subprocess.run([sys.executable, "scripts/tenants.py", "suspend", "--slug", "acme", "--reason", "unpaid"],
                         cwd=BACKEND, env=saas["cloud_env"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    _wait(lambda: httpx.get(f"{cloud}/api/v1/employees", headers=h).status_code == 402, timeout=40, what="suspension")
