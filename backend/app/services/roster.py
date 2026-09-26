"""Who belongs where: department validation against the locked client profile,
and the per-camera licence cap ("max 200 people per camera")."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import http_error
from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.kiosk_heartbeats import KioskHeartbeat
from app.services.client_profile import get_profile

ONLINE_WINDOW = timedelta(minutes=5)


async def active_count_at(db: AsyncSession, kiosk_id: str, exclude_employee_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(Employee).where(
        Employee.home_kiosk_id == kiosk_id, Employee.is_active.is_(True), Employee.deleted_at.is_(None)
    )
    if exclude_employee_id:
        stmt = stmt.where(Employee.id != exclude_employee_id)
    return int((await db.execute(stmt)).scalar_one())


async def validate_assignment(
    db: AsyncSession,
    *,
    department: str | None,
    home_kiosk_id: str | None,
    will_be_active: bool = True,
    employee_id: str | None = None,
    department_changed: bool = True,
    camera_changed: bool = True,
) -> None:
    """Raise a 422 if the department isn't one of the client's configured ones,
    or if the target camera is already at its licensed capacity."""
    profile = await get_profile(db)
    departments: list[str] = profile.get("departments") or []
    if department_changed and department and departments and department not in departments:
        raise http_error(
            422, "unknown_department",
            f"'{department}' is not a configured {profile['department_label'].lower()}. "
            f"Choose one of: {', '.join(departments)}",
        )
    if camera_changed and home_kiosk_id and will_be_active:
        cap = int(profile.get("max_enrolled_per_camera") or 0)
        if cap > 0 and await active_count_at(db, home_kiosk_id, exclude_employee_id=employee_id) >= cap:
            raise http_error(
                422, "camera_full",
                f"Camera '{home_kiosk_id}' already has {cap} active {profile['person_label_plural'].lower()} "
                f"(licence limit). Assign another camera or deactivate someone first.",
            )


def liveness_state(device_json: dict[str, Any] | None) -> str:
    """'on' / 'off' from the kiosk's last heartbeat; 'unknown' for kiosks
    older than the 2026-09-26 liveness fix (they don't report it)."""
    info = (device_json or {}).get("liveness")
    if not isinstance(info, dict):
        return "unknown"
    return "on" if info.get("available") else "off"


async def camera_overview(db: AsyncSession) -> list[dict[str, Any]]:
    """Every known camera with how many people are enrolled at it vs the cap."""
    profile = await get_profile(db)
    cap = int(profile.get("max_enrolled_per_camera") or 0)
    heartbeats = {h.kiosk_id: h for h in (await db.execute(select(KioskHeartbeat))).scalars().all()}
    event_kiosks = {k for (k,) in (await db.execute(select(AttendanceEvent.kiosk_id).distinct())).all()}
    enrolled_rows = (
        await db.execute(
            select(Employee.home_kiosk_id, func.count())
            .where(Employee.home_kiosk_id.is_not(None), Employee.is_active.is_(True), Employee.deleted_at.is_(None))
            .group_by(Employee.home_kiosk_id)
        )
    ).all()
    enrolled = {k: int(n) for k, n in enrolled_rows}
    now = datetime.now(timezone.utc)
    out = []
    event_kiosks.discard("manual")  # hand-entered IN/OUT rows, not a camera
    for kiosk_id in sorted(set(heartbeats) | event_kiosks | set(enrolled)):
        hb = heartbeats.get(kiosk_id)
        online = False
        if hb is not None:
            seen = hb.last_seen_at if hb.last_seen_at.tzinfo else hb.last_seen_at.replace(tzinfo=timezone.utc)
            online = now - seen < ONLINE_WINDOW
        out.append({
            "kiosk_id": kiosk_id,
            "enrolled": enrolled.get(kiosk_id, 0),
            "cap": cap,
            "online": online,
            "liveness": liveness_state(hb.device_json if hb is not None else None),
        })
    return out
