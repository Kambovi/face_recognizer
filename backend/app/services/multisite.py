"""Multi-site: several factories / branches, one head-office view.

Every site runs its own install (cameras stay on the local network, works
offline). A site with an HQ link configured pushes a small snapshot of
today's numbers to the HQ install every `PUSH_INTERVAL` seconds -- outbound
HTTPS only, so a site behind a normal router needs no port forwarding. The
HQ install is any install (typically on a small cloud VM) where the sites
are registered on the Sites page; each gets its own token.

No faces, embeddings or names leave a site: only counts.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import Alert
from app.models.settings import Setting
from app.services.analytics_overview import compute_overview
from app.services.client_profile import get_profile
from app.services.muster import muster
from app.services.settings_service import get_all_settings

logger = structlog.get_logger(__name__)
LINK_KEY = "client_hq_link"  # client_* -> hidden from the Settings API (holds a secret)
PUSH_INTERVAL = 300
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def build_snapshot(db: AsyncSession) -> dict[str, Any]:
    cfg = await get_all_settings(db)
    today = datetime.now(LOCAL_TZ).date()
    ov = await compute_overview(db, today, today, int(cfg.get("working_days_per_week", 5)))
    k = ov["kpis"]
    cams = ov.get("locations", [])
    open_alerts = (await db.execute(select(func.count()).select_from(Alert).where(Alert.acknowledged_at.is_(None)))).scalar_one()
    m = await muster(db)
    profile = await get_profile(db)
    return {
        "org_name": profile.get("org_name"),
        "date": today.isoformat(),
        "roster": k.get("roster", 0),
        "present": k.get("present_latest_day", 0),
        # present / roster today (the period KPI skips weekends; HQ wants "now")
        "attendance_pct": round(100 * k.get("present_latest_day", 0) / k["roster"], 1) if k.get("roster") else 0.0,
        "late": k.get("late_count", 0),
        "unknown_visitors": k.get("unknown_visitors", 0),
        "cameras_total": len(cams),
        "cameras_online": sum(1 for c in cams if c.get("online")),
        "cameras_liveness_off": sum(1 for c in cams if c.get("online") and c.get("liveness") == "off"),
        "open_alerts": int(open_alerts),
        "inside_now": len(m["inside"]) + len(m["visitors_inside"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_link(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(Setting).where(Setting.key == LINK_KEY))).scalar_one_or_none()
    return dict(row.value_json) if row is not None else {}


async def save_link(db: AsyncSession, link: dict[str, Any]) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == LINK_KEY))).scalar_one_or_none()
    if row is None:
        db.add(Setting(key=LINK_KEY, value_json=link))
    else:
        row.value_json = link
    await db.flush()


async def push_once(db: AsyncSession, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    link = await get_link(db)
    if not link.get("url") or not link.get("token"):
        return {"pushed": False, "reason": "not_configured"}
    snap = await build_snapshot(db)
    url = link["url"].rstrip("/") + "/api/v1/hq/ingest"
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        r = await client.post(url, json=snap, headers={"X-Site-Token": link["token"]})
        r.raise_for_status()
        link.update(last_push_at=datetime.now(timezone.utc).isoformat(), last_error=None)
        result = {"pushed": True}
    except httpx.HTTPError as exc:
        link.update(last_error=f"{type(exc).__name__}: {str(exc)[:150]}")
        result = {"pushed": False, "reason": link["last_error"]}
    finally:
        if own:
            await client.aclose()
    await save_link(db, link)
    await db.commit()
    return result


async def push_loop(session_factory: Any) -> None:  # pragma: no cover - timing loop
    while True:
        try:
            async with session_factory() as db:
                await push_once(db)
        except Exception as exc:  # noqa: BLE001 - never kill the API
            logger.warning("hq_push_failed", error=str(exc)[:200])
        await asyncio.sleep(PUSH_INTERVAL)
