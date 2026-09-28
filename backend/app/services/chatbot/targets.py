"""Find who the user means: a person (by name, employee ID or face ID), a
department, a camera or a contractor. Tolerates typos ("Rahul Sharma" vs
"Rahul Sarma"). When too many people match, the result carries a
department breakdown so the chat can ask the user to narrow down first.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employees import Employee
from app.services.roster import camera_overview

Kind = Literal["employee", "department", "camera", "contractor"]
MAX_CHOICES = 8
MIN_SCORE = 55


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", s.lower())).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def score_name(query: str, name: str) -> float:
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 100.0
    qt, nt = q.split(), n.split()
    if all(any(w == t for w in nt) for t in qt):
        return 90.0
    if all(any(w.startswith(t) for w in nt) for t in qt):
        return 80.0
    if q in n:
        return 75.0
    # typo tolerance: best word-to-word similarity, averaged over query words
    per = [max(_ratio(t, w) for w in nt) for t in qt]
    avg = sum(per) / len(per)
    whole = _ratio(q, n)
    best = max(avg, whole)
    return round(best * 85, 1) if best >= 0.75 else 0.0


def score_code(query: str, code: str) -> float:
    q, c = _norm(query).replace(" ", ""), _norm(code).replace(" ", "")
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0
    if c.startswith(q) and len(q) >= 2:
        return 70.0
    # "E-1001" vs "e1001", or the digits alone
    qd, cd = re.sub(r"\D", "", q), re.sub(r"\D", "", c)
    if qd and qd == cd and len(qd) >= 2:
        return 92.0
    return 0.0


def _choice(kind: Kind, id_: str, label: str, sub: str, score: float) -> dict[str, Any]:
    return {"kind": kind, "id": id_, "label": label, "sub": sub, "score": score}


async def find_targets(
    db: AsyncSession,
    query: str,
    kind: str = "any",
    department: str | None = None,
) -> dict[str, Any]:
    query = (query or "").strip()
    kinds = {"employee", "department", "camera", "contractor"} if kind in ("any", "", None) else {kind}
    found: list[dict[str, Any]] = []

    people = list((await db.execute(select(Employee).where(Employee.deleted_at.is_(None)))).scalars().all())

    if "employee" in kinds:
        for p in people:
            if department and _norm(p.department or "No department") != _norm(department):
                continue
            s = max(score_code(query, p.emp_code), score_code(query, p.face_id), score_name(query, p.name),
                    100.0 if query == p.id else 0.0)
            if s >= MIN_SCORE or (not query and department):
                bits = [p.emp_code, p.department or "No department"]
                if p.designation:
                    bits.append(p.designation)
                if not p.is_active:
                    bits.append("inactive")
                found.append(_choice("employee", p.id, p.name, " · ".join(bits), s or 60.0))

    if "department" in kinds and not department:
        counts: dict[str, int] = {}
        for p in people:
            if p.department and p.is_active:
                counts[p.department] = counts.get(p.department, 0) + 1
        for d, n in counts.items():
            s = score_name(query, d) if query else 60.0
            if s >= MIN_SCORE:
                found.append(_choice("department", d, d, f"Department · {n} active", s))

    if "contractor" in kinds and not department:
        counts = {}
        for p in people:
            if p.contractor and p.is_active:
                counts[p.contractor] = counts.get(p.contractor, 0) + 1
        for c, n in counts.items():
            s = score_name(query, c) if query else 60.0
            if s >= MIN_SCORE:
                found.append(_choice("contractor", c, c, f"Contractor · {n} active", s))

    if "camera" in kinds and not department:
        for cam in await camera_overview(db):
            k = cam["kiosk_id"]
            s = max(score_code(query, k), score_name(query, k.replace("_", " ").replace("-", " "))) if query else 60.0
            if s >= MIN_SCORE:
                found.append(_choice("camera", k, k, f"Camera · {cam['enrolled']} enrolled · {cam['role']}", s))

    found.sort(key=lambda c: (-c["score"], c["label"]))
    # exact hit (ID or full name) -> hide the weak fuzzy tail
    if found and found[0]["score"] >= 90:
        found = [c for c in found if c["score"] >= 75]
    total = len(found)
    result: dict[str, Any] = {"query": query, "department": department, "total": total,
                              "candidates": found[:MAX_CHOICES]}
    emp = [c for c in found if c["kind"] == "employee"]
    if len(emp) > MAX_CHOICES:
        by_dept: dict[str, int] = {}
        for cand in emp:
            d = cand["sub"].split(" · ")[1]
            by_dept[d] = by_dept.get(d, 0) + 1
        result["departments"] = [{"name": d, "count": n} for d, n in sorted(by_dept.items(), key=lambda x: -x[1])]
    return result
