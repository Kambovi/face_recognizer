from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.db import Base
import app.models  # noqa: F401 - populate Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# A tenant's database (SaaS, app/tenancy.py) is migrated by passing its URL in
# config.attributes["sync_url"]; otherwise this install's own database.
SYNC_URL: str = config.attributes.get("sync_url") or settings.database_url_sync
config.set_main_option("sqlalchemy.url", SYNC_URL.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # DATABASE_URL_SYNC is always a sync driver (psycopg2 for Postgres, or
    # sqlite) -- Alembic itself is sync, this is what it's for; the app's
    # own runtime engine (app/db.py) uses the separate async DATABASE_URL.
    sync_engine = create_engine(SYNC_URL, poolclass=pool.NullPool)
    with sync_engine.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
