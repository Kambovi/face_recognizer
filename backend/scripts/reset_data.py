#!/usr/bin/env python
"""Clear data from the database -- safely (always takes a backup first).

Run from the `backend` folder with the backend venv active, AFTER stopping
the backend and the kiosk (the script refuses if a camera pinged in the last
2 minutes, because a running system would keep writing while we delete):

    python scripts/reset_data.py show                 # just print counts

    python scripts/reset_data.py attendance           # all attendance history +
                                                      # unknown faces; KEEPS people
    python scripts/reset_data.py attendance --before 2026-10-01
                                                      # only history before a date

    python scripts/reset_data.py people               # every enrolled person, their
                                                      # face photos and attendance
    python scripts/reset_data.py people --codes EMP0001 EMP0002
    python scripts/reset_data.py people --code-like "EMP0%"   # SQL LIKE pattern

    python scripts/reset_data.py all                  # attendance + people
                                                      # (= fresh install)

Always KEPT: login users, settings/thresholds, the vendor client profile
(sector, departments, camera cap), shifts, camera list, audit log.

Options:
    --yes           don't ask to type DELETE (for scripted use)
    --purge-media   also delete the face-crop JPEGs that belonged to the deleted
                    rows (files still referenced by remaining rows are kept)
    --no-backup     skip the backup (NOT recommended)
    --force-running run even though a camera looks online

Backups go to backend/backups/<db-name>-<timestamp>.db. To undo a reset:
stop the backend, copy the backup over dev.db, start the backend.
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.models.attendance_events import AttendanceEvent  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.consents import Consent  # noqa: E402
from app.models.employees import Employee  # noqa: E402
from app.models.enums import OwnerType  # noqa: E402
from app.models.face_templates import FaceTemplate  # noqa: E402
from app.models.kiosk_heartbeats import KioskHeartbeat  # noqa: E402
from app.models.unknown_identities import UnknownIdentity  # noqa: E402
from app.services.audit import write_audit  # noqa: E402

ONLINE_WINDOW = timedelta(minutes=2)


# ---------------------------------------------------------------- helpers
def _sqlite_path() -> Path | None:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def backup_sqlite(db_path: Path) -> Path:
    """Consistent copy via SQLite's online-backup API (safe even mid-write)."""
    out_dir = db_path.parent / "backups"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"{db_path.stem}-{stamp}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def vacuum_sqlite(db_path: Path) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("VACUUM")
    finally:
        con.close()


def _local_midnight_utc(d: date) -> datetime:
    tz = ZoneInfo(get_settings().app_timezone)
    return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)


async def _count(db, model, *where) -> int:
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return int((await db.execute(q)).scalar_one())


async def counts(db) -> dict[str, int]:
    return {
        "people (active)": await _count(db, Employee, Employee.is_active.is_(True)),
        "people (all)": await _count(db, Employee),
        "person face templates": await _count(db, FaceTemplate, FaceTemplate.owner_type == OwnerType.EMPLOYEE),
        "attendance events": await _count(db, AttendanceEvent),
        "unknown faces": await _count(db, UnknownIdentity),
        "unknown face templates": await _count(db, FaceTemplate, FaceTemplate.owner_type == OwnerType.UNKNOWN),
        "audit log rows": await _count(db, AuditLog),
    }


def _print_counts(title: str, c: dict[str, int]) -> None:
    print(title)
    for k, v in c.items():
        print(f"  {k:<24} {v}")


# ---------------------------------------------------------------- deleters
# Each returns the media paths (relative to MEDIA_ROOT) that belonged to the
# deleted rows, so --purge-media can remove the files afterwards.
async def _paths(db, stmt) -> set[str]:
    return {p for (p,) in (await db.execute(stmt)).all() if p}


async def clear_attendance(db, before: date | None) -> set[str]:
    ev_where = []
    if before is not None:
        ev_where.append(AttendanceEvent.occurred_at < _local_midnight_utc(before))

    paths = await _paths(db, select(AttendanceEvent.crop_path).where(*ev_where))
    await db.execute(delete(AttendanceEvent).where(*ev_where))

    # Unknown faces: all of them for a full clear; with --before only the ones
    # that no longer have any sighting left.
    unk_q = select(UnknownIdentity.id, UnknownIdentity.best_crop_path)
    if before is not None:
        still_seen = select(AttendanceEvent.unknown_identity_id).where(AttendanceEvent.unknown_identity_id.is_not(None))
        unk_q = unk_q.where(UnknownIdentity.id.not_in(still_seen))
    unk_rows = (await db.execute(unk_q)).all()
    unk_ids = [r[0] for r in unk_rows]
    paths |= {r[1] for r in unk_rows if r[1]}
    for i in range(0, len(unk_ids), 500):
        chunk = unk_ids[i : i + 500]
        tpl = (FaceTemplate.owner_type == OwnerType.UNKNOWN) & FaceTemplate.owner_id.in_(chunk)
        paths |= await _paths(db, select(FaceTemplate.source_image_path).where(tpl))
        await db.execute(delete(FaceTemplate).where(tpl))
        await db.execute(delete(UnknownIdentity).where(UnknownIdentity.id.in_(chunk)))
    return paths


async def clear_people(db, codes: list[str] | None, code_like: str | None) -> set[str]:
    q = select(Employee.id)
    if codes:
        q = q.where(Employee.emp_code.in_(codes))
    if code_like:
        q = q.where(Employee.emp_code.like(code_like))
    ids = [r[0] for r in (await db.execute(q)).all()]
    paths: set[str] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        tpl = (FaceTemplate.owner_type == OwnerType.EMPLOYEE) & FaceTemplate.owner_id.in_(chunk)
        paths |= await _paths(db, select(FaceTemplate.source_image_path).where(tpl))
        paths |= await _paths(db, select(AttendanceEvent.crop_path).where(AttendanceEvent.employee_id.in_(chunk)))
        await db.execute(delete(FaceTemplate).where(tpl))
        # SQLite doesn't enforce ON DELETE CASCADE unless PRAGMA foreign_keys is
        # on, so delete children explicitly instead of relying on it.
        await db.execute(
            delete(AttendanceEvent).where(
                or_(AttendanceEvent.employee_id.in_(chunk), AttendanceEvent.original_employee_id.in_(chunk))
            )
        )
        await db.execute(delete(Consent).where(Consent.employee_id.in_(chunk)))
        await db.execute(
            update(UnknownIdentity)
            .where(UnknownIdentity.resolved_employee_id.in_(chunk))
            .values(resolved_employee_id=None)
        )
        await db.execute(delete(Employee).where(Employee.id.in_(chunk)))
    return paths


async def still_referenced(db) -> set[str]:
    refs = await _paths(db, select(AttendanceEvent.crop_path))
    refs |= await _paths(db, select(UnknownIdentity.best_crop_path))
    refs |= await _paths(db, select(FaceTemplate.source_image_path))
    return refs


def purge_media(paths: set[str]) -> tuple[int, int]:
    root = Path(get_settings().media_root).resolve()
    removed = missing = 0
    for rel in paths:
        p = (root / rel.replace("\\", "/")).resolve()
        if root not in p.parents:  # never touch anything outside MEDIA_ROOT
            continue
        try:
            p.unlink()
            removed += 1
        except FileNotFoundError:
            missing += 1
    return removed, missing


# ---------------------------------------------------------------- main
async def run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        before_counts = await counts(db)
        if args.mode == "show":
            _print_counts("Current data:", before_counts)
            return 0

        last_ping = (await db.execute(select(func.max(KioskHeartbeat.last_seen_at)))).scalar_one_or_none()
        if last_ping is not None and not args.force_running:
            if last_ping.tzinfo is None:
                last_ping = last_ping.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_ping < ONLINE_WINDOW:
                print("A camera pinged the server less than 2 minutes ago -- the system looks RUNNING.")
                print("Stop the kiosk and the backend first, then run this again (or pass --force-running).")
                return 2

    _print_counts("Current data:", before_counts)
    what = {
        "attendance": "ALL attendance history and unknown faces" if not args.before
        else f"attendance history before {args.before} (and unknown faces seen only then)",
        "people": "the selected people, their face photos and their attendance" if (args.codes or args.code_like)
        else "EVERY enrolled person, their face photos and their attendance",
        "all": "ALL attendance history, unknown faces AND all enrolled people (fresh install)",
    }[args.mode]
    print(f"\nThis will delete: {what}.")
    print("Kept: users/logins, settings, client profile, shifts, cameras, audit log.")
    if not args.yes and input('Type DELETE to continue: ').strip() != "DELETE":
        print("Cancelled. Nothing was changed.")
        return 1

    db_path = _sqlite_path()
    if not args.no_backup:
        if db_path is None:
            print("Not a SQLite database: take a pg_dump backup yourself, then re-run with --no-backup.")
            return 2
        print(f"Backup saved: {backup_sqlite(db_path)}")

    async with AsyncSessionLocal() as db:
        paths: set[str] = set()
        if args.mode in ("people", "all"):
            paths |= await clear_people(db, args.codes, args.code_like)
        if args.mode in ("attendance", "all"):
            paths |= await clear_attendance(db, args.before)
        after_counts = await counts(db)
        await write_audit(
            db, None, "data_reset", "database", args.mode,
            before=before_counts,
            after={**after_counts, "before_date": str(args.before) if args.before else None},
        )
        await db.commit()
        orphaned = paths - await still_referenced(db)

    await engine.dispose()
    if db_path is not None:
        vacuum_sqlite(db_path)

    _print_counts("\nDone. Data now:", after_counts)
    if args.purge_media:
        removed, missing = purge_media(orphaned)
        print(f"Media: deleted {removed} image file(s) ({missing} were already gone).")
    elif orphaned:
        print(f"{len(orphaned)} image file(s) in MEDIA_ROOT are no longer used (re-run with --purge-media to delete).")
    print("Start the backend and kiosk again.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Safely clear data (auto-backup first).")
    ap.add_argument("mode", choices=["show", "attendance", "people", "all"])
    ap.add_argument("--before", type=date.fromisoformat, help="attendance: only delete before this date (YYYY-MM-DD)")
    ap.add_argument("--codes", nargs="+", help="people: only these IDs (emp code / roll no)")
    ap.add_argument("--code-like", help='people: SQL LIKE pattern on the ID, e.g. "EMP0%%"')
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--purge-media", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--force-running", action="store_true")
    args = ap.parse_args()
    if args.before and args.mode != "attendance":
        ap.error("--before only works with the 'attendance' mode")
    if (args.codes or args.code_like) and args.mode != "people":
        ap.error("--codes / --code-like only work with the 'people' mode")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
