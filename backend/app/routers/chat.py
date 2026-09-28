"""HR chatbot.

  GET  /chat/status    mode, model, policy folder status        (any user)
  POST /chat           ask a question, or confirm a choice      (any user)
  GET  /chat/config    chatbot settings, API key never returned (admin)
  PUT  /chat/config    update; blank api_key keeps the old one  (admin)
  POST /chat/reindex   re-read the policy folder now            (admin)
  POST /chat/test      one round-trip to the configured model   (admin)

Salaries are shown to admins only. Every report that includes salaries
is written to the audit log.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, http_error, require_admin
from app.models.enums import UserRole
from app.models.users import User
from app.services.audit import write_audit
from app.services.chatbot import engine, llm
from app.services.chatbot.policy import get_index
from app.services.client_profile import get_profile

router = APIRouter(prefix="/chat", tags=["chatbot"])


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatAction(BaseModel):
    type: Literal["report", "filter"]
    kind: Literal["employee", "department", "camera", "contractor"] = "employee"
    id: str | None = None
    query: str | None = None
    department: str | None = None
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class ChatIn(BaseModel):
    message: str = Field(default="", max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=40)
    action: ChatAction | None = None


class ChatConfigIn(BaseModel):
    enabled: bool = True
    provider: Literal["off", "anthropic", "openai", "ollama"] = "off"
    model: str = Field(default="", max_length=100)
    base_url: str = Field(default="", max_length=300)
    api_key: str = Field(default="", max_length=300)
    temperature: float = Field(default=0.2, ge=0, le=1)
    org_note: str = Field(default="", max_length=1000)


@router.get("/status")
async def chat_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    cfg = await engine.get_config(db)
    idx = get_index().status()
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "mode": engine.mode_of(cfg),
        "provider": cfg.get("provider"),
        "model": cfg.get("model"),
        "can_see_salary": user.role == UserRole.ADMIN,
        "policy": {"files": idx["files"], "chunks": idx["chunks"]},
    }


@router.post("")
async def chat(payload: ChatIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    cfg = await engine.get_config(db)
    if not cfg.get("enabled", True):
        raise http_error(403, "chatbot_disabled", "Chatbot is turned off in Settings")
    if payload.action and payload.action.type == "report" and not payload.action.id:
        raise http_error(422, "bad_action", "action.id is required")
    can_see_salary = user.role == UserRole.ADMIN
    profile = await get_profile(db)
    reply = await engine.respond(
        db, cfg,
        message=payload.message,
        history=[h.model_dump() for h in payload.history],
        action=payload.action.model_dump() if payload.action else None,
        org_name=str(profile.get("org_name") or "the organisation"),
        can_see_salary=can_see_salary,
    )
    rep = reply.get("report")
    if rep:
        await write_audit(db, user.id, "chat_report", rep["kind"], str(rep["target"])[:100], before=None,
                          after={"month": rep["month"], "salary_shown": not rep["salary_hidden"], "rows": len(rep["rows"])})
        await db.commit()
    return reply


@router.get("/config")
async def read_config(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = engine.public_config(await engine.get_config(db))
    cfg["policy"] = get_index().status()
    return cfg


@router.put("/config")
async def update_config(payload: ChatConfigIn, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = await engine.get_config(db)
    data = payload.model_dump()
    if not data["api_key"]:
        data.pop("api_key")
    cfg.update(data)
    await engine.save_config(db, cfg)
    await write_audit(db, user.id, "chat_config", "settings", "chatbot", before=None,
                      after={k: v for k, v in data.items() if k != "api_key"})
    await db.commit()
    out = engine.public_config(cfg)
    out["policy"] = get_index().status()
    return out


@router.post("/reindex")
async def reindex(_user: User = Depends(require_admin)) -> dict[str, Any]:
    idx = get_index()
    idx.refresh(force=True)
    return idx.status()


@router.post("/test")
async def test_model(db: AsyncSession = Depends(get_db), _user: User = Depends(require_admin)) -> dict[str, Any]:
    cfg = await engine.get_config(db)
    try:
        out = await llm.complete(cfg, "Reply with the single word OK.", [{"role": "user", "content": "ping"}])
        return {"ok": True, "reply": out.text[:200]}
    except llm.LLMError as exc:
        return {"ok": False, "error": str(exc)[:400]}
