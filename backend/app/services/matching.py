"""Step 7 -- 1:N SIMILARITY SEARCH against face_templates.

On Postgres this runs (almost) literally the SQL given in the spec, letting
pgvector's `<=>` cosine-distance operator do the nearest-neighbor search in
the database. SQLite (used only by the test suite, see app/db.py) has no
pgvector extension, so the same function computes cosine distance in Python
instead against the small in-memory fixture -- correctness-identical for
test-sized data, never used in production (app/db.py's `is_postgres`/dialect
check is the one and only branch point).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate


@dataclass
class MatchRow:
    owner_id: str
    similarity: float


def _to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)


async def search_templates(
    db: AsyncSession, owner_type: OwnerType, query_embedding: list[float], limit: int = 5
) -> list[MatchRow]:
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"

    if dialect == "postgresql":
        sql = text(
            """
            SELECT owner_id, 1 - (embedding <=> CAST(:q AS vector)) AS similarity
            FROM face_templates
            WHERE owner_type = :owner_type
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :limit
            """
        )
        result = await db.execute(
            sql,
            {
                "q": _to_pgvector_literal(query_embedding),
                "owner_type": owner_type.value,
                "limit": limit,
            },
        )
        return [MatchRow(owner_id=row.owner_id, similarity=float(row.similarity)) for row in result]

    # SQLite fallback (tests only): same semantics, computed in Python.
    result = await db.execute(select(FaceTemplate).where(FaceTemplate.owner_type == owner_type))
    templates = result.scalars().all()
    q = np.asarray(query_embedding, dtype=np.float64)
    scored = [
        MatchRow(owner_id=t.owner_id, similarity=_cosine_similarity(q, np.asarray(t.embedding, dtype=np.float64)))
        for t in templates
    ]
    scored.sort(key=lambda r: r.similarity, reverse=True)
    return scored[:limit]


def top_unique_owners(rows: list[MatchRow], limit: int = 5) -> list[MatchRow]:
    """De-duplicated view of `search_templates` results (an owner can appear
    more than once since it may have up to 5 templates) -- used by the
    Correction Modal's "top-5 nearest matches" UI."""
    seen: dict[str, float] = {}
    for row in rows:
        if row.owner_id not in seen or row.similarity > seen[row.owner_id]:
            seen[row.owner_id] = row.similarity
    ordered = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
    return [MatchRow(owner_id=oid, similarity=sim) for oid, sim in ordered[:limit]]
