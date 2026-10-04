"""Dashboard logins, managed from the UI (admin only), and the audit log.

  GET    /users                     list
  POST   /users                     create -> temporary password shown ONCE
  PATCH  /users/{id}                name / role / active
  POST   /users/{id}/reset-password new temporary password shown ONCE
  DELETE /users/{id}
  GET    /audit                     who changed what (admin)

A temporary password must be changed at first login (must_change_password).
The last active admin can't be demoted, disabled or deleted.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import http_error, require_admin
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.users import User
from app.security import hash_password
from app.services.audit import write_audit

router = APIRouter(tags=["users"])
Role = Literal["admin", "hr", "viewer"]


def temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(14))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def _out(u: User) -> dict[str, Any]:
    return {
        "id": u.id, "email": u.email, "name": u.name, "role": u.role.value, "is_active": u.is_active,
        "must_change_password": u.must_change_password, "last_login_at": u.last_login_at,
        "locked": bool(u.locked_until and u.locked_until > datetime.now(u.locked_until.tzinfo)),
        "created_at": u.created_at,
    }


class UserCreate(BaseModel):
    email: EmailStr
    name: str | None = Field(default=None, max_length=120)
    role: Role = "viewer"


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: Role | None = None
    is_active: bool | None = None


async def _active_admins(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(User).where(
        User.role == UserRole.ADMIN, User.is_active.is_(True)))).scalar_one())


async def _get(db: AsyncSession, user_id: str) -> User:
    u = await db.get(User, user_id)
    if u is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "User not found")
    return u


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db), _a: User = Depends(require_admin)) -> list[dict[str, Any]]:
    return [_out(u) for u in (await db.execute(select(User).order_by(User.email))).scalars().all()]


@router.post("/users", status_code=201)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none():
        raise http_error(409, "exists", "A login with this email already exists")
    pw = temp_password()
    u = User(email=email, name=payload.name, role=UserRole(payload.role), password_hash=hash_password(pw),
             must_change_password=True)
    db.add(u)
    await db.flush()
    await write_audit(db, admin.id, "user_create", "user", u.id, after={"email": email, "role": payload.role})
    await db.commit()
    return {**_out(u), "temporary_password": pw}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, payload: UserPatch, db: AsyncSession = Depends(get_db),
                      admin: User = Depends(require_admin)) -> dict[str, Any]:
    u = await _get(db, user_id)
    before = _out(u)
    losing_admin = u.role == UserRole.ADMIN and u.is_active and (
        (payload.role is not None and payload.role != "admin") or payload.is_active is False)
    if losing_admin and await _active_admins(db) <= 1:
        raise http_error(409, "last_admin", "This is the last active admin -- add another admin first")
    if payload.name is not None:
        u.name = payload.name
    if payload.role is not None and payload.role != u.role.value:
        u.role = UserRole(payload.role)
        u.token_version = (u.token_version or 0) + 1  # new role takes effect at next login
    if payload.is_active is not None and payload.is_active != u.is_active:
        u.is_active = payload.is_active
        u.token_version = (u.token_version or 0) + 1
        u.locked_until = None
        u.failed_logins = 0
    await write_audit(db, admin.id, "user_update", "user", u.id,
                      before={k: before[k] for k in ("name", "role", "is_active")},
                      after=payload.model_dump(exclude_unset=True))
    await db.commit()
    return _out(u)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> dict[str, Any]:
    u = await _get(db, user_id)
    pw = temp_password()
    u.password_hash = hash_password(pw)
    u.must_change_password = True
    u.token_version = (u.token_version or 0) + 1
    u.locked_until = None
    u.failed_logins = 0
    await write_audit(db, admin.id, "user_password_reset", "user", u.id)
    await db.commit()
    return {**_out(u), "temporary_password": pw}


@router.delete("/users/{user_id}", status_code=204, response_model=None)
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    u = await _get(db, user_id)
    if u.id == admin.id:
        raise http_error(409, "self", "You can't delete your own login")
    if u.role == UserRole.ADMIN and u.is_active and await _active_admins(db) <= 1:
        raise http_error(409, "last_admin", "This is the last active admin")
    await write_audit(db, admin.id, "user_delete", "user", u.id, before={"email": u.email, "role": u.role.value})
    await db.delete(u)
    await db.commit()


@router.get("/audit")
async def audit_log(
    entity: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    _a: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    q = select(AuditLog, User.email).join(User, User.id == AuditLog.actor_user_id, isouter=True)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if action:
        q = q.where(AuditLog.action == action)
    rows = (await db.execute(q.order_by(AuditLog.at.desc()).limit(limit))).all()
    return [{"id": a.id, "at": a.at, "actor": email or ("system" if a.actor_user_id is None else a.actor_user_id),
             "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "before": a.before, "after": a.after}
            for a, email in rows]
