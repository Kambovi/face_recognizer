from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.kiosk_heartbeats import KioskHeartbeat

router = APIRouter(tags=["health"])

HEARTBEAT_STALE_AFTER = timedelta(minutes=5)


@router.get("/health")
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
