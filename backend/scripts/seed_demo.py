#!/usr/bin/env python
"""`make seed` -- populates a fresh database with a realistic, fully
synthetic demo dataset:

  * 100 enrolled employees, each with 2-3 face templates and a procedurally
    drawn PIL portrait.
  * ~2.5 weeks of attendance history plus a live mix of "already left",
    "still clocked in", "late", and "absent" employees for *today*, so the
    dashboard, analytics, and exceptions views all have real data to show
    immediately after `docker compose up`.
  * 5 unenrolled "unknown" identities, each seen 2-4 times.

Run via `make seed` (docker compose exec -T api python scripts/seed_demo.py).
Safe to re-run: it refuses to do anything if employees already exist.

DEMO DATABASES ONLY. On 2026-09-22 this was run against the same dev.db the
real camera was writing to, so 100 fake people + 3 weeks of fake history got
mixed into real data (fake people always "absent" -> attendance % looked
wrong). It now refuses on any database that has a client profile or any
attendance/unknown-face data, and seeded IDs start with DEMO so they can be
removed with:  python scripts/reset_data.py people --code-like "DEMO%"
For a demo, point DATABASE_URL at a separate file, e.g.
    set DATABASE_URL=sqlite+aiosqlite:///./demo.db

Design notes (see docs/DECISIONS.md, "seed script uses synthetic
embeddings"): face templates use synthetic, deterministic 512-d embeddings
rather than running real SCRFD/ArcFace against the PIL-drawn portraits --
a simple procedural line drawing is not something a real face detector can
find a face in, and this script's job is a populated, browsable dataset for
`docker compose up`, not another exercise of the ML pipeline (scripts/
smoke.py in the kiosk covers that with the real pipeline end-to-end,
synthetic camera frames included). Attendance events are still created
through the real `upsert_attendance_event` state machine and unknown
clustering through the real `cluster_or_create_unknown`, so the seeded data
exercises the same dedupe/IN-OUT/clustering logic production traffic does.
"""
from __future__ import annotations

import asyncio
import base64
import io
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import AsyncSessionLocal, engine  # noqa: E402
from app.models.attendance_events import AttendanceEvent  # noqa: E402
from app.models.consents import Consent  # noqa: E402
from app.models.employees import Employee  # noqa: E402
from app.models.enums import OwnerType, RejectReason, SubjectType  # noqa: E402
from app.models.face_templates import EMBEDDING_DIM, FaceTemplate  # noqa: E402
from app.models.shifts import Shift  # noqa: E402
from app.models.unknown_identities import UnknownIdentity  # noqa: E402
from app.security import encrypt_embedding  # noqa: E402
from app.services.attendance import (  # noqa: E402
    RecognitionEventInput,
    upsert_attendance_event,
)
from app.services.client_profile import load_raw  # noqa: E402
from app.services.ids import next_employee_face_id  # noqa: E402
from app.services.media import save_base64_jpeg  # noqa: E402
from app.services.unknown_identity import cluster_or_create_unknown  # noqa: E402

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
MODEL_VERSION = "buffalo_l"
KIOSK_ID = "kiosk-01"

SEED = 20240115  # deterministic across runs, purely for reproducible demo data
rng = np.random.default_rng(SEED)
pyrng = random.Random(SEED)

FIRST_NAMES = [
    "Aarav", "Vivian", "Noah", "Priya", "Liam", "Sofia", "Kenji", "Amara", "Mateo", "Elena",
    "Ravi", "Grace", "Yusuf", "Mei", "Diego", "Nadia", "Ethan", "Ines", "Omar", "Chloe",
]
LAST_NAMES = [
    "Sharma", "Nguyen", "Patel", "Kim", "Rossi", "Johansson", "Okafor", "Fernandes", "Novak", "Silva",
    "Iyer", "Kowalski", "Haddad", "Yamamoto", "Brennan", "Costa", "Andersson", "Reyes", "Chowdhury", "Dube",
]
DEPARTMENTS = ["Engineering", "Operations", "Sales", "Support", "Finance", "Human Resources"]
DESIGNATIONS = ["Associate", "Senior Associate", "Lead", "Manager", "Analyst", "Specialist"]

PORTRAIT_SIZE = (320, 320)


def _draw_portrait(skin: tuple[int, int, int], hair: tuple[int, int, int], accessory: tuple[int, int, int]) -> bytes:
    """A simple, clearly-synthetic procedural portrait (oval face, two dot
    eyes, a hairline band, a colored collar) -- purely for the UI to have
    something to show in crop thumbnails. Not intended to be detectable by a
    real face detector; see module docstring."""
    w, h = PORTRAIT_SIZE
    img = Image.new("RGB", (w, h), (235, 235, 238))
    draw = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2 - 10

    draw.ellipse((cx - 90, cy - 110, cx + 90, cy + 110), fill=skin)
    draw.pieslice((cx - 95, cy - 130, cx + 95, cy + 40), start=180, end=360, fill=hair)
    draw.ellipse((cx - 40, cy - 20, cx - 12, cy + 8), fill=(40, 30, 30))
    draw.ellipse((cx + 12, cy - 20, cx + 40, cy + 8), fill=(40, 30, 30))
    draw.arc((cx - 35, cy + 20, cx + 35, cy + 60), start=15, end=165, fill=(90, 55, 55), width=4)
    draw.rectangle((cx - 70, cy + 110, cx + 70, h), fill=accessory)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _random_color() -> tuple[int, int, int]:
    return tuple(int(v) for v in rng.integers(60, 230, size=3))


def _base64_portrait() -> str:
    skin = tuple(int(v) for v in rng.integers(150, 225, size=3))
    hair = _random_color()
    accessory = _random_color()
    jpeg_bytes = _draw_portrait(skin, hair, accessory)
    return base64.b64encode(jpeg_bytes).decode("ascii")


def _unit_embedding() -> list[float]:
    v = rng.normal(size=EMBEDDING_DIM)
    v = v / np.linalg.norm(v)
    return v.astype(np.float64).tolist()


def _noisy_variant(base: list[float], noise_std: float = 0.03) -> list[float]:
    """A slightly perturbed copy of `base`, renormalized -- simulates the
    same synthetic "person" being seen again with natural embedding
    variation, while staying comfortably above any similarity threshold used
    in this codebase (cosine similarity stays > 0.95 at this noise level)."""
    v = np.asarray(base, dtype=np.float64) + rng.normal(scale=noise_std, size=EMBEDDING_DIM)
    v = v / np.linalg.norm(v)
    return v.tolist()


def _working_days_back(n: int, before: date) -> list[date]:
    """The `n` most recent Mon-Fri dates strictly before `before`."""
    days: list[date] = []
    cursor = before - timedelta(days=1)
    while len(days) < n:
        if cursor.weekday() < 5:  # Monday=0 .. Sunday=6
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    return days


async def _seed_employees(db) -> list[Employee]:
    default_shift = (await db.execute(select(Shift).where(Shift.is_default.is_(True)))).scalars().first()
    if default_shift is None:
        default_shift = (await db.execute(select(Shift))).scalars().first()

    employees: list[Employee] = []
    for i in range(1, 101):
        name = f"{pyrng.choice(FIRST_NAMES)} {pyrng.choice(LAST_NAMES)}"
        face_id = await next_employee_face_id(db)
        employee = Employee(
            face_id=face_id,
            emp_code=f"DEMO{i:04d}",  # DEMO prefix: `reset_data.py people --code-like "DEMO%"` removes them
            name=name,
            department=pyrng.choice(DEPARTMENTS),
            designation=pyrng.choice(DESIGNATIONS),
            shift_id=default_shift.id if default_shift else None,
            is_active=True,
        )
        db.add(employee)
        await db.flush()

        db.add(
            Consent(
                employee_id=employee.id,
                policy_version="v1",
                purpose_text="Biometric attendance enrollment (demo seed data)",
            )
        )

        base_embedding = _unit_embedding()
        portrait_b64 = _base64_portrait()
        crop_path = save_base64_jpeg(portrait_b64, subdir="employees")
        n_templates = int(rng.integers(2, 4))  # 2-3 templates per employee
        for t in range(n_templates):
            embedding = base_embedding if t == 0 else _noisy_variant(base_embedding)
            db.add(
                FaceTemplate(
                    owner_type=OwnerType.EMPLOYEE,
                    owner_id=employee.id,
                    embedding=embedding,
                    embedding_encrypted=encrypt_embedding(embedding),
                    quality_score=round(float(rng.uniform(0.55, 0.95)), 3),
                    model_version=MODEL_VERSION,
                    source_image_path=crop_path,
                    is_primary=(t == 0),
                )
            )
        employees.append(employee)

    await db.flush()
    print(f"  seeded {len(employees)} employees (2-3 templates each)")
    return employees


async def _seed_attendance(db, employees: list[Employee]) -> None:
    shifts_by_id = {s.id: s for s in (await db.execute(select(Shift))).scalars().all()}
    now_local = datetime.now(LOCAL_TZ)
    today = now_local.date()
    history_days = _working_days_back(12, today)
    all_days = history_days + ([today] if today.weekday() < 5 else [])

    events_created = 0
    for employee in employees:
        shift = shifts_by_id.get(employee.shift_id) if employee.shift_id else None
        shift_in = shift.in_time if shift else datetime.strptime("09:00", "%H:%M").time()
        shift_out = shift.out_time if shift else datetime.strptime("18:00", "%H:%M").time()

        crop_path = None
        template_result = await db.execute(
            select(FaceTemplate.source_image_path).where(
                FaceTemplate.owner_type == OwnerType.EMPLOYEE, FaceTemplate.owner_id == employee.id
            )
        )
        row = template_result.first()
        crop_path = row[0] if row else None

        for day in all_days:
            is_today = day == today
            if pyrng.random() > 0.88:  # ~12% absenteeism, any given day
                continue

            in_local = datetime.combine(day, shift_in, tzinfo=LOCAL_TZ) + timedelta(minutes=pyrng.randint(-5, 25))
            if is_today and in_local > now_local:
                continue  # hasn't "arrived" yet today -- stays absent for now

            out_local = datetime.combine(day, shift_out, tzinfo=LOCAL_TZ) + timedelta(minutes=pyrng.randint(-10, 35))
            skip_out = pyrng.random() < (0.15 if is_today else 0.04)
            if is_today and out_local > now_local:
                skip_out = True

            similarity = round(float(rng.uniform(0.6, 0.97)), 3)
            liveness_score = round(float(rng.uniform(0.85, 0.99)), 3)

            in_data = RecognitionEventInput(
                subject_type=SubjectType.EMPLOYEE,
                employee_id=employee.id,
                unknown_identity_id=None,
                occurred_at=in_local.astimezone(timezone.utc),
                similarity=similarity,
                liveness_score=liveness_score,
                kiosk_id=KIOSK_ID,
                crop_path=crop_path,
                reject_reason=None,
                client_event_id=None,
            )
            await upsert_attendance_event(db, in_data, dedupe_window_minutes=5)
            events_created += 1

            if not skip_out and out_local > in_local:
                out_data = RecognitionEventInput(
                    subject_type=SubjectType.EMPLOYEE,
                    employee_id=employee.id,
                    unknown_identity_id=None,
                    occurred_at=out_local.astimezone(timezone.utc),
                    similarity=round(float(rng.uniform(0.6, 0.97)), 3),
                    liveness_score=round(float(rng.uniform(0.85, 0.99)), 3),
                    kiosk_id=KIOSK_ID,
                    crop_path=crop_path,
                    reject_reason=None,
                    client_event_id=None,
                )
                await upsert_attendance_event(db, out_data, dedupe_window_minutes=5)
                events_created += 1

    # A couple of pre-identification rejects today, so the dashboard's
    # "liveness_failure" exception kind has something to show too.
    for _ in range(2):
        reject_time = now_local - timedelta(minutes=pyrng.randint(5, 180))
        if reject_time > now_local:
            continue
        reject_data = RecognitionEventInput(
            subject_type=None,
            employee_id=None,
            unknown_identity_id=None,
            occurred_at=reject_time.astimezone(timezone.utc),
            similarity=None,
            liveness_score=round(float(rng.uniform(0.1, 0.5)), 3),
            kiosk_id=KIOSK_ID,
            crop_path=None,
            reject_reason=RejectReason.LIVENESS_FAILED,
            client_event_id=None,
        )
        await upsert_attendance_event(db, reject_data, dedupe_window_minutes=5)
        events_created += 1

    await db.flush()
    print(f"  seeded {events_created} attendance events across {len(all_days)} days (incl. today)")


async def _seed_unknowns(db) -> None:
    created = 0
    for _ in range(5):
        base_embedding = _unit_embedding()
        portrait_b64 = _base64_portrait()
        sightings = int(rng.integers(2, 5))  # 2-4 sightings
        first_seen_days_ago = pyrng.randint(1, 10)

        for s in range(sightings):
            embedding = base_embedding if s == 0 else _noisy_variant(base_embedding, noise_std=0.05)
            crop_path = save_base64_jpeg(portrait_b64, subdir="unknowns")
            occurred_at_local = datetime.now(LOCAL_TZ) - timedelta(
                days=first_seen_days_ago - int(s * first_seen_days_ago / max(sightings - 1, 1)),
                hours=pyrng.randint(0, 8),
            )
            result = await cluster_or_create_unknown(
                db,
                embedding=embedding,
                quality_score=round(float(rng.uniform(0.4, 0.85)), 3),
                crop_path=crop_path,
                model_version=MODEL_VERSION,
                unknown_cluster_threshold=0.55,
                unknown_max_templates=5,
                occurred_at=occurred_at_local.astimezone(timezone.utc),
            )
            event_data = RecognitionEventInput(
                subject_type=SubjectType.UNKNOWN,
                employee_id=None,
                unknown_identity_id=result.unknown.id,
                occurred_at=occurred_at_local.astimezone(timezone.utc),
                similarity=result.similarity,
                liveness_score=round(float(rng.uniform(0.8, 0.98)), 3),
                kiosk_id=KIOSK_ID,
                crop_path=crop_path,
                reject_reason=RejectReason.BELOW_THRESHOLD,
                client_event_id=None,
            )
            await upsert_attendance_event(db, event_data, dedupe_window_minutes=5)
        created += 1

    await db.flush()
    print(f"  seeded {created} unknown identities (2-4 sightings each)")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(func.count()).select_from(Employee))).scalar_one()
        if existing > 0:
            print(f"Refusing to seed: {existing} employee(s) already exist. Nothing to do.")
            return
        events = (await db.execute(select(func.count()).select_from(AttendanceEvent))).scalar_one()
        unknowns = (await db.execute(select(func.count()).select_from(UnknownIdentity))).scalar_one()
        profile = await load_raw(db)
        if events or unknowns or profile:
            print(
                "Refusing to seed: this database already has real data "
                f"({events} attendance events, {unknowns} unknown faces"
                f"{', a client profile' if profile else ''}).\n"
                "Demo data must never be mixed into a real install. Use a separate DB, e.g.\n"
                "    set DATABASE_URL=sqlite+aiosqlite:///./demo.db"
            )
            return

        print("Seeding demo data...")
        employees = await _seed_employees(db)
        await _seed_attendance(db, employees)
        await _seed_unknowns(db)
        await db.commit()
        print("Demo data seeded successfully.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
