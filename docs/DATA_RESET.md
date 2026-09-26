# Database clear / reset guide (`reset_data.py`)

Last updated: 2026-09-25

Script ka path: `D:\DS PROJECTS\face-attendance\backend\scripts\reset_data.py`

Ye script database se data **safely** delete karta hai:

- Kuch bhi mitane se pehle **pura backup** leta hai (`backend\backups\dev-<date-time>.db`).
- Agar koi camera pichhle 2 minute me online tha, to chalne se **mana kar deta hai**. Chalte system ki database badalne se data kharab ho sakta hai.
- Jab tak aap `DELETE` type nahi karte, kuch nahi mitata.
- Har reset `audit_log` me likha jata hai.

**Ye cheezein kabhi nahi mitti:** login users, settings/thresholds, client profile (sector, departments, camera cap), shifts, camera list, audit log.

---

## Kab kaunsa mode chalana hai

| Mode | Kya mitata hai | Kya bachta hai | Kab use karein |
|---|---|---|---|
| `show` | Kuch nahi, sirf ginti dikhata hai | Sab | Pehle hamesha ye chalao |
| `attendance` | Saari attendance history + saare unknown faces | Enrolled log aur unke face photos | Testing ke baad real use shuru karna ho, lekin enroll kiye log rakhne ho |
| `attendance --before 2026-10-01` | Sirf us date se pehle ki history (aur wo unknown faces jo sirf tab dikhe the) | Baaki sab | Purana data hatana ho |
| `people` | Saare enrolled log + unke photos + unki attendance | Unknown faces | Poora roster dobara banana ho |
| `people --codes EMP0001 EMP0002` | Sirf ye IDs wale log | Baaki sab | Kuch test logon ko hatana ho |
| `people --code-like "DEMO%"` | Wo log jinki ID "DEMO" se shuru hoti hai | Baaki sab | Demo/seed data hatana |
| `all` | attendance + people, sab kuch | Users, settings, profile, shifts, cameras | Naye client ke liye fresh install jaisa |

Extra options:

| Option | Matlab |
|---|---|
| `--purge-media` | Deleted data ki face-crop JPEG files bhi `MEDIA_ROOT` (D:\data\media) se hata deta hai. Jo files abhi bhi kisi bache hue record me use ho rahi hain, wo nahi hatti. |
| `--yes` | `DELETE` type karne ka sawaal skip (sirf scripts ke liye) |
| `--no-backup` | Backup skip. **Mat use karo.** |
| `--force-running` | Camera online dikhne par bhi chala do. **Sirf tab jab pakka pata ho ki kiosk band hai.** |

---

## Step by step (Windows PowerShell)

1. **Kiosk band karo**: kiosk wali PowerShell window me `Ctrl+C`.
2. **Backend band karo**: uvicorn wali window me `Ctrl+C`.
3. Naya PowerShell kholo:

   ```powershell
   cd "D:\DS PROJECTS\face-attendance\backend"
   .venv\Scripts\Activate.ps1
   python scripts\reset_data.py show
   ```

4. Jo mode chahiye wo chalao. Example: sab kuch saaf karna ho to:

   ```powershell
   python scripts\reset_data.py all --purge-media
   ```

   Poochne par `DELETE` type karke Enter dabao.

5. Output me `Backup saved: ...` wali line dikhegi. Wo path note kar lo.
6. Backend aur kiosk dobara chalu karo.

---

## Galti ho gayi? Backup se wapas kaise laayein

1. Backend aur kiosk band karo.
2. `backend\backups\` me sahi time wali file dhundo, jaise `dev-20260925-171500.db`.
3. Purani `dev.db` ka naam badal do (jaise `dev-broken.db`), phir backup file ko copy karke uska naam `dev.db` rakh do.
4. Backend chalu karo.

Note: agar `--purge-media` use kiya tha, to face-crop photos wapas nahi aayengi. Attendance ka data wapas aa jayega, sirf thumbnails khaali dikhenge.

---

## Ye problem hui kyun thi (22 Sept 2026 wala case)

- 22 Sept ko `seed_demo.py` (demo data script) usi `dev.db` par chal gaya tha jisme real camera bhi likh raha tha.
- Isse 100 nakli employees (Ines Silva, Mei Kim, EMP0001–EMP0100…), 4 Sept se nakli attendance history aur 5 nakli unknown faces (UNK-0001 se UNK-0005) real data me mix ho gaye.
- Nakli log roz "absent" gine gaye, isliye attendance % galat (~22%) dikhta tha. Koi real employee enroll nahi tha, isliye aap hamesha "Unknown" dikhte the.

**Ab ye dobara nahi hoga:**

- `seed_demo.py` ab kisi bhi aisi database par nahi chalega jisme attendance, unknown faces ya client profile ho.
- Demo IDs ab `DEMO0001` jaisi banti hain. Inhe `python scripts\reset_data.py people --code-like "DEMO%"` se hataya ja sakta hai.
- Demo chahiye to alag database file use karo:

  ```powershell
  $env:DATABASE_URL="sqlite+aiosqlite:///./demo.db"
  $env:DATABASE_URL_SYNC="sqlite:///./demo.db"
  ```
