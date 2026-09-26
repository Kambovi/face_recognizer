"""Raise alerts for watchlisted people / faces and spoof attempts.

Cool-downs stop one person standing at a camera from raising 30 alerts: a
watchlisted subject raises at most one alert per `alert_cooldown_minutes`,
spoof attempts at most one per camera per `spoof_alert_cooldown_minutes`.
Every new alert is also handed to the notifier (WhatsApp, if configured).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import Alert
from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.unknown_identities import UnknownIdentity

logger = structlog.get_logger(__name__)


async def _recent(db: AsyncSession, since: datetime, **match: Any) -> bool:
    q = select(Alert.id).where(Alert.created_at >= since)
    for col, val in match.items():
        q = q.where(getattr(Alert, col) == val)
    return (await db.execute(q.limit(1))).first() is not None


async def on_event(
    db: AsyncSession,
    event: AttendanceEvent,
    config: dict[str, Any],
    *,
    employee: Employee | None = None,
    unknown: UnknownIdentity | None = None,
) -> Alert | None:
    alert: Alert | None = None
    if employee is not None and employee.watchlist_reason:
        since = event.occurred_at - timedelta(minutes=float(config.get("alert_cooldown_minutes", 30)))
        if not await _recent(db, since, kind="watchlist", employee_id=employee.id):
            alert = Alert(
                kind="watchlist", kiosk_id=event.kiosk_id, employee_id=employee.id, event_id=event.id,
                title=f"Watchlist: {employee.name} ({employee.emp_code}) at {event.kiosk_id}",
                detail=employee.watchlist_reason,
            )
    elif unknown is not None and unknown.watchlist_reason:
        since = event.occurred_at - timedelta(minutes=float(config.get("alert_cooldown_minutes", 30)))
        if not await _recent(db, since, kind="watchlist", unknown_identity_id=unknown.id):
            alert = Alert(
                kind="watchlist", kiosk_id=event.kiosk_id, unknown_identity_id=unknown.id, event_id=event.id,
                title=f"Watchlist: {unknown.label or unknown.face_id} at {event.kiosk_id}",
                detail=unknown.watchlist_reason,
            )
    elif (
        event.subject_type is None
        and event.reject_reason is not None
        and event.reject_reason.value == "liveness_failed"
        and event.liveness_score is not None  # None = model missing (fail-closed), not an attack
        and bool(config.get("alert_on_spoof", True))
    ):
        since = event.occurred_at - timedelta(minutes=float(config.get("spoof_alert_cooldown_minutes", 10)))
        if not await _recent(db, since, kind="spoof", kiosk_id=event.kiosk_id):
            alert = Alert(
                kind="spoof", kiosk_id=event.kiosk_id, event_id=event.id,
                title=f"Possible photo / screen held up at {event.kiosk_id}",
                detail=f"Liveness score {event.liveness_score:.2f}",
            )
    if alert is None:
        return None
    alert.created_at = event.occurred_at
    db.add(alert)
    await db.flush()
    logger.info("alert_raised", kind=alert.kind, kiosk_id=alert.kiosk_id)
    try:
        from app.services.notify import notify_alert

        await notify_alert(db, alert, config)
    except Exception as exc:  # noqa: BLE001 - a notification failure must never lose the event
        logger.warning("alert_notify_failed", exception_type=type(exc).__name__)
    return alert
