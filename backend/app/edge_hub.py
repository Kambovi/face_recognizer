"""Cloud side of the edge tunnel.

Each client's edge box keeps ONE outbound WebSocket open to the cloud
(wss://<cloud>/api/v1/edge/ws, site token in the Authorization header): no
port forwarding, no static IP, works behind any office router. The cloud
uses it to ask the box for things that never leave the site -- enrol a
face, show a photo, search the policy documents -- and the box answers on
the same socket. Data passes through the cloud's memory to the browser; it
is never written to the cloud's disk or database.

One process holds the sockets, so the cloud API runs as ONE uvicorn worker
(async, plenty for hundreds of tenants). Scaling out later = put the
pending-call map behind Redis pub/sub.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import WebSocket, status

from app.deps import http_error

logger = structlog.get_logger(__name__)
DEFAULT_TIMEOUT = 30.0


class EdgeOffline(Exception):
    pass


class EdgeError(Exception):
    pass


@dataclass
class EdgeConn:
    ws: WebSocket
    tenant: str
    site_id: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: str | None = None
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, msg: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(msg))


class EdgeHub:
    def __init__(self) -> None:
        self.conns: dict[str, EdgeConn] = {}

    def online(self, tenant: str) -> bool:
        return tenant in self.conns

    def status(self, tenant: str) -> dict[str, Any]:
        c = self.conns.get(tenant)
        return {"online": c is not None, "connected_at": c.connected_at if c else None,
                "version": c.version if c else None}

    async def register(self, conn: EdgeConn) -> None:
        old = self.conns.get(conn.tenant)
        self.conns[conn.tenant] = conn
        if old is not None and old is not conn:
            for fut in old.pending.values():
                if not fut.done():
                    fut.set_exception(EdgeOffline("replaced by a new connection"))
            try:
                await old.ws.close(code=4009)
            except Exception:  # noqa: BLE001
                pass

    def unregister(self, conn: EdgeConn) -> None:
        if self.conns.get(conn.tenant) is conn:
            del self.conns[conn.tenant]
        for fut in conn.pending.values():
            if not fut.done():
                fut.set_exception(EdgeOffline("edge disconnected"))

    def on_message(self, conn: EdgeConn, msg: dict[str, Any]) -> None:
        if msg.get("type") == "rpc_result":
            fut = conn.pending.pop(str(msg.get("id")), None)
            if fut is not None and not fut.done():
                if msg.get("ok"):
                    fut.set_result(msg.get("result"))
                else:
                    fut.set_exception(EdgeError(str(msg.get("error") or "edge error")))
        elif msg.get("type") == "hello":
            conn.version = str(msg.get("version") or "")[:40]

    async def call(self, tenant: str, method: str, params: dict[str, Any] | None = None,
                   timeout: float = DEFAULT_TIMEOUT) -> Any:
        conn = self.conns.get(tenant)
        if conn is None:
            raise EdgeOffline("edge box not connected")
        rid = uuid.uuid4().hex
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        conn.pending[rid] = fut
        try:
            await conn.send({"type": "rpc", "id": rid, "method": method, "params": params or {}})
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as exc:
            raise EdgeOffline(f"edge box did not answer {method} in {timeout:.0f}s") from exc
        finally:
            conn.pending.pop(rid, None)


hub = EdgeHub()


async def edge_call(method: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    """Call the current request's tenant's edge box; HTTP errors for the UI."""
    from app.tenancy import current_tenant

    tenant = current_tenant.get()
    if tenant is None:
        raise http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "no_tenant", "No tenant for this request")
    try:
        return await hub.call(tenant.slug, method, params, timeout)
    except EdgeOffline as exc:
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "edge_offline",
                         "The site's face-recognition box is offline (check its power / internet). " + str(exc)) from exc
    except EdgeError as exc:
        raise http_error(status.HTTP_502_BAD_GATEWAY, "edge_error", str(exc)) from exc
