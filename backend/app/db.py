"""Async SQLAlchemy engine/session setup.

Production runs against Postgres+pgvector (per spec). The test suite runs
against SQLite+aiosqlite with zero external services, which is why
`app/models/types.py` defines a dialect-aware Vector column type and
`app/services/matching.py` branches its similarity search on the bound
dialect. Everything else is identical between the two.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {}

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_models_for_tests() -> None:
    """Create all tables directly from ORM metadata.

    Used only by the SQLite test suite, which does not run Alembic
    migrations. Production always migrates via `alembic upgrade head`
    (see backend/Dockerfile CMD).
    """
    import app.models  # noqa: F401  (ensure all model modules are imported)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
