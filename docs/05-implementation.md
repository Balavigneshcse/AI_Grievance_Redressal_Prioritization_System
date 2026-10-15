# SYNAPSE: Technical Implementation

## Phase 4 - Checkpoint 4

Covers: what is built, how it runs, the API, and the evidence from the first end-to-end run.

Date: 15 October 2026 | Status: backend and frontend complete and tested end to end

---

## 1. What is built

| Layer | Location | State |
|---|---|---|
| API server | `backend/app/main.py` (FastAPI, 30 routes, OpenAPI at `/docs`) | complete |
| Database | `backend/app/models.py` (SQLAlchemy 2, 11 tables, pgvector column + HNSW index), `backend/app/db.py` (create, seed departments in en/ta/hi) | complete |
| Auth | `backend/app/api/auth.py`, `backend/app/security.py`: register with mobile + email + strong password, email OTP (hashed, 10 min, 5 attempts), login, forgot/reset by OTP, JWT with password-version invalidation | complete |
| Complaint intake | `backend/app/api/complaints.py`: multipart text + photos/videos + GPS or manual address, EXIF GPS fallback, tracking ID, acknowledgement email, media served through an authenticated route | complete |
| Analysis worker | `backend/app/services/worker.py` + `pipeline.py`: one background thread; language hint, PII mask, offline geocode, Gemma 3 (text + first photo) with JSON schema, bge-m3 embedding, pgvector duplicate search, NumPy second opinion, YAML rules, decision, status event, email | complete |
| Rules engine | `backend/app/services/rules.py`, `config/rules.yaml`: 10 starter rules in English, Tamil, Hindi and romanised forms; hot reload; admin test endpoint | complete |
| District office routing | `config/tn_mapping.json` from the team's Tamil Nadu spreadsheet (38 districts, 20 departments mapped onto our 8 categories, 760 offices with SLA, 41 keyword hints): each complaint gets a district, a named office and a due time | complete |
| Officer review | `backend/app/api/review.py`: review queue sorted by urgency then age with flags, department queues, accept / reassign / merge / request info / resolve / close / reopen with mandatory reason, override log, status emails | complete |
| Admin | `backend/app/api/admin.py`: read/write rules with change log, rule tester, metrics (totals, by status, by department, live accuracy per language from officer corrections, eval runs, second-opinion report) | complete |
| Notifications | `backend/app/services/notifier.py`: OTP, acknowledgement, routed, under review, status templates in en/ta/hi; every send logged | complete |
| Local services | `docker-compose.yml`: PostgreSQL 17 + pgvector (port 5434), Mailpit (8025/1025) | running |
| Seed | `backend/seed.py`: super admin, Coimbatore district admin, two Coimbatore department admins (water, roads), one citizen | done |
| Frontend | `frontend/` (React 18 + Vite, Tailwind v4, shadcn/ui on Base UI, lucide-react, react-router, react-hook-form + zod, i18next en/ta/hi, react-leaflet): register, OTP verify, login, forgot/reset, my complaints, new complaint with in-app camera, GPS, map pin, reverse geocode and bottom sheet, track page with 3 s polling, evidence highlighting and timeline, officer queue with filters and flags, officer workspace with accept / reassign / merge / request-info dialogs; `npm run build` passes | complete, verified in the browser against the live API (15 Oct 15:25) |

---

## 2. Running it

```bash
docker compose up -d
```

```bash
cd backend && python seed.py && python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

Open `http://localhost:8000/docs` for the API, `http://localhost:8025` for the mail inbox, `http://localhost:5173` for the app. Seed accounts (password from `SEED_PASSWORD` in `.env`): `admin@synapse.local` (super admin), `district.coimbatore@synapse.local` (district admin, Coimbatore), `officer.water@synapse.local` and `officer.roads@synapse.local` (department admins, Coimbatore), `citizen@synapse.local`.

---

## 3. API

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/auth/register` | public | mobile, email, password, language; sends OTP |
| POST | `/auth/verify-otp` | public | activates the account, returns JWT |
| POST | `/auth/resend-otp` | public | new registration code |
| POST | `/auth/login` | public | JWT; 403 if unverified |
| POST | `/auth/forgot`, `/auth/reset` | public | password reset by OTP; invalidates old sessions |
| GET | `/auth/me` | any | current user |
| GET | `/departments` | public | ids and names in three languages |
| POST | `/complaints` | complainant | multipart intake, returns 202 + tracking ID, queues analysis |
| GET | `/complaints/mine` | complainant | own complaints |
| GET | `/complaints/{id}`, `/complaints/track/{tracking_id}`, `/complaints/{id}/timeline` | owner or staff | detail with analysis, decision, timeline; PII and second opinion only for staff |
| GET | `/media/{id}` | owner or staff | photo or video file |
| POST | `/geo/reverse` | public | lat/lng to nearest locality |
| GET | `/review/queue` | staff | complaints in the caller's scope; `view=review|active|resolved|all`, filters by department, urgency, language, district |
| GET | `/departments/{dept}/queue` | staff (own department for department admins) | routed, in-progress and awaiting-info complaints |
| GET | `/review/{id}` | staff, inside scope | full detail including masked text, PII map, complainant name and Aadhaar last 4 |
| POST | `/review/{id}/decision` | staff, inside scope | accept, reassign, merge, request_info, resolve, close, reopen; reason required |
| GET, POST | `/admin/users` | super admin, district admin | list and create staff accounts (district admin: department admins of own district only); the generated password is returned once |
| PATCH | `/admin/users/{id}` | super admin, district admin | enable or disable, rename, move department, reset password |
| GET | `/admin/districts` | staff | the 38 Tamil Nadu districts with staff counts |
| GET | `/admin/overview` | super admin, district admin | complaint counts per district and department |
| GET, PUT | `/admin/rules` | super admin (read: all staff) | YAML rules with change log |
| POST | `/admin/rules/test` | staff | run the rules against a text |
| POST | `/admin/models/reload` | super admin | pick up a newly trained second-opinion model |
| GET | `/admin/metrics` | staff | dashboard data |
| GET | `/health` | public | db, Ollama, models, queue depth |

---

## 4. Evidence: first end-to-end run (15 Oct 2026, 14:20)

Driven by a script against the live API with Gemma sharing the GPU with the synthetic-data generator.

| Step | Result |
|---|---|
| `/health` | db ok, Ollama ok, gemma3:4b, bge-m3 and second-opinion model present |
| Register (Tamil preferred) | 201; OTP email arrived in Mailpit with a Tamil subject |
| Verify OTP | 200, JWT issued |
| File complaint: "thanni 3 days ah varala sir. veetla 2 kids irukanga, rendu perum vomiting and fever. Anna Nagar 4th street ... my number 98xxxxxxxx", with browser GPS | 202, tracking ID SYN-2026-000001, acknowledgement email sent |
| Worker | 50 s wall clock (Gemma 38 s while the generator held the GPU); language ta+en; model said health, critical, 0.95; evidence spans copied verbatim from the Tanglish text; place resolved to Gandhipuram, Coimbatore |
| Rules | R5 water keyword forced department Water Supply; R8 repeat complaint raised the floor |
| Decision | review queue, reasons: rule overrides model department, critical always checked |
| PII | citizen response has no PII map; officer response shows `[PHONE_1]` mapped to the number and the masked text |
| Officer | queue shows the complaint with flags critical and disagreement; reassign to Water / Critical with reason; status routed; routed email sent in Tamil |
| Admin metrics | 1 complaint, 1 critical open, review rate 1.0, auto-closed 0, live accuracy for ta recorded the correction as a model miss |
| Mail | 4 emails to the citizen: OTP, acknowledgement, under review, routed |

**Second run (14:48), after the Tamil Nadu office mapping was added.** A Hinglish street-light complaint with Ukkadam GPS, filed twice:

| Step | Result |
|---|---|
| Model | said Safety (women feel unsafe in the dark), Medium, confidence 0.95 |
| Rule R5b (street light, three languages) | overrode department to Roads; the override is a disagreement, so the complaint went to review instead of auto-routing |
| District office | district Coimbatore from the locality; keyword RR008 picked the Street Lighting office rather than the Roads default; due time set 24 h out for Medium |
| Duplicate detection | the second filing matched the first at similarity 1.00 and was flagged as a possible duplicate |
| Officer queue | shows the complaint with flags disagreement and duplicate, office name and due time |

Together the two runs cover every Phase 1 problem except photo evidence, which is implemented (first photo goes to the model, EXIF GPS read) and will be shown live.

---

## 5. Known limits at this checkpoint

- Latency per complaint is 17-20 s with the GPU free, more while training or generation runs; the UI shows an "analysing" state.
- Notifications are email only (OTP, acknowledgement, under review, routed, resolved). No SMS. WhatsApp intake and notifications are in the roadmap and deliberately not built.
- Video: the file is stored and served; only photos go to the model. Key-frame extraction is a stretch.
- Rules editor UI, dashboard charts and department queue screens are after the core complainant and officer flows.
- No automated tests beyond the end-to-end script and `scripts/run_eval.py` yet.

---

## 6. Day 1 evening: roles, identity, video evidence, async mail (15 Oct 2026, 18:00-19:30)

### Role hierarchy

| Role | Scope | Can do |
|---|---|---|
| `super_admin` | all districts | create district admins and any staff account, rules editor, metrics, model reload, every complaint |
| `district_admin` | one Tamil Nadu district | review queue of the district (cases that need a human), add departments by creating their department admins, disable them |
| `dept_admin` | one department in one district | sees only that department's complaints in that district: accept (starts work), request info, resolve, close, reassign, merge |
| `complainant` | own complaints | file, track, reply |

Scoping lives in `backend/app/api/deps.py` (`scope_complaints`, `can_access`) and is applied by every review route, the detail route and the media route. A department admin opening another department's complaint gets 403. Disabling an account bumps its password version, which ends every open session. The migration in `db.py` renames the day-1 roles (`admin` → `super_admin`, `officer` → `dept_admin`) and adds `users.district`, `users.full_name`, `users.is_active`.

Frontend: `/admin` (super and district admins) lists staff with an active switch, shows complaint counts per district, and creates accounts in a dialog; the generated password is shown once with a copy button. The queue page has four views (needs review, active work, resolved, all), is scoped by role, and refreshes itself every 5 s, so a department admin sees a new routed complaint without reloading.

### Complaint identity

Every complaint now carries `complainant_name` and `aadhaar_last4` (exactly four digits), entered in a "Your details" card on the form and validated by the API (400 otherwise). They are stored on the complaint, shown to the owner and to staff, and never sent to the model: the model only sees the masked complaint text.

### Video evidence

The camera dialog has a video mode: MediaRecorder at 1.5 Mbit/s with sound when a microphone is available, a running clock, and an automatic stop at 5 minutes. Limits, enforced on both sides: photos up to 25 MB, videos up to 100 MB and 300 s (`MAX_PHOTO_MB`, `MAX_VIDEO_MB`, `MAX_VIDEO_SECONDS`). Uploads are streamed to disk in 1 MB pieces so a 100 MB video never sits in memory. Videos are evidence for the office; the model still reads only the first photo.

### Performance

- Mail is asynchronous: `notify()` writes a `queued` row and an outbox thread (`services/notifier.py`) delivers it through one persistent SMTP connection, with three attempts and the reason stored on failure. Registration, intake and the analysis worker no longer wait 7-10 s per email on a slow network.
- Gemma and bge-m3 are warmed at startup and kept loaded (`LLM_KEEP_ALIVE=2h`), so the first complaint after a restart does not pay the model load.
- The worker logs the time per complaint and the model share of it; the API logs which mail server it uses at startup and every send.

### Console fixes

Google Fonts were removed (the hackathon network closes those connections); the UI uses the system fonts that ship with Windows and Android and cover Tamil and Devanagari. The two `Button`s that render a router `Link` now pass `nativeButton={false}`, which clears the Base UI warning.
