"""Outbound notifications: WhatsApp (Meta Cloud API) or any webhook.

What gets sent:
  * every new alert (watchlist hit, spoof attempt) -- immediately
  * a daily summary at `daily_time` (e.g. "10:00"): present / absent / late,
    cameras online, open alerts
  * a monthly summary on the 1st (last month's attendance %, OT hours)

Channels:
  whatsapp -- Meta WhatsApp Cloud API. Business-initiated messages need
              pre-approved templates, so each message type names a template
              that has ONE body variable ({{1}}) receiving the whole text.
              Leave a template name empty to send plain text instead (only
              delivered inside the 24 h customer-service window -- fine for
              testing, not for production).
  webhook  -- POST {"text": ..., "kind": ...} to a URL. Works with most
              Indian WhatsApp resellers (Interakt, AiSensy, Gupshup ...) and
              with Slack / Teams incoming webhooks.

The config holds an access token, so it lives under a `client_*` settings
key (hidden from the ordinary Settings API) and the token is never returned.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import Alert
from app.models.settings import Setting
from app.security import decrypt_text, encrypt_text

logger = structlog.get_logger(__name__)
KEY = "client_notify"
LOCAL_TZ = ZoneInfo("Asia/Kolkata")
GRAPH = "https://graph.facebook.com/v20.0"

DEFAULTS: dict[str, Any] = {
    "channel": "off",  # off | whatsapp | webhook
    "recipients": [],  # WhatsApp numbers with country code, digits only: 919812345678
    "phone_number_id": "",
    "access_token": "",
    "template_alert": "",
    "template_daily": "",
    "template_monthly": "",
    "template_language": "en",
    "webhook_url": "",
    "send_alerts": True,
    "send_daily": True,
    "daily_time": "10:00",
    "send_monthly": True,
    "last_daily": None,
    "last_monthly": None,
    "last_error": None,
}


async def get_config(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(Setting).where(Setting.key == KEY))).scalar_one_or_none()
    cfg = {**DEFAULTS, **(dict(row.value_json) if row is not None else {})}
    cfg["access_token"] = decrypt_text(cfg.get("access_token"))  # stored encrypted (security.encrypt_text)
    return cfg


async def save_config(db: AsyncSession, cfg: dict[str, Any]) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == KEY))).scalar_one_or_none()
    clean = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    clean["access_token"] = encrypt_text(clean.get("access_token") or "")
    if row is None:
        db.add(Setting(key=KEY, value_json=clean))
    else:
        row.value_json = clean
    await db.flush()


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in cfg.items() if k != "access_token"}
    out["access_token_set"] = bool(cfg.get("access_token"))
    return out


async def send(cfg: dict[str, Any], text: str, kind: str, client: httpx.AsyncClient | None = None) -> None:
    """Raises httpx.HTTPError (or KeyError for a half-filled config) on failure."""
    channel = cfg.get("channel", "off")
    if channel == "off":
        return
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        if channel == "webhook":
            r = await client.post(cfg["webhook_url"], json={"text": text, "kind": kind})
            r.raise_for_status()
            return
        template = (cfg.get(f"template_{kind}") or "").strip()
        for to in cfg.get("recipients") or []:
            body: dict[str, Any] = {"messaging_product": "whatsapp", "to": str(to)}
            if template:
                body.update(type="template", template={
                    "name": template,
                    "language": {"code": cfg.get("template_language") or "en"},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": text[:1000]}]}],
                })
            else:
                body.update(type="text", text={"body": text[:4000]})
            r = await client.post(
                f"{GRAPH}/{cfg['phone_number_id']}/messages",
                json=body,
                headers={"Authorization": f"Bearer {cfg['access_token']}"},
            )
            r.raise_for_status()
    finally:
        if own:
            await client.aclose()


async def send_logged(cfg: dict[str, Any], text: str, kind: str, client: httpx.AsyncClient | None = None) -> bool:
    try:
        await send(cfg, text, kind, client)
        cfg["last_error"] = None
        return True
    except (httpx.HTTPError, KeyError) as exc:
        detail = exc.response.text[:200] if isinstance(exc, httpx.HTTPStatusError) else f"{type(exc).__name__}: {str(exc)[:150]}"
        cfg["last_error"] = f"{datetime.now(timezone.utc).isoformat(timespec='minutes')} {kind}: {detail}"
        logger.warning("notify_failed", kind=kind, detail=detail)
        return False


async def notify_alert(db: AsyncSession, alert: Alert, config: dict[str, Any]) -> None:
    cfg = await get_config(db)
    if cfg["channel"] == "off" or not cfg.get("send_alerts"):
        return
    when = alert.created_at.astimezone(LOCAL_TZ).strftime("%d %b %H:%M")
    text = f"ALERT {when}: {alert.title}" + (f" — {alert.detail}" if alert.detail else "")
    if not await send_logged(cfg, text, "alert"):
        await save_config(db, cfg)


# ------------------------------------------------------------------ summaries
async def daily_text(db: AsyncSession) -> str:
    from app.services.multisite import build_snapshot

    s = await build_snapshot(db)
    absent = max(0, int(s["roster"]) - int(s["present"]))
    extra = f", anti-spoofing OFF on {s['cameras_liveness_off']}" if s.get("cameras_liveness_off") else ""
    return (
        f"{s['org_name']} — {datetime.now(LOCAL_TZ).strftime('%d %b')}: "
        f"{s['present']}/{s['roster']} present ({s['attendance_pct']}%), {absent} absent, {s['late']} late. "
        f"{s['cameras_online']}/{s['cameras_total']} cameras online{extra}. Open alerts: {s['open_alerts']}."
    )


def month_end(month_start: date) -> date:
    return (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


async def monthly_text(db: AsyncSession, month_start: date) -> str:
    from app.services.client_profile import get_profile
    from app.services.timesheet import build_timesheet, person_totals

    ts = await build_timesheet(db, month_start, month_end(month_start))
    totals = [person_totals(ts, p.id) for p in ts.people]
    working = sum(t["working_days"] for t in totals)
    paid = sum(t["present"] + 0.5 * t["half_days"] for t in totals)
    ot = round(sum(t["ot_hours"] for t in totals), 1)
    late = sum(int(t["late_days"]) for t in totals)
    pct = round(100 * paid / working, 1) if working else 0.0
    org = (await get_profile(db)).get("org_name")
    return (
        f"{org} — {month_start.strftime('%B %Y')}: attendance {pct}% across {len(ts.people)} people, "
        f"{late} late arrivals, {ot} overtime hours. Full report: Reports → Monthly PDF."
    )


async def run_schedules(db: AsyncSession, now: datetime | None = None, client: httpx.AsyncClient | None = None) -> list[str]:
    """Send whatever summary is due. Returns the kinds sent."""
    cfg = await get_config(db)
    if cfg["channel"] == "off":
        return []
    local = (now or datetime.now(timezone.utc)).astimezone(LOCAL_TZ)
    sent: list[str] = []
    today = local.date().isoformat()
    hh, mm = (int(x) for x in str(cfg.get("daily_time") or "10:00").split(":"))
    due = (local.hour, local.minute) >= (hh, mm)
    if cfg.get("send_daily") and cfg.get("last_daily") != today and due:
        if await send_logged(cfg, await daily_text(db), "daily", client):
            sent.append("daily")
        cfg["last_daily"] = today  # one attempt per day, success or not
    month_key = local.strftime("%Y-%m")
    if cfg.get("send_monthly") and local.day == 1 and cfg.get("last_monthly") != month_key and due:
        prev = (local.date().replace(day=1) - timedelta(days=1)).replace(day=1)
        if await send_logged(cfg, await monthly_text(db, prev), "monthly", client):
            sent.append("monthly")
        cfg["last_monthly"] = month_key
    await save_config(db, cfg)
    await db.commit()
    return sent


async def schedule_loop(session_factory: Any) -> None:  # pragma: no cover - timing loop
    while True:
        try:
            async with session_factory() as db:
                await run_schedules(db)
        except Exception as exc:  # noqa: BLE001 - never kill the API
            logger.warning("notify_schedule_failed", error=str(exc)[:200])
        await asyncio.sleep(60)
