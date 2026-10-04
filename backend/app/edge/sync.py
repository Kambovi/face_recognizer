"""The edge box's three background jobs:

  tunnel_loop   keep the WebSocket to the cloud open; answer its calls;
                receive config pushes. Reconnects with back-off.
  outbox_loop   send queued recognition results + camera heartbeats to the
                cloud (POST /edge/results), oldest first; keep them until
                the cloud has them. Works through internet outages.
  config_loop   pull settings / camera tokens / people / licence every few
                minutes (backup for a broken tunnel).
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

import httpx
import structlog
from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.edge import rpc
from app.edge.state import state
from app.models.edge import EdgeOutbox

logger = structlog.get_logger(__name__)
VERSION = "edge-3.0"
BATCH = 200
_heartbeats: dict[str, dict[str, Any]] = {}


def queue_heartbeat(kiosk_id: str, device: dict[str, Any]) -> None:
    _heartbeats[kiosk_id] = {"kiosk_id": kiosk_id, "device": device}


def _base() -> str:
    return get_settings().cloud_url.rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().edge_site_token}"}


async def pull_config(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"{_base()}/api/v1/edge/config", headers=_headers(), timeout=20)
        if r.status_code == 200:
            state.apply(r.json())
            return True
        logger.warning("edge_config_refused", status=r.status_code, body=r.text[:200])
    except httpx.HTTPError as exc:
        logger.warning("edge_config_failed", error=type(exc).__name__)
    return False


async def push_outbox_once(client: httpx.AsyncClient) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(EdgeOutbox).order_by(EdgeOutbox.id).limit(BATCH))).scalars().all()
        hbs = list(_heartbeats.values())
        if not rows and not hbs:
            return 0
        try:
            r = await client.post(f"{_base()}/api/v1/edge/results", headers=_headers(), timeout=30,
                                  json={"results": [x.payload for x in rows], "heartbeats": hbs})
        except httpx.HTTPError as exc:
            state.last_push_error = type(exc).__name__
            return 0
        if r.status_code != 200:
            state.last_push_error = f"HTTP {r.status_code}: {r.text[:120]}"
            for x in rows:
                x.attempts += 1
                x.last_error = state.last_push_error[:300]
            await db.commit()
            return 0
        body = r.json()
        done = set(body.get("accepted") or [])
        failed = body.get("failed") or {}
        for x in rows:
            if x.client_event_id in done:
                await db.delete(x)
            else:
                x.attempts += 1
                x.last_error = str(failed.get(x.client_event_id, "not accepted"))[:300]
                if x.attempts >= 50:  # a result the cloud keeps refusing: drop, don't block the queue
                    logger.error("edge_result_dropped", client_event_id=x.client_event_id, error=x.last_error)
                    await db.delete(x)
        await db.commit()
        for h in hbs:
            _heartbeats.pop(h["kiosk_id"], None)
        state.last_push_at = time.time()
        state.last_push_error = None
        return len(done)


async def outbox_size() -> int:
    async with AsyncSessionLocal() as db:
        return int((await db.execute(select(func.count()).select_from(EdgeOutbox))).scalar_one())


async def outbox_loop(wake: asyncio.Event) -> None:  # pragma: no cover - timing loop
    async with httpx.AsyncClient() as client:
        while True:
            try:
                sent = await push_outbox_once(client)
            except Exception as exc:  # noqa: BLE001 - never die
                logger.warning("edge_outbox_failed", error=str(exc)[:200])
                sent = 0
            if sent >= BATCH:
                continue
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass


async def config_loop() -> None:  # pragma: no cover - timing loop
    async with httpx.AsyncClient() as client:
        while True:
            await pull_config(client)
            await asyncio.sleep(300 if state.cloud_connected else 60)


async def _serve(ws: Any) -> None:
    await ws.send(json.dumps({"type": "hello", "version": VERSION}))
    async for text in ws:
        try:
            msg = json.loads(text)
        except ValueError:
            continue
        if msg.get("type") == "config":
            state.apply(msg)
        elif msg.get("type") == "rpc":
            asyncio.create_task(_answer(ws, msg))


async def _answer(ws: Any, msg: dict[str, Any]) -> None:
    rid = msg.get("id")
    try:
        result = await rpc.handle(str(msg.get("method")), msg.get("params") or {})
        reply = {"type": "rpc_result", "id": rid, "ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - report to the cloud, keep serving
        logger.warning("edge_rpc_failed", method=msg.get("method"), error=str(exc)[:200])
        reply = {"type": "rpc_result", "id": rid, "ok": False, "error": str(exc)[:300]}
    try:
        await ws.send(json.dumps(reply, default=str))
    except Exception:  # noqa: BLE001 - connection gone; the cloud times out
        pass


async def tunnel_loop() -> None:  # pragma: no cover - network loop
    from websockets.asyncio.client import connect

    url = _base().replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/edge/ws"
    delay = 2.0
    while True:
        try:
            async with connect(url, additional_headers=_headers(), max_size=64 * 1024 * 1024,
                               ping_interval=20, ping_timeout=20, open_timeout=20) as ws:
                state.cloud_connected = True
                delay = 2.0
                logger.info("edge_tunnel_connected", url=url)
                await _serve(ws)
        except Exception as exc:  # noqa: BLE001 - offline / refused: retry
            logger.warning("edge_tunnel_down", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        state.cloud_connected = False
        await asyncio.sleep(delay + random.random())
        delay = min(delay * 2, 60.0)


async def prune_detections(days: int) -> int:
    """Forget detection photo index rows older than the retention period
    (the photos themselves are removed by services/retention.py)."""
    from datetime import datetime, timedelta, timezone

    from app.models.edge import EdgeDetection

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    async with AsyncSessionLocal() as db:
        res = await db.execute(delete(EdgeDetection).where(EdgeDetection.occurred_at < cutoff))
        await db.commit()
        return int(res.rowcount or 0)
