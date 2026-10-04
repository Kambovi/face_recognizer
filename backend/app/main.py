from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings, insecure_settings, validate_for_production
from app.routers import (
    alerts,
    chat,
    devices,
    users,
    hq,
    leaves,
    notify,
    analytics,
    attendance,
    auth,
    dashboard,
    employees,
    health,
    kiosk,
    media,
    profile,
    reports,
    settings as settings_router,
    shifts,
    unknowns,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

settings = get_settings()
validate_for_production(settings)  # production + published secrets -> refuse to start


def _migrate_to_head() -> None:
    """Apply any pending Alembic migrations on startup, so updating the product
    never needs a manual `alembic upgrade head` step at the client site (a
    forgotten upgrade = a crash on the first query touching a new column)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "app" / "migrations"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("api_startup", database=settings.database_url.split("@")[-1], env=settings.app_env)
    weak = insecure_settings(settings)
    if weak:
        logger.warning("INSECURE_SECRETS", secrets=weak,
                       fix="python scripts/gen_secrets.py --write  (required before going live)")
    if ":memory:" not in settings.database_url:
        import asyncio

        try:
            await asyncio.to_thread(_migrate_to_head)
            logger.info("migrations_applied")
        except Exception as exc:  # noqa: BLE001 - surface clearly, keep serving
            logger.error("migration_failed", error=str(exc)[:300])
    push_task = None
    if ":memory:" not in settings.database_url:
        import asyncio

        from app.db import AsyncSessionLocal
        from app.services.multisite import push_loop
        from app.services.notify import schedule_loop
        from app.services.retention import retention_loop

        push_task = asyncio.gather(
            push_loop(AsyncSessionLocal), schedule_loop(AsyncSessionLocal), retention_loop(AsyncSessionLocal)
        )
    yield
    if push_task is not None:
        push_task.cancel()


app = FastAPI(
    title="Face Attendance API",
    version="3.0.0",
    lifespan=lifespan,
    # no public API explorer on a live install
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        # auth is a bearer header, never a cookie -> no credentials needed
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Site-Token"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "detail" in detail and "code" in detail:
        body = detail
    else:
        body = {"detail": str(detail), "code": "http_error"}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # jsonable_encoder: a custom validator's ValueError sits in `ctx` and is
    # not JSON-serialisable -- without this the 422 turned into a 500.
    errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    return JSONResponse(status_code=422, content={"detail": "Validation error", "code": "validation_error", "errors": errors})


API_PREFIX = "/api/v1"

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(employees.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(attendance.router, prefix=API_PREFIX)
app.include_router(unknowns.router, prefix=API_PREFIX)
app.include_router(analytics.router, prefix=API_PREFIX)
app.include_router(settings_router.router, prefix=API_PREFIX)
app.include_router(kiosk.router, prefix=API_PREFIX)
app.include_router(media.router, prefix=API_PREFIX)
app.include_router(shifts.router, prefix=API_PREFIX)
app.include_router(profile.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(alerts.router, prefix=API_PREFIX)
app.include_router(hq.router, prefix=API_PREFIX)
app.include_router(notify.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(leaves.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(devices.router, prefix=API_PREFIX)
