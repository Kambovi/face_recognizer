"""Shared enum types.

All are mapped with `native_enum=False` (see app/models/base.py::str_enum),
i.e. stored as plain VARCHAR + CHECK constraint on every dialect. This avoids
Postgres native ENUM types, which need their own ALTER TYPE migration dance
whenever a value is added, and which SQLite cannot represent at all -- a
plain string column with a CHECK constraint gets us portability and
DB-enforced validity for free.
"""
from __future__ import annotations

import enum


class OwnerType(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    UNKNOWN = "UNKNOWN"


class SubjectType(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    UNKNOWN = "UNKNOWN"


class EventType(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"


class RejectReason(str, enum.Enum):
    LIVENESS_FAILED = "liveness_failed"
    BELOW_THRESHOLD = "below_threshold"
    TOO_SMALL = "too_small"


class UnknownStatus(str, enum.Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    VIEWER = "viewer"
