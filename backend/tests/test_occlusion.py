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


# ---- server-side guard: unclear / near-miss faces never become unknown people
from app.models.sightings import Sighting  # noqa: E402
from app.schemas.kiosk import KioskEventRequest  # noqa: E402
from app.services.recognition import process_kiosk_event  # noqa: E402
from app.services.settings_service import DEFAULT_SETTINGS  # noqa: E402

_i = 0


async def _post(db, embedding, quality):
    global _i
    _i += 1
    return await process_kiosk_event(db, KioskEventRequest(
        client_event_id=f"00000000-0000-0000-0000-{_i:012d}", kiosk_id="exit-gate", occurred_at=T,
        embedding=embedding, quality_score=quality, liveness_score=0.95), dict(DEFAULT_SETTINGS))


async def test_covered_face_of_an_employee_is_not_an_unknown(db_session):
    emp = Employee(face_id="EMP-2", emp_code="E2", name="Bilal")
    db_session.add(emp)
    await db_session.flush()
    e = vec(1)
    db_session.add(FaceTemplate(owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=e,
                                embedding_encrypted=encrypt_embedding(e), quality_score=0.8, model_version="t"))
    await db_session.flush()
    v = np.zeros(512)
    v[1], v[30] = 0.35, (1 - 0.35**2) ** 0.5  # cos = 0.35: below the 0.38 match, above the 0.30 near-match
    out = await _post(db_session, v.tolist(), 0.8)
    assert out.event is None
    out = await _post(db_session, vec(200), 0.4)  # nobody's face, but a poor frame
    assert out.event is None
    assert (await db_session.execute(select(UnknownIdentity))).first() is None
    rows = (await db_session.execute(select(Sighting))).scalars().all()
    assert len(rows) == 2 and all(r.employee_id is None and r.unknown_identity_id is None for r in rows)
    out = await _post(db_session, vec(300), 0.8)  # a clear stranger still becomes UNK
    assert out.event is not None and out.event.unknown_identity_id is not None


async def test_kiosk_endpoint_accepts_the_unclear_outcome(client, db_session):
    from app.config import get_settings

    r = await client.post("/api/v1/kiosk/event", headers={"Authorization": f"Bearer {get_settings().kiosk_service_token}"},
                          json={"client_event_id": "00000000-0000-0000-0000-00000000abcd", "kiosk_id": "k",
                                "occurred_at": T.isoformat(), "embedding": vec(5), "quality_score": 0.3,
                                "liveness_score": 0.9})
    assert r.status_code == 200 and r.json()["event_id"] is None
