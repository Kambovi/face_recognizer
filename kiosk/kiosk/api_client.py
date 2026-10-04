"""Thin HTTP client the kiosk uses to reach the backend. Every call is
service-token authenticated and short-timeout; callers decide what to do on
failure (pipeline.py routes failed event posts into the offline queue)."""
from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


class ApiClient:
    def __init__(self, base_url: str, service_token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {service_token}"}
        self._client = httpx.Client(timeout=timeout)

    def post_event(self, payload: dict[str, Any]) -> bool:
        try:
            resp = self._client.post(
                f"{self.base_url}/api/v1/kiosk/event", json=payload, headers=self._headers
            )
            if resp.status_code in (400, 409, 413, 422):
                # The server looked at it and will never accept it (too old,
                # clock wrong, bad crop): drop it instead of queueing forever.
                logger.warning("kiosk_event_rejected", status=resp.status_code, body=resp.text[:200])
                return True
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("kiosk_event_post_failed", exception_type=type(exc).__name__)
            return False

    def post_heartbeat(self, kiosk_id: str, device: dict[str, Any]) -> bool:
        try:
            resp = self._client.post(
                f"{self.base_url}/api/v1/kiosk/heartbeat",
                json={"kiosk_id": kiosk_id, "device": device},
                headers=self._headers,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("kiosk_heartbeat_post_failed", exception_type=type(exc).__name__)
            return False

    def get_settings(self) -> dict[str, Any] | None:
        try:
            # Service-token authed, kiosk-scoped read of the same runtime
            # `settings` table the admin dashboard edits (see
            # backend/app/routers/kiosk.py) -- the kiosk token intentionally
            # cannot reach the admin-only PATCH /settings endpoint.
            resp = self._client.get(f"{self.base_url}/api/v1/kiosk/config", headers=self._headers)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("kiosk_settings_fetch_failed", exception_type=type(exc).__name__)
            return None

    def close(self) -> None:
        self._client.close()
