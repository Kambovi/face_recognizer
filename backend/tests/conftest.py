from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_SYNC", "sqlite:///:memory:")
os.environ.setdefault("EMBEDDING_ENCRYPTION_KEY", "Uh6Z8s4y6b0e7z3v1c9x2q5w8n1m4k7j0h3g6f9d2s5=")
os.environ.setdefault("JWT_SECRET", "test_secret")
os.environ.setdefault("KIOSK_SERVICE_TOKEN", "test_token")
os.environ.setdefault("MEDIA_ROOT", "/tmp/face_attendance_test_media")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - populate Base.metadata
from app.db import Base, get_db
from app.main import app as fastapi_app
from app.models.enums import UserRole
from app.models.shifts import Shift
from app.models.users import User
from app.security import create_access_token, hash_password


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db_session):
    user = User(email="admin@example.org", password_hash=hash_password("secret123"), role=UserRole.ADMIN)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session):
    user = User(email="viewer@example.org", password_hash=hash_password("secret123"), role=UserRole.VIEWER)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def admin_token(admin_user):
    return create_access_token(subject=admin_user.id, role="admin")


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def kiosk_headers():
    return {"Authorization": "Bearer test_token"}


@pytest_asyncio.fixture
async def default_shift(db_session):
    import datetime as dt

    shift = Shift(name="General", in_time=dt.time(9, 0), out_time=dt.time(18, 0), grace_minutes=15, is_default=True)
    db_session.add(shift)
    await db_session.flush()
    return shift
