"""Import every model module so `Base.metadata` (used by Alembic autogenerate
and by the SQLite test bootstrap in app.db.init_models_for_tests) sees all
tables."""
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.attendance_events import AttendanceEvent  # noqa: F401
from app.models.consents import Consent  # noqa: F401
from app.models.employees import Employee  # noqa: F401
from app.models.face_templates import FaceTemplate  # noqa: F401
from app.models.kiosk_heartbeats import KioskHeartbeat  # noqa: F401
from app.models.settings import Setting  # noqa: F401
from app.models.shifts import Shift  # noqa: F401
from app.models.unknown_identities import UnknownIdentity  # noqa: F401
from app.models.users import User  # noqa: F401

__all__ = [
    "AuditLog",
    "AttendanceEvent",
    "Consent",
    "Employee",
    "FaceTemplate",
    "KioskHeartbeat",
    "Setting",
    "Shift",
    "UnknownIdentity",
    "User",
]
