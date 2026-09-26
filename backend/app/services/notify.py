"""Outbound notifications. Filled in by the WhatsApp milestone; until a
channel is configured this is a no-op."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import Alert


async def notify_alert(db: AsyncSession, alert: Alert, config: dict[str, Any]) -> None:
    return None
