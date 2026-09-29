"""Hand-over-face frames (low quality) must not teach any face template:
not to an unknown cluster, and not to a person when an unknown is linked
or promoted (2026-09-29, UNK-0051)."""
from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy import select

from app.models.employees import Employee
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.security import encrypt_embedding
from app.services.unknown_identity import cluster_or_create_unknown, link_unknown_to_employee, promote_unknown_to_employee

T = dt.datetime(2026, 9, 29, 14, 0, tzinfo=dt.timezone.utc)


def vec(i: int, j: int | None = None) -> list[float]:
    v = np.zeros(512)
    v[i] = 1.0
    if j is not None:
        v[j] = 0.6
    return (v / np.linalg.norm(v)).tolist()


async def _unknown_with(db, qualities: list[float]) -> UnknownIdentity:
    u = UnknownIdentity(face_id="UNK-0051", first_seen_at=T, last_seen_at=T, sighting_count=len(qualities))
    db.add(u)
    await db.flush()
    for k, q in enumerate(qualities):
        e = vec(1, 10 + k)
        db.add(FaceTemplate(owner_type=OwnerType.UNKNOWN, owner_id=u.id, embedding=e, embedding_encrypted=encrypt_embedding(e),
                            quality_score=q, model_version="t"))
    await db.flush()
    return u


async def _templates(db, owner_type, owner_id) -> list[float]:
    rows = (await db.execute(select(FaceTemplate).where(FaceTemplate.owner_type == owner_type,
                                                        FaceTemplate.owner_id == owner_id))).scalars().all()
    return sorted(round(t.quality_score, 2) for t in rows)


async def test_cluster_does_not_learn_from_a_bad_frame(db_session):
    first = await cluster_or_create_unknown(db_session, vec(1), 0.75, None, "t", 0.4, 15, T, min_template_quality=0.5)
    bad = await cluster_or_create_unknown(db_session, vec(1, 20), 0.36, None, "t", 0.4, 15, T + dt.timedelta(minutes=9),
                                          min_template_quality=0.5)
    assert bad.unknown.id == first.unknown.id and bad.unknown.sighting_count == 2
    assert await _templates(db_session, OwnerType.UNKNOWN, first.unknown.id) == [0.75]


async def test_link_adopts_only_good_templates(db_session):
    emp = Employee(face_id="EMP-1", emp_code="E1", name="Bilal")
    db_session.add(emp)
    await db_session.flush()
    u = await _unknown_with(db_session, [0.76, 0.35, 0.41])
    await link_unknown_to_employee(db_session, u, emp, "was me", True, "admin", min_template_quality=0.5)
    assert await _templates(db_session, OwnerType.EMPLOYEE, emp.id) == [0.76]


async def test_promote_drops_bad_templates(db_session):
    u = await _unknown_with(db_session, [0.73, 0.35])
    emp = await promote_unknown_to_employee(db_session, u, "New Person", "E9", None, None, None, "admin",
                                            min_template_quality=0.5)
    assert await _templates(db_session, OwnerType.EMPLOYEE, emp.id) == [0.73]
    assert await _templates(db_session, OwnerType.UNKNOWN, u.id) == []
