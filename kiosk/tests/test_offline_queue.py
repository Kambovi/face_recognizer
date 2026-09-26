"""Unit tests for kiosk/offline_queue.py (spec step 11: offline resilience).
Complements backend/tests/test_nn5_offline_replay.py, which tests idempotency
on the server side (the unique `client_event_id` constraint); these tests
cover the kiosk-local SQLite queue itself."""
from __future__ import annotations

from pathlib import Path

import pytest

from kiosk.offline_queue import OfflineQueue


@pytest.fixture
def queue(tmp_path: Path) -> OfflineQueue:
    return OfflineQueue(str(tmp_path / "nested" / "offline_events.db"))


def test_creates_parent_directories(tmp_path: Path):
    path = tmp_path / "a" / "b" / "c" / "queue.db"
    assert not path.parent.exists()
    OfflineQueue(str(path))
    assert path.exists()


def test_enqueue_then_pending_round_trips_payload(queue: OfflineQueue):
    payload = {"client_event_id": "evt-1", "embedding": [0.1, 0.2, 0.3]}
    queue.enqueue("evt-1", payload)

    pending = queue.pending()
    assert len(pending) == 1
    cid, stored_payload = pending[0]
    assert cid == "evt-1"
    assert stored_payload == payload


def test_enqueue_is_idempotent_on_client_event_id(queue: OfflineQueue):
    """`INSERT OR IGNORE` on the primary key -- re-enqueuing the same
    client_event_id (e.g. a retry race) must never duplicate a row."""
    payload = {"client_event_id": "evt-1", "n": 1}
    queue.enqueue("evt-1", payload)
    queue.enqueue("evt-1", {"client_event_id": "evt-1", "n": 2})  # different payload, same id

    assert queue.count() == 1
    _, stored = queue.pending()[0]
    assert stored["n"] == 1  # first write wins; OR IGNORE never overwrites


def test_pending_orders_by_enqueued_at(queue: OfflineQueue):
    queue.enqueue("evt-1", {"seq": 1})
    queue.enqueue("evt-2", {"seq": 2})
    queue.enqueue("evt-3", {"seq": 3})

    ordered = [payload["seq"] for _cid, payload in queue.pending()]
    assert ordered == [1, 2, 3]


def test_remove_deletes_the_row(queue: OfflineQueue):
    queue.enqueue("evt-1", {})
    assert queue.count() == 1
    queue.remove("evt-1")
    assert queue.count() == 0
    assert queue.pending() == []


def test_remove_nonexistent_id_is_a_noop(queue: OfflineQueue):
    queue.remove("does-not-exist")  # must not raise
    assert queue.count() == 0


def test_mark_attempt_increments_attempts_without_affecting_pending(queue: OfflineQueue):
    queue.enqueue("evt-1", {"x": 1})
    queue.mark_attempt("evt-1")
    queue.mark_attempt("evt-1")

    with queue._connect() as conn:  # internal access is fine for a white-box test
        (attempts,) = conn.execute(
            "SELECT attempts FROM queued_events WHERE client_event_id = ?", ("evt-1",)
        ).fetchone()
    assert attempts == 2
    assert len(queue.pending()) == 1  # still pending -- marking an attempt doesn't remove it


def test_count_reflects_multiple_enqueues_and_removals(queue: OfflineQueue):
    for i in range(5):
        queue.enqueue(f"evt-{i}", {"i": i})
    assert queue.count() == 5

    queue.remove("evt-2")
    assert queue.count() == 4


def test_queue_survives_reopening_the_same_path(tmp_path: Path):
    """A kiosk restart must not lose queued events -- reopening the same
    sqlite file (a new OfflineQueue instance) sees prior rows."""
    path = str(tmp_path / "queue.db")
    q1 = OfflineQueue(path)
    q1.enqueue("evt-1", {"survives": True})

    q2 = OfflineQueue(path)
    pending = q2.pending()
    assert len(pending) == 1
    assert pending[0][1]["survives"] is True
