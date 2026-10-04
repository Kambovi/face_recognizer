"""Import every model module so `Base.metadata` (used by Alembic autogenerate
and by the SQLite test bootstrap in app.db.init_models_for_tests) sees all
tables."""
from app.models.alerts import Alert  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.attendance_events import AttendanceEvent  # noqa: F401
from app.models.consents import Consent  # noqa: F401
from app.models.edge import EdgeDetection, EdgeOutbox  # noqa: F401
from app.models.employees import Employee  # noqa: F401
from app.models.face_templates import FaceTemplate  # noqa: F401
from app.models.holidays import Holiday  # noqa: F401
from app.models.kiosk_devices import KioskDevice  # noqa: F401
from app.models.kiosk_heartbeats import KioskHeartbeat  # noqa: F401
from app.models.leave_openings import LeaveOpening  # noqa: F401
from app.models.leaves import Leave  # noqa: F401
from app.models.payroll import EmployeePayroll, PayrollAdjustment, PayrollRun, Payslip  # noqa: F401
from app.models.settings import Setting  # noqa: F401
from app.models.shift_assignments import ShiftAssignment  # noqa: F401
from app.models.sightings import Sighting  # noqa: F401
from app.models.sites import Site  # noqa: F401
from app.models.shifts import Shift  # noqa: F401
from app.models.unknown_identities import UnknownIdentity  # noqa: F401
from app.models.users import User  # noqa: F401

__all__ = [
    "Alert",
    "AuditLog",
    "AttendanceEvent",
    "Consent",
    "EdgeDetection",
    "EdgeOutbox",
    "Employee",
    "FaceTemplate",
    "Holiday",
    "KioskDevice",
    "KioskHeartbeat",
    "Leave",
    "LeaveOpening",
    "EmployeePayroll",
    "PayrollAdjustment",
    "PayrollRun",
    "Payslip",
    "Setting",
    "Shift",
    "ShiftAssignment",
    "Sighting",
    "Site",
    "UnknownIdentity",
    "User",
]
