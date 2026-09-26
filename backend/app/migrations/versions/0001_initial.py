"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models.base import str_enum
from app.models.enums import EventType, OwnerType, RejectReason, SubjectType, UnknownStatus, UserRole
from app.models.face_templates import EMBEDDING_DIM
from app.models.types import GUID, Vector, new_uuid_str
from app.security import hash_password

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "shifts",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("in_time", sa.Time(), nullable=False),
        sa.Column("out_time", sa.Time(), nullable=False),
        sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "users",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", str_enum(UserRole, "user_role"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "employees",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("face_id", sa.String(20), nullable=False, unique=True),
        sa.Column("emp_code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("department", sa.String(120), nullable=True),
        sa.Column("designation", sa.String(120), nullable=True),
        sa.Column("shift_id", GUID, sa.ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_employees_face_id", "employees", ["face_id"])
    op.create_index("ix_employees_emp_code", "employees", ["emp_code"])
    op.create_index("ix_employees_department", "employees", ["department"])

    op.create_table(
        "consents",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("purpose_text", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
    )
    op.create_index("ix_consents_employee_id", "consents", ["employee_id"])

    op.create_table(
        "unknown_identities",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("face_id", sa.String(20), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sighting_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_crop_path", sa.String(500), nullable=True),
        sa.Column("status", str_enum(UnknownStatus, "unknown_status"), nullable=False),
        sa.Column("resolved_employee_id", GUID, sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_unknown_identities_face_id", "unknown_identities", ["face_id"])
    op.create_index("ix_unknown_identities_status", "unknown_identities", ["status"])

    op.create_table(
        "face_templates",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("owner_type", str_enum(OwnerType, "owner_type"), nullable=False),
        sa.Column("owner_id", GUID, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("embedding_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("source_image_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_face_templates_owner", "face_templates", ["owner_type", "owner_id"])
    op.create_index("ix_face_templates_owner_id", "face_templates", ["owner_id"])

    op.create_table(
        "attendance_events",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("subject_type", str_enum(SubjectType, "subject_type"), nullable=True),
        sa.Column("employee_id", GUID, sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True),
        sa.Column("unknown_identity_id", GUID, sa.ForeignKey("unknown_identities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_type", str_enum(EventType, "event_type"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("liveness_score", sa.Float(), nullable=True),
        sa.Column("kiosk_id", sa.String(100), nullable=False),
        sa.Column("crop_path", sa.String(500), nullable=True),
        sa.Column("reject_reason", str_enum(RejectReason, "reject_reason"), nullable=True),
        sa.Column("is_manual_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("overridden_by", sa.String(255), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("original_employee_id", GUID, nullable=True),
        sa.Column("original_unknown_identity_id", GUID, nullable=True),
        sa.Column("client_event_id", GUID, nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(employee_id IS NOT NULL AND unknown_identity_id IS NULL) OR "
            "(employee_id IS NULL AND unknown_identity_id IS NOT NULL) OR "
            "(employee_id IS NULL AND unknown_identity_id IS NULL "
            " AND reject_reason IN ('liveness_failed', 'too_small'))",
            name="ck_attendance_events_exactly_one_subject",
        ),
    )
    op.create_index("ix_attendance_events_employee_occurred", "attendance_events", ["employee_id", "occurred_at"])
    op.create_index("ix_attendance_events_unknown_occurred", "attendance_events", ["unknown_identity_id", "occurred_at"])
    op.create_index("ix_attendance_events_occurred_at", "attendance_events", ["occurred_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("actor_user_id", GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
    )

    op.create_table(
        "kiosk_heartbeats",
        sa.Column("kiosk_id", sa.String(100), primary_key=True),
        sa.Column("device_json", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    # --- Seed: one default shift + one admin user ---------------------------
    shifts_table = sa.table(
        "shifts",
        sa.column("id", GUID), sa.column("name", sa.String), sa.column("in_time", sa.Time),
        sa.column("out_time", sa.Time), sa.column("grace_minutes", sa.Integer), sa.column("is_default", sa.Boolean),
    )
    import datetime as _dt

    op.bulk_insert(
        shifts_table,
        [
            {
                "id": new_uuid_str(),
                "name": "General Shift",
                "in_time": _dt.time(9, 0, 0),
                "out_time": _dt.time(18, 0, 0),
                "grace_minutes": 15,
                "is_default": True,
            }
        ],
    )

    users_table = sa.table(
        "users",
        sa.column("id", GUID), sa.column("email", sa.String), sa.column("password_hash", sa.String),
        sa.column("role", sa.String), sa.column("created_at", sa.DateTime),
    )
    import datetime as _dt

    op.bulk_insert(
        users_table,
        [
            {
                "id": new_uuid_str(),
                "email": "admin@example.com",
                # Password: "ChangeMe123!" -- CHANGE THIS IMMEDIATELY after
                # first login in any real deployment. See README.
                "password_hash": hash_password("ChangeMe123!"),
                "role": "admin",
                "created_at": _dt.datetime.now(_dt.timezone.utc),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("kiosk_heartbeats")
    op.drop_table("settings")
    op.drop_table("audit_log")
    op.drop_table("attendance_events")
    op.drop_table("face_templates")
    op.drop_table("unknown_identities")
    op.drop_table("consents")
    op.drop_table("employees")
    op.drop_table("users")
    op.drop_table("shifts")
