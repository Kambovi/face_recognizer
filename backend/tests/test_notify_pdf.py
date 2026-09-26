"""WhatsApp / webhook notifications, daily schedule, monthly PDF."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import httpx

from app.models.alerts import Alert
from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.services import notify

IST = ZoneInfo("Asia/Kolkata")


def _recorder() -> tuple[list[dict], httpx.AsyncClient]:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": json.loads(request.content)})
        return httpx.Response(200, json={"ok": True})

    return calls, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_whatsapp_template_message_shape():
    calls, client = _recorder()
    cfg = {**notify.DEFAULTS, "channel": "whatsapp", "recipients": ["919800000001", "919800000002"],
           "phone_number_id": "123", "access_token": "tok", "template_alert": "security_alert"}
    assert await notify.send_logged(cfg, "ALERT: X at gate", "alert", client)
    assert len(calls) == 2
    assert calls[0]["url"].endswith("/123/messages") and calls[0]["auth"] == "Bearer tok"
    tpl = calls[0]["body"]["template"]
    assert tpl["name"] == "security_alert"
    assert tpl["components"][0]["parameters"][0]["text"] == "ALERT: X at gate"


async def test_failure_is_recorded_not_raised():
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text='{"error":"bad token"}')

    cfg = {**notify.DEFAULTS, "channel": "webhook", "webhook_url": "https://hooks.test/x"}
    ok = await notify.send_logged(cfg, "hi", "daily", httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert ok is False and "bad token" in cfg["last_error"]


async def test_daily_summary_sends_once_after_the_set_time(db_session, default_shift):
    db_session.add(Employee(face_id="F1", emp_code="E1", name="A"))
    await db_session.flush()
    cfg = await notify.get_config(db_session)
    cfg.update(channel="webhook", webhook_url="https://hooks.test/x", daily_time="10:00", send_monthly=False)
    await notify.save_config(db_session, cfg)
    calls, client = _recorder()
    early = datetime(2026, 9, 26, 9, 30, tzinfo=IST)
    later = datetime(2026, 9, 26, 10, 5, tzinfo=IST)
    assert await notify.run_schedules(db_session, now=early, client=client) == []
    assert await notify.run_schedules(db_session, now=later, client=client) == ["daily"]
    assert await notify.run_schedules(db_session, now=later, client=client) == []  # not twice
    assert "present" in calls[0]["body"]["text"] and calls[0]["body"]["kind"] == "daily"


async def test_config_api_hides_token_and_normalises_numbers(client, admin_headers):
    r = await client.put("/api/v1/notify/config", headers=admin_headers, json={
        "channel": "whatsapp", "recipients": ["98765 43210", "+91-99999-00000"], "phone_number_id": "1",
        "access_token": "secret-token", "daily_time": "09:45"})
    assert r.status_code == 200
    body = r.json()
    assert body["recipients"] == ["919876543210", "919999900000"]
    assert "access_token" not in body and body["access_token_set"] is True
    # saving again without a token keeps the old one
    r = await client.put("/api/v1/notify/config", headers=admin_headers, json={"channel": "whatsapp", "daily_time": "10:00"})
    assert r.json()["access_token_set"] is True
    bad = await client.put("/api/v1/notify/config", headers=admin_headers, json={"daily_time": "25:00"})
    assert bad.status_code == 422


async def test_alert_goes_out_immediately(db_session, monkeypatch):
    sent: list[str] = []

    async def fake_send(cfg, text, kind, client=None):
        sent.append(text)

    monkeypatch.setattr(notify, "send", fake_send)
    cfg = await notify.get_config(db_session)
    cfg.update(channel="webhook", webhook_url="https://x")
    await notify.save_config(db_session, cfg)
    alert = Alert(kind="watchlist", kiosk_id="gate", title="Watchlist: Ravi at gate", detail="Dismissed",
                  created_at=datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc))
    await notify.notify_alert(db_session, alert, {})
    assert sent == ["ALERT 26 Sep 10:30: Watchlist: Ravi at gate — Dismissed"]


async def test_monthly_pdf(client, admin_headers, db_session, default_shift):
    e = Employee(face_id="F9", emp_code="E9", name="Priya", department="Ops", contractor="Sharma Manpower",
                 created_at=datetime(2026, 1, 1, tzinfo=IST))
    db_session.add(e)
    await db_session.flush()
    for d in (1, 2, 3):
        db_session.add(AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=e.id, event_type=EventType.IN,
                                       occurred_at=datetime.combine(date(2026, 9, d), time(9, 30), tzinfo=IST), kiosk_id="g"))
    await db_session.commit()
    r = await client.get("/api/v1/reports/monthly.pdf?month=2026-09", headers=admin_headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 2000
