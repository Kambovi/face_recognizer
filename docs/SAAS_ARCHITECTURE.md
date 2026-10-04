# SaaS architecture (v3) -- cloud + edge box

Ye document batata hai ki product ab **SaaS** kaise chalta hai: client ko code nahi milta, sirf dashboard ka access milta hai (jaise Keka), aur chehre (faces) + photos + policy PDFs client ki site par hi rehte hain.

## 1. Teen modes (ek hi codebase)

| `APP_ROLE` | Kahan chalta hai | Kya karta hai |
|---|---|---|
| `standalone` (default) | Ek PC par sab kuch | Purana tareeka: demo, pilot, chhote client jo cloud nahi chahte |
| `cloud` | Aapka server (AWS/Azure/...) | Dashboard, payroll, reports, chatbot, users, sab clients (har client ka **alag database**) |
| `edge` | Client ki site par ek chhota PC (edge box) | Cameras se aane wale faces match karta hai, face templates + photos + policy PDFs rakhta hai |

## 2. Picture

```
 CLIENT SITE (Acme factory)                         YOUR CLOUD SERVER
 ┌───────────────────────────────┐                 ┌───────────────────────────────────────┐
 │ IP camera ──RTSP──► kiosk.py  │                 │  Caddy (HTTPS, *.attendance.in)        │
 │   (detect, liveness, embed)   │                 │     │                                  │
 │            │ LAN, camera token│                 │     ▼                                  │
 │            ▼                  │  outbound 443   │  API (APP_ROLE=cloud, 1 worker)        │
 │  EDGE BOX (app.edge.main)     │ ═══════════════►│   ├─ tenant from acme.attendance.in    │
 │   • face templates (SQLite,   │  WebSocket +    │   ├─ control DB: tenants, edge boxes   │
 │     encrypted)                │  HTTPS results  │   └─ fa_acme DB, fa_school2 DB, ...    │
 │   • face photos (disk)        │                 │        (attendance, people, payroll,    │
 │   • policy PDFs               │ ◄═══════════════│         users, audit -- NO faces)      │
 │   • outbox (offline queue)    │  "enrol this",  │                                        │
 │   • licence check             │  "show photo"   │  Browser: HR / owner (anywhere)        │
 └───────────────────────────────┘                 └───────────────────────────────────────┘
```

* Edge box **khud cloud se connect** karta hai (outbound HTTPS 443). Client ke router par koi port forward, static IP, VPN nahi chahiye. Client ka IP address connect karne ka idea isliye nahi liya: dynamic IP, NAT, Jio/Airtel routers, firewall -- har jagah toot-ta hai.
* Optional: tenant ka dashboard sirf office ke IP se khule -- `tenants.py set --slug acme --allowed-cidrs 203.0.113.10/32`.

## 3. Data kahan rehta hai

| Data | Cloud | Edge box |
|---|---|---|
| Face templates (embeddings) | ❌ kabhi nahi | ✅ (encrypted, edge ki apni key) |
| Face photos (detections, enrolment, unknown best shot) | ❌ (sirf reference `det:<id>`) | ✅ |
| Policy documents (PDF/DOCX) | ❌ | ✅ |
| Employees, departments, salary, bank (encrypted), PAN (encrypted) | ✅ | sirf ids (`people` list) |
| Attendance events, sightings, alerts, leave, holidays, payroll | ✅ | outbox me thodi der (jab tak cloud tak na pahunche) |
| Users / logins / audit log | ✅ | ❌ |

Photo dekhna: browser → cloud `/api/v1/media/...` → tunnel → edge photo bhejta hai → cloud seedha browser ko deta hai (disk/DB me save nahi hota). Policy search: chatbot cloud me, search edge par (`policy.search`), sirf matching paragraph wapas aata hai.

## 4. Ek camera event ka safar

1. Kiosk face detect + liveness + embedding karta hai → `POST /api/v1/kiosk/event` **edge box** ko (LAN, per-camera token).
2. Edge: licence valid? time sahi? liveness pass? → `match_locally()` apne templates se → employee / unknown / unclear / reject.
3. Photo edge disk par, result (`MatchResult`: ids, time, score, `det:<event id>`) **outbox** me.
4. Outbox loop result `POST /api/v1/edge/results` se cloud bhejta hai; internet band ho to queue me rehta hai (restart ke baad bhi).
5. Cloud `record_result()`: IN/OUT rules, shift-aware day, sightings, watchlist/inactive alerts, unknown ka mirror row (UNK-xxxx). Same `client_event_id` dobara aaye to dobara count nahi hota.

## 5. Tunnel par cloud kya maang sakta hai (`app/edge/rpc.py`)

`enroll`, `templates.list|delete|purge|counts`, `unknown.adopt|split|delete`, `media.get` (sirf `det:/unk:/tpl:/emp:` references, koi raw path nahi), `policy.search|status|reindex`, `ping`.

Edge box offline ho to ye actions dashboard par saaf error dete hain: *"The site's face-recognition box is offline"*. Attendance phir bhi edge par record hoti rehti hai aur baad me sync ho jaati hai.

## 6. Licence = subscription lock

* Cloud ke paas Ed25519 **private key** (`LICENCE_PRIVATE_KEY`), edge ke paas sirf **public key**.
* Har config sync par cloud naya licence deta hai (7 din valid). Edge 7 din + 7 din grace tak offline chal sakta hai.
* Client suspend (`tenants.py suspend`) → dashboard 402, aur naya licence nahi milta → max 14 din baad edge camera events lena band (kiosk events queue me rehte hain; resume par 72 ghante tak ke wapas aa jaate hain).
* Licence copy/edit nahi ho sakta (signature toot jaata hai) -- test: `tests/test_licence.py`.

## 7. Code protection -- honest picture

* **Cloud code** (payroll, reports, analytics, dashboard, chatbot, multi-tenant) aapke server par hi rehta hai. Client ko kabhi nahi milta. ✅
* **Edge box** par recognition code chalana padega (faces wahi rehte hain). Is code ko bachane ke liye:
  1. Edge build me sirf zaroori modules (`app/edge`, `app/services/{matching,face_store,unknown_identity,media,embedding,...}`, kiosk) -- payroll/reports wale routers ship mat karo.
  2. Nuitka se compile (`python -m nuitka --standalone --follow-imports app/edge/main.py ...`) -- Python source nahi jaata. *(Next step: build script + test on Windows; abhi documented hai, automated nahi.)*
  3. Licence ke bina edge bekaar hai -- cloud ke bina koi dashboard/payroll nahi.
  4. Contract me reverse-engineering / tampering clause (BUSINESS_PLAYBOOK.md).

## 8. Tenancy (har client ka alag database)

* Control DB (`fa_control`): `tenants` (slug, naam, status, plan limits, encrypted DB URL, allowed IPs) + `edge_sites` (hashed token, last seen, IP, version).
* Har tenant: `fa_<slug>` database, wahi Alembic migrations. API start par sab tenant DBs migrate hote hain; ya `tenants.py migrate`.
* Request ka tenant host name se: `acme.<BASE_DOMAIN>`. Dev/test me `X-Tenant: acme` header (production me band).
* Fayde: ek client ka data dusre me kabhi nahi, client-wise backup/restore/delete, bada client alag server par shift.

## 9. Limits (v3)

* Ek tenant = ek edge box (ek site). Multi-site client = har site alag tenant + purana HQ (Sites) feature, ya agla version (ek tenant, kai edge boxes, templates sab boxes par sync).
* Cloud API ek worker (WebSockets ek process me). ~300 tenants tak theek; uske baad Redis pub/sub.
* Edge box kharab = faces dobara enrol karne padenge, **agar backup nahi hai**. `deploy/edge` me `./data` folder ka USB/NAS backup zaroori (EMBEDDING_ENCRYPTION_KEY ke saath).
* Enrolment ke liye edge box online hona chahiye.

## 10. Files

| File | Kya |
|---|---|
| `backend/app/tenancy.py` | control DB, tenant resolve middleware, per-tenant engines |
| `backend/app/edge_hub.py`, `routers/edge.py` | cloud side tunnel, `/edge/config`, `/edge/results` |
| `backend/app/edge/` | edge box app: `main.py`, `sync.py` (tunnel/outbox/config), `rpc.py`, `state.py` |
| `backend/app/services/recognition.py` | `match_locally()` + `record_result()` |
| `backend/app/services/biometrics.py` | routers ke liye: standalone = local, cloud = edge RPC |
| `backend/app/services/face_store.py` | templates/photos ka local kaam (standalone + edge) |
| `backend/app/licence.py` | licence sign/verify, `python -m app.licence keygen` |
| `backend/scripts/tenants.py` | vendor console |
| `deploy/cloud/*`, `deploy/edge/*` | docker compose, Caddy, backup |
| `tests/test_saas_e2e.py` | asli cloud + edge processes ka end-to-end test (SQLite ya `E2E_PG=` Postgres) |
