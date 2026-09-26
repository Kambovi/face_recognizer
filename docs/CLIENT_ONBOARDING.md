# Naya client onboarding: step by step guide

Last updated: 2026-09-25

Ye guide ek naye client (hospital, school ya business) par Face Attendance install karke go-live karne ke liye hai. Steps usi order me karo jisme likhe hain.

Ek nazar me:

| # | Step | Kaun karega | Kitna time |
|---|---|---|---|
| 1 | Client se jaankari lena | Aap + client | 1 meeting |
| 2 | Hardware aur camera lagana | Aap + client ka IT | 0.5–1 din |
| 3 | Software install | Aap | 1–2 ghante |
| 4 | Secrets (`.env`) banana | Aap | 10 min |
| 5 | Fresh database | Aap | 5 min |
| 6 | Vendor lock (sector, departments, cap) | **Sirf aap** | 5 min |
| 7 | Login users | Aap | 10 min |
| 8 | Shift timing | Aap | 10 min |
| 9 | Cameras (kiosk) chalu karna | Aap | 30 min per camera |
| 10 | Logon ka enrollment | Aap + client admin | 1–2 min per person |
| 11 | Testing aur go-live | Aap + client | 1 din |
| 12 | Handover | Aap | 1 ghanta |

---

## Step 1: Client se ye jaankari lo (setup se pehle)

Sector aur departments ek baar lock hone ke baad sirf vendor PIN se hi badlenge, isliye ye sab pehle confirm karwa lo.

| Kya poochna hai | Kyun | Example |
|---|---|---|
| Sector: `business`, `school` ya `hospital` | UI ka rang aur shabd (Employee / Student / Staff) | hospital |
| Organisation ka poora naam | Header aur login page par dikhega | City Care Hospital |
| Departments / classes / wards ki poori list | Enrollment me sirf isi list se chuna ja sakega | OPD, ICU, Nursing, Admin |
| Kitne entry points (cameras) | Har entry point ka ek camera ID banega | main-gate, staff-entry |
| Har entry point par kitne log | Ek camera par max 200 log enroll ho sakte hain | main-gate: 180 |
| Duty timing (in, out, grace) | Late aur absent isi se gine jaate hain | 09:00–18:00, 15 min grace |
| Admin kaun hoga (naam, email) | Dashboard login | hr@citycare.in |
| Logon ki list (naam, ID, department, entry point) | Enrollment tez hota hai | Excel sheet |

- [ ] Sab jaankari likh kar client se sign/confirm karwa li
- [ ] Vendor PIN tay kiya (kam se kam 6 akshar). Ye **sirf aapki company** ke paas rahega, client ko kabhi mat dena.
- [ ] Har person se photo/biometric consent ka form client ke paas hai (DPDP ke liye zaroori, dekho `docs/DPDP_COMPLIANCE.md`)

---

## Step 2: Hardware aur camera

**Server PC** (jahan backend, dashboard aur kiosk chalenge):

| Cheez | Kam se kam | Behtar |
|---|---|---|
| OS | Windows 10/11 64-bit | Windows 11 |
| CPU | Intel i5 8th gen / Ryzen 5 | i7 / Ryzen 7 |
| RAM | 8 GB | 16 GB |
| Disk | 256 GB SSD | 512 GB SSD |
| GPU | Zaroori nahi | NVIDIA (3+ cameras ke liye) |
| Network | Cameras aur PC ek hi LAN par | Wired LAN |

**Camera** (har entry point par ek):

- 1080p (2 MP) ya zyada. IP camera (RTSP) ya USB webcam dono chalte hain.
- Chehra frame me **kam se kam 80 pixel chauda** hona chahiye (120+ behtar).
- Aankh ki height par lagao, lagbhag **1.5–1.8 m**. Upar se neeche jhuka hua camera (CCTV style) chehra theek nahi pakadta.
- Neeche ya upar ka jhukaav **15° se kam**, side angle **30° se kam**.
- Roshni **saamne se** aani chahiye. Camera ke saamne khidki ya tez light (backlight) nahi honi chahiye. WDR wala camera lo.
- Aisi jagah lagao jahan log ek-ek karke, seedha camera ki taraf dekhte hue guzarein (darwaza, turnstile).

- [ ] Har camera ka test photo liya, chehra saaf aur seedha dikh raha hai
- [ ] IP camera ka RTSP URL, username, password likh liya

---

## Step 3: Software install

1. PC par install karo: **Python 3.11** (install karte waqt "Add to PATH" tick karo), **Node.js 20 LTS**, **Git** (optional).
2. Project folder copy karo, jaise `C:\FaceAttendance\`. Ye cheezein **copy mat karo**:
   - `backend\dev.db` (aapka test data)
   - `backend\backups\`
   - `backend\.env` (har client ke liye naya banega)
   - `.venv` aur `node_modules` folders
3. Backend:

   ```powershell
   cd C:\FaceAttendance\backend
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   pip install onnxruntime==1.19.2
   ```

4. Kiosk:

   ```powershell
   cd C:\FaceAttendance\kiosk
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install onnxruntime==1.19.2
   ```

5. Frontend:

   ```powershell
   cd C:\FaceAttendance\frontend
   npm install
   ```

---

## Step 4: Secrets (`backend\.env`) banao

Har client ke liye **naye** secrets banao. Default wale mat chhodo.

```powershell
cd C:\FaceAttendance\backend
.venv\Scripts\Activate.ps1
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Teeno outputs ko `backend\.env` file me aise daalo:

```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
DATABASE_URL_SYNC=sqlite:///./dev.db
EMBEDDING_ENCRYPTION_KEY=<pehla output>
JWT_SECRET=<doosra output>
KIOSK_SERVICE_TOKEN=<teesra output>
MEDIA_ROOT=C:\FaceAttendance\data\media
APP_TIMEZONE=Asia/Kolkata
```

> **Bahut zaroori:** `EMBEDDING_ENCRYPTION_KEY` kho gayi to saare enrolled chehre hamesha ke liye bekaar ho jaayenge, aur sabko dobara enroll karna padega. Ye `.env` file apne password manager me client ke naam se save karo.

---

## Step 5: Fresh database

Backend pehli baar chalte hi database khud ban jaati hai. Saare tables, ek default admin aur ek "General Shift" (09:00–18:00, 15 min grace) usi waqt ban jaate hain.

```powershell
cd C:\FaceAttendance\backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Browser me `http://localhost:8000/api/v1/health` kholo. `"status"` dikhna chahiye. Phir `Ctrl+C` se band kar do.

Agar galti se purani `dev.db` copy ho gayi thi, to use saaf karo (dekho `docs/DATA_RESET.md`):

```powershell
python scripts\reset_data.py all --purge-media
```

> `seed_demo.py` client ke PC par **kabhi mat chalana**. Wo nakli 100 log daal deta hai.

---

## Step 6: Vendor lock (sirf aap, ek hi baar)

Is step se sector ka theme, shabd, departments ki list aur per-camera cap lock ho jaate hain. Client ka admin inhe nahi badal sakta.

```powershell
cd C:\FaceAttendance\backend
.venv\Scripts\Activate.ps1
python scripts\setup_client.py init --type hospital --name "City Care Hospital" --departments "OPD" "ICU" "Nursing" "Admin" --camera-cap 200
```

- `--type`: `business`, `school` ya `hospital`
- `--camera-cap`: ek camera par max kitne log (default 200)
- Script vendor PIN do baar poochega. Wahi PIN do jo Step 1 me tay kiya tha.

Check karo:

```powershell
python scripts\setup_client.py show
```

Baad me koi badlav (naya department, bada cap) sirf PIN se hoga:

```powershell
python scripts\setup_client.py update --add-department "Radiology"
python scripts\setup_client.py update --camera-cap 300
```

---

## Step 7: Login users

Default login `admin@example.com` / `ChangeMe123!` hai. **Ise client ko mat dena.**

```powershell
python scripts\manage_users.py create --email hr@citycare.in --role admin
python scripts\manage_users.py create --email owner@citycare.in --role viewer
python scripts\manage_users.py delete --email admin@example.com
```

- `admin`: sab kuch (enrollment, dashboard par edit, unknown faces, settings)
- `viewer`: sirf dashboard aur analytics dekh sakta hai

Apne liye ek alag vendor admin bhi bana lo (support ke kaam aayega):

```powershell
python scripts\manage_users.py create --email support@<aapki-company>.com --role admin
```

---

## Step 8: Shift timing

Default shift 09:00–18:00 hai, 15 min grace ke saath. Agar client ki timing alag hai:

1. Backend chalu karo aur `http://localhost:8000/docs` kholo.
2. Upar **Authorize** dabao aur admin se login karo.
3. `POST /api/v1/shifts` kholo, "Try it out" dabao aur naya shift bharo:

   ```json
   { "name": "Morning", "in_time": "08:00", "out_time": "16:00", "grace_minutes": 10, "is_default": true }
   ```

4. Enrollment ke waqt har person ko sahi shift chuno.

> Dashboard par abhi shift edit karne ki screen nahi hai. Ye aage banani hai.

---

## Step 9: Cameras (kiosk) chalu karo

Har entry point ke liye ek **alag PowerShell window** me ek kiosk chalega. Pehle backend chalu karo:

```powershell
cd C:\FaceAttendance\backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Phir har camera ke liye (naam aur source badal kar):

```powershell
cd C:\FaceAttendance\kiosk
.venv\Scripts\Activate.ps1
$env:KIOSK_ID="main-gate"
$env:CAMERA_SOURCE="rtsp://user:pass@192.168.1.50:554/stream1"   # USB webcam ke liye "0"
$env:API_BASE_URL="http://localhost:8000"
$env:KIOSK_SERVICE_TOKEN="<.env wala KIOSK_SERVICE_TOKEN>"
$env:MODEL_CACHE_DIR="C:\FaceAttendance\models"
$env:OFFLINE_QUEUE_PATH="C:\FaceAttendance\data\queue\main-gate.db"
python -m kiosk.main
```

- `KIOSK_ID` chhota aur saaf rakho: `main-gate`, `staff-entry`, `opd-door`. Yahi naam dashboard par dikhega.
- Har camera ka `OFFLINE_QUEUE_PATH` **alag** hona chahiye.
- Pehli baar model download hoga (internet chahiye). Uske baad offline chalta hai.

Dashboard (naya PowerShell):

```powershell
cd C:\FaceAttendance\frontend
$env:VITE_API_BASE_URL="http://<server-PC-ka-IP>:8000"
npm run build
npm run preview -- --host 0.0.0.0 --port 5173
```

Client ke doosre computers se `http://<server-PC-ka-IP>:5173` kholo.

- [ ] `http://localhost:8000/api/v1/health` par `"status":"ok"` aa raha hai
- [ ] Analytics page par har camera "online" dikh raha hai

---

## Step 10: Logon ka enrollment

**Tarika A: photos se (sabse accha)**

1. Dashboard par **Staff / Students / Employees** page kholo, phir **Add** dabao.
2. Naam, ID, department (locked list se), designation, shift aur **home camera** bharo.
3. Consent tick karo, phir **Enroll photos** se 3–5 photos daalo:
   - seedha saamne, halka left, halka right
   - achhi roshni, chashma ho to ek photo bina chashme
   - sirf ek chehra per photo, chehra bada aur saaf

**Tarika B: camera ke saamne se (walk-in)**

1. Person ko camera ke saamne se 2–3 baar guzarne do. Wo Dashboard par "Unknown" dikhega.
2. Dashboard par us row ka **Identify** dabao, phir **Register** tab me details bharo aur save karo.
3. Agar person pehle se list me hai, to **Link** tab se use jod do.

Dhyan rakho:

- Ek camera par cap (default 200) poora hone par system naye log add nahi karne dega (`camera_full` error). Tab person ko doosre camera par daalo, ya PIN se cap badhao.
- Enrollment ke baad har person ko ek baar camera ke saamne se guzaar kar check karo ki naam aa raha hai.

---

## Step 11: Testing aur go-live checklist

- [ ] 5–10 enrolled log alag-alag time par camera se guzre, sabka **IN** sahi naam ke saath aaya
- [ ] Ek person do baar guzra, duplicate entry nahi bani
- [ ] Shaam ko **OUT** time sahi aaya
- [ ] Ek late person **Late** me dikha
- [ ] Ek anjaan aadmi guzra, wo **ek hi** Unknown ID me aaya (baar-baar naya ID nahi)
- [ ] Dashboard ke edit drawer se ek galat entry theek karke dekhi
- [ ] Analytics page par KPI, camera cards aur charts data dikha rahe hain
- [ ] CSV export download ho raha hai
- [ ] Testing ka data saaf kiya: `python scripts\reset_data.py attendance` (enrolled log bache rahenge)
- [ ] PC restart karke dekha ki sab dobara chalu ho jaata hai

> **Known limitation (bechne se pehle theek karna hai):** liveness (photo/phone screen se dhokha pakadna) abhi kaam nahi karta. MiniFASNet model download fail hota hai aur system "fail-open" chalta hai. Jab tak ye theek na ho, client ko anti-spoofing ka vaada mat karo.

---

## Step 12: Handover

Client ko do:

- Dashboard ka URL aur unke admin/viewer logins
- 30 min ki training: Dashboard, edit drawer (Identify / Fix time / Wrong person), Analytics, CSV export
- Support ka contact number

Apne paas rakho (client ko **mat** do):

- Vendor PIN
- `backend\.env` ki copy (khaaskar `EMBEDDING_ENCRYPTION_KEY`)
- Support admin login
- Setup ki tareekh, cameras ki list, `setup_client.py show` ka output

---

## Baad me: backup aur roz ka kaam

**Roz ka backup** (Windows Task Scheduler me raat ko chalao):

```powershell
cd C:\FaceAttendance\backend
.venv\Scripts\python.exe -c "import sqlite3,datetime; s=sqlite3.connect('dev.db'); d=sqlite3.connect('backups/daily-'+datetime.date.today().isoformat()+'.db'); s.backup(d); d.close(); s.close()"
```

Is backup ke saath `data\media` folder bhi hafte me ek baar kisi doosri drive par copy karo.

**Common problems:**

| Problem | Kya check karein |
|---|---|
| Camera "offline" dikh raha hai | Kiosk window chal rahi hai? `KIOSK_SERVICE_TOKEN` `.env` se match karta hai? |
| Enrolled person Unknown aa raha hai | Camera ki height/roshni, enrollment photos ki quality. 2 aur photos add karo. |
| Ek hi insaan ke kai Unknown IDs | Camera angle aur roshni theek karo. `docs/TUNING.md` dekho. |
| Photos 401 / nahi dikh rahe | Browser refresh karo, dobara login karo |
| Naya person add nahi ho raha (`camera_full`) | Us camera ka cap bhar gaya. Doosra camera chuno, ya PIN se cap badhao. |
| Department list me naya department nahi hai | `setup_client.py update --add-department` (vendor PIN) |
| Data galti se mit gaya | `docs/DATA_RESET.md` ka "Backup se wapas" section |
