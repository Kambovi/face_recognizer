#!/usr/bin/env python
"""VENDOR-ONLY: one-time client setup (sector theme, wording, departments, camera cap).

Run this ONCE while installing the product at a client. It locks the profile
with a vendor PIN that only your company keeps. After that the client's
admins can see the profile but can't change it -- any later change (e.g.
the client pays for a new department or a bigger camera limit) needs the PIN.

Run from the `backend` folder with the backend venv active:

    python scripts/setup_client.py show

    python scripts/setup_client.py init --type school --name "St. Mary's School" \\
        --departments "Class 1-A" "Class 1-B" "Class 2-A" "Staff"

    python scripts/setup_client.py update --add-department "Class 3-A"
    python scripts/setup_client.py update --remove-department "Class 1-B"
    python scripts/setup_client.py update --camera-cap 300
    python scripts/setup_client.py update --name "St. Mary's Senior School"

--type is one of: business, school, hospital (sets the UI theme and words
like Employee / Student / Staff). The PIN is asked interactively (hidden);
`init` asks for it twice. Pass --pin only in scripted installs.

The backend does NOT need a restart; users see the change on next page load.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import audit_log  # noqa: E402,F401  (register table)
from app.models.employees import Employee  # noqa: E402
from app.security import hash_password, verify_password  # noqa: E402
from app.services.audit import write_audit  # noqa: E402
from app.services.client_profile import DEFAULT_CAMERA_CAP, PRESETS, load_raw, public_view, save_raw  # noqa: E402

MIN_PIN_LEN = 6


def _ask_pin(given: str | None, confirm: bool) -> str:
    pin = given or getpass.getpass("Vendor PIN: ")
    if confirm and not given and pin != getpass.getpass("Repeat vendor PIN: "):
        sys.exit("ERROR: PINs do not match.")
    if len(pin) < MIN_PIN_LEN:
        sys.exit(f"ERROR: vendor PIN must be at least {MIN_PIN_LEN} characters.")
    return pin


def _clean(names: list[str] | None) -> list[str]:
    out: list[str] = []
    for n in names or []:
        n = n.strip()
        if n and n not in out:
            out.append(n)
    return out


def _print(profile: dict) -> None:
    view = public_view(profile)
    if not view["configured"]:
        print("NOT CONFIGURED yet -- the product runs with the default business wording.")
        print("Run: python scripts/setup_client.py init --type <business|school|hospital> --name \"...\"")
        return
    print(f"Organisation : {view['org_name']}")
    print(f"Sector       : {view['org_type']}  (people are called '{view['person_label_plural']}')")
    print(f"Camera cap   : {view['max_enrolled_per_camera']} active {view['person_label_plural'].lower()} per camera")
    label = view["department_label_plural"]
    deps = view["departments"]
    print(f"{label:13}: {len(deps)}" + ("" if deps else "  (none -- any value allowed)"))
    for d in deps:
        print(f"   - {d}")
    print(f"Locked since : {view.get('setup_at', '?')}")


async def cmd_show(_args) -> None:
    async with AsyncSessionLocal() as db:
        _print(await load_raw(db) or {})


async def cmd_init(args) -> None:
    async with AsyncSessionLocal() as db:
        if await load_raw(db):
            sys.exit("ERROR: this installation is already set up and locked. Use `update` (needs the vendor PIN).")
        pin = _ask_pin(args.pin, confirm=True)
        profile = {
            "org_type": args.type,
            "org_name": args.name.strip(),
            "departments": _clean(args.departments),
            "max_enrolled_per_camera": args.camera_cap,
            "vendor_pin_hash": hash_password(pin),
            "setup_at": datetime.now(timezone.utc).isoformat(),
        }
        await save_raw(db, profile)
        await write_audit(db, None, "client_setup_init", "client_profile", "global", after=public_view(profile))
        await db.commit()
    print("OK: client profile saved and LOCKED.\n")
    _print(profile)
    print("\nKeep the vendor PIN with your company -- the client must not have it.")


async def cmd_update(args) -> None:
    async with AsyncSessionLocal() as db:
        profile = await load_raw(db)
        if not profile:
            sys.exit("ERROR: not set up yet -- run `init` first.")
        pin = _ask_pin(args.pin, confirm=False)
        if not verify_password(pin, profile.get("vendor_pin_hash", "")):
            await write_audit(db, None, "client_setup_denied", "client_profile", "global", after={"reason": "bad_pin"})
            await db.commit()
            sys.exit("ERROR: wrong vendor PIN. Nothing changed.")

        before = public_view(profile)
        deps: list[str] = list(profile.get("departments") or [])
        for d in _clean(args.add_department):
            if d not in deps:
                deps.append(d)
        for d in _clean(args.remove_department):
            if d not in deps:
                sys.exit(f"ERROR: '{d}' is not in the list.")
            in_use = (await db.execute(
                select(func.count()).select_from(Employee).where(
                    Employee.department == d, Employee.is_active.is_(True), Employee.deleted_at.is_(None)
                )
            )).scalar_one()
            if in_use and not args.force:
                sys.exit(f"ERROR: {in_use} active people are in '{d}'. Move them first, or add --force.")
            deps.remove(d)
        profile["departments"] = deps
        if args.name:
            profile["org_name"] = args.name.strip()
        if args.type:
            profile["org_type"] = args.type
        if args.camera_cap is not None:
            profile["max_enrolled_per_camera"] = args.camera_cap
        await save_raw(db, profile)
        await write_audit(db, None, "client_setup_update", "client_profile", "global", before=before, after=public_view(profile))
        await db.commit()
    print("OK: updated.\n")
    _print(profile)


def main() -> None:
    p = argparse.ArgumentParser(description="VENDOR-ONLY one-time client setup.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the current client profile")

    i = sub.add_parser("init", help="first-time setup (locks the profile)")
    i.add_argument("--type", required=True, choices=sorted(PRESETS))
    i.add_argument("--name", required=True, help="organisation name shown in the app")
    i.add_argument("--departments", nargs="*", help="departments / classes / wards")
    i.add_argument("--camera-cap", type=int, default=DEFAULT_CAMERA_CAP, help="max active people per camera")
    i.add_argument("--pin", help="vendor PIN (avoid: stays in shell history)")

    u = sub.add_parser("update", help="change a locked profile (needs the vendor PIN)")
    u.add_argument("--type", choices=sorted(PRESETS))
    u.add_argument("--name")
    u.add_argument("--add-department", nargs="*")
    u.add_argument("--remove-department", nargs="*")
    u.add_argument("--camera-cap", type=int)
    u.add_argument("--force", action="store_true", help="remove a department even if people are in it")
    u.add_argument("--pin")
    args = p.parse_args()

    handler = {"show": cmd_show, "init": cmd_init, "update": cmd_update}[args.cmd]

    async def run() -> None:
        try:
            await handler(args)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
