"""Face-photo retention (DPDP: keep personal data only as long as needed).

Every `crop_retention_days` (setting, default 90) old detection photos under
MEDIA_ROOT/events/<date>/ are deleted. Photos still in use are kept: an
enrolled face template's picture or an open unknown person's best photo.
The attendance record itself stays; only its photo goes (crop_path = NULL).
Runs from the API's background loop every 6 hours; 0 = keep forever.
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.attendance_events import AttendanceEvent
from app.models.face_templates import FaceTemplate
from app.models.unknown_identities import UnknownIdentity
from app.services.settings_service import get_all_settings
from app.services.shiftday import LOCAL_TZ

logger = structlog.get_logger(__name__)


async def purge_old_crops(db: AsyncSession, today: date | None = None, days: int | None = None) -> dict[str, int]:
    if days is None:
        cfg = await get_all_settings(db)
        days = int(cfg.get("crop_retention_days") or 0)
    if days <= 0:
        return {"files": 0, "folders": 0}
    today = today or datetime.now(LOCAL_TZ).date()
    cutoff = today - timedelta(days=days)
    keep: set[str] = set()
    for (p,) in (await db.execute(select(FaceTemplate.source_image_path))).all():
        if p:
            keep.add(Path(p).as_posix())
    for (p,) in (await db.execute(select(UnknownIdentity.best_crop_path))).all():
        if p:
            keep.add(Path(p).as_posix())

    root = get_settings().media_root_path
    events = root / "events"
    files = folders = 0
    if events.is_dir():
        for day_dir in sorted(events.iterdir()):
            try:
                d = date.fromisoformat(day_dir.name)
            except ValueError:
                continue
            if d >= cutoff or not day_dir.is_dir():
                continue
            kept_any = False
            for f in day_dir.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(root).as_posix()
                if rel in keep:
                    kept_any = True
                    continue
                f.unlink(missing_ok=True)
                files += 1
            if not kept_any:
                shutil.rmtree(day_dir, ignore_errors=True)
                folders += 1
    cutoff_dt = datetime.combine(cutoff, datetime.min.time(), tzinfo=LOCAL_TZ)
    stmt = update(AttendanceEvent).where(AttendanceEvent.occurred_at < cutoff_dt, AttendanceEvent.crop_path.is_not(None))
    if keep:
        stmt = stmt.where(AttendanceEvent.crop_path.not_in(keep))
    await db.execute(stmt.values(crop_path=None))
    await db.commit()
    if files:
        logger.info("crop_retention_purged", files=files, folders=folders, older_than=cutoff.isoformat())
    return {"files": files, "folders": folders}


def delete_employee_photos(employee_id: str) -> None:
    folder = get_settings().media_root_path / "employees" / employee_id
    if folder.is_dir() and folder.resolve().is_relative_to(get_settings().media_root_path.resolve()):
        shutil.rmtree(folder, ignore_errors=True)


async def retention_loop(session_factory: Any) -> None:  # pragma: no cover - timing loop
    while True:
        try:
            async with session_factory() as db:
                await purge_old_crops(db)
        except Exception as exc:  # noqa: BLE001 - never kill the API
            logger.warning("crop_retention_failed", error=str(exc)[:200])
        await asyncio.sleep(6 * 3600)
