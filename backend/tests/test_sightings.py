"""IN / OUT rules (2026-09-29) + the sightings log + 'how many times seen'
chatbot report."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func, select

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import OwnerType
from app.models.face_templates import FaceTemplate
from app.models.sightings import Sighting
from app.models.unknown_identities import UnknownIdentity
from app.schemas.kiosk import KioskEventRequest
from app.security import encrypt_embedding
from app.services.chatbot import engine
from app.services.chatbot.report import build_detection_report, parse_date
from app.services.muster import set_camera_role
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS
from app.services.unknown_identity import link_unknown_to_employee

IST = ZoneInfo("Asia/Kolkata")
CONFIG = dict(DEFAULT_SETTINGS, similarity_threshold=0.3)
DAY = dt.date(2026, 9, 28)
_n = 0


def at(hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime.combine(DAY, dt.time(hh, mm), tzinfo=IST)


async def _person(db, code="E1", name="Asha Rani") -> tuple[Employee, list[float]]:
    emp = Employee(face_id=f"F-{code}", emp_code=code, name=name, created_at=dt.datetime(2026, 1, 1, tzinfo=IST))
    db.add(emp)
    await db.flush()
    vec = np.zeros(512)
    vec[3] = 1.0
    db.add(FaceTemplate(owner_type=OwnerType.EMPLOYEE, owner_id=emp.id, embedding=vec.tolist(),
                        embedding_encrypted=encrypt_embedding(vec.tolist()), quality_score=0.9, model_version="t"))
    await db.flush()
    return emp, vec.tolist()


async def seen(db, vec, when: dt.datetime, kiosk="gate-1", config=CONFIG):
    global _n
    _n += 1
    await process_kiosk_event(db, KioskEventRequest(client_event_id=f"00000000-0000-0000-0000-{_n:012d}", kiosk_id=kiosk,
                                                    occurred_at=when, embedding=vec, liveness_score=0.9), config)


async def in_out(db, emp) -> dict[str, str]:
    evs = (await db.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == emp.id))).scalars().all()
    return {e.event_type.value: e.occurred_at.astimezone(IST).strftime("%H:%M") for e in evs}


async def test_client_bug_0810_then_0835_keeps_entry(db_session, default_shift):
    emp, vec = await _person(db_session)
    await seen(db_session, vec, at(8, 10))
    await seen(db_session, vec, at(8, 35), config=dict(CONFIG, dedupe_window_minutes=60))
    assert await in_out(db_session, emp) == {"IN": "08:10"}
    await seen(db_session, vec, at(13, 0))
    await seen(db_session, vec, at(18, 40))
    await seen(db_session, vec, at(18, 42))
    assert await in_out(db_session, emp) == {"IN": "08:10", "OUT": "18:42"}  # last detection = final exit
    n = (await db_session.execute(select(func.count()).select_from(Sighting))).scalar_one()
    assert n == 5


async def test_min_gap_setting(db_session, default_shift):
    emp, vec = await _person(db_session)
    cfg = dict(CONFIG, min_out_gap_minutes=0)  # "every later detection updates exit"
    await seen(db_session, vec, at(8, 10), config=cfg)
    await seen(db_session, vec, at(8, 35), config=cfg)
    assert await in_out(db_session, emp) == {"IN": "08:10", "OUT": "08:35"}


async def test_entry_and_exit_camera_roles(db_session, default_shift):
    await set_camera_role(db_session, "front-in", "entry")
    await set_camera_role(db_session, "front-out", "exit")
    emp, vec = await _person(db_session)
    await seen(db_session, vec, at(8, 10), "front-in")
    await seen(db_session, vec, at(15, 0), "front-in")    # entry camera again: counted only
    assert await in_out(db_session, emp) == {"IN": "08:10"}
    await seen(db_session, vec, at(9, 0), "front-out")    # exit camera: OUT, no gap needed
    await seen(db_session, vec, at(17, 30), "front-out")
    assert await in_out(db_session, emp) == {"IN": "08:10", "OUT": "17:30"}


async def test_late_replayed_earlier_detection_becomes_in(db_session, default_shift):
    emp, vec = await _person(db_session)
    await seen(db_session, vec, at(8, 30))
    await seen(db_session, vec, at(8, 5))  # offline queue delivered late
    assert await in_out(db_session, emp) == {"IN": "08:05"}


async def test_link_moves_sightings_to_the_person(db_session, default_shift):
    emp, _ = await _person(db_session)
    unk = UnknownIdentity(face_id="UNK-0009", first_seen_at=at(8), last_seen_at=at(8), sighting_count=1)
    db_session.add(unk)
    await db_session.flush()
    ev = AttendanceEvent(subject_type="UNKNOWN", unknown_identity_id=unk.id, event_type="IN", occurred_at=at(8),
                         kiosk_id="gate-1")
    db_session.add(ev)
    await db_session.flush()
    db_session.add(Sighting(occurred_at=at(8), kiosk_id="gate-1", subject_type="UNKNOWN", unknown_identity_id=unk.id,
                            event_id=ev.id))
    await db_session.flush()
    await link_unknown_to_employee(db_session, unk, emp, "was Asha", False, "admin")
    s = (await db_session.execute(select(Sighting))).scalar_one()
    assert s.employee_id == emp.id and s.unknown_identity_id is None


async def test_detection_report_and_chat_flow(db_session, default_shift):
    await set_camera_role(db_session, "office-entry", "entry")
    emp, vec = await _person(db_session, "E7", "Imran Ali")
    for h, m in ((8, 10), (8, 35), (12, 0)):
        await seen(db_session, vec, at(h, m), "office-entry")
    await seen(db_session, vec, at(18, 0), "gate-1")
    rep = await build_detection_report(db_session, "employee", emp.id, "2026-09", "2026-09-28", "office-entry")
    assert rep["rows"] == [{"date": "Mon 28 Sep", "emp_code": "E7", "name": "Imran Ali", "camera": "office-entry",
                            "count": 3, "first": "08:10", "last": "12:00"}]
    assert "seen 3 time(s) at office-entry on 28 Sep 2026" in rep["summary"]
    assert rep["nav"]["prev"]["date"] == "2026-09-27"
    month = await build_detection_report(db_session, "employee", emp.id, "2026-09", None)
    assert sum(r["count"] for r in month["rows"]) == 4

    r = await engine.basic_answer(db_session, "Imran Ali kitni baar office entry camera pr detect hua 28 sep ko")
    c = r["choices"][0]
    assert c["label"] == "Imran Ali" and c["report"] == "detections" and c["date"] == "2026-09-28"
    assert c["camera"] == "office-entry"
    out = await engine.run_action(db_session, c, include_salary=False, mode="basic")
    assert out["report"]["rows"][0]["count"] == 3


def test_parse_date():
    now = dt.date(2026, 9, 29)
    assert parse_date("28 sep ko", now) == "2026-09-28"
    assert parse_date("sep 28", now) == "2026-09-28"
    assert parse_date("28/09", now) == "2026-09-28"
    assert parse_date("aaj", now) == "2026-09-29"
    assert parse_date("kal kitni baar", now) == "2026-09-28"
    assert parse_date("15 dec", now) == "2025-12-15"
    assert parse_date("is mahine", now) is None
