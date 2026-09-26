from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def str_enum(enum_cls: Any, name: str) -> sa.Enum:
    """A portable VARCHAR+CHECK enum column (see models/enums.py docstring)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )
