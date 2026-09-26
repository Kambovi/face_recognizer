"""Emergency muster: who is inside the premises right now.

Each camera has a role, set by the client admin (Muster page):
  entry -- people seen here are coming IN
  exit  -- people seen here are going OUT
  both  -- one camera for in and out (default)

For every person (and every unidentified visitor) seen in the last
`muster_window_hours` (default 16h, long enough for a night shift), their
LATEST sighting decides:
  entry camera                 -> inside
  exit camera                  -> left
  both, and it's their first
  sighting (the IN row)        -> inside
  both, a later sighting       -> left (a single camera can't tell "walked
                                  past inside" from "walked out": the page
                                  says so and recommends an exit camera)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.models.unknown_identities import UnknownIdentity
from app.services.settings_service import get_setting, set_setting

CameraRole = Literal["entry", "exit", "both"]
ROLES_KEY = "camera_roles"
MANUAL_KIOSK = "manual"


async def camera_roles(db: AsyncSession) -> dict[str, str]:
    raw = await get_setting(db, ROLES_KEY)
    return {str(k): str(v) for k, v in (raw or {}).items() if v in ("entry", "exit", "both")}


async def set_camera_role(db: AsyncSession, kiosk_id: str, role: CameraRole) -> dict[str, str]:
    roles = await camera_roles(db)
    roles[kiosk_id] = role
    await set_setting(db, ROLES_KEY, roles)
    return roles


def is_inside(event: AttendanceEvent, role: str) -> bool:
    if event.kiosk_id == MANUAL_KIOSK:
        return event.event_type == EventType.IN
    if role == "entry":
        return True
    if role == "exit":
        return False
    return event.event_type == EventType.IN


async def muster(db: AsyncSession, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hours = float(await get_setting(db, "muster_window_hours") or 16)
    since = now - timedelta(hours=hours)
    roles = await camera_roles(db)
    rows = (
        await db.execute(
            select(AttendanceEvent)
            .where(
                AttendanceEvent.occurred_at >= since,
                AttendanceEvent.occurred_at <= now,
                AttendanceEvent.subject_type.is_not(None),
            )
            .order_by(AttendanceEvent.occurred_at)
        )
    ).scalars().all()
    latest: dict[tuple[str, str], AttendanceEvent] = {}
    for e in rows:
        key = ("E", e.employee_id) if e.subject_type == SubjectType.EMPLOYEE else ("U", e.unknown_identity_id)
        if key[1]:
            latest[key] = e  # type: ignore[index]

    emp_ids = [k[1] for k in latest if k[0] == "E"]
    unk_ids = [k[1] for k in latest if k[0] == "U"]
    people = {p.id: p for p in (await db.execute(select(Employee).where(Employee.id.in_(emp_ids)))).scalars()}
    unknowns = {u.id: u for u in (await db.execute(select(UnknownIdentity).where(UnknownIdentity.id.in_(unk_ids)))).scalars()}

    inside: list[dict[str, Any]] = []
    visitors: list[dict[str, Any]] = []
    left = 0
    for (kind, sid), e in latest.items():
        role = roles.get(e.kiosk_id, "both")
        if not is_inside(e, role):
            left += 1
            continue
        if kind == "E":
            p = people.get(sid)
            if p is None or not p.is_active:
                continue
            inside.append({
                "employee_id": p.id, "emp_code": p.emp_code, "name": p.name, "department": p.department,
                "designation": p.designation, "contractor": p.contractor, "last_seen_at": e.occurred_at,
                "last_camera": e.kiosk_id,
                "photo_url": f"/api/v1/media/crop/{e.id}" if e.crop_path else None,
            })
        else:
            u = unknowns.get(sid)
            if u is None or u.status.value == "IGNORED":
                continue
            visitors.append({
                "unknown_id": u.id, "face_id": u.face_id, "label": u.label, "last_seen_at": e.occurred_at,
                "last_camera": e.kiosk_id,
                "photo_url": (f"/api/v1/media/unknown/{u.id}" if u.best_crop_path
                              else f"/api/v1/media/crop/{e.id}" if e.crop_path else None),
            })
    inside.sort(key=lambda r: ((r["department"] or "~"), r["name"]))
    visitors.sort(key=lambda r: r["last_seen_at"], reverse=True)
    seen_cameras = sorted({e.kiosk_id for e in rows if e.kiosk_id != MANUAL_KIOSK} | set(roles))
    return {
        "generated_at": now,
        "window_hours": hours,
        "cameras": [{"kiosk_id": k, "role": roles.get(k, "both")} for k in seen_cameras],
        "has_exit_camera": any(r in ("exit",) for r in roles.values()),
        "inside": inside,
        "visitors_inside": visitors,
        "left_count": left,
    }
