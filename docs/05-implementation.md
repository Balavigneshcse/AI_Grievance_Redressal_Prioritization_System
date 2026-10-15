# SYNAPSE: Technical Implementation

## Phase 4 - Checkpoint 4

Covers: what is built, how it runs, the API, and the evidence from the first end-to-end run.

Date: 15 October 2026 | Status: backend complete and tested; frontend in progress

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
| Officer review | `backend/app/api/review.py`: review queue sorted by urgency then age with flags, department queues, accept / reassign / merge / request info / resolve / close / reopen with mandatory reason, override log, status emails | complete |
| Admin | `backend/app/api/admin.py`: read/write rules with change log, rule tester, metrics (totals, by status, by department, live accuracy per language from officer corrections, eval runs, second-opinion report) | complete |
| Notifications | `backend/app/services/notifier.py`: OTP, acknowledgement, routed, under review, status templates in en/ta/hi; every send logged | complete |
| Local services | `docker-compose.yml`: PostgreSQL 17 + pgvector (port 5434), Mailpit (8025/1025) | running |
| Seed | `backend/seed.py`: admin, two officers, one citizen | done |
| Frontend | `frontend/` (React + Vite, shadcn/ui, lucide): register, OTP, login, my complaints, new complaint with camera and location, track, officer queue and workspace | in progress |

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

Open `http://localhost:8000/docs` for the API, `http://localhost:8025` for the mail inbox, `http://localhost:5173` for the app. Seed accounts: `admin@synapse.local`, `officer.water@synapse.local`, `officer.roads@synapse.local`, `citizen@synapse.local`, password from `SEED_PASSWORD` in `.env`.

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
| GET | `/review/queue` | officer, admin | under-review complaints with flags and filters |
| GET | `/departments/{dept}/queue` | officer, admin | routed and in-progress complaints |
| GET | `/review/{id}` | officer, admin | full detail including masked text and PII map |
| POST | `/review/{id}/decision` | officer, admin | accept, reassign, merge, request_info, resolve, close, reopen; reason required |
| GET, PUT | `/admin/rules` | admin (read: officer too) | YAML rules with change log |
| POST | `/admin/rules/test` | staff | run the rules against a text |
| POST | `/admin/models/reload` | admin | pick up a newly trained second-opinion model |
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

This single run exercises every problem from Phase 1 except duplicates and photos, which need a second complaint and an image; both paths are implemented and will be shown in the demo.

---

## 5. Known limits at this checkpoint

- Latency per complaint is 17-20 s with the GPU free, more while training or generation runs; the UI shows an "analysing" state.
- Video: the file is stored and served; only photos go to the model. Key-frame extraction is a stretch.
- Rules editor UI, dashboard charts and department queue screens are after the core complainant and officer flows.
- No automated tests beyond the end-to-end script and `scripts/run_eval.py` yet.
