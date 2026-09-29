"""Head-office (multi-site) endpoints.

HQ side (this install collects other sites):
  GET    /hq/sites            all registered sites + their latest snapshot
  POST   /hq/sites            register a site -> returns its token ONCE (admin)
  DELETE /hq/sites/{id}       remove a site (admin)
  POST   /hq/ingest           a site pushes its snapshot (X-Site-Token header)

Site side (this install reports to an HQ):
  GET    /hq/link             where this site reports to + last push status
  PUT    /hq/link             set / clear the HQ url + token (admin)
  POST   /hq/link/test        push right now and report the result (admin)
"""
from __future__ import annotations

import re

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.sites import Site
from app.models.users import User
from app.services.audit import write_audit
from app.services.multisite import get_link, hash_token, new_token, push_once, save_link

router = APIRouter(prefix="/hq", tags=["multi-site"])


def _site_out(s: Site) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "created_at": s.created_at, "last_push_at": s.last_push_at, "snapshot": s.snapshot}


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class LinkIn(BaseModel):
    url: str = Field(default="", max_length=300)

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        v = v.strip()
        if v and not re.match(r"^https?://[^\s/@]+", v):
            raise ValueError("Head-office address must start with http:// or https:// (e.g. https://hq.example.in)")
        return v
    token: str = Field(default="", max_length=200)


@router.get("/sites")
async def list_sites(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [_site_out(s) for s in (await db.execute(select(Site).order_by(Site.name))).scalars().all()]


@router.post("/sites", status_code=201)
async def create_site(payload: SiteCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    token, digest = new_token()
    site = Site(name=payload.name.strip(), token_hash=digest)
    db.add(site)
    await db.flush()
    await write_audit(db, user.id, "site_create", "site", site.id, after={"name": site.name})
    await db.commit()
    return {**_site_out(site), "token": token}


@router.delete("/sites/{site_id}", status_code=204, response_model=None)
async def delete_site(site_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> None:
    site = await db.get(Site, site_id)
    if site is None:
        raise http_error(status.HTTP_404_NOT_FOUND, "not_found", "Site not found")
    await write_audit(db, user.id, "site_delete", "site", site_id, before={"name": site.name})
    await db.delete(site)
    await db.commit()


@router.post("/ingest")
async def ingest(
    snapshot: dict[str, Any], x_site_token: str = Header(default=""), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    if not x_site_token:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "no_token", "X-Site-Token header missing")
    site = (await db.execute(select(Site).where(Site.token_hash == hash_token(x_site_token)))).scalar_one_or_none()
    if site is None:
        raise http_error(status.HTTP_401_UNAUTHORIZED, "bad_token", "Unknown site token")
    # keep only plain scalar fields -- nothing from a site is ever rendered as HTML
    site.snapshot = {k: v for k, v in snapshot.items() if isinstance(v, (int, float, str, bool)) or v is None}
    site.last_push_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.get("/link")
async def read_link(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    link = await get_link(db)
    return {
        "url": link.get("url", ""),
        "token_set": bool(link.get("token")),
        "last_push_at": link.get("last_push_at"),
        "last_error": link.get("last_error"),
    }


@router.put("/link")
async def update_link(payload: LinkIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    link = await get_link(db)
    link["url"] = payload.url.strip()
    if payload.token.strip() or not payload.url.strip():
        link["token"] = payload.token.strip()
    link["last_error"] = None
    await save_link(db, link)
    await write_audit(db, user.id, "hq_link", "settings", "hq", after={"url": link["url"]})
    await db.commit()
    return await read_link(db, user)


@router.post("/link/test")
async def test_link(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    return await push_once(db)
