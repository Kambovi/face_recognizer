"""Human-readable, zero-padded, monotonic id generation: EMP-0042, UNK-0007."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.models.unknown_identities import UnknownIdentity

_SUFFIX_RE = re.compile(r"-(\d+)$")


async def _max_suffix(db: AsyncSession, model, column, prefix: str) -> int:
    result = await db.execute(select(column).where(column.like(f"{prefix}-%")))
    max_n = 0
    for (face_id,) in result:
        m = _SUFFIX_RE.search(face_id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n


async def next_employee_face_id(db: AsyncSession) -> str:
    n = await _max_suffix(db, Employee, Employee.face_id, "EMP")
    return f"EMP-{n + 1:04d}"


async def next_unknown_face_id(db: AsyncSession) -> str:
    n = await _max_suffix(db, UnknownIdentity, UnknownIdentity.face_id, "UNK")
    return f"UNK-{n + 1:04d}"
