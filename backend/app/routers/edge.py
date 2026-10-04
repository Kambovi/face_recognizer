"""Cloud endpoints for edge boxes (APP_ROLE=cloud). Authenticated by the
site token (Authorization: Bearer <token>), never by a dashboard login.

  WS   /edge/ws        the tunnel (cloud -> box calls, see app/edge_hub.py)
  GET  /edge/config    settings + camera tokens (hashes) + people ids + licence
  POST /edge/results   recognition results + camera heartbeats (idempotent)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Header, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.deps import http_error
from app.edge_hub import EdgeConn, hub
from app.models.employees import Employee
from app.models.kiosk_devices import KioskDevice
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.services.recognition import MatchResult, record_result
from app.services.settings_service import get_all_settings
from app.tenancy import EdgeSite, Tenant, TenantInfo, control_sessions, current_tenant, hash_token, sessions_for, tenant_by_slug

router = APIRouter(prefix="/edge", tags=["edge"])
logger = structlog.get_logger(__name__)
MAX_BATCH = 500


async def _site_from_token(token: str | None, ip: str | None = None) -> tuple[EdgeSite, TenantInfo]:
    if not token:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "no_site_token", "Site token missing")
    async with control_sessions()() as db:
        site = (await db.execute(select(EdgeSite).where(EdgeSite.token_hash == hash_token(token)))).scalar_one_or_none()
        if site is None or not site.enabled:
            raise http_error(status.HTTP_401_UNAUTHORIZED, "bad_site_token", "Unknown or disabled site token")
        tenant_row = await db.get(Tenant, site.tenant_id)
        site.last_seen_at = datetime.now(timezone.utc)
        if ip:
            site.last_ip = ip[:64]
        await db.commit()
    tenant = await tenant_by_slug(tenant_row.slug) if tenant_row else None
    if tenant is None:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "bad_site_token", "Tenant not found")
    if not tenant.active:
        raise http_error(status.HTTP_402_PAYMENT_REQUIRED, "tenant_suspended", tenant.status_reason or "Account suspended")
    return site, tenant


def _bearer(value: str | None) -> str | None:
    if value and value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


async def build_config(tenant: TenantInfo, site: EdgeSite) -> dict[str, Any]:
    from app.licence import issue

    settings = get_settings()
    async with sessions_for(tenant)() as db:
        cfg = await get_all_settings(db)
        devices = [{"kiosk_id": d.kiosk_id, "token_hash": d.token_hash, "enabled": d.enabled}
                   for d in (await db.execute(select(KioskDevice))).scalars().all()]
        people = [{"id": e.id, "face_id": e.face_id, "active": e.is_active}
                  for e in (await db.execute(select(Employee).where(Employee.deleted_at.is_(None)))).scalars().all()]
    licence = issue(settings.licence_private_key, tenant=tenant.slug, site=site.id, max_cameras=tenant.max_cameras,
                    max_people=tenant.max_people) if settings.licence_private_key else None
    return {"tenant": {"slug": tenant.slug, "name": tenant.name}, "settings": cfg, "devices": devices,
            "people": people, "licence": licence, "at": datetime.now(timezone.utc).isoformat()}


@router.get("/config")
async def edge_config(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    site, tenant = await _site_from_token(_bearer(authorization), request.client.host if request.client else None)
    return await build_config(tenant, site)


class ResultsIn(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_BATCH)
    heartbeats: list[dict[str, Any]] = Field(default_factory=list, max_length=50)


@router.post("/results")
async def edge_results(payload: ResultsIn, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    site, tenant = await _site_from_token(_bearer(authorization), request.client.host if request.client else None)
    accepted: list[str] = []
    failed: dict[str, str] = {}
    token = current_tenant.set(tenant)
    try:
        async with sessions_for(tenant)() as db:
            cfg = await get_all_settings(db)
            for raw in payload.results:
                cid = str(raw.get("client_event_id", ""))[:64]
                try:
                    r = MatchResult.from_json(raw)
                    if r.crop_ref and not r.crop_ref.startswith("det:"):
                        r.crop_ref = None  # only references, never local paths
                    if r.unknown_crop_ref and not r.unknown_crop_ref.startswith("unk:"):
                        r.unknown_crop_ref = None
                    await record_result(db, r, cfg, mirror_unknowns=True)
                    accepted.append(cid)
                except Exception as exc:  # noqa: BLE001 - one bad item must not block the batch
                    await db.rollback()
                    failed[cid] = str(exc)[:200]
                    logger.warning("edge_result_failed", tenant=tenant.slug, client_event_id=cid, error=str(exc)[:200])
            # "last seen" on Admin -> Cameras: the box talks to the cameras, not the cloud
            seen = {str(x.get("kiosk_id", ""))[:64] for x in payload.results} | {
                str(x.get("kiosk_id", ""))[:64] for x in payload.heartbeats}
            if seen:
                now = datetime.now(timezone.utc)
                for dev in (await db.execute(select(KioskDevice).where(KioskDevice.kiosk_id.in_(seen)))).scalars().all():
                    dev.last_used_at = now
            for hb in payload.heartbeats:
                kid = str(hb.get("kiosk_id", ""))[:64]
                if not kid:
                    continue
                row = (await db.execute(select(KioskHeartbeat).where(KioskHeartbeat.kiosk_id == kid))).scalar_one_or_none()
                raw_device = hb.get("device")
                device: dict[str, Any] = dict(raw_device) if isinstance(raw_device, dict) else {}
                if row is None:
                    db.add(KioskHeartbeat(kiosk_id=kid, device_json=device))
                else:
                    row.device_json = device
                    row.last_seen_at = datetime.now(timezone.utc)
            await db.commit()
    finally:
        current_tenant.reset(token)
    return {"accepted": accepted, "failed": failed}


@router.websocket("/ws")
async def edge_ws(ws: WebSocket) -> None:
    token = _bearer(ws.headers.get("authorization"))
    try:
        site, tenant = await _site_from_token(token, ws.client.host if ws.client else None)
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = EdgeConn(ws=ws, tenant=tenant.slug, site_id=site.id)
    await hub.register(conn)
    logger.info("edge_connected", tenant=tenant.slug, site=site.name)
    try:
        await conn.send({"type": "config", **(await build_config(tenant, site))})
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if msg.get("type") == "config_request":
                await conn.send({"type": "config", **(await build_config(tenant, site))})
            else:
                hub.on_message(conn, msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(conn)
        logger.info("edge_disconnected", tenant=tenant.slug)


async def push_config(tenant: TenantInfo) -> None:
    """Send fresh settings / camera tokens / people to the tenant's box now
    (after an admin changes something it needs)."""
    conn = hub.conns.get(tenant.slug)
    if conn is None:
        return
    async with control_sessions()() as db:
        site = await db.get(EdgeSite, conn.site_id)
    if site is not None:
        try:
            await conn.send({"type": "config", **(await build_config(tenant, site))})
        except Exception as exc:  # noqa: BLE001
            logger.warning("edge_config_push_failed", tenant=tenant.slug, error=str(exc)[:200])
