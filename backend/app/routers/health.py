from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.kiosk_heartbeats import KioskHeartbeat

router = APIRouter(tags=["health"])

HEARTBEAT_STALE_AFTER = timedelta(minutes=5)


async def _cloud_health() -> dict:
    """SaaS cloud: no tenant on this path -- report the control database
    and how many edge boxes are connected."""
    from app.edge_hub import hub
    from app.tenancy import control_sessions

    status = "ok"
    try:
        async with control_sessions()() as db:
            await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        status = "degraded"
    return {"status": status, "role": "cloud", "edges_online": len(hub.conns),
            "time": datetime.now(timezone.utc).isoformat()}


async def health(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"

    heartbeats = list((await db.execute(select(KioskHeartbeat))).scalars().all())
    now = datetime.now(timezone.utc)
    device_block: dict | None = None
    overall_status = "ok"

    if heartbeats:
        latest = max(heartbeats, key=lambda h: h.last_seen_at)
        stale = (now - latest.last_seen_at) > HEARTBEAT_STALE_AFTER
        device_block = dict(latest.device_json)
        device_block["kiosk_id"] = latest.kiosk_id
        device_block["last_seen_at"] = latest.last_seen_at.isoformat()
        device_block["stale"] = stale
        if stale or device_block.get("status") == "degraded":
            overall_status = "degraded"
    else:
        device_block = {"status": "unknown", "detail": "no kiosk has reported in yet"}

    if db_status != "ok":
        overall_status = "degraded"

    body = {
        "status": overall_status,
        "db": db_status,
        "model": "buffalo_l (kiosk-side; see device block)",
        "device": device_block,
        "time": now.isoformat(),
    }
    if overall_status != "ok":
        response.status_code = 200  # still 200 -- degraded is a valid, non-error health state
    return body


async def tls_ask(domain: str = "") -> Response:
    """Caddy on-demand TLS: may a certificate be issued for this host name?
    Only for <active tenant>.<BASE_DOMAIN> (stops strangers making us
    request certificates for random names)."""
    from app.tenancy import slug_from_host, tenant_by_slug

    s = get_settings()
    if domain.lower().rstrip(".") == s.base_domain.lower():
        return Response(status_code=200)
    slug = slug_from_host(domain, s.base_domain)
    t = await tenant_by_slug(slug) if slug else None
    return Response(status_code=200 if t is not None and t.status != "deleted" else 404)


from app.config import get_settings  # noqa: E402

if get_settings().role == "cloud":
    router.add_api_route("/health", _cloud_health, methods=["GET"])
    router.add_api_route("/health/tls-ask", tls_ask, methods=["GET"])
else:
    router.add_api_route("/health", health, methods=["GET"])
