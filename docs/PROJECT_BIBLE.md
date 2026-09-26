# Face Attendance: Project Bible

> Is project ki poori kitaab. Ek AI engineer ke liye likhi gayi hai jisne model to banaye hain, lekin kabhi poora end-to-end deployment nahi kiya.
> Shuru se padho, ya Contents se seedha chapter par jao. Har command copy-paste karke chal sakti hai.
>
> Last updated: 26 Sep 2026 · Code: branch `feature/product-v2`

## Contents

1. [Product 10 minute me](#1-product-10-minute-me)
2. [Ek chehra system me kaise chalta hai (data flow)](#2-ek-chehra-system-me-kaise-chalta-hai)
3. [Folder ka naksha](#3-folder-ka-naksha)
4. [Apne laptop par chalana (Windows, bina Docker)](#4-apne-laptop-par-chalana-windows-bina-docker)
5. [Git: is project ke liye sab kuch](#5-git-is-project-ke-liye-sab-kuch)
6. [Configuration: .env, Settings, client profile](#6-configuration)
7. [Database, migrations, backup](#7-database-migrations-backup)
8. [Admin scripts](#8-admin-scripts)
9. [Recognition tuning](#9-recognition-tuning)
10. [Testing aur release checklist](#10-testing-aur-release-checklist)
11. [Docker: kya, kyun, kaise](#11-docker-kya-kyun-kaise)
12. [Production deployment ke 3 tareeke](#12-production-deployment-ke-3-tareeke)
13. [Troubleshooting](#13-troubleshooting)
14. [Security, privacy aur DPDP](#14-security-privacy-aur-dpdp)
15. [Known gaps aur roadmap](#15-known-gaps-aur-roadmap)
16. [Command cheat-sheet](#16-command-cheat-sheet)

---

## 1. Product 10 minute me

**Kya karta hai:** entry gate ke CCTV/IP camera (ya USB webcam) se log bina ruke guzarte hain. System unka chehra pehchaan kar attendance (IN/OUT) lagata hai. Dashboard par live attendance, analytics, reports aur payroll export milta hai, aur WhatsApp par alerts aate hain.

**Teen hisse (teeno alag process hain):**

```
 Camera ──RTSP/USB──> KIOSK (Python)            BACKEND (FastAPI)               FRONTEND (React)
                      har camera ka ek         ek hi server                    browser me dashboard
                      - motion, face detect    - matching, IN/OUT              - Dashboard, Reports,
                      - quality + liveness     - database, reports               Shifts, Muster, Sites
                      - embedding (ArcFace)    - alerts, WhatsApp              - admin edits
                             │                         ▲   │                           │
                             └── POST /kiosk/event ────┘   └──── /api/v1/* (JSON) ─────┘
                                 (sirf 512 numbers +
                                  chhoti crop photo)
                                                       │
                                            SQLite (dev.db) ya PostgreSQL
                                            + D:\data\media (face crops)
```

| Hissa | Folder | Language / framework | Chalane ki command |
|---|---|---|---|
| Kiosk | `kiosk/` | Python 3.11, OpenCV, InsightFace `buffalo_l`, ONNX Runtime, MiniFASNet | `python -m kiosk.main` |
| Backend | `backend/` | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | `uvicorn app.main:app` |
| Frontend | `frontend/` | React 18, TypeScript, Vite, Tailwind, Recharts | `npm run dev` |
| Database | `backend/dev.db` | SQLite (abhi); Docker me PostgreSQL + pgvector | apne aap |

**Kuch zaroori shabd:**

- **Embedding:** ek chehre ke 512 numbers. Do chehron ke embedding ka *cosine similarity* 1 ke paas ho to same insaan, 0 ke paas ho to alag.
- **Template:** enrolled person ka saved embedding. Har person ke 1–5 hote hain (alag photos se).
- **Threshold:** kitni similarity par "ye wahi hai" maana jaaye (`similarity_threshold` = 0.38).
- **Unknown identity (UNK-xxxx):** jo chehra kisi employee se match nahi hua. Uske repeat visits ek hi UNK id me jude rehte hain.
- **Liveness:** asli chehra hai ya photo/phone screen, ye MiniFASNet batata hai.
- **Kiosk ID:** camera ka naam (`main-gate`). Har kiosk process ek camera chalata hai.

---

## 2. Ek chehra system me kaise chalta hai

Kiosk ki file `kiosk/kiosk/pipeline.py` me har frame ke saath ye hota hai:

1. **Capture** (`capture.py`): camera se frame aata hai (`CAMERA_SOURCE` = `0` USB, ya `rtsp://...`).
2. **Motion gate** (`motion_gate.py`): kuch hila hi nahi to aage kuch nahi hota. CPU bachata hai.
3. **Detect** (`face_engine.py`, SCRFD): frame me chehre dhoondhta hai.
4. **Subject gate** (`subject_gate.py`): wahi aadmi abhi-abhi process hua tha to skip karta hai.
5. **Best-shot buffer** (`bestshot.py`): 1–2 second ke frames me se sabse achha chuna jaata hai.
6. **Quality gate** (`quality.py`): dhundla, andhera, sir jhuka ya aadha chehra ho to reject. Kharab photo ka embedding kabhi sahi match nahi hota, isliye yahi rok dete hain.
7. **Liveness** (`liveness.py`): MiniFASNet V2 + V1SE. Photo ya screen lagi to reject aur spoof alert. Model na ho to reject (fail-closed).
8. **Embed** (ArcFace): 512 numbers banate hain.
9. **Send** (`api_client.py`): `POST /api/v1/kiosk/event` par bhejte hain. Internet ya backend band ho to `offline_queue.py` me save ho jaata hai aur baad me bhej diya jaata hai.

Backend ki file `backend/app/services/recognition.py` me:

10. **Match** (`matching.py`): saare employee templates se cosine similarity nikalti hai. ≥ threshold ho to employee maana jaata hai.
11. **Match nahi hua** to `unknown_identity.py` chalta hai: purane UNK se jodta hai (same camera par thodi der pehle dikha ho to dheela threshold), warna naya UNK banata hai.
12. **IN/OUT** (`attendance.py`): din ka pehla sighting IN, baad ke OUT (latest wins). 5 min ke andar ke duplicates ek hi row me jud jaate hain. Night shift ke liye din `shiftday.py` tay karta hai.
13. **Alerts** (`alerts.py`): watchlist wala person dikhe ya spoof ho to alert banta hai, aur `notify.py` se WhatsApp par jaata hai.
14. Dashboard har 30 second me refresh hota hai aur naya record dikh jaata hai.

Reports (`timesheet.py`) in events se har person ka har din nikaalte hain: P / HD / A / WO, late minutes, overtime. Payroll, contractor aur muster roll sab isi se bante hain, isliye sab reports ke numbers aapas me match karte hain.

---

## 3. Folder ka naksha

```
face-attendance/
├── backend/                     FastAPI server
│   ├── app/
│   │   ├── main.py              app banana, routers jodna, startup par migrations + background loops
│   │   ├── config.py            .env se infra settings (DB url, secrets, media path)
│   │   ├── models/              database tables (SQLAlchemy)
│   │   ├── schemas/             API ke request/response shapes (Pydantic)
│   │   ├── routers/             API endpoints (URL -> function)
│   │   ├── services/            asli logic (matching, attendance, timesheet, alerts ...)
│   │   └── migrations/versions/ Alembic migrations 0001 ... 0005
│   ├── scripts/                 admin tools (users, cameras, client setup, import, reset)
│   ├── tests/                   pytest
│   ├── requirements.txt         Python libraries
│   └── dev.db                   SQLite database (GIT ME NAHI jaata)
├── kiosk/
│   ├── kiosk/                   camera pipeline (upar ka section 2)
│   └── tests/
├── frontend/
│   ├── src/pages/               ek file = ek page (Dashboard, Reports, Shifts, Muster ...)
│   ├── src/components/          reusable UI (tables, drawer, bell, forms)
│   ├── src/api/                 client.ts (API calls) + types.ts
│   └── package.json
├── docs/                        ye kitaab + client deployment + business docs
├── docker-compose.yml           Docker se sab ek saath chalane ke liye
├── .env.example                 .env ka namoona (asli .env git me nahi jaata)
└── Makefile                     Linux/Mac shortcuts (make up, make test)

Code ke comments me kahin-kahin `docs/DECISIONS.md`, `ARCHITECTURE.md`, `TUNING.md`, `RUNBOOK.md` ka zikr hai.
Wo purane engineering notes the, jo ab is kitaab me mila diye gaye hain. Poora purana text chahiye to git history me hai:
`git show 8f46b35:docs/DECISIONS.md` (isi tarah baaki files ke naam se).

Project ke bahar:
D:\data\media\                   face crops (events\, unknowns\, employees\)
D:\models\                       downloaded AI models (buffalo_l, minifasnet)
D:\data\queue\                   kiosk ki offline queue
```

`/data/media` aur `/models` Windows par us drive ke root par bante hain jahan se command chalayi (yaani `D:\data\media`). Inhe `.env` me `MEDIA_ROOT` aur `MODEL_CACHE_DIR` se badal sakte ho.

---

## 4. Apne laptop par chalana (Windows, bina Docker)

### 4.1 Ek baar ka setup

| Tool | Version | Kyun |
|---|---|---|
| Python | 3.11 | backend + kiosk |
| Node.js | 20 LTS | frontend |
| Git | koi bhi naya | code |
| (optional) DB Browser for SQLite | | database dekhne ke liye |

```powershell
# 1. code lao
cd "D:\DS PROJECTS"
git clone https://github.com/Kambovi/face_recognizer face-attendance
cd face-attendance
git checkout feature/product-v2

# 2. backend
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
pip install onnxruntime==1.19.2
deactivate

# 3. kiosk
cd ..\kiosk
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install onnxruntime==1.19.2
deactivate

# 4. frontend
cd ..\frontend
npm install
```

> **PowerShell "running scripts is disabled" error:** ek baar `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` chala do.

### 4.2 `.env` banao (root folder me)

`.env.example` ko copy karke `.env` bana lo. Laptop (SQLite) ke liye ye zaroori lines hain:

```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
DATABASE_URL_SYNC=sqlite:///./dev.db
EMBEDDING_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">
KIOSK_SERVICE_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))">
APP_TIMEZONE=Asia/Kolkata
```

Backend `.env` ko **apne current folder** se padhta hai. Isliye ya to ye file `backend\` me bhi rakho, ya har window me `$env:` se set karo (section 4.3). Kiosk `.env` nahi padhta, use `$env:` chahiye.

### 4.3 Roz chalana: 3 PowerShell windows

**Window 1: Backend**

```powershell
cd "D:\DS PROJECTS\face-attendance\backend"
.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- `--reload` code badalne par apne aap restart karta hai. Sirf development ke liye hai.
- Start hote hi database migrations apne aap lag jaati hain.
- Check: browser me `http://localhost:8000/api/v1/health` kholo. `"status":"ok"` (ya `degraded` agar koi camera nahi chal raha) aana chahiye.
- API ki poori list aur "Try it out": `http://localhost:8000/docs`.

**Window 2: Kiosk (ek window = ek camera)**

```powershell
cd "D:\DS PROJECTS\face-attendance\kiosk"
.venv\Scripts\Activate.ps1
$env:KIOSK_ID="kiosk-01"
$env:CAMERA_SOURCE="0"                           # laptop webcam; IP camera: rtsp://user:pass@192.168.1.50:554/stream1
$env:API_BASE_URL="http://localhost:8000"
$env:KIOSK_SERVICE_TOKEN="<.env wala token>"
python -m kiosk.main
```

Pehli baar chalne par models download honge (`buffalo_l` ~ 300 MB + liveness ~ 3.5 MB). Iske liye internet chahiye.

**Window 3: Frontend**

```powershell
cd "D:\DS PROJECTS\face-attendance\frontend"
npm run dev
```

Browser me `http://localhost:5173` kholo. Pehla login `admin@example.com` / `ChangeMe123!` hai. **Isse turant badlo** (section 8).

**Band karna:** har window me `Ctrl+C`. Order: kiosk → frontend → backend.

### 4.4 Development workflow (code badalna)

1. Nayi branch banao: `git checkout -b feature/meri-cheez` (section 5).
2. Backend badla? `--reload` apne aap restart kar dega.
3. Frontend badla? Vite browser apne aap update kar dega.
4. Kiosk badla? Kiosk window me `Ctrl+C` karke dobara chalao.
5. Database table badli? Migration banao (section 7.3).
6. Commit karne se pehle tests chalao (section 10).

---

## 5. Git: is project ke liye sab kuch

### 5.1 Mental model

- **Repository (repo):** project + uski poori history. Tumhare PC par ek copy hai (`.git` folder), GitHub par doosri (`origin`).
- **Commit:** code ki ek photo, ek message ke saath.
- **Branch:** commits ki ek line. `main` = jo client ko diya ja sakta hai, `bilal_dev` = tumhara kaam, `feature/xyz` = ek naya feature.
- **Push / pull:** tumhare PC → GitHub / GitHub → tumhare PC.

### 5.2 Branch strategy (is project ke liye)

```
main ───────●─────────────────────●────────  (sirf tested, client ko dene layak; har release par tag v2.0.0)
             \                   /
feature/product-v2 ──●──●──●──●─┘            (ek bada kaam; khatam hone par main me merge)
```

- Client ke paas hamesha kisi **tag** ka code jaata hai (`v2.0.0`), branch ka nahi. Isse pata rehta hai kis client par kaunsa version hai.

### 5.3 Roz ki commands

```powershell
git status                              # kya badla, kya commit hona baaki hai
git diff                                # exact badlav dekho
git add backend/app/services/x.py       # ek file stage karo (git add . se bacho, galat file chali jaati hai)
git commit -m "Fix late count for night shift"
git push                                # GitHub par bhejo
git pull                                # GitHub se naya lao
git log --oneline -15                   # pichhle 15 commits
git branch -a                           # saari branches
git checkout -b feature/import-tool     # nayi branch banao aur us par jao
git checkout main                       # branch badlo
```

### 5.4 Release (client ko dene se pehle)

```powershell
git checkout main
git pull
git merge feature/product-v2            # ya GitHub par Pull Request banao aur merge karo
git tag -a v2.0.0 -m "v2: payroll, muster, alerts, multi-site"
git push origin main --tags
```

Client ke PC par install: `git clone ...` karke `git checkout v2.0.0`. Update ke liye `git fetch --tags` aur `git checkout v2.1.0`.

### 5.5 Galti theek karna

| Kya hua | Command |
|---|---|
| Ek file ke badlav phenkne hain (commit nahi hue) | `git restore path\file.py` |
| Stage ki hui file wapas nikalni hai | `git restore --staged path\file.py` |
| Aakhri commit ka message galat hai (push nahi hua) | `git commit --amend -m "naya message"` |
| Kaam adha hai aur branch badalni hai | `git stash`, baad me `git stash pop` |
| Galti se `dev.db` ya `.env` stage ho gaya | `git rm --cached backend/dev.db` (file PC par rahegi) |
| Pichhla commit ulta karna hai (push ho chuka) | `git revert <commit-id>` (history nahi mitti, safe hai) |

### 5.6 Kya kabhi commit nahi karna

`.gitignore` ye sab pehle se rokta hai:

- `.env`: secrets
- `backend/dev.db`, `*.db`: asli logon ka biometric data
- `node_modules/`, `.venv/`: dependencies, jo dobara install ho jaati hain
- `backend/backups/`, `data/`

> Purani history me `.env` aur `dev.db` ek baar chale gaye the. Isliye repo **private** rakho. Chaho to baad me `git filter-repo` se history saaf kar sakte ho.

### 5.7 Bundle (jab internet ya GitHub access na ho)

```powershell
git bundle create update.bundle main..feature/product-v2        # bhejne wala
git fetch .\update.bundle feature/product-v2:feature/product-v2 # lene wala
```

---

## 6. Configuration

Settings teen jagah rehti hain. Kaunsi setting kahan hai, ye yaad rakhna zaroori hai:

| Kahan | Kya | Kaun badalta hai | Restart chahiye? |
|---|---|---|---|
| `.env` / environment variables | DB address, secrets, media path, camera source | Tum (installer) | Haan |
| Settings page (database me `settings` table) | thresholds, OT rules, weekly off, liveness, alerts | Client admin | Nahi, 30 sec me lag jaati hai |
| Client profile (`setup_client.py`) | sector, org naam, departments, camera cap | **Sirf tum**, vendor PIN se | Nahi |

### 6.1 Environment variables

| Variable | Kiske liye | Example / default |
|---|---|---|
| `DATABASE_URL` | backend | `sqlite+aiosqlite:///./dev.db` ya `postgresql+asyncpg://user:pass@db:5432/face_attendance` |
| `DATABASE_URL_SYNC` | backend (Alembic) | `sqlite:///./dev.db` |
| `EMBEDDING_ENCRYPTION_KEY` | backend | Fernet key. **Kho gayi to saare chehre bekaar ho jaate hain.** |
| `JWT_SECRET` | backend | login tokens sign karne ke liye |
| `JWT_EXPIRE_MINUTES` | backend | 480 (8 ghante ka login) |
| `KIOSK_SERVICE_TOKEN` | backend + har kiosk | dono me same hona chahiye |
| `MEDIA_ROOT` | backend | `D:\data\media` |
| `APP_TIMEZONE` | backend | `Asia/Kolkata` |
| `CORS_ORIGINS` | backend | production me dashboard ka address |
| `KIOSK_ID` | kiosk | `main-gate` |
| `CAMERA_SOURCE` | kiosk | `0`, `rtsp://...`, `synthetic` (test) |
| `API_BASE_URL` | kiosk | `http://localhost:8000` |
| `MODEL_CACHE_DIR` | kiosk | `D:\models` |
| `OFFLINE_QUEUE_PATH` | kiosk | har camera ka alag: `D:\data\queue\main-gate.db` |
| `DEVICE_PREFERENCE` | kiosk | `auto` / `cpu` / `cuda` |
| `VITE_API_BASE_URL` | frontend (build time) | `http://192.168.1.10:8000` |

### 6.2 Runtime settings (Settings page)

Sabse zyada kaam aane wali settings:

| Key | Default | Kab badlein |
|---|---|---|
| `similarity_threshold` | 0.38 | Galat aadmi match ho raha hai to badhao (0.42). Apne log "Unknown" aa rahe hain to ghatao (0.34). |
| `unknown_cluster_threshold` | 0.40 | Ek anjaan aadmi ke kai UNK ban rahe hain to ghatao |
| `liveness_threshold` | 0.5 | Har camera par calibrate karo (section 9.3) |
| `liveness_required` | true | Sirf demo me false karna |
| `dedupe_window_minutes` | 5 | |
| `quality_*` | | Kharab frames kitne sakht tareeke se rokne hain |
| `weekly_off_days` | [6] (Sunday) | Settings → Payroll & overtime |
| `ot_min_minutes` / `ot_rounding_minutes` | 30 / 15 | Client ki OT policy ke hisaab se |
| `full_day_min_hours` / `half_day_min_hours` | 0 / 0 | Sirf tab set karo jab exit camera bhi ho |
| `muster_window_hours` | 16 | |
| `alert_cooldown_minutes` | 30 | |

Settings page ke "Advanced (raw JSON)" box me koi bhi key seedha daal sakte ho.

### 6.3 Client profile (vendor lock)

```powershell
python scripts\setup_client.py show
python scripts\setup_client.py init --type school --name "St. Mary's School" --departments "Class 1-A" "Class 1-B" --camera-cap 200
python scripts\setup_client.py update --add-department "Class 2-A"        # PIN maangega
```

---

## 7. Database, migrations, backup

### 7.1 Tables

| Table | Kya hai |
|---|---|
| `employees` | log (naam, ID, department, shift, home camera, contractor, watchlist) |
| `face_templates` | har person ke embeddings (encrypted copy ke saath) |
| `consents` | photo ki anumati ka record (DPDP) |
| `attendance_events` | har IN/OUT, rejects (liveness fail, too small) bhi |
| `unknown_identities` | UNK-xxxx chehre |
| `shifts`, `shift_assignments` | shifts aur roster |
| `alerts` | watchlist/spoof alerts |
| `sites` | head-office par juri factories |
| `settings` | runtime settings + client profile + WhatsApp config |
| `users` | dashboard logins |
| `audit_log` | kisne kya badla (sab edits) |
| `kiosk_heartbeats` | camera zinda hai ya nahi |

### 7.2 SQLite vs PostgreSQL

| | SQLite (abhi) | PostgreSQL + pgvector (Docker) |
|---|---|---|
| Setup | kuch nahi, ek file | server chahiye (Docker me 1 line) |
| Kitne log / camera | ~500 log, 2–3 camera tak theek | hazaaron log, kai camera |
| Face search | Python me sab templates scan karta hai | database ke andar vector index se |
| Ek saath likhna | ek writer (kai kiosk hon to wait) | bahut saare |
| Backup | file copy / `reset_data.py` backup | `pg_dump` |

Chhote client (< 300 log, 1–2 camera) ke liye SQLite theek hai. Bade client ke liye Postgres use karo (section 11).

### 7.3 Migrations (Alembic)

Table me column jodna ho to seedha database mat chhedo, migration banao:

```powershell
cd backend
.venv\Scripts\Activate.ps1
# 1. app/models/... me column jodo
# 2. migration file banao (auto-detect)
alembic revision --autogenerate -m "add employee blood group"
# 3. app/migrations/versions/ me bani file PADHO aur theek karo
#    (SQLite ke liye op.batch_alter_table use karo, 0002-0005 dekho)
# 4. lagao (backend start par apne aap bhi lagti hai)
alembic upgrade head
alembic current          # kaunsa version laga hai
alembic downgrade -1     # ek step wapas (sirf dev me)
```

Har migration ko pehle **asli DB ki copy** par test karo.

### 7.4 Backup aur restore

**SQLite:** backend chalte hue bhi safe backup:

```powershell
cd backend
.venv\Scripts\python.exe -c "import sqlite3,datetime; s=sqlite3.connect('dev.db'); d=sqlite3.connect('backups/dev-'+datetime.date.today().isoformat()+'.db'); s.backup(d); d.close(); s.close()"
```

Isse Windows Task Scheduler me roz raat chala do. `D:\data\media` bhi hafte me ek baar doosri drive par copy karo.

**Restore:** backend band karo → backup file ko `dev.db` naam se copy karo → backend chalao.

**Postgres (Docker):**

```bash
docker compose exec -T db pg_dump -U face_attendance face_attendance | gzip > backup_$(date +%F).sql.gz
gunzip -c backup_2026-09-26.sql.gz | docker compose exec -T db psql -U face_attendance face_attendance
```

> **Backup ke saath `.env` (khaaskar `EMBEDDING_ENCRYPTION_KEY`) bhi rakho.** Key ke bina backup kisi kaam ka nahi.

### 7.5 Data saaf karna

Dekho `backend/scripts/reset_data.py`. Modes: `show`, `attendance`, `people`, `all`. Ye hamesha pehle backup leta hai:

```powershell
python scripts\reset_data.py show
python scripts\reset_data.py attendance --before 2026-10-01
python scripts\reset_data.py all --purge-media          # fresh install jaisa
```

---

## 8. Admin scripts

Sab `backend` folder se, venv activate karke, chalte hain:

| Script | Kaam | Example |
|---|---|---|
| `manage_users.py` | dashboard logins | `create --email hr@x.com --role admin`, `reset-password --email ...`, `delete --email admin@example.com` |
| `manage_cameras.py` | camera ka naam badalna (purana data saath jaata hai) | `rename --old kiosk-01 --new main-gate` |
| `setup_client.py` | vendor lock (sector, departments, cap) | section 6.3 |
| `import_people.py` | **CSV + photos se bulk import** | `--template people.csv`, phir `--csv people.csv --photos D:\photos` |
| `reset_data.py` | data saaf karna, backup ke saath | section 7.5 |
| `seed_demo.py` | 100 nakli log, **sirf alag demo DB par** | `$env:DATABASE_URL="sqlite+aiosqlite:///./demo.db"` phir chalao |
| `kiosk.liveness_check` (kiosk folder se) | liveness calibration | section 9.3 |

---

## 9. Recognition tuning

### 9.1 Camera sabse bada factor hai

- 1080p ya zyada. Chehra frame me **kam se kam 80 px** chauda ho (120+ behtar).
- Aankh ki height par lagao (1.5–1.8 m). Jhukav 15° se kam ho.
- Roshni saamne se aaye. Peeche khidki ya tez light (backlight) na ho.
- Aisi jagah jahan log ek-ek karke camera ki taraf dekhte hue chalein.

Achhe camera aur roshni ke saath default settings kaafi hain. Kharab camera ki kami koi threshold theek nahi kar sakta.

### 9.2 Lakshan → ilaaj

| Lakshan | Pehle ye check karo | Phir ye setting |
|---|---|---|
| Enrolled aadmi "Unknown" aata hai | enrollment photos (3–5, saaf, seedhi), camera angle | `similarity_threshold` 0.38 → 0.34 |
| Ek aadmi ko doosra samajh liya | dono ki photos, kahin jaanne wale jaise to nahi dikhte | `similarity_threshold` → 0.42–0.45 |
| Ek anjaan ke kai UNK ids | roshni, sir jhuka hua | `unknown_cluster_threshold` ↓, `quality_*` sakht |
| Log dikhe hi nahi | `min_face_pixels` se chhota chehra, motion gate | camera paas lao |
| Asli log liveness fail | calibration | `liveness_threshold` ↓ |
| Ek visit ke 2 IN | `dedupe_window_minutes` ↑ | |

### 9.3 Liveness calibration (har camera par ek baar)

```powershell
cd kiosk
.venv\Scripts\Activate.ps1
$env:CAMERA_SOURCE="rtsp://..."
python -m kiosk.liveness_check --label real  --seconds 30     # 3-4 log normal guzrein
python -m kiosk.liveness_check --label spoof --seconds 30     # phone par photo dikhao, printout dikhao
python -m kiosk.liveness_check --recommend
```

Jo number aaye, use Settings me `liveness_threshold` me daal do. Agar "overlap" warning aaye to pehle roshni ya angle theek karo.

---

## 10. Testing aur release checklist

```powershell
# Backend
cd backend; .venv\Scripts\Activate.ps1
python -m pytest -q                 # ~69 tests
ruff check app tests scripts        # style / bugs
mypy app                            # types

# Kiosk
cd ..\kiosk; .venv\Scripts\Activate.ps1
python -m pytest -q
ruff check kiosk tests

# Frontend
cd ..\frontend
npx tsc -b                          # TypeScript errors
npm run lint
npx vitest run
npm run build                       # production build
```

**Release se pehle:**

- [ ] Saare tests aur lint pass
- [ ] Nayi migration asli DB ki copy par test ki
- [ ] Laptop par 1 din asli camera ke saath chalaya
- [ ] Liveness photo aur phone se test ki
- [ ] Report, payroll aur PDF ek baar download karke dekhe
- [ ] `git tag vX.Y.Z` banaya aur release notes likhe

---

## 11. Docker: kya, kyun, kaise

### 11.1 Docker kya hai (AI engineer ki bhasha me)

Docker ek **container** banata hai: tumhara code + Python + saari libraries + OS ki zaroori cheezein, ek band dabbe me. Wo dabba kisi bhi machine par bilkul ek jaisa chalta hai. Jaise tum model ke saath `requirements.txt` bhejte ho, Docker usse aage jaakar *poora environment* bhej deta hai.

- **Image:** dabbe ka blueprint (`backend/Dockerfile` se banta hai).
- **Container:** chalta hua dabba.
- **Volume:** container ke bahar rehne wala data (database, photos, models). Container hat jaaye to bhi data bacha rehta hai.
- **docker compose:** kai containers ek file (`docker-compose.yml`) se ek saath chalana.

Is project ki compose file me 4 services hain:

```
db     PostgreSQL 16 + pgvector      volume: pgdata
api    backend (FastAPI)             volumes: media, models     port 8000
kiosk  camera pipeline               volumes: models, kiosk_queue
web    frontend (nginx)              port 3000
```

### 11.2 Is project ke liye Docker ke fayde

| Fayda | Bina Docker (abhi) | Docker ke saath |
|---|---|---|
| Naye client par install | Python, Node, venv, pip, npm: 1–2 ghante, har PC par alag problem | `docker compose up -d`: 10 min |
| "Mere laptop par to chal raha tha" | Python version ya DLL ka farak | har jagah same image |
| Auto start / crash hone par restart | khud script ya NSSM banao | `restart: unless-stopped` pehle se hai |
| Database | SQLite (ek writer) | PostgreSQL + pgvector (bade clients, kai camera) |
| Update | har folder me pull aur pip | `git pull && docker compose up -d --build` |
| Rollback | mushkil | purane tag ki image chala do |
| Backup | files dhoondo | volumes + `pg_dump` |
| GPU | CUDA khud install karo | `ORT_FLAVOR=gpu` + ek block uncomment |

### 11.3 Nuksaan aur saavdhaniyan (zaroor padho)

1. **RAM:** Docker Desktop khud ~2 GB leta hai, aur containers ~3 GB (compose me limits: db 512 MB, api 1.5 GB, kiosk 1 GB). Kam se kam 8 GB RAM chahiye, 16 GB behtar. Tumhara laptop isi wajah se slow tha. Client ka server alag machine hogi.
2. **Windows par USB webcam container ke andar nahi pahunchti.** Docker Desktop (WSL2) USB camera pass nahi karta. Iske do hal hain:
   - (a) **IP camera (RTSP)** use karo. Ye network par hota hai aur container se seedha chalta hai. Production me ye hi sahi hai.
   - (b) Kiosk ko **native** chalao (section 4.3) aur baaki (`db`, `api`, `web`) Docker me.
3. **Docker Desktop ka license:** chhoti company (250 se kam employees *aur* $10M se kam revenue) ke liye free hai. Bade client (hospital chain, badi factory) ke server par Docker Desktop lagaoge to unhe paid subscription chahiye. Isse bachne ke liye client server par **Linux + Docker Engine** chalao, jo poori tarah free/open-source hai ([Docker FAQ](https://www.docker.com/pricing/faq/)).
4. **Existing SQLite data Postgres me apne aap nahi jaata.** Laptop ka data demo tha, isliye naye client ko seedha Postgres par shuru karo.

### 11.4 Docker install

- **Windows (tumhara laptop):** WSL2 enable karo (`wsl --install`, phir restart), phir Docker Desktop install karo. Settings → Resources me RAM 6 GB tak do.
- **Client server (Ubuntu 22.04/24.04), sabse achha:**

  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER      # logout/login
  docker --version && docker compose version
  ```

### 11.5 Pehli baar chalana

```bash
git clone https://github.com/Kambovi/face_recognizer face-attendance
cd face-attendance
git checkout v2.0.0                   # ya feature/product-v2
cp .env.example .env
# .env me badlo: POSTGRES_PASSWORD, JWT_SECRET, EMBEDDING_ENCRYPTION_KEY, KIOSK_SERVICE_TOKEN,
# DATABASE_URL / DATABASE_URL_SYNC (naye password ke saath), CAMERA_SOURCE (rtsp://...),
# KIOSK_ID, VITE_API_BASE_URL=http://<server-ip>:8000

docker compose up -d --build          # sab build karke background me chalao
docker compose ps                     # sab "healthy/running" hone chahiye
docker compose logs -f api            # backend ke logs (Ctrl+C se bahar)
curl http://localhost:8000/api/v1/health
```

Dashboard: `http://<server-ip>:3000`. Migrations `api` container start par apne aap chalti hain.

Admin scripts container ke andar chalte hain:

```bash
docker compose exec api python scripts/manage_users.py create --email hr@client.com --role admin
docker compose exec api python scripts/setup_client.py init --type hospital --name "City Care" --departments OPD ICU
docker compose exec -it api python scripts/import_people.py --csv /data/import/people.csv --photos /data/import/photos --api http://localhost:8000
```

Import ke liye CSV aur photos container me pahunchane hain: `api` service ki `volumes:` list me `- ./import:/data/import` jodo.

### 11.6 Roz ki Docker commands

| Kaam | Command |
|---|---|
| Sab chalu | `docker compose up -d` |
| Sab band (data safe) | `docker compose down` |
| Status | `docker compose ps` |
| Logs | `docker compose logs -f api` / `kiosk` / `web` |
| Ek service restart | `docker compose restart kiosk` |
| Container ke andar shell | `docker compose exec api bash` |
| Code update | `git pull && docker compose up -d --build` |
| Disk bharne lage | `docker system prune` (purani images hata deta hai) |
| **Sab kuch + DATA mitana (khatarnak)** | `docker compose down -v` |

### 11.7 Ek se zyada camera

`docker-compose.yml` me har camera ke liye `kiosk` service ki copy banao, alag naam aur alag queue volume ke saath:

```yaml
  kiosk-gate2:
    build: { context: ./kiosk, args: { ORT_FLAVOR: "${ORT_FLAVOR:-cpu}" } }
    restart: unless-stopped
    depends_on: { api: { condition: service_healthy } }
    environment:
      API_BASE_URL: http://api:8000
      KIOSK_ID: gate-2
      KIOSK_SERVICE_TOKEN: ${KIOSK_SERVICE_TOKEN}
      CAMERA_SOURCE: rtsp://user:pass@192.168.1.51:554/stream1
      MODEL_CACHE_DIR: /models
    volumes:
      - models:/models
      - kiosk_queue_gate2:/data/queue
    mem_limit: 1024m
# aur neeche volumes: me  kiosk_queue_gate2:
```

Ek CPU server par 2–4 camera aaram se chalte hain. Usse zyada ho to GPU wala server lo (section 11.8).

### 11.8 GPU

`.env` me `ORT_FLAVOR=gpu` karo, compose me `api` aur `kiosk` ke `deploy:` blocks uncomment karo, aur server par NVIDIA driver + `nvidia-container-toolkit` install karo. Phir `docker compose up -d --build`.

### 11.9 Hybrid (tumhare laptop ke liye best)

```powershell
docker compose up -d db api web      # sirf ye teen Docker me
# kiosk native chalao (section 4.3) with API_BASE_URL=http://localhost:8000
```

---

## 12. Production deployment ke 3 tareeke

| | A. Windows PC native | B. Linux mini-server + Docker (**recommended**) | C. Multi-site + head office |
|---|---|---|---|
| Kab | chhota client, 1–2 camera, Windows PC hi milega | zyaadatar clients | ek owner, kai factories |
| Hardware | client ka i5/16GB PC | mini-PC (i5/i7, 16 GB, 512 GB SSD) ~ ₹35–60k, ya client ka server | har site par B + ek cloud VM (2 vCPU / 4 GB) |
| Auto-start | NSSM services (neeche) | Docker `restart: unless-stopped` | wahi |
| DB | SQLite | Postgres | har site ka apna + HQ ka apna |

### 12.1 Windows par auto-start (NSSM)

[NSSM](https://nssm.cc) se har process ko Windows service bana do. PC restart hone par sab apne aap chalu ho jaayega:

```powershell
nssm install FA-Backend "C:\FaceAttendance\backend\.venv\Scripts\uvicorn.exe" "app.main:app --host 0.0.0.0 --port 8000"
nssm set FA-Backend AppDirectory "C:\FaceAttendance\backend"
nssm install FA-Kiosk-MainGate "C:\FaceAttendance\kiosk\.venv\Scripts\python.exe" "-m kiosk.main"
nssm set FA-Kiosk-MainGate AppDirectory "C:\FaceAttendance\kiosk"
nssm set FA-Kiosk-MainGate AppEnvironmentExtra KIOSK_ID=main-gate CAMERA_SOURCE=rtsp://... API_BASE_URL=http://localhost:8000 KIOSK_SERVICE_TOKEN=... MODEL_CACHE_DIR=C:\FaceAttendance\models OFFLINE_QUEUE_PATH=C:\FaceAttendance\data\queue\main-gate.db
nssm set FA-Backend AppStdout "C:\FaceAttendance\logs\backend.log"
nssm start FA-Backend
nssm start FA-Kiosk-MainGate
```

Frontend: `npm run build` karo, phir `frontend\dist` ko serve karo. Tareeke: backend ke saath `npx serve -s dist -l 5173` ek aur NSSM service me, ya IIS/nginx se.

### 12.2 Head office (multi-site) ke liye HTTPS

Cloud VM par B wala setup chalao, aur saamne [Caddy](https://caddyserver.com) lagao. Caddy free SSL certificate apne aap le leta hai:

```
# /etc/caddy/Caddyfile
hq.tumhari-company.in {
    reverse_proxy /api/* localhost:8000
    reverse_proxy localhost:3000
}
```

Phir har site par: Sites page → "Connect to head office" → `https://hq.tumhari-company.in` + token.

### 12.3 Remote support

Client ke PC/server par **Tailscale** (free, private network) ya AnyDesk lagao, taaki bina jaaye log dekh sako aur update kar sako. Client se likhit anumati lo.

---

## 13. Troubleshooting

| Problem | Kaaran / ilaaj |
|---|---|
| Dashboard khaali, login nahi hota | backend chal raha hai? `http://localhost:8000/api/v1/health` kholo. Frontend ka `VITE_API_BASE_URL` sahi hai? |
| Camera "Offline" | kiosk window chal rahi hai? `KIOSK_SERVICE_TOKEN` dono jagah same hai? kiosk log me 401 to nahi? |
| "Anti-spoofing OFF" laal patti | kiosk ko internet nahi mila ya file adhoori hai. `MODEL_CACHE_DIR\minifasnet\` me dono `.onnx` files haath se daalo. |
| Sab "liveness failed" | calibration karo (9.3). Model load nahi hua to log me `liveness_unavailable` dikhega. |
| Photos nahi dikhti | `MEDIA_ROOT` sahi drive par hai? browser refresh / dobara login karo. |
| `database is locked` (SQLite) | kai kiosk ek saath likh rahe hain. Postgres par jao, ya kam camera lagao. |
| Migration fail on start | backend log padho. Asli DB ki copy par `alembic upgrade head` chala kar dekho. |
| Kiosk bahut CPU le raha hai | `capture_fps` ghatao, `idle_fps` 1 rakho, `det_size` 480. Ya GPU lo. |
| Port 8000 busy | koi purana uvicorn chal raha hai. Task Manager me `python.exe` band karo, ya `--port 8001`. |
| Night shift dashboard me ajeeb | known gap hai (section 15). Reports aur payroll sahi hain. |

**Logs kahan milenge:**

- Native: jis window me process chal raha hai (production me NSSM ka `AppStdout` file).
- Docker: `docker compose logs api`.
- Logs JSON me hote hain. `level":"error"` dhoondho.

---

## 14. Security, privacy aur DPDP

- **Biometric data sensitive hai.** India ka DPDP Act 2023 har person ki **likhit consent**, sirf batae hue maqsad (attendance) ke liye use, aur kaam khatam hone par data mitana maangta hai.
- System ye sab karta hai:
  - Enrollment se pehle consent zaroori hai (`consents` table).
  - Embeddings encrypted copy ke saath rehte hain.
  - Har edit `audit_log` me jaata hai.
  - Face data ki sirf ek crop photo save hoti hai; asli uploaded photos save nahi hoti.
  - Multi-site par sirf ginti bahar jaati hai.
- **Tumhari zimmedari:**
  - `EMBEDDING_ENCRYPTION_KEY`, `JWT_SECRET` aur vendor PIN password manager me rakho.
  - Har client ke secrets alag hon.
  - Default admin (`admin@example.com`) har install par delete karo.
  - Dashboard ko internet par khula mat chhodo. LAN ya VPN se hi khule; HQ par HTTPS lagao.
  - Contract khatam hone par client ka data mitao: `reset_data.py all --purge-media`, backups bhi. Ye likhit me do.
- `crop_retention_days` (90) aur `unknown_auto_ignore_days` settings abhi koi automatic job nahi padhta. Purane crops ki safai abhi manually karni hoti hai (roadmap me hai).

---

## 15. Known gaps aur roadmap

| Gap | Asar | Plan |
|---|---|---|
| InsightFace `buffalo_l` commercial license | bechne se pehle legal risk | InsightFace se license lo, ya doosra model |
| Dashboard "aaj" night shift ko calendar din se dikhata hai | raat 12 ke baad wale sighting agle din | dashboard ko bhi `shiftday.py` se jodna |
| Crop retention auto-delete nahi | disk bharti hai, DPDP | roz ka cleanup job |
| SQLite se Postgres data migration tool nahi | purane client ko upgrade karna mushkil | ek script |
| Leave / holiday calendar nahi | holiday "absent" ginta hai | holidays table + payroll me |
| Payroll formats client template se verify nahi | import fail ho sakta hai | pehle client par milaana |
| HD phone screen liveness 100% nahi | spoof ka chhota risk | better anti-spoof model / IR camera |

---

## 16. Command cheat-sheet

```powershell
# ---- roz ----
cd backend; .venv\Scripts\Activate.ps1; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
cd kiosk;   .venv\Scripts\Activate.ps1; $env:CAMERA_SOURCE="0"; $env:KIOSK_SERVICE_TOKEN="..."; python -m kiosk.main
cd frontend; npm run dev

# ---- git ----
git status | git add <file> | git commit -m "..." | git push | git pull
git checkout -b feature/x | git stash | git stash pop | git tag -a v2.0.0 -m "..." | git push --tags

# ---- admin (backend folder) ----
python scripts\manage_users.py create --email hr@x.com --role admin
python scripts\setup_client.py show
python scripts\import_people.py --template people.csv
python scripts\import_people.py --csv people.csv --photos D:\photos --dry-run
python scripts\reset_data.py show
alembic upgrade head | alembic current

# ---- test ----
python -m pytest -q | ruff check app | mypy app | npx tsc -b | npm run lint | npm run build

# ---- docker ----
docker compose up -d --build | docker compose ps | docker compose logs -f api
docker compose exec api python scripts/manage_users.py list
docker compose down            # data safe
docker compose down -v         # DATA BHI MITAYEGA
```
