"""NON-NEGOTIABLE #3: liveness cannot be bypassed -- test proving failed
liveness produces zero recognition (1:N matching) calls.

The kiosk never even embeds a face whose liveness check failed (see
kiosk/kiosk/pipeline.py), so by the time an event reaches the backend,
`payload.embedding` is None and `reject_reason='liveness_failed'`. This test
proves that code path at the point that matters most: even if a mock/buggy
kiosk somehow posted a liveness_failed event, app/services/recognition.py
must still never call into `matching.search_templates`."""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

from app.schemas.kiosk import KioskEventRequest
from app.services.recognition import process_kiosk_event
from app.services.settings_service import DEFAULT_SETTINGS


async def test_liveness_failed_event_never_calls_matching(db_session):
    payload = KioskEventRequest(
        client_event_id="33333333-3333-3333-3333-333333333333",
        kiosk_id="kiosk-1",
        occurred_at=dt.datetime.now(dt.timezone.utc),
        embedding=None,
        liveness_score=0.12,
        reject_reason="liveness_failed",
    )

    with patch("app.services.recognition.matching.search_templates", new_callable=AsyncMock) as mock_search:
        outcome = await process_kiosk_event(db_session, payload, dict(DEFAULT_SETTINGS))
        mock_search.assert_not_called()

    assert outcome.event.reject_reason.value == "liveness_failed"
    assert outcome.event.employee_id is None
    assert outcome.event.unknown_identity_id is None
    assert outcome.face_id is None


async def test_too_small_event_also_never_calls_matching(db_session):
    payload = KioskEventRequest(
        client_event_id="44444444-4444-4444-4444-444444444444",
        kiosk_id="kiosk-1",
        occurred_at=dt.datetime.now(dt.timezone.utc),
        embedding=None,
        reject_reason="too_small",
    )
    with patch("app.services.recognition.matching.search_templates", new_callable=AsyncMock) as mock_search:
        await process_kiosk_event(db_session, payload, dict(DEFAULT_SETTINGS))
        mock_search.assert_not_called()


async def test_passing_liveness_with_an_embedding_does_call_matching(db_session):
    """Sanity check for the test above: when liveness passes (or is
    disabled) and an embedding IS present, matching MUST run -- otherwise
    the previous two tests would be vacuously true."""
    payload = KioskEventRequest(
        client_event_id="55555555-5555-5555-5555-555555555555",
        kiosk_id="kiosk-1",
        occurred_at=dt.datetime.now(dt.timezone.utc),
        embedding=[0.01] * 512,
        liveness_score=0.99,
    )
    with patch("app.services.recognition.matching.search_templates", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []
        await process_kiosk_event(db_session, payload, dict(DEFAULT_SETTINGS))
        # Called at least once (employee search; falls through to an unknown-
        # cluster search too since the mock returns no matches) -- the point
        # here is just that it's called at all, unlike the liveness-failed case.
        assert mock_search.called
