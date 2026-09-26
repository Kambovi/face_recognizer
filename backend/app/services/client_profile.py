"""Client profile -- the one-time, vendor-locked setup of an installation.

Set ONCE by the vendor while installing at a client (scripts/setup_client.py),
then frozen: the client's own admins can read it but cannot change it -- not
from the UI, not via PATCH /settings (the key isn't a tunable), and not by
re-running the setup script without the vendor PIN chosen at install time.

It carries:
  * the sector (business / school / hospital) -> UI theme + wording
    ("Employee" vs "Student" vs "Staff", "Department" vs "Class" ...)
  * the organisation name shown in the header / login page
  * the fixed list of departments (or classes / wards) people can belong to
  * the per-camera licence cap (max active people whose home camera is one
    entry point; 200 by default)

Stored as one JSON row in the existing `settings` table under the key
`client_profile` (no schema change needed); `settings_service.get_all_settings`
hides every `client_*` key so it never shows up among the tunables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting

PROFILE_KEY = "client_profile"
OrgType = Literal["business", "school", "hospital"]
DEFAULT_CAMERA_CAP = 200

# Wording per sector. Every label the UI shows for "a person on the roster".
PRESETS: dict[str, dict[str, str]] = {
    "business": {
        "person_label": "Employee",
        "person_label_plural": "Employees",
        "id_label": "Emp ID",
        "department_label": "Department",
        "department_label_plural": "Departments",
        "designation_label": "Designation",
    },
    "school": {
        "person_label": "Student",
        "person_label_plural": "Students",
        "id_label": "Roll No",
        "department_label": "Class",
        "department_label_plural": "Classes",
        "designation_label": "Section / Role",
    },
    "hospital": {
        "person_label": "Staff member",
        "person_label_plural": "Staff",
        "id_label": "Staff ID",
        "department_label": "Department",
        "department_label_plural": "Departments",
        "designation_label": "Designation",
    },
}

# Used until the vendor runs setup: behaves exactly like the product did before.
UNCONFIGURED: dict[str, Any] = {
    "configured": False,
    "org_type": "business",
    "org_name": "Face Attendance",
    "departments": [],
    "max_enrolled_per_camera": DEFAULT_CAMERA_CAP,
    **PRESETS["business"],
}


def public_view(stored: dict[str, Any] | None) -> dict[str, Any]:
    """What the API returns -- never the vendor PIN hash."""
    if not stored:
        return dict(UNCONFIGURED)
    org_type = stored.get("org_type", "business")
    view = {**UNCONFIGURED, **PRESETS.get(org_type, PRESETS["business"])}
    for key in ("org_type", "org_name", "departments", "max_enrolled_per_camera", "setup_at"):
        if key in stored:
            view[key] = stored[key]
    for key in PRESETS["business"]:  # optional per-client wording overrides
        if stored.get(key):
            view[key] = stored[key]
    view["configured"] = True
    return view


async def load_raw(db: AsyncSession) -> dict[str, Any] | None:
    row = (await db.execute(select(Setting).where(Setting.key == PROFILE_KEY))).scalar_one_or_none()
    return dict(row.value_json) if row is not None else None


async def get_profile(db: AsyncSession) -> dict[str, Any]:
    return public_view(await load_raw(db))


async def save_raw(db: AsyncSession, profile: dict[str, Any]) -> None:
    profile = {**profile, "updated_at": datetime.now(timezone.utc).isoformat()}
    row = (await db.execute(select(Setting).where(Setting.key == PROFILE_KEY))).scalar_one_or_none()
    if row is None:
        db.add(Setting(key=PROFILE_KEY, value_json=profile))
    else:
        row.value_json = profile
    await db.flush()
