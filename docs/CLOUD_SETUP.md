# Cloud server + database setup (go-live guide)

Product live karne ke liye cloud par kya lena hai, DB ka config kya rakhna hai, aur pehla client kaise jodna hai. Architecture: `docs/SAAS_ARCHITECTURE.md`.

---

## 1. Kya khareedna hai

### Server (cloud)
Cloud par face recognition **nahi** chalta (wo edge box par hai), isliye server halka chahiye.

| Stage | Clients | Server | Disk |
|---|---|---|---|
| Pilot / launch | 1 - 30 | 2 vCPU, 4 GB RAM | 60 GB SSD |
| Growth | 30 - 150 | 4 vCPU, 8 GB RAM | 120 GB SSD |
| Bada | 150+ | API server 4 vCPU/8 GB + alag managed Postgres (4 vCPU/16 GB) | DB 250 GB+ |

* **Region: India** (AWS Mumbai `ap-south-1` / Hyderabad `ap-south-2`, Azure Central India, Google Cloud Mumbai `asia-south1` / Delhi `asia-south2`). Hospitals / schools / companies poochte hain "data India me hai?" -- jawab haan hona chahiye.
* **OS:** Ubuntu Server 24.04 LTS.
* Data size andaza: 200 log x 4 events/din ≈ 3 lakh rows/saal/client ≈ 300 MB/saal (indexes ke saath). 100 clients ≈ 30 GB/saal.

### Domain
Ek domain, jaise `attendance.example.in`. DNS me 2 records:

| Type | Name | Value |
|---|---|---|
| A | `attendance.example.in` | server ka public IP |
| A | `*.attendance.example.in` | server ka public IP |

Har client ka dashboard: `https://<client>.attendance.example.in`. HTTPS certificate Caddy apne aap leta hai (Let's Encrypt, on-demand) -- sirf unhi naamon ke liye jo tenant hain.

### Edge box (har client site par, client ke kharche par ya rent par)
* Mini PC: Intel i5 (8th gen+) / Ryzen 5, **8-16 GB RAM**, 256 GB SSD, wired LAN. 2-4 cameras CPU par aaram se. Zyada cameras / bheed wale gate = NVIDIA GPU (Jetson / GTX 1650+).
* UPS zaroori. Internet: kuch bhi chalega (results chhote hote hain); sirf outbound 443.
* Windows ya Ubuntu. Ubuntu + Docker sabse aasaan (`deploy/edge`).

---

## 2. Server tayyar karna (ek baar)

```bash
# 1. login ke liye SSH key; password login band
sudo adduser fa && sudo usermod -aG sudo fa
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl restart ssh

# 2. firewall: sirf 22 (apne IP se), 80, 443
sudo ufw default deny incoming
sudo ufw allow from <AAPKA_OFFICE_IP> to any port 22
sudo ufw allow 80,443/tcp
sudo ufw enable

# 3. security updates apne aap
sudo apt update && sudo apt install -y unattended-upgrades fail2ban gnupg
sudo dpkg-reconfigure -plow unattended-upgrades

# 4. Docker
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker fa
```

Code server par **private** GitHub repo se (deploy key, read-only):
```bash
git clone git@github.com:Kambovi/face_recognizer.git /opt/fa && cd /opt/fa && git checkout feature/saas-v3
```
> Git history me purana `.env` aur `dev.db` (asli employees ka data) hai. Repo **private** rakho; public karne se pehle history saaf karo (`git filter-repo`).

---

## 3. `.env` (cloud) -- har value kya hai

```bash
cd /opt/fa/deploy/cloud
cp .env.cloud.example .env
cd ../../backend
python3 -m venv /tmp/v && /tmp/v/bin/pip install cryptography   # sirf keys banane ke liye
/tmp/v/bin/python -c "import secrets;print(secrets.token_urlsafe(32))"      # POSTGRES_PASSWORD
/tmp/v/bin/python -c "import secrets;print(secrets.token_urlsafe(48))"      # JWT_SECRET
/tmp/v/bin/python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # EMBEDDING_ENCRYPTION_KEY
PYTHONPATH=. /tmp/v/bin/python -m app.licence keygen                         # LICENCE_PRIVATE_KEY / PUBLIC
```

| Variable | Value | Kyun |
|---|---|---|
| `BASE_DOMAIN` | `attendance.example.in` | tenant = subdomain |
| `ACME_EMAIL` | aapka email | Let's Encrypt notices |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | `fa_app` / 32+ random | DB login (server ke bahar kabhi nahi khulta) |
| `JWT_SECRET` | 48+ random | login tokens sign |
| `EMBEDDING_ENCRYPTION_KEY` | Fernet key | cloud DB me tenant DB URLs, API keys, PAN, bank account encrypted |
| `LICENCE_PRIVATE_KEY` | keygen se | edge licences sign; **sirf is server par** |
| `JWT_EXPIRE_MINUTES` | 480 | 8 ghante session |
| `APP_TIMEZONE` | `Asia/Kolkata` | |

`APP_ENV=production` compose me set hai: koi bhi secret default/kamzor ho to API **start hi nahi hogi** (jaan-boojh kar).

**In keys ka backup** password manager + offline copy me. `EMBEDDING_ENCRYPTION_KEY` kho gayi = PAN/bank/API keys padhe nahi jaayenge. `LICENCE_PRIVATE_KEY` kho gayi = har edge box me nayi public key daalni padegi.

---

## 4. Database config

`deploy/cloud/docker-compose.yml` me Postgres 16 + pgvector (migrations ko extension chahiye) ye settings ke saath chalta hai:

| Setting | Value (8 GB server) | Matlab |
|---|---|---|
| `max_connections` | 300 | har tenant ke chhote pools (2+4) + background jobs |
| `shared_buffers` | 1 GB (RAM ka ~25%; 4 GB server par 512MB) | cache |
| `effective_cache_size` | 3 GB (~75%) | planner hint |
| `work_mem` | 8 MB | sort/report queries |
| `maintenance_work_mem` | 256 MB | index / vacuum |
| `wal_compression` | on | kam disk |
| `log_min_duration_statement` | 500 ms | slow query log |
| `password_encryption` | scram-sha-256 | |

* Port `5432` sirf `127.0.0.1` par -- internet se DB kabhi nahi khulta. Admin ke liye: `ssh -L 5432:127.0.0.1:5432 fa@server`.
* Ek database **har client**: `fa_<slug>` (vendor console banata hai). Control DB: `fa_control`.
* App user `fa_app` ko `CREATEDB` chahiye (naye client ka DB banane ke liye). Docker image me ye user superuser hai; **managed DB** (AWS RDS / Azure Flexible Server) me:
  ```sql
  CREATE ROLE fa_app LOGIN PASSWORD '...' CREATEDB;
  CREATE DATABASE fa_control OWNER fa_app;
  \c template1
  CREATE EXTENSION IF NOT EXISTS vector;   -- har naye DB me apne aap aa jaata hai
  ```
  RDS / Azure dono pgvector support karte hain. Managed DB lene par compose se `db` service hata do aur URLs me RDS host daalo; backup/point-in-time-restore wo khud karte hain.
* 150+ clients: Postgres ke aage **PgBouncer** (transaction mode) lagao, ya bada DB server.

### Backup (bina iske live mat jao)
```bash
cd /opt/fa/deploy/cloud
python3 -c "import secrets;print(secrets.token_urlsafe(32))" > backup.pass && chmod 600 backup.pass
sudo crontab -e     # roz raat 2:15
15 2 * * * /opt/fa/deploy/cloud/backup.sh >> /var/log/fa_backup.log 2>&1
```
* Har client ka DB alag encrypted file (`pg_dump -Fc` + GPG AES-256), 30 din local.
* **Server se bahar copy** (dusre region ka object storage: AWS S3 / Azure Blob / Backblaze) -- `backup.sh` ki last line (`rclone`) on karo.
* Mahine me ek baar restore test: `gpg -d ... | pg_restore -d fa_restore_test`.

---

## 5. Chalu karna

```bash
cd /opt/fa/deploy/cloud
docker compose up -d --build
docker compose ps                      # api: healthy
curl -s https://attendance.example.in/api/v1/health    # {"status":"ok","role":"cloud",...}
```

Update (naya version):
```bash
cd /opt/fa && git pull && cd deploy/cloud && ./backup.sh && docker compose up -d --build
# migrations sab tenant DBs par apne aap; ya: docker compose exec api python scripts/tenants.py migrate
```

---

## 6. Naya client jodna (vendor console)

```bash
docker compose exec api python scripts/tenants.py create \
  --slug acme --name "Acme Industries" --type business \
  --departments Production Stores Office \
  --admin-email hr@acme.in --admin-name "HR Head" \
  --max-cameras 2 --max-people 200
```
Output (sirf ek baar dikhta hai -- turant client file me save):
* Dashboard URL `https://acme.attendance.example.in`
* Admin email + **temporary password** (pehle login par badalna zaroori)
* Edge box ke liye `CLOUD_URL`, `EDGE_SITE_TOKEN`, `LICENCE_PUBLIC_KEY`

Baaki commands:
```bash
tenants.py list                                   # sab clients + edge box last seen
tenants.py suspend --slug acme --reason "Invoice Nov unpaid"     # dashboard band, licence renew band
tenants.py resume  --slug acme
tenants.py set --slug acme --max-cameras 4        # plan upgrade
tenants.py set --slug acme --allowed-cidrs 203.0.113.10/32       # dashboard sirf office IP se
tenants.py edge-token --slug acme --replace       # edge box badla / token leak
tenants.py profile --slug acme --add-department Packing
```

## 7. Client site par edge box

```bash
git clone ... /opt/fa && cd /opt/fa/deploy/edge      # (aage: compiled edge build)
cp .env.edge.example .env     # CLOUD_URL, EDGE_SITE_TOKEN, LICENCE_PUBLIC_KEY, nayi EMBEDDING_ENCRYPTION_KEY
docker compose up -d --build
curl http://localhost:8000/api/v1/edge/status   # cloud_connected: true, licence: ok
```
1. Client admin dashboard me **Admin → Cameras → Add camera** (`main-gate`) → token copy → edge `.env` me `CAMERA_TOKEN_MAIN_GATE` + RTSP URL.
2. **Settings → Statutory payroll**: PT state, go-live date. **Holidays** bharo. Staff import (`scripts/import_people.py` cloud par chalakar) / dashboard se.
3. Photos se enrol (Staff → Manage → photos): photos seedha edge box par jaati hain.
4. Edge `./data` folder ka roz USB/NAS backup (faces sirf yahin hain).

Router: kuch nahi khol-na. Edge box sirf bahar `https://attendance.example.in:443` jaata hai.

## 8. Monitoring
* Uptime check (UptimeRobot / Better Stack): `https://attendance.example.in/api/v1/health` har 1 min.
* `tenants.py list` me edge box "last seen" purana = client ka box band / internet gaya → client ko call.
* Disk 80% par alert. `docker compose logs -f api` (JSON logs).

## 9. Go-live security checklist
- [ ] `APP_ENV=production`, sab secrets naye (API start ho gayi = check pass)
- [ ] DB port bahar band (`ss -tlnp | grep 5432` → sirf 127.0.0.1)
- [ ] SSH sirf key + sirf aapke IP se
- [ ] Backup cron + server ke bahar copy + ek restore test
- [ ] Har client: admin ne temporary password badla; per-camera tokens; shared `KIOSK_SERVICE_TOKEN` khaali
- [ ] InsightFace **commercial licence** (buffalo_l non-commercial hai) -- bechne se pehle
- [ ] DPDP: consent form (FORMS_AND_TEMPLATES.md), privacy notice, retention (`crop_retention_days`), breach process. Rules Nov 2025 me notify hue; notice / consent / security wali main duties **13 May 2027** se lagu.
- [ ] Client contract: data processor clause, edge box hardware ki zimmedari, backup, SLA
