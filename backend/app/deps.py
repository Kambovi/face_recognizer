from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.users import User
from app.security import decode_access_token

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


class ErrorBody(dict):
    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail=detail, code=code)


def http_error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"detail": detail, "code": code})


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "not_authenticated", "Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", str(exc)) from exc

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_token", "User no longer exists")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise http_error(status.HTTP_403_FORBIDDEN, "forbidden", "Admin role required")
    return user


async def require_kiosk_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.credentials != settings.kiosk_service_token:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "invalid_kiosk_token", "Invalid or missing kiosk service token")
    return credentials.credentials
