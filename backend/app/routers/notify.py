"""WhatsApp / webhook notification settings (admin).

  GET  /notify/config        current settings (access token never returned)
  PUT  /notify/config        update; omit or leave access_token blank to keep it
  POST /notify/test          send a test message now
  POST /notify/daily-now     send today's summary now (demo / check)
"""
from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.users import User
from app.services.audit import write_audit
from app.services.notify import daily_text, get_config, public_config, save_config, send_logged

router = APIRouter(prefix="/notify", tags=["notifications"])


class NotifyIn(BaseModel):
    channel: Literal["off", "whatsapp", "webhook"] = "off"
    recipients: list[str] = Field(default_factory=list, max_length=20)
    phone_number_id: str = ""
    access_token: str = ""
    template_alert: str = ""
    template_daily: str = ""
    template_monthly: str = ""
    template_language: str = "en"
    webhook_url: str = ""
    send_alerts: bool = True
    send_daily: bool = True
    daily_time: str = "10:00"
    send_monthly: bool = True

    @field_validator("recipients")
    @classmethod
    def _digits(cls, v: list[str]) -> list[str]:
        out = []
        for n in v:
            d = re.sub(r"\D", "", n)
            if d:
                if len(d) == 10:  # bare Indian mobile -> add country code
                    d = "91" + d
                out.append(d)
        return out

    @field_validator("daily_time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
            raise ValueError("daily_time must be HH:MM")
        return v


@router.get("/config")
async def read_config(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    return public_config(await get_config(db))


@router.put("/config")
async def update_config(payload: NotifyIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = await get_config(db)
    data = payload.model_dump()
    if not data["access_token"]:
        data.pop("access_token")
    cfg.update(data)
    await save_config(db, cfg)
    await write_audit(db, user.id, "notify_config", "settings", "notify",
                      after={k: v for k, v in data.items() if k != "access_token"})
    await db.commit()
    return public_config(cfg)


@router.post("/test")
async def test(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = await get_config(db)
    ok = await send_logged(cfg, "Test message from your face attendance system. Notifications are working.", "alert")
    await save_config(db, cfg)
    await db.commit()
    return {"sent": ok, "error": cfg.get("last_error")}


@router.post("/daily-now")
async def daily_now(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = await get_config(db)
    text = await daily_text(db)
    ok = await send_logged(cfg, text, "daily")
    await save_config(db, cfg)
    await db.commit()
    return {"sent": ok, "text": text, "error": cfg.get("last_error")}
