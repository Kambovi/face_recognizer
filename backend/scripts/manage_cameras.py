#!/usr/bin/env python
"""Cameras (kiosks / entry points) -- list them, rename one.

A camera's name is its KIOSK_ID: the kiosk process sends it with every
event and heartbeat, and it is what the dashboard's "Entry point" filter
shows. Renaming therefore has TWO halves:

  1. this script  -> renames the old id to the new id in the database, so
                     past attendance stays under the new name;
  2. you          -> start that camera's kiosk with the new KIOSK_ID
                     ($env:KIOSK_ID="new-name") from now on.

Run from the `backend` folder with the backend venv active:

    python scripts/manage_cameras.py list
    python scripts/manage_cameras.py rename --old kiosk-01 --new main-gate --dry-run
    python scripts/manage_cameras.py rename --old kiosk-01 --new main-gate

Safe order for a rename:  stop that kiosk (Ctrl+C) -> run rename ->
set $env:KIOSK_ID to the new name -> start the kiosk again.
If the kiosk had events stuck in its offline queue while you renamed, they
arrive later under the OLD name; just run the same rename again.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.models import audit_log  # noqa: E402,F401  (register table)
from app.models.attendance_events import AttendanceEvent  # noqa: E402
from app.models.kiosk_heartbeats import KioskHeartbeat  # noqa: E402
from app.services.audit import write_audit  # noqa: E402

LOCAL_TZ_NOTE = "times shown in your PC's local time"
VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def _local(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "-"


async def cmd_list(_args) -> None:
    async with AsyncSessionLocal() as db:
        ev_rows = (
            await db.execute(
                select(
                    AttendanceEvent.kiosk_id,
                    func.count(),
                    func.min(AttendanceEvent.occurred_at),
                    func.max(AttendanceEvent.occurred_at),
                ).group_by(AttendanceEvent.kiosk_id)
            )
        ).all()
        hb = {h.kiosk_id: h for h in (await db.execute(select(KioskHeartbeat))).scalars().all()}

    stats = {k: (n, first, last) for k, n, first, last in ev_rows}
    ids = sorted(set(stats) | set(hb))
    if not ids:
        print("No cameras yet. A camera appears here after its kiosk sends its first heartbeat or event.")
        return
    now = datetime.now(timezone.utc)
    print(f"{'CAMERA (KIOSK_ID)':28} {'EVENTS':>7}  {'FIRST EVENT':16}  {'LAST EVENT':16}  STATUS ({LOCAL_TZ_NOTE})")
    for k in ids:
        n, first, last = stats.get(k, (0, None, None))
        h = hb.get(k)
        if h is None:
            status = "no heartbeat (old/renamed id?)"
        else:
            last_seen = h.last_seen_at if h.last_seen_at.tzinfo else h.last_seen_at.replace(tzinfo=timezone.utc)
            status = ("ONLINE" if now - last_seen < timedelta(minutes=5) else "offline") + f", last heartbeat {_local(last_seen)}"
        print(f"{k:28} {n:>7}  {_local(first):16}  {_local(last):16}  {status}")


async def cmd_rename(args) -> None:
    old, new = args.old.strip(), args.new.strip()
    if not VALID_ID.match(new):
        sys.exit("ERROR: new name may use letters, digits, '-', '_' and '.' only (no spaces), max 100 chars.")
    if old == new:
        sys.exit("ERROR: old and new names are the same.")

    async with AsyncSessionLocal() as db:
        n_events = int(
            (await db.execute(select(func.count()).select_from(AttendanceEvent).where(AttendanceEvent.kiosk_id == old))).scalar_one()
        )
        old_hb = (await db.execute(select(KioskHeartbeat).where(KioskHeartbeat.kiosk_id == old))).scalar_one_or_none()
        new_hb = (await db.execute(select(KioskHeartbeat).where(KioskHeartbeat.kiosk_id == new))).scalar_one_or_none()
        new_events = int(
            (await db.execute(select(func.count()).select_from(AttendanceEvent).where(AttendanceEvent.kiosk_id == new))).scalar_one()
        )

        if n_events == 0 and old_hb is None:
            sys.exit(f"ERROR: no camera called {old!r}. Run `list` to see the exact names.")

        print(f"'{old}' -> '{new}': {n_events} attendance events, heartbeat row: {'yes' if old_hb else 'no'}")
        if new_events or new_hb:
            print(f"NOTE: '{new}' already exists ({new_events} events) -- the two cameras' history will be MERGED under '{new}'.")

        if old_hb is not None:
            seen = old_hb.last_seen_at if old_hb.last_seen_at.tzinfo else old_hb.last_seen_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - seen < timedelta(minutes=2):
                print("WARNING: this kiosk sent a heartbeat in the last 2 minutes -- it is probably still RUNNING with the old")
                print("         KIOSK_ID and will re-create the old name. Stop it first (Ctrl+C in its terminal).")

        if args.dry_run:
            print("Dry run -- nothing changed.")
            return
        if not args.yes and input("Proceed? Type YES: ") != "YES":
            sys.exit("Cancelled.")

        await db.execute(update(AttendanceEvent).where(AttendanceEvent.kiosk_id == old).values(kiosk_id=new))
        if old_hb is not None:
            if new_hb is None:
                db.add(KioskHeartbeat(kiosk_id=new, device_json=old_hb.device_json, last_seen_at=old_hb.last_seen_at))
            await db.delete(old_hb)
        await write_audit(db, None, "camera_rename_cli", "kiosk", new, before={"kiosk_id": old}, after={"kiosk_id": new, "events": n_events})
        await db.commit()

    print(f"OK: renamed. Now start that camera's kiosk with:  $env:KIOSK_ID=\"{new}\"")
    print("Old face-crop JPEGs stay in their old folders on disk; the database still points at them, so photos keep working.")


def main() -> None:
    p = argparse.ArgumentParser(description="List / rename cameras (kiosk ids).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show every camera with event counts and online status")
    r = sub.add_parser("rename", help="rename a camera id everywhere in the database")
    r.add_argument("--old", required=True)
    r.add_argument("--new", required=True)
    r.add_argument("--dry-run", action="store_true", help="only show what would change")
    r.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = p.parse_args()

    handler = {"list": cmd_list, "rename": cmd_rename}[args.cmd]

    async def run() -> None:
        try:
            await handler(args)
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
