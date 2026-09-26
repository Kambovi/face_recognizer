"""Step 1b -- SCENE-CHANGE / NEW-PERSON GATE.

Motion alone is not enough: a person standing still and fidgeting produces
motion for seconds at a time. This module implements the three ordered
checks from the spec, split into two phases because of where they sit in the
pipeline:

  * `check_pre_embedding` runs checks 1 (track continuity) and 2 (bounding
    box IoU) right after detection, BEFORE the expensive best-shot buffering
    / liveness / embedding work -- both checks only need the detected box,
    so there's no reason to pay for embedding to make this call.
  * `check_embedding` runs check 3 (embedding similarity against the recent
    ring buffer) AFTER an embedding has been computed, but before the 1:N
    Postgres search / any DB write ("skip before writing anything"). This is
    the safety net for when track continuity breaks (e.g. a brief occlusion
    assigns a new track id) but the face is actually the same recently-seen
    person.

Call `record_processed(...)` once a face has actually been sent onward, to
update the track/ring-buffer state that later frames are compared against.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

Box = tuple[float, float, float, float]  # x1, y1, x2, y2

# A track with no matching detection for this long is considered "left the
# frame" -- the next detection near the same spot starts a NEW track, which
# is exactly the "left and re-entered" re-processing rule.
TRACK_TIMEOUT_SECONDS = 2.0


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1, inter_y1 = max(ax1, bx1), max(ay1, by1)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)


@dataclass
class SubjectGateConfig:
    iou_same_subject: float = 0.85
    dedupe_window_minutes: float = 5.0
    same_person_threshold: float = 0.90
    recent_embedding_buffer: int = 5


@dataclass
class _Track:
    track_id: str
    box: Box
    last_seen: float
    recognized: bool = False


@dataclass
class GateDecision:
    process: bool
    reason: str | None
    track_id: str | None = None
    is_new_track: bool = False


@dataclass
class _RingEntry:
    embedding: np.ndarray
    timestamp: float


class SubjectGate:
    def __init__(self, config: SubjectGateConfig | None = None) -> None:
        self.config = config or SubjectGateConfig()
        self._tracks: dict[str, _Track] = {}
        self._last_processed_box: Box | None = None
        self._last_processed_time: float = 0.0
        self._ring: deque[_RingEntry] = deque(maxlen=self.config.recent_embedding_buffer)

    # -- track bookkeeping ----------------------------------------------

    def _evict_stale(self, now: float) -> None:
        stale = [tid for tid, t in self._tracks.items() if now - t.last_seen > TRACK_TIMEOUT_SECONDS]
        for tid in stale:
            del self._tracks[tid]

    def _match_or_create_track(self, box: Box, now: float) -> tuple[str, bool]:
        best_id, best_iou = None, 0.0
        for tid, t in self._tracks.items():
            score = iou(box, t.box)
            if score > best_iou:
                best_id, best_iou = tid, score

        if best_id is not None and best_iou >= self.config.iou_same_subject:
            track = self._tracks[best_id]
            track.box = box
            track.last_seen = now
            return best_id, False

        new_id = str(uuid.uuid4())
        self._tracks[new_id] = _Track(track_id=new_id, box=box, last_seen=now)
        return new_id, True

    # -- checks 1 & 2 ------------------------------------------------------

    def check_pre_embedding(self, box: Box, now: float | None = None) -> GateDecision:
        now = time.monotonic() if now is None else now
        self._evict_stale(now)
        track_id, is_new_track = self._match_or_create_track(box, now)
        track = self._tracks[track_id]

        # Check 1: track continuity -- an already-recognised, still-present
        # track needs no further work at all.
        if not is_new_track and track.recognized:
            return GateDecision(process=False, reason="track_continuity", track_id=track_id)

        # Check 2: bounding-box IoU against the last *processed* face, within
        # the dedupe window.
        if self._last_processed_box is not None:
            gap_minutes = (now - self._last_processed_time) / 60.0
            if (
                gap_minutes < self.config.dedupe_window_minutes
                and iou(box, self._last_processed_box) > self.config.iou_same_subject
            ):
                track.recognized = True
                return GateDecision(process=False, reason="iou_same_subject", track_id=track_id)

        return GateDecision(process=True, reason=None, track_id=track_id, is_new_track=is_new_track)

    # -- check 3 -------------------------------------------------------------

    def check_embedding(self, embedding: np.ndarray, now: float | None = None) -> GateDecision:
        now = time.monotonic() if now is None else now
        window_seconds = self.config.dedupe_window_minutes * 60.0
        best_sim = 0.0
        for entry in self._ring:
            if now - entry.timestamp > window_seconds:
                continue
            best_sim = max(best_sim, cosine_similarity(embedding, entry.embedding))

        if best_sim > self.config.same_person_threshold:
            return GateDecision(process=False, reason="embedding_similarity")

        # Below threshold against everything recent -> genuine new subject,
        # process immediately even if within the dedupe window of someone else.
        return GateDecision(process=True, reason=None)

    # -- state update after a subject is actually processed -------------------

    def record_processed(self, box: Box, embedding: np.ndarray | None, track_id: str | None, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._last_processed_box = box
        self._last_processed_time = now
        # `embedding` is None for rejects that never reached the embedding
        # step (too_small, liveness_failed) -- there is no real embedding to
        # compare future visitors against, so skip the ring buffer entirely
        # rather than push a placeholder in. (A 0-d nan placeholder used to
        # be pushed here; check_embedding's cosine_similarity() would then
        # broadcast against it and raise TypeError the next time the ring was
        # scanned -- a real crash bug, fixed by this guard.)
        if embedding is not None:
            self._ring.append(_RingEntry(embedding=np.asarray(embedding, dtype=np.float64), timestamp=now))
        if track_id and track_id in self._tracks:
            self._tracks[track_id].recognized = True
            self._tracks[track_id].box = box
            self._tracks[track_id].last_seen = now
