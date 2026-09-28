"""Application configuration.

Everything here has a working default so `docker compose up` succeeds with a
bare .env.example. Runtime-tunable recognition/pipeline parameters (similarity
threshold, liveness, dedupe window, etc.) are NOT here on purpose -- those
live in the `settings` DB table (see app/services/settings_service.py) so
they can be changed from the dashboard without a redeploy. This module only
holds infrastructure-level configuration that legitimately requires a
process restart to change (DB DSN, JWT secret, ports, ...).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    database_url_sync: str = "sqlite:///./dev.db"

    # --- Auth ---
    jwt_secret: str = "dev_only_change_me_to_a_long_random_string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # --- Biometric data protection ---
    embedding_encryption_key: str = "Uh6Z8s4y6b0e7z3v1c9x2q5w8n1m4k7j0h3g6f9d2s5="

    # --- Kiosk auth ---
    kiosk_service_token: str = "dev_only_kiosk_service_token"

    # --- Media ---
    media_root: str = "/data/media"
    crop_max_dim: int = 224

    # --- Timezone ---
    app_timezone: str = "Asia/Kolkata"

    # --- Device / model ---
    device_preference: str = "auto"
    model_cache_dir: str = "/models"
    insightface_model_name: str = "buffalo_l"

    # --- Chatbot: folder of company policy documents (.txt .md .pdf .docx) ---
    policy_dir: str = "./data/policy"

    # --- CORS ---
    cors_origins: str = "*"

    @property
    def media_root_path(self) -> Path:
        p = Path(self.media_root)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
