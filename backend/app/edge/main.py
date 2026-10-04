"""Edge box API (APP_ROLE=edge). Serves the cameras on the local network
exactly like a standalone install does (same /api/v1/kiosk/* endpoints, so
the kiosk program is unchanged) -- but matches faces against its OWN
templates and sends only the results to the cloud.

    uvicorn app.edge.main:app --host 0.0.0.0 --port 8000

Local status: GET /api/v1/edge/status (no secrets, for the installer).
"""
from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, insecure_settings, validate_for_production
from app.db import get_db
from app.deps import bearer_scheme, hash_device_token, http_error
from app.edge import sync
from app.edge.state import state
from app.models.edge import EdgeDetection, EdgeOutbox
from app.routers.kiosk import _check_event_time, _enforce_liveness
from app.schemas.kiosk import (
    KioskConfigResponse,
    KioskEventRequest,
    KioskEventResponse,
    KioskHeartbeatRequest,
    KioskHeartbeatResponse,
)
from app.services.media import BadImage
from app.services.recognition import match_locally

logger = structlog.get_logger(__name__)
settings = get_settings()
validate_for_production(settings)
API = "/api/v1"
_lock = asyncio.Lock()
_wake = asyncio.Event()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "migrations"))
    command.upgrade(cfg, "head")


async def _retention_loop() -> None:  # pragma: no cover - timing loop
    from app.db import AsyncSessionLocal
    from app.services.retention import purge_old_crops

    while True:
        try:
            days = int(state.settings.get("crop_retention_days") or 0)
            if days > 0:
                async with AsyncSessionLocal() as db:
                    await purge_old_crops(db, days=days)
                await sync.prune_detections(days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge_retention_failed", error=str(exc)[:200])
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pragma: no cover - startup wiring
    weak = insecure_settings(settings)
    if weak:
        logger.warning("EDGE_SETUP_INCOMPLETE", missing=weak)
    if ":memory:" not in settings.database_url:
        await asyncio.to_thread(_migrate)
    state.load()
    tasks = []
    if settings.cloud_url and settings.edge_site_token:
        tasks = [asyncio.create_task(sync.tunnel_loop()), asyncio.create_task(sync.outbox_loop(_wake)),
                 asyncio.create_task(sync.config_loop()), asyncio.create_task(_retention_loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Face Attendance Edge", version=sync.VERSION, lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.exception_handler(HTTPException)
async def _http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    body = detail if isinstance(detail, dict) and "code" in detail else {"detail": str(detail), "code": "http_error"}
    return JSONResponse(status_code=exc.status_code, content=body)


class CameraAuth:
    def __init__(self, kiosk_id: str | None) -> None:
        self.kiosk_id = kiosk_id

    def check(self, claimed: str) -> None:
        if self.kiosk_id is not None and claimed != self.kiosk_id:
            raise http_error(403, "kiosk_id_mismatch", "This camera token belongs to a different camera")


async def camera_auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> CameraAuth:
    """Per-camera tokens are created on the cloud (Admin -> Cameras); the box
    gets their hashes in its config. A shared KIOSK_SERVICE_TOKEN in the
    box's .env also works (single-camera sites, first setup)."""
    if credentials is None or not credentials.credentials:
        raise http_error(401, "invalid_kiosk_token", "Missing camera token")
    tok = credentials.credentials
    dev = state.devices.get(hash_device_token(tok))
    if dev is not None:
        if not dev.get("enabled", True):
            raise http_error(401, "kiosk_disabled", "This camera has been disabled")
        return CameraAuth(str(dev["kiosk_id"]))
    shared = settings.kiosk_service_token
    if shared and hmac.compare_digest(tok.encode(), shared.encode()):
        return CameraAuth(None)
    raise http_error(401, "invalid_kiosk_token", "Invalid camera token")


def _require_licence() -> None:
    lic = state.licence_state()
    if not lic.valid:
        # 503: the kiosk keeps the event in its offline queue and retries
        raise http_error(503, "licence_" + lic.reason,
                         "Subscription not active on this box (licence " + lic.reason + "). Check the internet connection "
                         "or contact your service provider.")


@app.post(f"{API}/kiosk/event", response_model=KioskEventResponse)
async def kiosk_event(payload: KioskEventRequest, db: AsyncSession = Depends(get_db),
                      auth: CameraAuth = Depends(camera_auth)) -> KioskEventResponse:
    auth.check(payload.kiosk_id)
    _require_licence()
    cfg = state.settings
    _check_event_time(payload, cfg)
    _enforce_liveness(payload, cfg)
    is_pg = db.bind is not None and db.bind.dialect.name == "postgresql"
    try:
        async with (nullcontext() if is_pg else _lock):
            existing = await db.get(EdgeDetection, payload.client_event_id)
            if existing is not None:  # a kiosk retry of something already handled
                return KioskEventResponse(event_id=payload.client_event_id, subject_type=None, face_id=None,
                                          event_type=None, similarity=None, created=False)
            result, crop_path = await match_locally(db, payload, cfg, edge=True)
            db.add(EdgeDetection(client_event_id=payload.client_event_id, kiosk_id=payload.kiosk_id,
                                 occurred_at=result.occurred_at, crop_path=crop_path))
            db.add(EdgeOutbox(client_event_id=payload.client_event_id, payload=result.to_json()))
            await db.commit()
    except BadImage as exc:
        raise http_error(422, "bad_crop", str(exc)) from exc
    _wake.set()
    subject = {"employee": "EMPLOYEE", "unknown": "UNKNOWN"}.get(result.outcome)
    face_id = (state.people.get(result.employee_id or "", {}) or {}).get("face_id") if result.employee_id else None
    return KioskEventResponse(event_id=payload.client_event_id, subject_type=subject, face_id=face_id,
                              event_type=None, similarity=result.similarity, created=True)


@app.post(f"{API}/kiosk/heartbeat", response_model=KioskHeartbeatResponse)
async def kiosk_heartbeat(payload: KioskHeartbeatRequest, auth: CameraAuth = Depends(camera_auth)) -> KioskHeartbeatResponse:
    auth.check(payload.kiosk_id)
    sync.queue_heartbeat(payload.kiosk_id, payload.device)
    return KioskHeartbeatResponse(ok=True)


@app.get(f"{API}/kiosk/config", response_model=KioskConfigResponse)
async def kiosk_config(_auth: CameraAuth = Depends(camera_auth)) -> KioskConfigResponse:
    return KioskConfigResponse(settings=state.settings)


@app.get(f"{API}/health")
async def health() -> dict[str, Any]:
    lic = state.licence_state()
    return {"status": "ok" if lic.valid else "degraded", "role": "edge", "cloud_connected": state.cloud_connected,
            "licence": lic.reason, "time": datetime.now(timezone.utc).isoformat()}


@app.get(f"{API}/edge/status")
async def status() -> dict[str, Any]:
    """For the installer at the site: is the box set up and talking to the cloud?"""
    lic = state.licence_state()
    return {
        "tenant": state.tenant.get("name"),
        "cloud_url": settings.cloud_url,
        "cloud_connected": state.cloud_connected,
        "config_age_seconds": int(datetime.now(timezone.utc).timestamp() - state.config_at) if state.config_at else None,
        "licence": lic.reason,
        "licence_hours_left": round(lic.seconds_left / 3600, 1),
        "cameras_registered": len(state.devices),
        "people": len(state.people),
        "outbox_waiting": await sync.outbox_size(),
        "last_push_error": state.last_push_error,
    }
