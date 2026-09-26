from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import http_error
from app.models.users import User
from app.schemas.auth import LoginRequest, LoginResponse
from app.security import create_access_token, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise http_error(401, "invalid_credentials", "Incorrect email or password")
    token = create_access_token(subject=user.id, role=user.role.value)
    return LoginResponse(access_token=token, role=user.role.value, email=user.email)
