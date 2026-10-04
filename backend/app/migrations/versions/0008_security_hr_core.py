"""security + HR core: user lockout / forced password change / token
version / HR role, per-camera tokens, holidays, joining + leaving dates,
per-person weekly off, leave types + half-day leave.

Revision ID: 0008_security_hr_core
Revises: 0007_sightings
Create Date: 2026-10-04

"""
from __future__ import annotations

import datetime as _dt
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, UTCDateTime

revision: str = "0008_security_hr_core"
down_revision: Union[str, None] = "0007_sightings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_PASSWORDS = ("ChangeMe123!",)


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("name", sa.String(120), nullable=True))
        b.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("locked_until", UTCDateTime(), nullable=True))
        b.add_column(sa.Column("last_login_at", UTCDateTime(), nullable=True))
        b.add_column(sa.Column("password_changed_at", UTCDateTime(), nullable=True))

    # Anyone still on the published default password must change it at next login.
    conn = op.get_bind()
    for uid, pw_hash in conn.execute(sa.text("SELECT id, password_hash FROM users")).fetchall():
        for default in DEFAULT_PASSWORDS:
            try:
                if bcrypt.checkpw(default.encode(), str(pw_hash).encode()):
                    conn.execute(sa.text("UPDATE users SET must_change_password = :t WHERE id = :id"),
                                 {"t": True, "id": uid})
            except ValueError:
                pass

    with op.batch_alter_table("employees") as b:
        b.add_column(sa.Column("date_of_joining", sa.Date(), nullable=True))
        b.add_column(sa.Column("date_of_leaving", sa.Date(), nullable=True))
        b.add_column(sa.Column("weekly_off_days", sa.JSON(), nullable=True))

    with op.batch_alter_table("leaves") as b:
        b.add_column(sa.Column("leave_type", sa.String(20), nullable=True))
        b.add_column(sa.Column("portion", sa.Float(), nullable=False, server_default="1"))

    op.create_table(
        "holidays",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="festival"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("day", name="uq_holidays_day"),
    )
    op.create_index("ix_holidays_day", "holidays", ["day"])

    op.create_table(
        "kiosk_devices",
        sa.Column("id", GUID, primary_key=True),
        sa.Column("kiosk_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.UniqueConstraint("kiosk_id", name="uq_kiosk_devices_kiosk_id"),
        sa.UniqueConstraint("token_hash", name="uq_kiosk_devices_token_hash"),
    )
    op.create_index("ix_kiosk_devices_kiosk_id", "kiosk_devices", ["kiosk_id"])
    op.create_index("ix_kiosk_devices_token_hash", "kiosk_devices", ["token_hash"])

    # Go-live date: days before the system was installed are "not tracked"
    # (paid), not absent. = the day the first person was added.
    first = conn.execute(sa.text("SELECT MIN(created_at) FROM employees")).scalar()
    exists = conn.execute(sa.text("SELECT 1 FROM settings WHERE key = 'attendance_start_date'")).scalar()
    if first is not None and not exists:
        if isinstance(first, str):
            first = _dt.datetime.fromisoformat(first.replace("Z", "+00:00").split(".")[0])
        day = (first.replace(tzinfo=first.tzinfo or _dt.timezone.utc)
               .astimezone(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).date().isoformat())
        settings = sa.table("settings", sa.column("key", sa.String), sa.column("value_json", sa.JSON),
                            sa.column("updated_at", UTCDateTime()))
        cols = {c["name"] for c in sa.inspect(conn).get_columns("settings")}
        row = {"key": "attendance_start_date", "value_json": day}
        if "updated_at" in cols:
            row["updated_at"] = _dt.datetime.now(_dt.timezone.utc)
        op.bulk_insert(settings, [row])


def downgrade() -> None:
    op.drop_index("ix_kiosk_devices_token_hash", table_name="kiosk_devices")
    op.drop_index("ix_kiosk_devices_kiosk_id", table_name="kiosk_devices")
    op.drop_table("kiosk_devices")
    op.drop_index("ix_holidays_day", table_name="holidays")
    op.drop_table("holidays")
    with op.batch_alter_table("leaves") as b:
        b.drop_column("portion")
        b.drop_column("leave_type")
    with op.batch_alter_table("employees") as b:
        b.drop_column("weekly_off_days")
        b.drop_column("date_of_leaving")
        b.drop_column("date_of_joining")
    with op.batch_alter_table("users") as b:
        for c in ("password_changed_at", "last_login_at", "locked_until", "failed_logins",
                  "token_version", "must_change_password", "is_active", "name"):
            b.drop_column(c)
