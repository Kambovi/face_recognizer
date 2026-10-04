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
    # Comma-separated list of browser origins allowed to call the API, e.g.
    # "https://acme.yourapp.in". Empty = same-origin only (the dashboard is
    # served from the same host via the reverse proxy). "*" only in development.
    cors_origins: str = ""

    # --- Environment ---
    # "development" (laptop / tests) or "production" (any real client). In
    # production the API REFUSES TO START with the published default secrets
    # (see validate_for_production) and hides /docs.
    app_env: str = "development"

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if not raw and not self.is_production:
            return ["*"]
        return [o for o in raw if o != "*" or not self.is_production]

    @property
    def media_root_path(self) -> Path:
        p = Path(self.media_root)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


# Values published in the source code / .env.example. Anyone who has seen the
# repository knows them, so a production install must never run with them.
INSECURE_DEFAULTS = {
    "dev_only_change_me_to_a_long_random_string",
    "Uh6Z8s4y6b0e7z3v1c9x2q5w8n1m4k7j0h3g6f9d2s5=",
    "dev_only_kiosk_service_token",
    "change_me_dev_only",
    "test_secret",
    "test_token",
}


def insecure_settings(s: Settings) -> list[str]:
    """Names of secrets that are missing, published defaults or too short."""
    problems: list[str] = []
    if s.jwt_secret in INSECURE_DEFAULTS or len(s.jwt_secret) < 32:
        problems.append("JWT_SECRET")
    if s.embedding_encryption_key in INSECURE_DEFAULTS:
        problems.append("EMBEDDING_ENCRYPTION_KEY")
    if s.kiosk_service_token and (s.kiosk_service_token in INSECURE_DEFAULTS or len(s.kiosk_service_token) < 24):
        problems.append("KIOSK_SERVICE_TOKEN")
    for marker in INSECURE_DEFAULTS:
        if marker in s.database_url:
            problems.append("DATABASE_URL (default password)")
            break
    return problems


def validate_for_production(s: Settings) -> None:
    """Raise if this is a production install still using published secrets.
    Fix: run `python scripts/gen_secrets.py` and restart."""
    if not s.is_production:
        return
    bad = insecure_settings(s)
    if bad:
        raise RuntimeError(
            "Refusing to start in production with insecure secrets: " + ", ".join(bad)
            + ". Run `python scripts/gen_secrets.py --write` (backend folder) and restart."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
