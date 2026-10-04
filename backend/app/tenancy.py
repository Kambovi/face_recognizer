"""SaaS multi-tenancy: one database per client ("tenant").

APP_ROLE=cloud only. A small CONTROL database lists the tenants and their
edge boxes; every tenant has its own database with the normal schema (the
same Alembic migrations as a standalone install), so one client's data can
never show up in another client's query, and a client can be backed up,
moved or deleted on its own.

A request finds its tenant from the host name: acme.<BASE_DOMAIN> ->
tenant "acme". Edge boxes find theirs from their site token. The tenant is
kept in a context variable for the request, and app.db.get_db hands out a
session on that tenant's database.

Standalone and edge installs never touch this module's databases.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import ipaddress
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings
from app.models.types import GUID, UTCDateTime, new_uuid_str

logger = structlog.get_logger(__name__)
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
RESERVED_SLUGS = {"www", "api", "admin", "app", "mail", "edge", "status", "docs", "static", "cdn"}


class ControlBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(ControlBase):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    slug: Mapped[str] = mapped_column(sa.String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    # active / suspended (unpaid, on request) / deleted
    status: Mapped[str] = mapped_column(sa.String(12), nullable=False, default="active")
    status_reason: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    db_url_enc: Mapped[str] = mapped_column(sa.Text, nullable=False)  # security.encrypt_text
    plan: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="standard")
    max_cameras: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=2)
    max_people: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=200)
    # dashboard may only be opened from these networks (empty = anywhere)
    allowed_cidrs: Mapped[list[str] | None] = mapped_column(sa.JSON(), nullable=True)
    paid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class EdgeSite(ControlBase):
    __tablename__ = "edge_sites"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid_str)
    tenant_id: Mapped[str] = mapped_column(GUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    version: Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sync_url(async_url: str) -> str:
    return async_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")


# ------------------------------------------------------------------ control db
_control_engine: AsyncEngine | None = None
_control_sessions: async_sessionmaker[AsyncSession] | None = None


def control_sessions() -> async_sessionmaker[AsyncSession]:
    global _control_engine, _control_sessions
    if _control_sessions is None:
        _control_engine = create_async_engine(get_settings().control_database_url, pool_pre_ping=True)
        _control_sessions = async_sessionmaker(_control_engine, expire_on_commit=False, autoflush=False)
    return _control_sessions


async def init_control_db() -> None:
    control_sessions()
    assert _control_engine is not None
    async with _control_engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)


# ------------------------------------------------------------------ tenant registry
@dataclass
class TenantInfo:
    id: str
    slug: str
    name: str
    status: str
    status_reason: str | None
    db_url: str
    max_cameras: int
    max_people: int
    allowed_cidrs: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status == "active"


def _info(t: Tenant) -> TenantInfo:
    from app.security import decrypt_text

    return TenantInfo(id=t.id, slug=t.slug, name=t.name, status=t.status, status_reason=t.status_reason,
                      db_url=decrypt_text(t.db_url_enc), max_cameras=t.max_cameras, max_people=t.max_people,
                      allowed_cidrs=list(t.allowed_cidrs or []))


_cache: dict[str, tuple[float, TenantInfo | None]] = {}
CACHE_SECONDS = 30.0
_engines: dict[str, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]] = {}


def forget_tenant(slug: str) -> None:
    _cache.pop(slug, None)


async def tenant_by_slug(slug: str) -> TenantInfo | None:
    hit = _cache.get(slug)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with control_sessions()() as db:
        t = (await db.execute(select(Tenant).where(Tenant.slug == slug, Tenant.status != "deleted"))).scalar_one_or_none()
    info = _info(t) if t else None
    _cache[slug] = (time.monotonic(), info)
    return info


async def all_tenants(active_only: bool = True) -> list[TenantInfo]:
    async with control_sessions()() as db:
        q = select(Tenant).where(Tenant.status != "deleted")
        if active_only:
            q = q.where(Tenant.status == "active")
        return [_info(t) for t in (await db.execute(q.order_by(Tenant.slug))).scalars().all()]


def sessions_for(tenant: TenantInfo) -> async_sessionmaker[AsyncSession]:
    hit = _engines.get(tenant.slug)
    if hit is None or str(hit[0].url) != str(sa.engine.make_url(tenant.db_url)):
        engine = create_async_engine(tenant.db_url, pool_pre_ping=True, pool_size=5, max_overflow=5) \
            if tenant.db_url.startswith("postgresql") else create_async_engine(tenant.db_url)
        hit = (engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False))
        _engines[tenant.slug] = hit
    return hit[1]


async def dispose_engines() -> None:
    for engine, _ in list(_engines.values()):
        await engine.dispose()
    _engines.clear()
    if _control_engine is not None:
        await _control_engine.dispose()


# ------------------------------------------------------------------ request context
current_tenant: contextvars.ContextVar[TenantInfo | None] = contextvars.ContextVar("current_tenant", default=None)


def slug_from_host(host: str, base_domain: str) -> str | None:
    host = (host or "").split(":")[0].strip().lower().rstrip(".")
    base = base_domain.strip().lower().rstrip(".")
    if not host or not base or not host.endswith("." + base):
        return None
    sub = host[: -len(base) - 1]
    return sub if SLUG_RE.match(sub) and "." not in sub else None


def ip_allowed(ip: str | None, cidrs: list[str]) -> bool:
    if not cidrs:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


# Paths that are not tenant dashboards (edge boxes authenticate by site token).
TENANT_FREE_PREFIXES = ("/api/v1/health", "/api/v1/edge/")


class TenantMiddleware:
    """Pure ASGI middleware (works for HTTP and WebSocket)."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope["type"] not in ("http", "websocket") or get_settings().role != "cloud":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if not path.startswith("/api/") or path.startswith(TENANT_FREE_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        settings = get_settings()
        slug = slug_from_host(headers.get("host", ""), settings.base_domain)
        if slug is None and not settings.is_production:
            slug = headers.get("x-tenant")  # local testing without wildcard DNS
        tenant = await tenant_by_slug(slug) if slug else None
        if tenant is None:
            await _reject(scope, send, 404, "unknown_tenant", "No such organisation on this service")
            return
        if not tenant.active:
            await _reject(scope, send, 402, "tenant_suspended",
                          tenant.status_reason or "This account is suspended. Please contact your service provider.")
            return
        client = scope.get("client")
        if not ip_allowed(client[0] if client else None, tenant.allowed_cidrs) and not path.startswith("/api/v1/profile"):
            await _reject(scope, send, 403, "ip_not_allowed", "This dashboard can only be opened from your office network")
            return
        token = current_tenant.set(tenant)
        try:
            await self.app(scope, receive, send)
        finally:
            current_tenant.reset(token)


async def _reject(scope: dict[str, Any], send: Callable[..., Any], status: int, code: str, detail: str) -> None:
    import json

    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 4000 + (status % 1000)})
        return
    body = json.dumps({"detail": detail, "code": code}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def tenant_session() -> AsyncIterator[AsyncSession]:
    tenant = current_tenant.get()
    if tenant is None:
        raise RuntimeError("no tenant in this request (cloud role)")
    async with sessions_for(tenant)() as session:
        yield session


async def for_each_tenant(job: Callable[[AsyncSession], Awaitable[Any]], name: str) -> None:
    """Run a background job on every active tenant's database."""
    for t in await all_tenants():
        token = current_tenant.set(t)
        try:
            async with sessions_for(t)() as db:
                await job(db)
        except Exception as exc:  # noqa: BLE001 - one tenant must not stop the others
            logger.warning("tenant_job_failed", job=name, tenant=t.slug, error=str(exc)[:200])
        finally:
            current_tenant.reset(token)
        await asyncio.sleep(0)


def migrate_tenant_db(db_url: str) -> None:
    """alembic upgrade head on one tenant database (sync; run in a thread)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "migrations"))
    cfg.attributes["sync_url"] = sync_url(db_url)
    command.upgrade(cfg, "head")
