from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SettingsResponse(BaseModel):
    settings: dict[str, Any]
    device: dict[str, Any] | None = None


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any]
