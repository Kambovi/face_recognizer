"""Watchlist + spoof alerts raised from kiosk events, with cool-downs."""
from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy import select

from app.models.alerts import Alert
from app.models.employees import Employee
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.schemas.kiosk import KioskEventRequest
from app.security import encrypt_embedding
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS

CONFIG = dict(DEFAULT_SETTINGS, similarity_threshold=0.3)
T0 = dt.datetime(2026, 9, 26, 5, 0, tzinfo=dt.timezone.utc)


async def _enrolled(db, code: str, reason: str | None, active: bool = False) -> tuple[Employee, list[float]]:
    emp = Employee(face_id=f"F-{code}", emp_code=code, name=f"Name {code}", watchlist_reason=reason, is_active=active)
    db.add(emp)
    await db.flush()
    vec = np.zeros(512)
    vec[len(code)] = 1.0
    db.add(FaceTemplate(owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=vec.tolist(),
                        embedding_encrypted=encrypt_embedding(vec.tolist()), quality_score=0.9, model_version="t"))
    await db.flush()
    return emp, vec.tolist()


def _ev(i: int, minutes: float, emb: list[float] | None, **kw) -> KioskEventRequest:
    return KioskEventRequest(client_event_id=f"c{i}", kiosk_id="gate", occurred_at=T0 + dt.timedelta(minutes=minutes),
                             embedding=emb, **kw)


async def test_watchlisted_person_raises_one_alert_per_cooldown(db_session):
    emp, vec = await _enrolled(db_session, "BAN", "Dismissed 2026-09-01, not allowed inside")
    await process_kiosk_event(db_session, _ev(1, 0, vec, liveness_score=0.9), CONFIG)
    await process_kiosk_event(db_session, _ev(2, 10, vec, liveness_score=0.9), CONFIG)   # within 30 min
    await process_kiosk_event(db_session, _ev(3, 45, vec, liveness_score=0.9), CONFIG)   # after cool-down
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert len(alerts) == 2
    assert alerts[0].kind == "watchlist" and alerts[0].employee_id == emp.id
    assert "Dismissed" in (alerts[0].detail or "")


async def test_normal_people_raise_nothing(db_session):
    _, vec = await _enrolled(db_session, "OK", None, active=True)
    await process_kiosk_event(db_session, _ev(1, 0, vec, liveness_score=0.9), CONFIG)
    assert (await db_session.execute(select(Alert))).first() is None


async def test_inactive_person_seen_raises_an_alert(db_session):
    emp, vec = await _enrolled(db_session, "LEFT", None, active=False)
    await process_kiosk_event(db_session, _ev(1, 0, vec, liveness_score=0.9), CONFIG)
    await process_kiosk_event(db_session, _ev(2, 5, vec, liveness_score=0.9), CONFIG)  # cool-down
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert [a.kind for a in alerts] == ["inactive_seen"] and alerts[0].employee_id == emp.id


async def test_spoof_alert_but_not_for_missing_model(db_session):
    await process_kiosk_event(db_session, _ev(1, 0, None, liveness_score=0.1, reject_reason="liveness_failed"), CONFIG)
    await process_kiosk_event(db_session, _ev(2, 2, None, liveness_score=0.2, reject_reason="liveness_failed"), CONFIG)
    await process_kiosk_event(db_session, _ev(3, 30, None, liveness_score=None, reject_reason="liveness_failed"), CONFIG)
    alerts = (await db_session.execute(select(Alert))).scalars().all()
    assert [a.kind for a in alerts] == ["spoof"]


async def test_alert_api_count_ack_and_watchlist(client, admin_headers, db_session):
    emp, vec = await _enrolled(db_session, "W1", "Theft case")
    await process_kiosk_event(db_session, _ev(1, 0, vec, liveness_score=0.9), CONFIG)
    assert (await client.get("/api/v1/alerts/count", headers=admin_headers)).json()["open"] == 1
    items = (await client.get("/api/v1/alerts?open_only=true", headers=admin_headers)).json()
    assert items[0]["photo_url"].startswith("/api/v1/media/crop/")
    r = await client.post(f"/api/v1/alerts/{items[0]['id']}/ack", headers=admin_headers)
    assert r.json()["acknowledged_by"] == "admin@example.org"
    assert (await client.get("/api/v1/alerts/count", headers=admin_headers)).json()["open"] == 0
    wl = (await client.get("/api/v1/alerts/watchlist", headers=admin_headers)).json()
    assert wl[0]["reason"] == "Theft case"
    r = await client.patch(f"/api/v1/employees/{emp.id}", headers=admin_headers, json={"watchlist_reason": ""})
    assert r.status_code == 200 and r.json()["watchlist_reason"] is None
