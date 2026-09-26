#!/usr/bin/env python
"""Bulk-import people (employees / students / staff) with their photos.

For a new client with 50-2000 people, instead of adding everyone by hand:

  1. Get a sheet from the client and save it as CSV (Excel: File > Save As >
     CSV UTF-8). Start from the template:
         python scripts/import_people.py --template people.csv
     Columns (only emp_code and name are required):
         emp_code, name, department, designation, shift, home_camera, contractor
     `department` must be one of the departments set with setup_client.py,
     `shift` is a shift NAME (e.g. General, Night), `home_camera` a camera id.

  2. Put photos in one folder, named by ID -- one or more per person:
         photos/EMP001.jpg  photos/EMP001_2.jpg  photos/EMP001-left.png
     or one sub-folder per person:  photos/EMP001/*.jpg
     Best: 3-5 clear, front-facing photos per person, face at least 200 px.

  3. With the backend RUNNING, from the backend folder:
         python scripts/import_people.py --csv people.csv --photos D:\\client\\photos --dry-run
         python scripts/import_people.py --csv people.csv --photos D:\\client\\photos

It uses the normal API (same checks as the web UI: department list, camera
cap, consent, photo quality) and records consent for every person -- only
import people whose written consent the client has collected. A result file
`<csv name>_result.csv` lists, per person, what happened and which photos
were rejected (and why), so you know exactly whom to re-photograph.

Re-running is safe: people whose ID already exists are not created twice;
photos are only added for them with --add-photos.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import sys
from pathlib import Path
from typing import Any

import httpx

COLUMNS = ["emp_code", "name", "department", "designation", "shift", "home_camera", "contractor"]
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_PHOTOS = 5


def write_template(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerow(["EMP001", "Ravi Kumar", "Production", "Operator", "General", "main-gate", "Sharma Manpower"])
        w.writerow(["EMP002", "Anita Singh", "Quality", "Inspector", "Night", "main-gate", ""])
    print(f"Template written: {path}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"emp_code", "name"} - {c.strip().lower() for c in (reader.fieldnames or [])}
        if missing:
            sys.exit(f"ERROR: CSV is missing column(s): {', '.join(sorted(missing))}")
        rows = []
        for raw in reader:
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            if row.get("emp_code") and row.get("name"):
                rows.append(row)
        return rows


def photos_for(folder: Path | None, code: str) -> list[Path]:
    if folder is None:
        return []
    found: list[Path] = []
    sub = folder / code
    if sub.is_dir():
        found = [p for p in sorted(sub.iterdir()) if p.suffix.lower() in PHOTO_EXT]
    else:
        low = code.lower()
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in PHOTO_EXT:
                stem = p.stem.lower()
                if stem == low or stem.startswith(low + "_") or stem.startswith(low + "-") or stem.startswith(low + " "):
                    found.append(p)
    return found[:MAX_PHOTOS]


class Api:
    def __init__(self, base: str, email: str, password: str) -> None:
        self.c = httpx.Client(base_url=base.rstrip("/") + "/api/v1", timeout=120)
        try:
            r = self.c.post("/auth/login", json={"email": email, "password": password})
        except httpx.ConnectError:
            sys.exit(f"ERROR: cannot reach the backend at {base} -- start it first (uvicorn app.main:app).")
        if r.status_code != 200:
            sys.exit(f"ERROR: login failed ({r.status_code}): {r.text[:200]}")
        self.c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    def existing_codes(self) -> dict[str, str]:
        out: dict[str, str] = {}
        page = 1
        while True:
            r = self.c.get("/employees", params={"page": page, "page_size": 500})
            r.raise_for_status()
            data = r.json()
            for e in data["items"]:
                out[e["emp_code"]] = e["id"]
            if page * data["page_size"] >= data["total"]:
                return out
            page += 1

    def shifts(self) -> dict[str, str]:
        return {s["name"].strip().lower(): s["id"] for s in self.c.get("/shifts").json()}


def err(r: httpx.Response) -> str:
    try:
        body = r.json()
        d = body.get("detail")
        if isinstance(d, dict):
            return f"{d.get('code')}: {d.get('detail')}"
        if body.get("errors"):
            return f"invalid: {body['errors'][0].get('loc', ['?'])[-1]} {body['errors'][0].get('msg', '')}"
        return str(d or body)[:200]
    except ValueError:
        return r.text[:200]


def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk-import people and photos", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--template", type=Path, help="write an example CSV here and exit")
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--photos", type=Path, help="folder with <ID>.jpg files or <ID>/ sub-folders")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--email", help="admin login (asked if not given)")
    ap.add_argument("--password", help="avoid: stays in shell history")
    ap.add_argument("--dry-run", action="store_true", help="check the CSV and photos, change nothing")
    ap.add_argument("--add-photos", action="store_true", help="also add photos for people who already exist")
    ap.add_argument("--consent-policy", default="v1")
    ap.add_argument("--consent-purpose", default="Biometric attendance (consent collected on paper by the organisation)")
    args = ap.parse_args()

    if args.template:
        write_template(args.template)
        return
    if not args.csv:
        ap.error("--csv is required (or use --template to get one)")
    if args.photos and not args.photos.is_dir():
        sys.exit(f"ERROR: photos folder not found: {args.photos}")

    rows = read_rows(args.csv)
    seen: set[str] = set()
    dupes: list[str] = []
    for r in rows:
        (dupes if r["emp_code"] in seen else []).append(r["emp_code"])
        seen.add(r["emp_code"])
    if dupes:
        sys.exit(f"ERROR: duplicate IDs in the CSV: {', '.join(sorted(set(dupes)))}")
    no_photo = [r["emp_code"] for r in rows if args.photos and not photos_for(args.photos, r["emp_code"])]
    print(f"{len(rows)} people in {args.csv.name}; {len(rows) - len(no_photo)} with photos.")
    if no_photo:
        print(f"  No photo found for {len(no_photo)}: {', '.join(no_photo[:15])}{' ...' if len(no_photo) > 15 else ''}")
    if args.dry_run:
        print("Dry run: nothing was changed. Remove --dry-run to import.")
        return

    email = args.email or input("Admin email: ")
    api = Api(args.api, email, args.password or getpass.getpass("Password: "))
    existing = api.existing_codes()
    shifts = api.shifts()

    results: list[dict[str, Any]] = []
    for i, r in enumerate(rows, 1):
        code = r["emp_code"]
        res: dict[str, Any] = {"emp_code": code, "name": r["name"], "status": "", "photos_ok": 0, "photos_rejected": "", "error": ""}
        try:
            if code in existing:
                emp_id = existing[code]
                res["status"] = "already existed"
                if not args.add_photos:
                    results.append(res)
                    print(f"[{i}/{len(rows)}] -- {code} {r['name']}: already existed (use --add-photos to add photos)")
                    continue
            else:
                shift_id = None
                if r.get("shift"):
                    shift_id = shifts.get(r["shift"].lower())
                    if shift_id is None:
                        raise ValueError(f"unknown shift '{r['shift']}' (known: {', '.join(shifts)})")
                body = {
                    "emp_code": code, "name": r["name"],
                    "department": r.get("department") or None, "designation": r.get("designation") or None,
                    "shift_id": shift_id, "home_kiosk_id": r.get("home_camera") or None,
                    "contractor": r.get("contractor") or None,
                }
                cr = api.c.post("/employees", json=body)
                if cr.status_code != 201:
                    raise ValueError(err(cr))
                emp_id = cr.json()["id"]
                existing[code] = emp_id
                con = api.c.post(f"/employees/{emp_id}/consent",
                                 json={"policy_version": args.consent_policy, "purpose_text": args.consent_purpose})
                if con.status_code != 201:
                    raise ValueError("consent: " + err(con))
                res["status"] = "created"
            pics = photos_for(args.photos, code)
            if pics:
                files = [("files", (p.name, p.read_bytes(), "image/jpeg")) for p in pics]
                er = api.c.post(f"/employees/{emp_id}/enroll", files=files)
                if er.status_code != 200:
                    raise ValueError("photos: " + err(er))
                out = er.json()
                res["photos_ok"] = out["accepted_count"]
                res["photos_rejected"] = "; ".join(f"{x['filename']} ({x['reason']})" for x in out["results"] if not x["accepted"])
                if out["accepted_count"] == 0:
                    res["error"] = "no usable photo -- will not be recognised until re-photographed"
            elif args.photos:
                res["error"] = "no photo found -- will not be recognised"
        except (ValueError, httpx.HTTPError) as exc:
            res["status"] = res["status"] or "failed"
            res["error"] = str(exc)
        results.append(res)
        mark = "OK " if not res["error"] else "!! "
        print(f"[{i}/{len(rows)}] {mark}{code} {r['name']}: {res['status']}, {res['photos_ok']} photo(s) {res['error']}")

    out_path = args.csv.with_name(args.csv.stem + "_result.csv")
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0].keys()) if results else ["emp_code"])
        w.writeheader()
        w.writerows(results)
    created = sum(1 for x in results if x["status"] == "created")
    problems = sum(1 for x in results if x["error"])
    print(f"\nDone: {created} created, {problems} need attention. Details: {out_path}")


if __name__ == "__main__":
    main()
