from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.kiosk_devices import KioskDevice
from app.models.users import User
from app.security import decode_access_token

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

# Paths a user who still has to change a temporary password may call.
PASSWORD_CHANGE_ALLOWED = ("/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout", "/api/v1/profile")


class ErrorBody(dict):
    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail=detail, code=code)


def http_error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"detail": detail, "code": code})


async def _user_from_token(credentials: HTTPAuthorizationCredentials | None, db: AsyncSession) -> User:
    if credentials is None:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "not_authenticated", "Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", str(exc)) from exc
    if payload.get("typ", "access") != "access":
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", "Wrong token type")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", "User no longer exists")
    # password changed / logged out everywhere since this token was issued
    if int(payload.get("tv", 0)) != int(user.token_version or 0):
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", "Session ended, please log in again")
    return user


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _user_from_token(credentials, db)
    if user.must_change_password and not request.url.path.startswith(PASSWORD_CHANGE_ALLOWED):
        raise http_error(status.HTTP_403_FORBIDDEN, "password_change_required",
                         "Set a new password before using the dashboard")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise http_error(status.HTTP_403_FORBIDDEN, "forbidden", "Admin role required")
    return user


async def require_hr(user: User = Depends(get_current_user)) -> User:
    """Admin or HR: people, leave, holidays, attendance fixes, payroll."""
    if user.role not in (UserRole.ADMIN, UserRole.HR):
        raise http_error(status.HTTP_403_FORBIDDEN, "forbidden", "HR or admin role required")
    return user


def can_see_salary(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.HR)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class KioskAuth:
    """Who is calling a /kiosk endpoint. `kiosk_id` is None only for the
    legacy shared KIOSK_SERVICE_TOKEN (then any kiosk_id may be claimed)."""

    def __init__(self, kiosk_id: str | None) -> None:
        self.kiosk_id = kiosk_id

    def check(self, claimed_kiosk_id: str) -> None:
        if self.kiosk_id is not None and claimed_kiosk_id != self.kiosk_id:
            raise http_error(status.HTTP_403_FORBIDDEN, "kiosk_id_mismatch",
                             "This camera token belongs to a different camera")


async def require_kiosk_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> KioskAuth:
    if credentials is None or not credentials.credentials:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_kiosk_token", "Invalid or missing kiosk service token")
    token = credentials.credentials
    device = (await db.execute(
        select(KioskDevice).where(KioskDevice.token_hash == hash_device_token(token))
    )).scalar_one_or_none()
    if device is not None:
        if not device.enabled:
            raise http_error(status.HTTP_401_UNAUTHORIZED, "kiosk_disabled", "This camera has been disabled")
        now = datetime.now(timezone.utc)
        if device.last_used_at is None or (now - device.last_used_at).total_seconds() > 60:
            device.last_used_at = now
            await db.flush()
        return KioskAuth(device.kiosk_id)
    # Legacy: one shared token for every camera (old installs). Empty = off.
    import hmac

    shared = settings.kiosk_service_token
    if shared and hmac.compare_digest(token.encode(), shared.encode()):
        return KioskAuth(None)
    raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_kiosk_token", "Invalid or missing kiosk service token")
