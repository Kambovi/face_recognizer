"""Step 11 -- OFFLINE RESILIENCE.

If the write path to the backend (`POST /api/v1/kiosk/event`) is unreachable
-- network partition, API down, or the Postgres behind it down, all of which
present identically to the kiosk as a failed HTTP call (see
docs/DECISIONS.md) -- events are written to this local SQLite queue instead
of being dropped, and replayed once the path is healthy again. Replay is
idempotent: every event carries a client-generated UUID
(`client_event_id`) that the backend enforces as a uniqueness constraint, so
replaying the same event twice (e.g. a reconnect race) never creates a
duplicate attendance row (NON-NEGOTIABLE #5).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OfflineQueue:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queued_events (
                    client_event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    enqueued_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def enqueue(self, client_event_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO queued_events (client_event_id, payload_json, enqueued_at) "
                "VALUES (?, ?, ?)",
                (client_event_id, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def pending(self) -> list[tuple[str, dict[str, Any]]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT client_event_id, payload_json FROM queued_events ORDER BY enqueued_at"
            ).fetchall()
        return [(cid, json.loads(payload)) for cid, payload in rows]

    def remove(self, client_event_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM queued_events WHERE client_event_id = ?", (client_event_id,))
            conn.commit()

    def mark_attempt(self, client_event_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE queued_events SET attempts = attempts + 1 WHERE client_event_id = ?",
                (client_event_id,),
            )
            conn.commit()

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM queued_events").fetchone()
        return int(n)
