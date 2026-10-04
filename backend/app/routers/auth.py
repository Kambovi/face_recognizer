"""Login, password change, logout-everywhere.

  POST /auth/login            email + password -> token (throttled, lockout)
  GET  /auth/me               who am I (works while a password change is pending)
  POST /auth/change-password  needs the current password; ends all other sessions
  POST /auth/logout           ends every session of this user (token_version += 1)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error
from app.models.users import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, LoginResponse, MeResponse
from app.security import create_access_token, hash_password, verify_password
from app.services.audit import write_audit
from app.services.passwords import LOCK_MINUTES, MAX_FAILED, login_throttle, password_problem

router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str:
    # Behind the reverse proxy run uvicorn with --proxy-headers
    # --forwarded-allow-ips=<proxy ip> so this is the real client address.
    return request.client.host if request.client else "unknown"


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    if not login_throttle.allow(_client_ip(request)):
        raise http_error(429, "too_many_attempts", "Too many login attempts. Try again in a few minutes.")
    email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if user is not None and user.locked_until is not None and user.locked_until > now:
        verify_password(payload.password, None)  # same timing as a normal attempt
        mins = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise http_error(423, "account_locked", f"Too many wrong passwords. Account locked for {mins} more minute(s).")

    ok = verify_password(payload.password, user.password_hash if user is not None else None)
    if user is None or not ok or not user.is_active:
        if user is not None and not ok:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.failed_logins = 0
                await write_audit(db, None, "login_locked", "user", user.id, after={"ip": _client_ip(request)})
            await db.commit()
        raise http_error(401, "invalid_credentials", "Incorrect email or password")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    await db.commit()
    token = create_access_token(subject=user.id, role=user.role.value, token_version=user.token_version or 0)
    return LoginResponse(access_token=token, role=user.role.value, email=user.email,
                         must_change_password=bool(user.must_change_password))


@router.get("/auth/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, name=user.name, role=user.role.value,
                      must_change_password=bool(user.must_change_password))


@router.post("/auth/change-password", response_model=LoginResponse)
async def change_password(
    payload: ChangePasswordRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> LoginResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise http_error(400, "wrong_password", "Current password is wrong")
    problem = password_problem(payload.new_password, user.email)
    if problem:
        raise http_error(422, "weak_password", problem)
    if verify_password(payload.new_password, user.password_hash):
        raise http_error(422, "weak_password", "New password must be different from the current one")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc)
    user.token_version = (user.token_version or 0) + 1  # other sessions end
    await write_audit(db, user.id, "password_change", "user", user.id)
    await db.commit()
    token = create_access_token(subject=user.id, role=user.role.value, token_version=user.token_version)
    return LoginResponse(access_token=token, role=user.role.value, email=user.email, must_change_password=False)


@router.post("/auth/logout", status_code=204, response_model=None)
async def logout_everywhere(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    user.token_version = (user.token_version or 0) + 1
    await write_audit(db, user.id, "logout_all", "user", user.id)
    await db.commit()
