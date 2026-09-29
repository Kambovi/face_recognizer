"""The conversation loop.

Two modes:
  llm    a language model is configured: it reads the question, calls the
         tools (search_policy / find_people) and writes the reply.
  basic  no model (or the model is unreachable): keyword rules -- people
         lookup if the question names someone, else policy passages.

Either way a report is only produced after the user *confirms* a choice
(the `action` sent by a button click), and its numbers come from
report.py, not from the model.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.chatbot import llm
from app.services.chatbot.policy import get_index
from app.services.chatbot.report import build_detection_report, build_report, parse_date, parse_month, today
from app.services.chatbot.targets import find_targets

logger = structlog.get_logger(__name__)

KEY = "client_chatbot"  # client_ prefix: hidden from the ordinary Settings API
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "provider": "off",  # off | anthropic | openai | ollama
    "model": "",
    "base_url": "",
    "api_key": "",
    "temperature": 0.2,
    "max_rounds": 4,
    "org_note": "",  # extra instructions, e.g. "Reply in Hindi"
}
MAX_HISTORY = 12
MAX_MSG_CHARS = 2000

TOOLS = [
    {
        "name": "search_policy",
        "description": "Search the company policy documents (leave, holidays, timings, salary rules, conduct...). "
                       "Pass short ENGLISH keywords even if the user wrote Hindi/Hinglish.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "find_people",
        "description": "Find the employee, department, camera or contractor the user is asking about, by name or ID. "
                       "Call this for ANY attendance / late / absent / leave / salary / payroll question about a "
                       "person or group. The app then shows the matches as buttons; the user confirms one and the "
                       "app shows the report table. You never see or state the numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "name, employee ID, department, camera or contractor"},
                "kind": {"type": "string", "enum": ["any", "employee", "department", "camera", "contractor"]},
                "department": {"type": "string", "description": "only people in this department (to narrow down)"},
                "month": {"type": "string", "description": "YYYY-MM the user asked about; omit for this month"},
                "report": {"type": "string", "enum": ["attendance", "detections"],
                           "description": "attendance = present/absent/late/leave/salary summary (default). "
                                          "detections = how many times the person was seen by the cameras "
                                          "(e.g. 'kitni baar detect hua')"},
                "date": {"type": "string", "description": "YYYY-MM-DD if the user asked about one specific day"},
                "camera": {"type": "string", "description": "camera name if the user named one (e.g. entry gate)"},
            },
            "required": ["query"],
        },
    },
]


# ------------------------------------------------------------------ config
async def get_config(db: AsyncSession) -> dict[str, Any]:
    row = (await db.execute(select(Setting).where(Setting.key == KEY))).scalar_one_or_none()
    return {**DEFAULTS, **(dict(row.value_json) if row is not None else {})}


async def save_config(db: AsyncSession, cfg: dict[str, Any]) -> None:
    row = (await db.execute(select(Setting).where(Setting.key == KEY))).scalar_one_or_none()
    clean = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    if row is None:
        db.add(Setting(key=KEY, value_json=clean))
    else:
        row.value_json = clean
    await db.flush()


def public_config(cfg: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in cfg.items() if k != "api_key"}
    out["api_key_set"] = bool(cfg.get("api_key"))
    return out


def mode_of(cfg: dict[str, Any]) -> str:
    return "llm" if cfg.get("provider") in llm.DEFAULT_BASE and cfg.get("model") else "basic"


# ------------------------------------------------------------------ helpers
def _reply(text: str, **kw: Any) -> dict[str, Any]:
    return {"text": text, "choices": kw.get("choices", []), "report": kw.get("report"),
            "sources": kw.get("sources", []), "mode": kw.get("mode", "basic"), "notice": kw.get("notice")}


def _choices_from(found: dict[str, Any], month: str, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """`extra`: report type / date / camera the question asked for; carried
    on every button so the confirmed report is the one that was asked."""
    extra = {k: v for k, v in (extra or {}).items() if v}
    if found.get("departments"):  # too many people: narrow by department first
        return [{"type": "filter", "kind": "employee", "query": found["query"], "department": d["name"],
                 "label": d["name"], "sub": f"{d['count']} matching", "month": month, **extra}
                for d in found["departments"][:10]]
    return [{"type": "report", "kind": c["kind"], "id": c["id"], "label": c["label"], "sub": c["sub"],
             "month": month, **extra}
            for c in found["candidates"]]


def _found_text(found: dict[str, Any]) -> str:
    n = found["total"]
    if n == 0:
        return f"'{found['query']}' se koi match nahi mila. Naam ya employee ID dobara check karein."
    if found.get("departments"):
        return f"{n} log mile. Pehle department chunein:"
    if n == 1:
        return "Ye sahi hai? Confirm karne ke liye click karein:"
    return f"{n} match mile. Sahi wala chunein:"


def _sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for h in hits:
        key = (h["source"], h["passage"])
        if key not in seen:
            seen.add(key)
            out.append({"source": h["source"], "passage": h["passage"], "snippet": h["text"][:400]})
    return out


# ------------------------------------------------------------------ actions (button clicks)
async def run_action(db: AsyncSession, action: dict[str, Any], include_salary: bool, mode: str) -> dict[str, Any]:
    month = parse_month(action.get("month"))
    extra = {k: action.get(k) for k in ("report", "date", "camera")}
    if action.get("type") == "filter":
        found = await find_targets(db, action.get("query", ""), "employee", department=action.get("department"))
        text = _found_text(found) if found["total"] else "Is department me koi match nahi."
        return _reply(text, choices=_choices_from(found, month, extra), mode=mode)
    if action.get("report") == "detections":
        month = action["date"][:7] if action.get("date") else month
        report = await build_detection_report(db, action["kind"], action["id"], month, action.get("date"),
                                              action.get("camera"))
        return _reply(report["summary"], report=report, mode=mode)
    report = await build_report(db, action["kind"], action["id"], month, include_salary)
    return _reply(report["summary"], report=report, mode=mode)


# ------------------------------------------------------------------ cameras
async def resolve_camera(db: AsyncSession, text: str) -> str | None:
    """A camera named in the text: its ID ("gate-1"), or "entry" / "exit"
    when exactly one camera has that role or that word in its ID."""
    from app.services.muster import camera_roles
    from app.services.roster import camera_overview

    t = (text or "").lower()
    if not t.strip():
        return None
    cams = [c["kiosk_id"] for c in await camera_overview(db)]
    norm = lambda x: re.sub(r"[\s_-]+", "", x.lower())  # noqa: E731
    for k in sorted(cams, key=len, reverse=True):
        if norm(k) and norm(k) in norm(t):
            return k
    roles = await camera_roles(db)
    for word in ("entry", "exit"):
        if re.search(rf"\b{word}\b", t):
            hits = [k for k in cams if roles.get(k) == word] or [k for k in cams if word in k.lower()]
            if len(hits) == 1:
                return hits[0]
    return None


# ------------------------------------------------------------------ basic mode
def _plain(md: str) -> str:
    """Markdown passage -> readable chat text (headings, bold, quotes)."""
    out = re.sub(r"^#{1,6}\s*(.+)$", lambda m: m.group(1).upper(), md, flags=re.M)
    out = re.sub(r"^>\s?", "", out, flags=re.M)
    return re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), out).strip()


DATA_WORDS = re.compile(
    r"\b(attendance|attendence|hazri|haziri|salary|salry|payroll|tankhwah|late|absent|present|leave|report|detail|"
    r"details|summary|emp|employee|staff|department|dept|camera|contractor|ot|overtime|kitne din|data)\b", re.I)
DETECT_WORDS = re.compile(
    r"kitni\s*(baar|bar|dafa|dafe)|how many times|\bdetect(ed|ion|ions)?\b|\bdikh[aie]\b|\bseen\b|\btimes seen\b", re.I)
FILLER = re.compile(
    r"\b(baar|bar|dafa|dafe|detect|detected|detection|detections|hua|hui|hue|dikha|dikhi|dikhe|seen|times|how|many|"
    r"kitni|kitna|par|pr|pe|on|at|aaj|kal|today|yesterday|office|entry|exit|gate|\d{1,4}(st|nd|rd|th)?|ka|ki|ke|ko|kaa|kya|hai|hain|do|dijiye|dikhao|batao|bataiye|chahiye|mujhe|please|pls|show|give|me|of|for|the|"
    r"this|last|month|mahine|pichle|pichla|is|id|emp|employee|staff|department|dept|camera|contractor|attendance|"
    r"attendence|hazri|haziri|salary|salry|payroll|tankhwah|late|absent|present|leave|report|detail|details|summary|"
    r"poori|pura|puri|full|and|aur|data|ot|overtime|kitne|din|january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|20\d\d(-\d\d)?)\b", re.I)


async def basic_answer(db: AsyncSession, message: str, notice: str | None = None) -> dict[str, Any]:
    month = parse_month(message)
    detections = bool(DETECT_WORDS.search(message))
    wants_data = detections or bool(DATA_WORDS.search(message))
    camera = await resolve_camera(db, message) if detections else None
    extra = {"report": "detections" if detections else None, "date": parse_date(message) if detections else None,
             "camera": camera}
    text = message
    if camera:
        text = re.sub(re.escape(camera), " ", text, flags=re.I)
    name = re.sub(r"\s+", " ", FILLER.sub(" ", re.sub(r"[^\w\s-]", " ", text))).strip(" -")
    found = await find_targets(db, name) if name else None
    if found and found["total"]:
        strong = found["candidates"][0]["score"] >= 80
        if wants_data or strong:
            return _reply(_found_text(found), choices=_choices_from(found, month, extra), notice=notice)
    hits = get_index().search(message, k=3)
    if hits:
        best = [h for h in hits if h["score"] >= 0.7 * hits[0]["score"]][:2]
        text = "Company policy me ye mila:\n\n" + "\n\n".join(_plain(h["text"])[:800] for h in best)
        return _reply(text, sources=_sources(best), notice=notice)
    if found is not None and wants_data:
        return _reply(_found_text(found), notice=notice)
    if not get_index().chunks:
        return _reply("Policy documents abhi add nahi hue. Kisi employee ka naam ya ID likhein, uska attendance/payroll "
                      "summary dikha dunga.", notice=notice)
    return _reply("Iska jawab policy me nahi mila. Kisi employee / department ka naam ya ID likhein, ya sawaal alag "
                  "shabdon me poochein.", notice=notice)


# ------------------------------------------------------------------ llm mode
def system_prompt(cfg: dict[str, Any], org_name: str, can_see_salary: bool) -> str:
    return f"""You are the HR assistant inside the face-attendance dashboard of {org_name}. Today is {today().isoformat()}.

You have two sources:
1. Company policy documents -> tool search_policy. Answer policy questions ONLY from the passages it returns and name the file you used, e.g. (leave_policy.pdf). If nothing relevant comes back, say the policy does not cover it. Never invent rules.
2. The attendance / payroll database -> tool find_people. For ANY question about a person's, department's, camera's or contractor's attendance, late marks, absents, leave, OT, salary or payroll, call find_people with the name or ID (and month as YYYY-MM if the user named one). The app shows the matches as buttons; the user confirms one and the app itself shows the report table. For "how many times was X seen / detected (kitni baar detect hua)" questions, call find_people with report="detections", plus date (YYYY-MM-DD) and camera if the user gave them.

Hard rules:
- Never state attendance numbers, salaries or any figures about a person yourself. You don't have them.
- After find_people, reply with ONE short line asking the user to pick the right match (or to pick a department first if there are many). If there are 0 matches, say so and ask for the correct name / ID.
- {"The user may see salaries." if can_see_salary else "This user is not allowed to see salaries; if asked, say salary is visible to admins only (attendance is still available)."}
- Reply in the user's language (Hindi, Hinglish or English). Be brief and friendly. No long preambles.
- Questions unrelated to HR, policy or attendance: politely say you only help with those.
{cfg.get("org_note") or ""}""".strip()


async def llm_answer(
    db: AsyncSession, cfg: dict[str, Any], history: list[dict[str, str]], message: str,
    org_name: str, can_see_salary: bool, client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = [
        {"role": h["role"], "content": h["content"][:MAX_MSG_CHARS]}
        for h in history[-MAX_HISTORY:] if h.get("role") in ("user", "assistant") and h.get("content")
    ]
    # providers require the conversation to start with a user turn
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    msgs.append({"role": "user", "content": message[:MAX_MSG_CHARS]})
    system = system_prompt(cfg, org_name, can_see_salary)
    choices: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    default_month = parse_month(message)
    try:
        for _ in range(max(1, int(cfg.get("max_rounds") or 4))):
            out = await llm.complete(cfg, system, msgs, TOOLS, client)
            if not out.tool_calls:
                text = out.text or ("Sahi match chunein:" if choices else "...")
                return _reply(text, choices=choices, sources=sources, mode="llm")
            msgs.append({"role": "assistant", "content": out.text, "tool_calls": out.tool_calls})
            for tc in out.tool_calls:
                if tc.name == "search_policy":
                    hits = get_index().search(str(tc.args.get("query", "")), k=4)
                    sources.extend(_sources(hits))
                    result: Any = [{"file": h["source"], "text": h["text"]} for h in hits] or "No matching policy text."
                elif tc.name == "find_people":
                    month = parse_month(tc.args.get("month")) if tc.args.get("month") else default_month
                    found = await find_targets(db, str(tc.args.get("query", "")), str(tc.args.get("kind") or "any"),
                                               department=tc.args.get("department") or None)
                    extra = {"report": tc.args.get("report") if tc.args.get("report") == "detections" else None,
                             "date": parse_date(str(tc.args.get("date"))) if tc.args.get("date") else None,
                             "camera": await resolve_camera(db, str(tc.args.get("camera") or ""))}
                    choices = _choices_from(found, month, extra)
                    # the model gets names / departments only -- never numbers
                    result = {"total": found["total"],
                              "matches": [{"kind": c["kind"], "name": c["label"], "info": c["sub"]} for c in found["candidates"]],
                              "departments_to_pick_from": [d["name"] for d in found.get("departments", [])],
                              "note": "Shown to the user as buttons. Ask them to pick one."}
                else:
                    result = f"Unknown tool {tc.name}"
                msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name,
                             "content": json.dumps(result, ensure_ascii=False)[:12000]})
        return _reply("Sahi match chunein:" if choices else "Maaf kijiye, jawab nahi bana paya. Dobara poochein.",
                      choices=choices, sources=sources, mode="llm")
    except llm.LLMError as exc:
        logger.warning("chatbot_llm_failed", error=str(exc)[:300])
        return await basic_answer(db, message, notice=f"AI model se connect nahi hua, basic mode me jawab: {str(exc)[:160]}")


async def respond(
    db: AsyncSession, cfg: dict[str, Any], *, message: str, history: list[dict[str, str]],
    action: dict[str, Any] | None, org_name: str, can_see_salary: bool, client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    mode = mode_of(cfg)
    if action:
        return await run_action(db, action, can_see_salary, mode)
    if not message.strip():
        return _reply("Kuch poochiye.", mode=mode)
    if mode == "llm":
        return await llm_answer(db, cfg, history, message, org_name, can_see_salary, client)
    return await basic_answer(db, message)
