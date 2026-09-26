"""Kiosk process configuration.

Infra-level settings (camera source, API endpoint, service token) come from
the environment. Recognition/pipeline TUNING parameters (thresholds, fps,
dedupe window, ...) are fetched from the backend's runtime `settings` table
at startup and refreshed periodically (see `SettingsCache` in
`kiosk/pipeline.py`) -- never hardcoded here, per NON-NEGOTIABLE #1.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KioskConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore", protected_namespaces=())

    kiosk_id: str = "kiosk-01"
    api_base_url: str = "http://api:8000"
    kiosk_service_token: str = "dev_only_kiosk_service_token"

    # "synthetic" | "<camera index>" | "rtsp://..."
    camera_source: str = "synthetic"

    device_preference: str = "auto"
    model_cache_dir: str = "/models"
    insightface_model_name: str = "buffalo_l"

    offline_queue_path: str = "/data/queue/offline_events.db"

    # How often (seconds) to re-pull tunable settings from the API.
    settings_refresh_seconds: int = 30
    # How often (seconds) to send a device-status heartbeat to the API.
    heartbeat_seconds: int = 60


def get_kiosk_config() -> KioskConfig:
    return KioskConfig()
