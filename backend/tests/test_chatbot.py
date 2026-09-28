"""HR chatbot: leave + salary maths, people lookup, policy search, the
confirm-before-report flow, salary visibility, and the LLM tool loop
(Anthropic + OpenAI formats, mocked)."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import docx
import httpx
import pytest

from app.models.attendance_events import AttendanceEvent
from app.models.employees import Employee
from app.models.enums import EventType, SubjectType
from app.models.leaves import Leave
from app.security import create_access_token
from app.services.chatbot import engine
from app.services.chatbot.policy import PolicyIndex, split_chunks
from app.services.chatbot.report import build_report, parse_month
from app.services.chatbot.targets import find_targets
from app.services.payroll import payable_salary
from app.services.timesheet import build_timesheet, person_totals

IST = ZoneInfo("Asia/Kolkata")
AUG = date(2026, 8, 1)


async def _emp(db, code, name, dept="Ops", salary=None, kiosk=None):
    e = Employee(face_id=f"F-{code}", emp_code=code, name=name, department=dept, monthly_salary=salary,
                 home_kiosk_id=kiosk, created_at=datetime(2026, 1, 1, tzinfo=IST))
    db.add(e)
    await db.flush()
    return e


def _seen(db, e, d, hh, mm=0, kiosk="gate"):
    db.add(AttendanceEvent(subject_type=SubjectType.EMPLOYEE, employee_id=e.id, event_type=EventType.IN,
                           occurred_at=datetime.combine(d, time(hh, mm), tzinfo=IST), kiosk_id=kiosk))


@pytest.fixture
def viewer_headers(viewer_user):
    return {"Authorization": f"Bearer {create_access_token(subject=viewer_user.id, role='viewer')}"}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    (tmp_path / "leave_policy.md").write_text(
        "# Leave policy\n\nEvery employee gets 12 casual leave days per year. Sick leave needs a medical "
        "certificate after 2 days.\n\n# Office timings\n\nOffice hours are 9:00 to 18:00 with 15 minutes grace.")
    d = docx.Document()
    d.add_paragraph("Salary is paid on the 7th of every month by bank transfer.")
    d.save(tmp_path / "salary.docx")
    idx = PolicyIndex(tmp_path)
    monkeypatch.setattr(engine, "get_index", lambda: idx)
    return idx


# ------------------------------------------------------------------ leave + salary
async def test_leave_days_and_paid_days(db_session, default_shift):
    a = await _emp(db_session, "E1", "Asha")
    _seen(db_session, a, date(2026, 8, 3), 9, 5)
    db_session.add_all([Leave(employee_id=a.id, day=date(2026, 8, 4), kind="paid"),
                        Leave(employee_id=a.id, day=date(2026, 8, 5), kind="unpaid"),
                        Leave(employee_id=a.id, day=date(2026, 8, 9), kind="paid")])  # a Sunday: stays WO
    await db_session.flush()
    ts = await build_timesheet(db_session, AUG, date(2026, 8, 31))
    assert ts.records[(a.id, date(2026, 8, 4))].status == "L"
    assert ts.records[(a.id, date(2026, 8, 5))].status == "LWP"
    assert ts.records[(a.id, date(2026, 8, 9))].status == "WO"
    t = person_totals(ts, a.id)
    assert (t["present"], t["leave"], t["unpaid_leave"], t["weekly_off"]) == (1, 1, 1, 5)
    assert t["paid_days"] == 7  # 1 present + 5 weekly off + 1 paid leave


def test_payable_salary_calendar_days():
    assert payable_salary(31000, 7, AUG) == 7000
    assert payable_salary(30000, 30, date(2026, 9, 1)) == 30000
    assert payable_salary(None, 10, AUG) is None


def test_parse_month():
    now = date(2026, 9, 28)
    assert parse_month("2026-07", now) == "2026-07"
    assert parse_month("rahul ka august ka data", now) == "2026-08"
    assert parse_month("pichle mahine ki attendance", now) == "2026-08"
    assert parse_month("december", now) == "2025-12"
    assert parse_month("kuch bhi", now) == "2026-09"


# ------------------------------------------------------------------ lookup
async def test_find_people_by_typo_code_and_department(db_session):
    await _emp(db_session, "E-1001", "Rahul Sharma", "Production")
    await _emp(db_session, "E-1002", "Rahul Verma", "Stores")
    await _emp(db_session, "E-2000", "Priya Singh", "Production")
    r = await find_targets(db_session, "rahul sarma")
    assert r["candidates"][0]["label"] == "Rahul Sharma"
    r = await find_targets(db_session, "1001")
    assert [c["label"] for c in r["candidates"]] == ["Rahul Sharma"]
    r = await find_targets(db_session, "rahul")
    assert {c["label"] for c in r["candidates"]} == {"Rahul Sharma", "Rahul Verma"}
    r = await find_targets(db_session, "production")
    assert r["candidates"][0] == {**r["candidates"][0], "kind": "department", "id": "Production"}


async def test_many_matches_ask_for_department_first(db_session):
    for i in range(12):
        await _emp(db_session, f"K{i}", f"Mohd Khan {i}", "Loading" if i < 7 else "Security")
    r = await find_targets(db_session, "khan")
    assert r["total"] == 12 and {d["name"] for d in r["departments"]} == {"Loading", "Security"}
    choices = engine._choices_from(r, "2026-08")
    assert choices[0]["type"] == "filter"
    r2 = await find_targets(db_session, "khan", "employee", department="Security")
    assert r2["total"] == 5 and "departments" not in r2


# ------------------------------------------------------------------ reports + API
async def test_report_admin_sees_salary_viewer_does_not(client, db_session, default_shift, admin_headers, viewer_headers):
    a = await _emp(db_session, "E1", "Asha", salary=31000)
    _seen(db_session, a, date(2026, 8, 3), 9, 40)  # late
    await db_session.commit()
    action = {"type": "report", "kind": "employee", "id": a.id, "month": "2026-08"}
    r = (await client.post("/api/v1/chat", json={"action": action}, headers=admin_headers)).json()
    rep = r["report"]
    assert rep["rows"][0]["late_days"] == 1 and rep["rows"][0]["payable"] == 6000  # 6 paid days
    assert any(c["key"] == "payable" for c in rep["columns"])
    assert "₹6,000" in r["text"] and rep["details"]["rows"]
    r = (await client.post("/api/v1/chat", json={"action": action}, headers=viewer_headers)).json()
    assert r["report"]["salary_hidden"] and "payable" not in r["report"]["rows"][0]
    assert "₹" not in r["text"]


async def test_department_and_camera_reports(db_session, default_shift):
    await _emp(db_session, "E1", "Asha", "Ops", 30000, kiosk="gate1")
    b = await _emp(db_session, "E2", "Bina", "Ops", 31000)
    await _emp(db_session, "E3", "Chand", "HR")
    _seen(db_session, b, date(2026, 8, 3), 9, 0, kiosk="gate1")
    await db_session.flush()
    rep = await build_report(db_session, "department", "Ops", "2026-08", True)
    assert [r["emp_code"] for r in rep["rows"]] == ["E1", "E2"] and rep["totals"]["name"] == "Total (2)"
    rep = await build_report(db_session, "camera", "gate1", "2026-08", False)
    assert {r["emp_code"] for r in rep["rows"]} == {"E1", "E2"}  # home camera + seen there


async def test_basic_mode_people_then_policy(client, db_session, admin_headers, policy):
    await _emp(db_session, "E-77", "Imran Ali")
    await db_session.commit()
    r = (await client.post("/api/v1/chat", json={"message": "Imran ki august ki attendance do"}, headers=admin_headers)).json()
    assert r["mode"] == "basic" and r["choices"][0]["label"] == "Imran Ali" and r["choices"][0]["month"] == "2026-08"
    assert r["report"] is None  # nothing shown before confirmation
    r = (await client.post("/api/v1/chat", json={"message": "sick chutti ka rule kya hai"}, headers=admin_headers)).json()
    assert "medical certificate" in r["text"] and r["sources"][0]["source"] == "leave_policy.md"
    r = (await client.post("/api/v1/chat", json={"message": "salary kab milti hai"}, headers=admin_headers)).json()
    assert "7th" in r["text"]


def test_policy_chunking_and_status(policy):
    st = policy.status()
    assert set(st["files"]) == {"leave_policy.md", "salary.docx"} and st["chunks"] >= 2
    assert all(len(c) <= 900 for c in split_chunks("word " * 1000))


# ------------------------------------------------------------------ LLM loop (mocked)
def _mock(replies: list[dict], seen: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(seen) - 1])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_anthropic_tool_loop_gives_choices_not_numbers(db_session, default_shift, policy):
    a = await _emp(db_session, "E1", "Asha Rani", salary=50000)
    _seen(db_session, a, date(2026, 8, 3), 9, 0)
    await db_session.flush()
    seen: list[dict] = []
    client = _mock([
        {"content": [{"type": "tool_use", "id": "t1", "name": "find_people",
                      "input": {"query": "Asha", "month": "2026-08"}}]},
        {"content": [{"type": "text", "text": "Asha Rani mili. Confirm karein?"}]},
    ], seen)
    cfg = {**engine.DEFAULTS, "provider": "anthropic", "model": "m", "api_key": "k"}
    r = await engine.respond(db_session, cfg, message="asha ki salary", history=[], action=None,
                             org_name="Acme", can_see_salary=True, client=client)
    assert r["mode"] == "llm" and r["text"].startswith("Asha Rani")
    assert r["choices"][0] == {**r["choices"][0], "type": "report", "id": a.id, "month": "2026-08"}
    tool_result = seen[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "50000" not in tool_result["content"]
    assert seen[0]["tools"][0]["name"] == "search_policy"


async def test_openai_format_policy_answer_with_sources(db_session, policy):
    seen: list[dict] = []
    client = _mock([
        {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_policy", "arguments": '{"query": "casual leave"}'}}]}}]},
        {"choices": [{"message": {"content": "Saal me 12 casual leave milti hain (leave_policy.md)."}}]},
    ], seen)
    cfg = {**engine.DEFAULTS, "provider": "ollama", "model": "qwen2.5:7b"}
    r = await engine.respond(db_session, cfg, message="kitni chutti milti hai", history=[
        {"role": "assistant", "content": "Namaste"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "Boliye"}],
        action=None, org_name="Acme", can_see_salary=False, client=client)
    assert "12 casual" in r["text"] and r["sources"][0]["source"] == "leave_policy.md"
    assert seen[0]["messages"][1]["role"] == "user"  # leading assistant turn dropped
    assert seen[1]["messages"][-1]["role"] == "tool" and "12 casual leave" in seen[1]["messages"][-1]["content"]


async def test_model_down_falls_back_to_basic(db_session, policy):
    await _emp(db_session, "E9", "Zoya Khan")
    await db_session.flush()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")))
    cfg = {**engine.DEFAULTS, "provider": "openai", "model": "gpt", "api_key": "x"}
    r = await engine.respond(db_session, cfg, message="Zoya Khan ka report", history=[], action=None,
                             org_name="Acme", can_see_salary=True, client=client)
    assert r["notice"] and "401" in r["notice"] and r["choices"][0]["label"] == "Zoya Khan"


# ------------------------------------------------------------------ config + leaves API
async def test_config_hides_key_and_leaves_api(client, db_session, admin_headers, viewer_headers):
    r = await client.put("/api/v1/chat/config", json={"provider": "anthropic", "model": "m", "api_key": "secret"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["api_key_set"] and "api_key" not in r.json()
    r = await client.put("/api/v1/chat/config", json={"provider": "anthropic", "model": "m2"}, headers=admin_headers)
    assert (await engine.get_config(db_session))["api_key"] == "secret"
    assert (await client.get("/api/v1/chat/config", headers=viewer_headers)).status_code == 403
    assert "client_chatbot" not in (await client.get("/api/v1/settings", headers=admin_headers)).json()["settings"]
    st = (await client.get("/api/v1/chat/status", headers=viewer_headers)).json()
    assert st["mode"] == "llm" and st["can_see_salary"] is False

    e = await _emp(db_session, "E1", "Asha")
    await db_session.commit()
    body = {"employee_id": e.id, "date_from": "2026-08-10", "date_to": "2026-08-12", "kind": "paid"}
    assert (await client.post("/api/v1/leaves", json=body, headers=viewer_headers)).status_code == 403
    assert (await client.post("/api/v1/leaves", json=body, headers=admin_headers)).json() == {"days": 3}
    rows = (await client.get(f"/api/v1/leaves?employee_id={e.id}", headers=admin_headers)).json()
    assert len(rows) == 3
    assert (await client.delete(f"/api/v1/leaves/{rows[0]['id']}", headers=admin_headers)).status_code == 204
    bad = {**body, "date_to": "2026-08-01"}
    assert (await client.post("/api/v1/leaves", json=bad, headers=admin_headers)).status_code == 422
