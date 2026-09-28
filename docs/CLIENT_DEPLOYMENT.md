# Naye client par deploy aur onboarding: step by step

> Deal pakki hone se go-live aur uske baad tak, har kaam isi order me karo. Har phase ke end me checklist hai. Sab tick ho tabhi agle phase par jao.
> Technical detail (commands ka matlab, Docker, troubleshooting) → `PROJECT_BIBLE.md`. Form ke namoone → `FORMS_AND_TEMPLATES.md`.
>
> Last updated: 26 Sep 2026

## Ek nazar me

| Phase | Kaam | Kaun | Kitna time |
|---|---|---|---|
| 0 | Deal ke baad: jaankari aur data maangna | Tum + client HR | 2–5 din (client ki speed par) |
| 1 | Site survey aur hardware | Tum + client IT | 1 din |
| 2 | Server install (Docker ya Windows) | Tum | 2–3 ghante |
| 3 | Vendor lock + admin + shifts | Tum | 1 ghanta |
| 4 | Employees aur photos ka import | Tum + HR | 1 din (500 log tak) |
| 5 | Cameras chalu + calibration | Tum | 30 min per camera |
| 6 | Pilot / parallel run | Tum + client | 7–14 din |
| 7 | Go-live + training + handover | Tum | 1 din |
| 8 | Baad ka support aur AMC | Tum | har mahine |

---

## Phase 0: Deal ke baad, site par jaane se pehle

**Client se ye maango.** Namoona `FORMS_AND_TEMPLATES.md` me hai.

| Kya | Kyun | Format |
|---|---|---|
| Sector (business / school / hospital), organisation ka poora naam | UI ka theme, shabd aur header | |
| Departments / classes / wards ki **final** list | Ye lock ho jaati hai; baad me badlav sirf vendor PIN se | list |
| Entry points (gates) ki list + har gate par kitne log | Har gate = ek camera; ek camera par max 200 log | list |
| Shifts: naam, in/out time, grace; night ya rotating shift? | Late, OT, payroll | table |
| Weekly off, OT policy (kitne min baad OT, rounding) | Payroll ki accuracy | |
| Contractors / agencies ke naam | Contractor bill check | list |
| **Employee sheet** | Bulk import | CSV / Excel (template niche) |
| **Har person ki 3–5 photos** | Pehchaan | JPG, file ka naam = ID |
| **Har person ka signed consent form** | DPDP Act; iske bina import mat karna | paper / scan |
| Admin kaun hoga (naam, email, phone); WhatsApp par report kise chahiye | Logins aur alerts | |
| Payroll software (Tally / Zoho / greytHR / Keka / Excel) + unka **import template** | Export ke column milaane ke liye | file |

**Employee sheet ka format.** Template banane ke liye:

```powershell
python scripts\import_people.py --template people.csv
```

| emp_code | name | department | designation | shift | home_camera | contractor | monthly_salary |
|---|---|---|---|---|---|---|---|
| EMP001 | Ravi Kumar | Production | Operator | General | main-gate | Sharma Manpower | 18000 |
| EMP002 | Anita Singh | Quality | Inspector | Night | main-gate | | 22500 |

- Sirf `emp_code` aur `name` zaroori hain.
- `department` bilkul wahi likho jo department list me hai.
- `shift` = shift ka naam, `home_camera` = camera ID. Ye dono Phase 3 aur 5 me banenge.
- `contractor` khaali = company ka apna staff.
- `monthly_salary` = gross monthly salary, sirf number (`18000`, `18,000` ya `₹18000` sab chalega). Khaali chhod sakte ho. Ye sirf admin ko dikhti hai (chatbot me payable salary ke liye).
- Excel me File → Save As → **CSV UTF-8** karo (warna Hindi naam toot jaate hain).

**Photo guideline.** Ye HR ko bhejo:

- 3–5 photo per person: 1 bilkul seedhi, 1 thoda left, 1 thoda right. Chashma ho to ek bina chashme.
- Achhi roshni, saada background, chehra photo ka bada hissa ho. Group photo ya ID card ki photo nahi chalegi.
- Phone camera kaafi hai. File ka naam ID se rakho: `EMP001.jpg`, `EMP001_2.jpg`, `EMP001_3.jpg`. Ya har person ka folder: `photos\EMP001\*.jpg`.

**Checklist:**

- [ ] Sab jaankari aur departments list client ne sign karke di
- [ ] Employee CSV + photos folder mile
- [ ] Consent forms mile (count = employees count)
- [ ] Vendor PIN tay kiya, password manager me save kiya
- [ ] Payroll template mila
- [ ] Company policy documents mile (leave, timing, salary, OT, notice period: PDF/Word). Ye HR chatbot ke liye hain

---

## Phase 1: Site survey aur hardware

- [ ] Har gate par camera ki jagah tay ki: aankh ki height (1.5–1.8 m), saamne se roshni, backlight nahi, log ek-ek karke guzrein
- [ ] Camera: 1080p IP camera (RTSP) ya USB. Chehra frame me ≥ 80 px chauda ho. Test photo lekar dekho.
- [ ] Server: mini-PC / PC (i5/i7, 16 GB RAM, SSD). 3 se zyada camera hon to GPU wala.
- [ ] Network: camera aur server ek LAN par hon, camera ka IP fixed ho. RTSP URL, username aur password likh lo.
- [ ] UPS: server aur switch ke liye, taaki bijli jaane par database kharab na ho.
- [ ] Exit par bhi camera lagega? (Emergency muster aur sahi OUT time ke liye recommended.)

Form: `FORMS_AND_TEMPLATES.md` → Site survey.

---

## Phase 2: Server install

Do tareeke hain. **B (Linux + Docker) recommended hai.** Kyun, ye `PROJECT_BIBLE.md` ke section 11 aur 12 me hai.

### 2B. Linux + Docker (recommended)

```bash
# Ubuntu 22.04/24.04 server par
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
git clone https://github.com/Kambovi/face_recognizer face-attendance && cd face-attendance
git checkout v2.0.0                          # jo release tag diya ho
cp .env.example .env
nano .env
```

`.env` me **har client ke liye naye** values daalo:

```
POSTGRES_PASSWORD=<lamba random>
DATABASE_URL=postgresql+asyncpg://face_attendance:<wahi password>@db:5432/face_attendance
DATABASE_URL_SYNC=postgresql+psycopg2://face_attendance:<wahi password>@db:5432/face_attendance
JWT_SECRET=<python3 -c "import secrets;print(secrets.token_urlsafe(48))">
EMBEDDING_ENCRYPTION_KEY=<python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
KIOSK_SERVICE_TOKEN=<python3 -c "import secrets;print(secrets.token_urlsafe(32))">
KIOSK_ID=main-gate
CAMERA_SOURCE=rtsp://user:pass@192.168.1.50:554/stream1
VITE_API_BASE_URL=http://<server-ka-IP>:8000
```

> `cryptography` server par na ho to ye key apne laptop par bana lo.

Kai camera hon to `docker-compose.yml` me har camera ki ek kiosk service jodo (Bible section 11.7). Import folder ke liye `api` service ki `volumes:` list me `- ./import:/data/import` jodo. Phir:

```bash
docker compose up -d --build
docker compose ps                        # sab running/healthy
curl http://localhost:8000/api/v1/health
```

Dashboard: `http://<server-IP>:3000`.

**Iske baad Phase 3–5 ki har `python scripts\...` command Docker me aise chalegi:**

```bash
docker compose exec -it api python scripts/<script>.py ...
```

### 2A. Windows PC (bina Docker)

1. Python 3.11, Node 20 LTS aur Git install karo.
2. Code clone karo, venvs banao aur `pip install` / `npm install` karo (Bible section 4.1).
3. `backend\.env` banao: upar wale secrets, `DATABASE_URL=sqlite+aiosqlite:///./dev.db`, `MEDIA_ROOT=C:\FaceAttendance\data\media`.
4. Backend ek baar chalao. Database apne aap banega, saath me default admin aur "General Shift" bhi.
5. NSSM se services banao, taaki PC restart par sab chalu ho (Bible section 12.1).
6. Frontend: `npm run build`, phir dist serve karo.

> Apna laptop wala `dev.db` **kabhi copy mat karna**. Client par hamesha khaali database se shuru karo. Galti se purana aa gaya ho to `python scripts\reset_data.py all --purge-media` chalao.

**Checklist:**

- [ ] Health OK, dashboard khulta hai
- [ ] `.env` ki copy password manager me: "<Client> – secrets"
- [ ] Server par roz ka backup set kiya (Bible section 7.4)

---

## Phase 3: Vendor lock, admins, shifts, rules

```powershell
cd backend; .venv\Scripts\Activate.ps1          # Docker: docker compose exec -it api ...

# 1. Vendor lock: sector, naam, departments, camera cap (PIN do baar maangega)
python scripts\setup_client.py init --type business --name "Acme Auto Parts Pvt Ltd" --departments "Production" "Quality" "Stores" "Maintenance" "Admin" --camera-cap 200
python scripts\setup_client.py show

# 2. Logins
python scripts\manage_users.py create --email hr@acme.in --role admin
python scripts\manage_users.py create --email owner@acme.in --role viewer
python scripts\manage_users.py create --email support@<tumhari-company>.in --role admin
python scripts\manage_users.py delete --email admin@example.com
```

Phir dashboard me HR ke login se:

- [ ] **Shifts page:** client ki saari shifts banao, sahi wali ko "Default" karo
- [ ] Rotating shift ho to **Roster** me pehle 2 hafte bhar do
- [ ] **Settings → Payroll & overtime:** weekly off, OT minimum, rounding. Full/half-day ghante sirf tab jab exit camera bhi ho.
- [ ] **Settings → WhatsApp:** numbers, templates/webhook, daily summary ka time. "Send test" dabao.
- [ ] **HR chatbot:** client ki policy files server ke policy folder me copy karo (Windows: `C:\FaceAttendance\app\backend\data\policy\`, ya `.env` me `POLICY_DIR`). **Settings → HR chatbot** me files ki list aur "passages" count dikhna chahiye.
- [ ] Chatbot ka AI model client se poochkar chuno: data bahar nahi jaana chahiye to **Ollama (local)**, warna **Claude/OpenAI** (API key client ke naam ki ho, bill unka). Kuch set na karo to Basic mode chalega. "Save & test model" dabao.

---

## Phase 4: Employees aur photos ka import (database me daalna)

Ye onboarding ka sabse bada kaam hai. `import_people.py` normal API se hi import karta hai: department check, camera cap, consent aur photo quality, sab wahi checks lagte hain jo dashboard par.

**1. Files server par rakho**

- Windows: `C:\FaceAttendance\import\people.csv` aur `C:\FaceAttendance\import\photos\`
- Docker: project ke `import/` folder me

**2. Dry run.** Isse kuch nahi badalta, sirf check hota hai:

```powershell
python scripts\import_people.py --csv C:\FaceAttendance\import\people.csv --photos C:\FaceAttendance\import\photos --dry-run
```

Ye batata hai kitne log hain, kiski photo nahi mili, aur CSV me duplicate IDs to nahi.

**3. Asli import.** Backend chalna chahiye:

```powershell
python scripts\import_people.py --csv C:\FaceAttendance\import\people.csv --photos C:\FaceAttendance\import\photos --api http://localhost:8000
```

Admin email aur password maangega. Har person ke liye ye hota hai:

1. Person banta hai
2. Consent record hota hai
3. Photos enroll hoti hain

**4. Result dekho:** `people_result.csv` banti hai.

| status | Matlab | Kya karein |
|---|---|---|
| created, error khaali | sab theek | kuch nahi |
| created + "no usable photo" | photo me chehra nahi mila / dhundli / chhoti | naye photos lo, phir `--add-photos` ke saath dobara chalao |
| failed: "not a configured department" | CSV me spelling galat | CSV theek karo, dobara chalao (jo ban gaye wo skip ho jaate hain) |
| failed: camera_full | us camera par 200 log ho gaye | doosra camera do, ya `setup_client.py update --camera-cap` |
| already existed | ye ID pehle se hai | photos jodni hon to `--add-photos` |
| already existed, salary updated | CSV me salary thi, update ho gayi | kuch nahi (salary badalne ka yahi tareeka hai) |
| failed: monthly_salary 'x' is not a number | salary column me text | number likho, dobara chalao |

Script dobara chalana safe hai; ek aadmi do baar nahi banta.

**5. Jin logon ki photo nahi thi,** unhe camera ke saamne se 2–3 baar guzaro. Wo dashboard par "Unknown" dikhenge. Wahan **Identify → Existing staff member** dabakar sahi person se jodo, ya **New** se naya banao.

**6. Contractors:** CSV me hi aa jaate hain. Baad me Staff page par edit bhi kar sakte ho.

**7. Watchlist:** jin logon ko andar nahi aane dena (pehle nikale gaye log), unka reason Staff page par bhar do.

**Checklist:**

- [ ] `people_result.csv` me koi "failed" nahi
- [ ] Har person ki ≥ 2 accepted photos (jin ki kam hain, unki list HR ko de di)
- [ ] Staff page par count = client ki list

---

## Phase 5: Cameras chalu aur calibration

- [ ] Har camera ka kiosk chalu hai, aur Analytics → "By camera" me **Online** dikhta hai
- [ ] Camera ka naam saaf ho (`main-gate`), `kiosk-01` jaisa nahi. Badalna ho to `manage_cameras.py rename`.
- [ ] **Liveness calibration** har camera par (Bible 9.3): real + spoof + recommend → threshold Settings me daalo
- [ ] "Anti-spoofing OFF" kahin nahi dikhta
- [ ] **Muster page → Camera directions:** entry/exit mark kiye
- [ ] 5–10 log guzre, sabka IN sahi naam ke saath aaya. Phone par photo dikhai to reject hua aur spoof alert aaya.
- [ ] Head office wala client ho to Sites page par connect karke test kiya

---

## Phase 6: Pilot / parallel run (7–14 din)

Purani machine / register band **mat** karo. Dono saath chalao aur roz milaan karo:

- [ ] Roz: dashboard vs register. Missed log kaun the aur kyun (photo? angle? roshni?)
- [ ] "Unknown" me apne log aa rahe hain to unhe Identify karke jodo. Har jodne se system seekhta hai.
- [ ] Hafte ke end me: payroll export client ke payroll software me **test import** kiya (Tally ki copy company me)
- [ ] Contractor report ek contractor ke bill se milaya
- [ ] Recognition rate nikalo: (sahi pehchane gaye / kul guzre) × 100. Target ≥ 95% ho. Kam ho to camera ya photos theek karo.

Pilot ke end me **acceptance sign-off** lo (form `FORMS_AND_TEMPLATES.md` me hai).

---

## Phase 7: Go-live, training, handover

```powershell
python scripts\reset_data.py attendance --before <go-live date>     # pilot ki attendance hatao, log aur photos rakho
```

**Training (60–90 min):**

| Kisko | Kya sikhana |
|---|---|
| HR / admin | Dashboard; Edit drawer (Identify, Fix time, Wrong person, Watchlist); naya person add + photos; Reports (payroll, contractor, muster roll, monthly PDF); Shifts aur roster; **Leave marking** (Staff → Manage → Leave); **Ask HR chatbot** (naam likho → confirm → report; policy ke sawaal) |
| Security | Bell alerts; Emergency muster aur roll call; spoof alert ka matlab |
| Owner | Phone par dashboard; WhatsApp summary; Analytics; Sites (agar multi-site) |

**Handover.** Client ko ye do:

- Dashboard ka URL aur unke logins
- Support number aur email, support ka samay (SLA)
- Ek page ka "Roz kya karein" guide (Dashboard dekho, Unknown identify karo, mahine ke end par payroll export)

**Apne paas rakho, client ko MAT do:**

- Vendor PIN
- `.env` secrets
- Support admin login
- Install ki tareekh, version (git tag), camera list, `setup_client.py show` ka output

Ye sab ek "Client file" me save karo (template `FORMS_AND_TEMPLATES.md` me hai).

---

## Phase 8: Go-live ke baad

**Pehla hafta:**

- [ ] Har roz 5 min remote se check: cameras online, alerts, unknown count
- [ ] Pehle mahine ka payroll client ke saath baith kar export kiya

**Har mahine (AMC visit / remote):**

- [ ] Backup chal raha hai? Ek backup restore karke test kiya (3 mahine me ek baar)
- [ ] Disk space (media folder)
- [ ] Naya version ho to update: native par `git fetch --tags && git checkout vX.Y.Z` phir restart; Docker par `docker compose up -d --build`. Pehle backup lo.
- [ ] Recognition rate aur liveness alerts ka trend dekha
- [ ] Monthly PDF client ko bheji

**Naya department / zyada camera cap:**

```powershell
python scripts\setup_client.py update --add-department "Paint Shop"
python scripts\setup_client.py update --camera-cap 300
```

Ye upsell hai: iska bill banao.

**Contract khatam hone par (DPDP):**

1. Client ko uska data export do: payroll aur muster roll CSV.
2. Phir `reset_data.py all --purge-media` chalao, backups bhi mitao.
3. Likhit confirmation do ki data mita diya gaya (form me hai).
