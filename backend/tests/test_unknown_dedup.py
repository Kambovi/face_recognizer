"""Duplicate-unknown fix (2026-09-25): one real person was split into dozens of
UNK- ids. Covers the three changes in services/unknown_identity.py:
looser cluster threshold, same-camera temporal prior, diverse templates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from app.models.attendance_events import AttendanceEvent
from app.models.enums import EventType, SubjectType
from app.services.settings_service import DEFAULT_SETTINGS
from app.services.unknown_identity import cluster_or_create_unknown

T0 = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def _unit(v: np.ndarray) -> list[float]:
    return (v / np.linalg.norm(v)).tolist()


def _pair_with_similarity(sim: float, seed: int = 0) -> tuple[list[float], list[float]]:
    rng = np.random.default_rng(seed)
    a = rng.standard_normal(512)
    a /= np.linalg.norm(a)
    noise = rng.standard_normal(512)
    noise -= noise.dot(a) * a
    noise /= np.linalg.norm(noise)
    b = sim * a + np.sqrt(1 - sim**2) * noise
    return a.tolist(), _unit(b)


async def _cluster(db, emb, at, **kw):
    params = dict(
        quality_score=0.8, crop_path=None, model_version="buffalo_l",
        unknown_cluster_threshold=DEFAULT_SETTINGS["unknown_cluster_threshold"],
        unknown_max_templates=DEFAULT_SETTINGS["unknown_max_templates"],
        occurred_at=at, kiosk_id="gate-1",
        recent_window_seconds=DEFAULT_SETTINGS["unknown_recent_window_seconds"],
        recent_threshold=DEFAULT_SETTINGS["unknown_recent_threshold"],
    )
    params.update(kw)
    r = await cluster_or_create_unknown(db, emb, **params)
    db.add(AttendanceEvent(subject_type=SubjectType.UNKNOWN, unknown_identity_id=r.unknown.id,
                           event_type=EventType.IN, occurred_at=at, kiosk_id=params["kiosk_id"]))
    await db.flush()
    return r


def test_cluster_threshold_is_not_stricter_than_employee_threshold():
    assert DEFAULT_SETTINGS["unknown_cluster_threshold"] <= DEFAULT_SETTINGS["similarity_threshold"] + 0.05


async def test_same_person_at_moderate_similarity_is_one_identity(db_session):
    a, b = _pair_with_similarity(0.45)
    first = await _cluster(db_session, a, T0)
    second = await _cluster(db_session, b, T0 + timedelta(hours=3))  # cold match, no temporal help
    assert first.created and not second.created
    assert second.unknown.id == first.unknown.id


async def test_same_camera_moments_later_uses_lower_threshold(db_session):
    a, b = _pair_with_similarity(0.33, seed=1)
    first = await _cluster(db_session, a, T0)
    soon = await _cluster(db_session, b, T0 + timedelta(seconds=40))
    assert soon.unknown.id == first.unknown.id


async def test_temporal_prior_does_not_apply_across_cameras_or_after_window(db_session):
    a, b = _pair_with_similarity(0.33, seed=2)
    first = await _cluster(db_session, a, T0)
    other_cam = await _cluster(db_session, b, T0 + timedelta(seconds=40), kiosk_id="gate-2")
    assert other_cam.created and other_cam.unknown.id != first.unknown.id

    c, d = _pair_with_similarity(0.33, seed=3)
    x = await _cluster(db_session, c, T0 + timedelta(hours=5))
    later = await _cluster(db_session, d, T0 + timedelta(hours=5, minutes=10))
    assert later.created and later.unknown.id != x.unknown.id


async def test_different_people_stay_separate(db_session):
    a, b = _pair_with_similarity(0.10, seed=4)
    first = await _cluster(db_session, a, T0)
    second = await _cluster(db_session, b, T0 + timedelta(seconds=20))
    assert second.created and second.unknown.id != first.unknown.id


async def test_near_identical_sightings_do_not_fill_template_slots(db_session):
    from sqlalchemy import func, select

    from app.models.face_templates import FaceTemplate

    a, _ = _pair_with_similarity(0.5, seed=5)
    r = None
    for i in range(6):
        r = await _cluster(db_session, a, T0 + timedelta(minutes=i))
    count = (await db_session.execute(
        select(func.count()).select_from(FaceTemplate).where(FaceTemplate.owner_id == r.unknown.id)
    )).scalar_one()
    assert count == 1
    assert r.unknown.sighting_count == 6
