# Business playbook: akele ye product kaise bechein aur chalayein

> Tum developer bhi ho, salesman bhi aur support bhi. Ye file business wala hissa sambhalti hai: kisko bechna hai, kitne me, kya kharcha hai, kaunse kaagaz chahiye, aur client ko kaise sambhalna hai.
>
> **Note:** price aur kharche ke numbers Sept 2026 ki market research par based andaaze hain. Legal/tax wale points ek CA/lawyer se confirm karke hi final karo. Main CA ya lawyer nahi hoon.
>
> Last updated: 26 Sep 2026

## Contents

1. [Kisko bechna hai](#1-kisko-bechna-hai)
2. [Pricing aur packages](#2-pricing-aur-packages)
3. [Tumhara kharcha aur munafa](#3-tumhara-kharcha-aur-munafa)
4. [Legal, tax aur compliance checklist](#4-legal-tax-aur-compliance-checklist)
5. [Contract me kya likhna hai](#5-contract-me-kya-likhna-hai)
6. [Sales process aur demo script](#6-sales-process-aur-demo-script)
7. [Objections ke jawab](#7-objections-ke-jawab)
8. [Support, SLA aur AMC](#8-support-sla-aur-amc)
9. [Akele kaam chalane ka system](#9-akele-kaam-chalane-ka-system)
10. [Badhne ka plan aur khatre](#10-badhne-ka-plan-aur-khatre)

---

## 1. Kisko bechna hai

**Pehla focus: factory, warehouse, logistics (100–1,000 workers).**

- Shift wala kaam aur contract labour hota hai.
- Proxy attendance (buddy punching) aam hai.
- CCTV pehle se laga hota hai.
- Dastane pehne haath fingerprint machine par nahi chalte.

Ek hi industrial area (Chakan, Manesar, Noida, Sanand...) chuno. Ek factory ka owner doosre ko jaanta hai.

| Priority | Segment | Kyun | Dhyan |
|---|---|---|---|
| 1 | Factory / warehouse | contractor + OT + shifts = saare naye features yahin kaam aate hain | |
| 2 | Private hospital / nursing home | 24x7 shifts, kai gates, budget hota hai | bechne me time lagta hai |
| 3 | Coaching institute / private school | market bada hai | bachchon ke data par DPDP ke sakht niyam (parents ki verified consent). Baad me lo. |
| Baad me | UAE / Saudi (blue-collar workforce) | zyada daam milta hai | Arabic UI aur local partner chahiye |
| Abhi nahi | Europe / USA | GDPR aur BIPA jaise biometric kanoon, bade case | |

**Ideal client:**

- 100+ log, 1–4 gates
- Payroll Tally/Excel/Zoho par
- Contractor labour hai
- Owner khud decision leta hai
- Kisi ghatna ya audit ke baad "security" ki baat karta hai

---

## 2. Pricing aur packages

**Model:** ek baar ka setup fee + har camera (entry point) ka monthly subscription. Hardware alag, cost + margin par.

Market reference (Sept 2026 research):

- App-based attendance: ₹35–150 per user per month
- Face attendance SaaS: ₹250–350 per user per year + base fee
- Biometric machine: ₹5k–65k per machine

Hamara pehle ka andaza ₹2,500–4,000 per camera per month tha. **Pehle 3–5 pilots me isko test karo.**

| Package | Kya milta hai | Suggested daam (andaza) |
|---|---|---|
| **Starter** | 1 camera, 200 log tak, dashboard, reports, payroll export | Setup ₹15–25k + ₹2,500/camera/month |
| **Pro** (recommended) | Starter + contractor report, shift roster/OT, muster, watchlist, WhatsApp, monthly PDF | Setup ₹25–40k + ₹3,500/camera/month |
| **Enterprise** | Pro + multi-site head office, priority support, custom payroll format | Setup ₹50k+ + ₹4,000/camera/month + ₹2,000/site/month (HQ) |
| Add-ons | extra department (setup ke baad), camera cap 200 → 300, naya payroll format, on-site training | ₹2–10k per item |

**Tareeke jo kaam aate hain:**

- **Saal bhar ka advance** lo to 2 mahine free (10 ka paisa, 12 ka service). Cash flow ke liye bahut zaroori hai.
- **Paid pilot:** 30 din ka ₹10–15k. Client sign kare to ye setup fee me adjust ho jaata hai. Free pilot se log serious nahi hote.
- **ROI se becho, feature se nahi.** Example: 300 workers × 3% proxy/extra hours × ₹500/day × 26 din = ₹1.17 lakh per month ki bachat. Subscription iska 5–10% hai.
- Daam GST ke bina batao aur quotation me "+ 18% GST" likho (rate CA se confirm karo).

---

## 3. Tumhara kharcha aur munafa

**Ek client ka ek baar ka kharcha (andaza, 2 gate wali factory):**

| Item | Kharcha (₹) | Kaun deta hai |
|---|---|---|
| Mini-PC / server (i5/i7, 16 GB, SSD) | 35,000 – 60,000 | client (hardware bill alag) |
| IP camera 2–4 MP, WDR | 3,000 – 8,000 per camera | client |
| PoE switch, cabling, bracket | 3,000 – 10,000 | client / installer |
| UPS | 4,000 – 8,000 | client |
| Tumhara install + training time | 2–3 din | setup fee se |
| Travel | asli kharcha | setup fee me jodo |

**Har mahine ka kharcha:**

| Item | Kharcha | Note |
|---|---|---|
| WhatsApp messages | Meta per-message charge | Utility templates sasti hoti hain. Meta ki current pricing dekho. 10 msg/din × 30 = 300 msg/mahina. Client se pass-through ya package me |
| Head-office VM (sirf multi-site) | ₹1,000 – 3,000 | 2 vCPU / 4 GB |
| Remote access tool | ₹0 – 1,000 | Tailscale free tier |
| InsightFace commercial license | **abhi pata nahi**, quote lena hai | Per-install / per-year ho sakta hai. Pricing me isko jodna zaroori hai |
| Domain, email, GitHub private | ₹200 – 1,000 | |

**Unit economics example** (Pro plan, 2 camera):

- Kamai: setup ₹30k (ek baar) + ₹7,000/mahina
- Direct kharcha: ~₹500/mahina (WhatsApp + tools) + license (TBD)
- Support time: ~2 ghante/mahina
- 10 aise clients = ₹70k/mahina recurring. 30 clients par akele sambhalna mushkil hoga; tab ek support/installer rakhne ka waqt hai.

---

## 4. Legal, tax aur compliance checklist

**Business setup** (CA se baat karo):

- [ ] Business ka form: sole proprietorship (sabse aasaan) ya OPC / Pvt Ltd (bade clients aur tender ke liye behtar, liability limited)
- [ ] Udyam (MSME) registration: free hai, kai clients aur banks maangte hain
- [ ] GST registration: services me turnover limit paar hone par zaroori hai. Bade B2B clients GST invoice hi maangte hain, isliye jaldi lena behtar. Software services par rate (aam taur par 18%) CA se confirm karo.
- [ ] Current account, invoice format (GSTIN, SAC code, due date)
- [ ] Professional indemnity / cyber insurance: biometric data sambhalte ho, isliye baad me zaroor lo

**Software license:**

- [ ] **InsightFace `buffalo_l` model: commercial use ke liye license chahiye.** Pehle paid client se pehle quote lo, pehle recurring paise aate hi kharido. Iske bina bada client (audit karne wala) khona pad sakta hai.
- [x] MiniFASNet liveness weights: Apache-2.0, commercial use OK. Notice file saath rakho.
- [x] FastAPI, React, SQLAlchemy etc.: MIT/BSD/Apache, commercial use OK.
- [ ] Docker Desktop: client company 250+ employees ya $10M+ revenue wali ho to paid. Isliye client server par Linux + Docker Engine (free).

**DPDP Act 2023 (India ka data protection kanoon):**

- Client = **Data Fiduciary** (data ka maalik). Tum = **Data Processor** (unki taraf se data process karte ho).
- [ ] Har employee ki **likhit consent** client le. Form `FORMS_AND_TEMPLATES.md` me hai. Consent ke bina enrollment nahi.
- [ ] Client ke saath **Data Processing Agreement (DPA)**: sirf attendance ke liye use, security measures, breach ki soochna, contract khatam hone par deletion.
- [ ] Bachche (school) = verified parental consent + extra niyam. Is segment me jaane se pehle lawyer se baat karo.
- [ ] Data India me, client ke server par. Multi-site par sirf ginti jaati hai. Ye selling point bhi hai.
- [ ] Data breach hone par client ko turant batane ka process likha ho
- DPDP ke niyam (Rules) phase me lagu ho rahe hain. Saal me ek baar lawyer se update lo.

---

## 5. Contract me kya likhna hai

Teen documents banao: **MSA** (master agreement) + **Order form / SOW** (har client ka scope aur daam) + **DPA**. Ek lawyer se template ek baar banwa lo (₹10–25k), phir har client ke liye sirf Order form bharo.

**Zaroori clauses:**

| Clause | Kya likhna |
|---|---|
| Scope | kitne camera, kitne log (per camera 200), kaunse features, kaunse payroll formats |
| Client ki zimmedari | camera, server, bijli, network, consent forms, sahi employee data |
| Accuracy | "Recognition rate target ≥ 95% under recommended camera placement and lighting". **100% ka vaada kabhi mat karo.** Liveness "reduces" spoofing, "eliminates" nahi. |
| SLA | support ka time, response time (section 8), uptime tumhare control wale hisse ka |
| Payment | advance, due date, late fee, na dene par service suspend karne ka haq |
| IP | software tumhara hai; client ko use ka license hai, source code nahi |
| Data | client ka data client ka; DPA attached; contract ke baad 30 din me export + deletion |
| Liability cap | pichhle 12 mahine ki fees tak |
| Termination | 30–90 din ka notice; lock-in ho to likho |
| Price badhna | saal me ek baar, X% tak |

---

## 6. Sales process aur demo script

**Pipeline stages.** Client register (section 9) me har lead ki stage track karo:

`Lead → Pehli call → Site visit + demo → Paid pilot → Proposal → Signed → Installed → Live → Renewal`

**Leads kahan se milenge:**

1. **CCTV installers / system integrators ko partner banao** (20–30% commission ya fixed referral). Ye roz factories me jaate hain. Ye sabse tez raasta hai.
2. CA aur payroll consultants: unke clients ko payroll ki dikkat hoti hai.
3. Industrial association ki meetings, local expos.
4. LinkedIn par plant HR / admin / owners ko seedha message, saath me 60 sec ka demo video.
5. IndiaMART / TradeIndia listing.
6. Har live client se referral: 1 mahina free.

**10 minute ka demo script** (apne laptop par demo DB ke saath, `seed_demo.py` alag DB par):

1. **(1 min) Dard:** "Aapke yahan proxy attendance / contractor bill / OT ka hisaab kaise hota hai?" Unhe bolne do.
2. **(2 min) Live:** laptop camera ke saamne chalo. Naam aa gaya, IN time aaya. Phone par apni photo dikhao, reject hui aur **bell baji**.
3. **(2 min) Dashboard + phone:** aaj kaun aaya, kaun late, kaun absent. Phone par wahi view.
4. **(2 min) Paisa:** Reports → Contractor bill check (man-days), Payroll export → Tally file download.
5. **(1 min) Safety:** Emergency button → andar kaun hai → roll call.
6. **(1 min) WhatsApp:** roz ka summary jo owner ko aata hai.
7. **(1 min) Close:** "30 din ka pilot aapke main gate par, ₹X, sign karne par adjust." Date tay karo.

---

## 7. Objections ke jawab

| Client bolta hai | Tum bolo |
|---|---|
| "Photo dikha kar attendance laga denge" | Live dikhao: phone ki photo reject hui aur alert aaya. "Har camera par hum calibrate karte hain." |
| "Chehra ka data kahin leak ho gaya to?" | "Data aapke server par, aapke building me rehta hai. Kahin upload nahi hota. Chehre ke numbers (embeddings) encrypted copy ke saath rehte hain, aur chhoti face-crop photos sirf aapke server par. Consent aur audit log sab hai." |
| "Biometric machine sasti hai" | "Machine par line lagti hai, dastane me nahi chalti, proxy hoti hai, aur contractor/OT report nahi deti. ₹X ki bachat har mahine hoti hai" (ROI example). |
| "Internet chala gaya to?" | "System local chalta hai. Internet sirf WhatsApp ke liye chahiye; camera offline ho to bhi data save hota hai." |
| "Hamare paas camera nahi hai" | "IP camera ₹3–8k ka aata hai. Hum installer bhej denge." |
| "Mask / helmet pehen kar aate hain" | "Gate par 2 second ke liye helmet/mask hatana policy banani hogi. Sab face systems ki yahi shart hai." |
| "Accuracy kitni hai?" | "Sahi camera placement par 95%+. Pilot me aapke yahan naap kar dikhayenge." (Pilot me sach me naapo.) |

---

## 8. Support, SLA aur AMC

| Problem kitni badi | Example | Response | Theek karna |
|---|---|---|---|
| P1 critical | koi attendance nahi lag rahi, server down | 2 ghante (working hours) | same / agla din |
| P2 major | ek camera offline, report galat | 1 working day | 2–3 din |
| P3 minor | UI sawaal, naya user banana | 2 working days | agla release |

- Support ka ek hi channel rakho (ek WhatsApp Business number + email), taaki har request likhit me aaye.
- **AMC** (subscription me shamil): mahine me remote health check, 3 mahine me backup restore test, updates, saal me ek site visit. Extra visits ka charge alag.
- Har client ke server par remote access (Tailscale/AnyDesk) client ki likhit anumati se.

---

## 9. Akele kaam chalane ka system

**Client register** (ek Google Sheet / Excel, har client ki ek row):

`Client | Sector | City | Contact | Phone | Stage | Cameras | People | Plan | ₹/month | Start | Renewal date | Version (git tag) | Server IP / Tailscale | Liveness calibrated? | Backup OK date | Next AMC | Notes`

**Har client ka ek folder** (password manager + encrypted drive):

- Signed MSA / Order / DPA
- `.env` secrets, vendor PIN
- Site survey, camera list, `setup_client.py show` ka output
- Acceptance sign-off
- Invoices

**Hafte ki routine:**

| Din | Kaam |
|---|---|
| Somvar | saare clients ka 10 min remote health check (cameras online, alerts, disk) |
| Mangal–Guru | sales: 10 naye contacts, 2 demos |
| Shukra | development: bug fixes / ek feature; release sirf test ke baad |
| Mahine ki 1 tareekh | invoices, monthly PDF clients ko, renewal reminders |

**Version control:**

- Har client par ek git **tag** install karo (`v2.0.0`). Register me likho.
- Naya version pehle apne laptop par, phir ek client par 1 hafta, phir sab par.

---

## 10. Badhne ka plan aur khatre

**Pehle 6 mahine:**

1. InsightFace license ka quote. 3 paid pilots (ek hi industrial area me).
2. Pilot data se asli recognition rate aur ROI numbers nikalo. Wahi case study banti hai.
3. 2 CCTV installer partners.
4. 10 paying clients. Isi waqt ek part-time installer / support banda.

**Khatre aur bachav:**

| Khatra | Bachav |
|---|---|
| Model license ke bina becha, client ne audit kiya | pehle recurring paise aate hi license lo; contract me third-party component clause |
| Accuracy ka vaada toota | contract me "recommended conditions" + pilot measurement |
| Data breach | client server par data, encrypted embeddings, VPN-only access, DPA, insurance |
| Tum bimaar ya busy, support ruk gaya | documentation (ye docs), scripts, remote access; baad me ek backup banda |
| Bada competitor sasta aaya | niche pakdo: contractor/OT/muster + on-premise + local support |
| Client paise nahi deta | advance / annual billing, suspend clause |
