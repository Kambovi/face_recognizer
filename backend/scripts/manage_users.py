#!/usr/bin/env python
"""Dashboard login users -- list / create / reset password / change role / delete.

Logins can also be managed in the dashboard (Settings -> Users, admin
only); this script is for the server console and for recovery (e.g. the
last admin forgot the password). Run it from the `backend` folder with the backend venv
active (same folder you run uvicorn from, so it uses the same database):

    cd "D:\\DS PROJECTS\\face-attendance\\backend"
    .venv\\Scripts\\Activate.ps1

    python scripts/manage_users.py list
    python scripts/manage_users.py create --email hr@company.com --role viewer
    python scripts/manage_users.py reset-password --email hr@company.com
    python scripts/manage_users.py set-role --email hr@company.com --role admin
    python scripts/manage_users.py delete --email hr@company.com

Passwords are asked interactively (hidden, typed twice) unless --password
is given. Roles:
    admin  -- everything (employees, enrollment, unknowns, settings, users, cameras)
    hr     -- people, leave, holidays, attendance fixes, payroll (no settings/users)
    viewer -- read-only dashboard / analytics, no salaries

The backend does NOT need to be restarted after any of these. Every change
is also written to the audit_log table.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import audit_log  # noqa: E402,F401  (register table)
from app.models.enums import UserRole  # noqa: E402
from app.models.users import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.audit import write_audit  # noqa: E402

from app.services.passwords import password_problem  # noqa: E402


def _ask_password(given: str | None) -> str:
    if given:
        pw = given
    else:
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat password: "):
            sys.exit("ERROR: passwords do not match.")
    problem = password_problem(pw)
    if problem:
        sys.exit(f"ERROR: {problem}.")
    return pw


async def _get_user(db, email: str) -> User:
    user = (await db.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
    if user is None:
        sys.exit(f"ERROR: no user with email {email!r}. Run `list` to see existing users.")
    return user


async def _admin_count(db) -> int:
    return int((await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN))).scalar_one())


async def cmd_list(_args) -> None:
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    if not users:
        print("No users found. (Did you run `alembic upgrade head`? It creates admin@example.com.)")
        return
    print(f"{'EMAIL':40} {'ROLE':8} CREATED")
    for u in users:
        print(f"{u.email:40} {u.role.value:8} {u.created_at:%Y-%m-%d %H:%M}")


async def cmd_create(args) -> None:
    email = args.email.strip().lower()
    if "@" not in email:
        sys.exit("ERROR: --email must be an email address (it is the login name).")
    async with AsyncSessionLocal() as db:
        exists = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
        if exists:
            sys.exit(f"ERROR: {email} already exists. Use reset-password or set-role instead.")
        pw = _ask_password(args.password)
        user = User(email=email, password_hash=hash_password(pw), role=UserRole(args.role))
        db.add(user)
        await db.flush()
        await write_audit(db, None, "user_create_cli", "user", user.id, after={"email": email, "role": args.role})
        await db.commit()
    print(f"OK: created {email} ({args.role}). They can log in at the dashboard now.")


async def cmd_reset_password(args) -> None:
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, args.email)
        pw = _ask_password(args.password)
        user.password_hash = hash_password(pw)
        user.must_change_password = False
        user.locked_until = None
        user.failed_logins = 0
        user.is_active = True
        user.token_version = (user.token_version or 0) + 1
        await write_audit(db, None, "user_password_reset_cli", "user", user.id, after={"email": user.email})
        await db.commit()
    print(f"OK: password changed for {user.email}. Their other open sessions have been logged out.")


async def cmd_set_role(args) -> None:
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, args.email)
        old = user.role.value
        if old == "admin" and args.role != "admin" and await _admin_count(db) <= 1:
            sys.exit("ERROR: this is the last admin -- create another admin first.")
        user.role = UserRole(args.role)
        user.token_version = (user.token_version or 0) + 1
        await write_audit(db, None, "user_role_change_cli", "user", user.id, before={"role": old}, after={"role": args.role})
        await db.commit()
    print(f"OK: {user.email}: {old} -> {args.role}. They have to log in again.")


async def cmd_delete(args) -> None:
    async with AsyncSessionLocal() as db:
        user = await _get_user(db, args.email)
        if user.role == UserRole.ADMIN and await _admin_count(db) <= 1:
            sys.exit("ERROR: refusing to delete the last admin -- you would be locked out.")
        if not args.yes and input(f"Delete {user.email}? Type YES: ") != "YES":
            sys.exit("Cancelled.")
        await write_audit(db, None, "user_delete_cli", "user", user.id, before={"email": user.email, "role": user.role.value})
        await db.delete(user)
        await db.commit()
    print(f"OK: deleted {args.email}. Their open session stops working on the next request.")


def main() -> None:
    p = argparse.ArgumentParser(description="Manage dashboard login users.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show all users")
    c = sub.add_parser("create", help="add a new login")
    c.add_argument("--email", required=True)
    c.add_argument("--role", choices=["admin", "hr", "viewer"], default="viewer")
    c.add_argument("--password", help="skip the prompt (avoid: it stays in shell history)")
    r = sub.add_parser("reset-password", help="set a new password")
    r.add_argument("--email", required=True)
    r.add_argument("--password")
    s = sub.add_parser("set-role", help="make admin / viewer")
    s.add_argument("--email", required=True)
    s.add_argument("--role", choices=["admin", "hr", "viewer"], required=True)
    d = sub.add_parser("delete", help="remove a login")
    d.add_argument("--email", required=True)
    d.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = p.parse_args()

    handler = {
        "list": cmd_list,
        "create": cmd_create,
        "reset-password": cmd_reset_password,
        "set-role": cmd_set_role,
        "delete": cmd_delete,
    }[args.cmd]

    async def run() -> None:
        try:
            await handler(args)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
