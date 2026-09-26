"""Dialect-aware column types.

`Vector(dim)` compiles to a real pgvector `vector(dim)` column on Postgres
(so `embedding <=> :query` cosine search runs in SQL, per spec section
"RECOGNITION PIPELINE" step 7), and transparently falls back to a JSON-encoded
TEXT column on SQLite so the full backend test suite can run with zero
external services. `app/services/matching.py` is the only place that branches
on which dialect is active, doing the equivalent cosine search in Python for
SQLite. See docs/DECISIONS.md.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector as _PGVector


class Vector(sa.types.TypeDecorator):
    impl = sa.Text
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: sa.engine.Dialect) -> sa.types.TypeEngine:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PGVector(self.dim))
        return dialect.type_descriptor(sa.Text())

    def process_bind_param(self, value: Any, dialect: sa.engine.Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value: Any, dialect: sa.engine.Dialect) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return [float(x) for x in value]
        return [float(x) for x in json.loads(value)]


class UTCDateTime(sa.types.TypeDecorator):
    """`sa.DateTime(timezone=True)` round-trips as tz-aware on Postgres, but
    SQLite (test suite only) has no real tz-aware storage and hands back a
    naive datetime, which then blows up any `a - b` against a tz-aware
    value elsewhere in the app. This type normalizes: always stored as UTC,
    always read back as tz-aware UTC, on both dialects."""

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: sa.engine.Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        if dialect.name != "postgresql":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: sa.engine.Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def new_uuid_str() -> str:
    return str(uuid.uuid4())


# Portable 36-char UUID string primary key type, avoids depending on the
# Postgres-only UUID column type or the pgcrypto extension so the same model
# definitions work unchanged against SQLite in tests.
GUID = sa.String(36)
