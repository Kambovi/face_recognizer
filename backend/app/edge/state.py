"""What the edge box knows from the cloud: runtime settings, camera tokens
(hashes only), the people ids it may see, and its licence. Kept on disk so
the box keeps working through an internet outage and a restart."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from app.config import get_settings
from app.licence import LicenceState, check
from app.services.settings_service import DEFAULT_SETTINGS

logger = structlog.get_logger(__name__)


def state_file() -> Path:
    p = get_settings().media_root_path.parent / "edge_state.json"
    return p


@dataclass
class EdgeState:
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)  # token_hash -> {kiosk_id, enabled}
    people: dict[str, dict[str, Any]] = field(default_factory=dict)   # employee id -> {face_id, active}
    licence: str | None = None
    tenant: dict[str, Any] = field(default_factory=dict)
    config_at: float = 0.0
    cloud_connected: bool = False
    last_push_at: float = 0.0
    last_push_error: str | None = None

    def apply(self, cfg: dict[str, Any]) -> None:
        if isinstance(cfg.get("settings"), dict):
            self.settings = {**DEFAULT_SETTINGS, **cfg["settings"]}
        if isinstance(cfg.get("devices"), list):
            self.devices = {d["token_hash"]: {"kiosk_id": d["kiosk_id"], "enabled": bool(d.get("enabled", True))}
                            for d in cfg["devices"] if d.get("token_hash")}
        if isinstance(cfg.get("people"), list):
            self.people = {p["id"]: {"face_id": p.get("face_id"), "active": bool(p.get("active", True))}
                           for p in cfg["people"] if p.get("id")}
        if cfg.get("licence"):
            self.licence = str(cfg["licence"])
        if isinstance(cfg.get("tenant"), dict):
            self.tenant = cfg["tenant"]
        self.config_at = time.time()
        self.save()

    def licence_state(self) -> LicenceState:
        return check(self.licence, get_settings().licence_public_key)

    def save(self) -> None:
        try:
            f = state_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"settings": self.settings, "devices": [
                {"token_hash": h, **d} for h, d in self.devices.items()], "people": [
                {"id": i, **p} for i, p in self.people.items()], "licence": self.licence, "tenant": self.tenant}))
            tmp.replace(f)
        except OSError as exc:
            logger.warning("edge_state_save_failed", error=str(exc))

    def load(self) -> None:
        try:
            data = json.loads(state_file().read_text())
        except (OSError, ValueError):
            return
        self.apply(data)


state = EdgeState()
