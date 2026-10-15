# SYNAPSE: AI Grievance Redressal Prioritization System

A multilingual complaint-triage system for government and corporate grievance portals. It reads complaints in free text (English, Tamil, Hindi, code-mixed), with photos, video and location, identifies the subject and urgency, routes to the right department with an explanation, keeps a human in the loop for uncertain and urgent cases, and keeps the complainant informed by email at every step.

All models run locally on the organisation's own hardware. No cloud AI APIs.

Built in 24 hours at SYNAPSE '26, V.S.B. Engineering College.

## Documents

| Phase | Document |
|---|---|
| 1. Problem understanding | [docs/01-problem-understanding.md](docs/01-problem-understanding.md) |
| 1. Models and datasets | [docs/02-models-and-datasets.md](docs/02-models-and-datasets.md) |
| 2. System architecture | [docs/03-system-architecture.md](docs/03-system-architecture.md) |
| 3. Database and UI/UX design, tech stack | [docs/04-database-and-ui.md](docs/04-database-and-ui.md) |
| 4. Technical implementation | [docs/05-implementation.md](docs/05-implementation.md) |
| Training and evaluation commands | [docs/training-commands.md](docs/training-commands.md) |

## Run

```bash
docker compose up -d
cd backend && python seed.py && python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

API docs at http://localhost:8000/docs, mail inbox at http://localhost:8025, app at http://localhost:5173.

## Stack

Backend: Python 3.12, FastAPI, SQLAlchemy. Database: PostgreSQL 16 with pgvector, via Docker Compose. Frontend: React + Vite, shadcn/ui, lucide icons. Models: all local through Ollama.

## Models

Single model for text and photos: Gemma 3 4B served by Ollama. Embeddings: bge-m3 served by Ollama. Second opinion: softmax regression in NumPy. See the models document for measurements on the build laptop (RTX 3050, 4 GB).

## Status

Phases 1 to 4 complete. Backend (FastAPI + PostgreSQL + local models) and frontend (React + shadcn/ui) both working end to end: register with email OTP, file a complaint with photo and location, local analysis, rules, district office routing, officer review, status emails.

## Test results

All measured on the build laptop (RTX 3050, 4 GB) against the live stack; details and every run are in `docs/06-test-report.md`.

**End-to-end suite** (`scripts/test_api_e2e.py`, run against a Mailpit-backed API): **118 of 118 checks pass** (16 Oct 2026, 02:40, straight after a reset). The suite grew with the product: 61 checks on day 1, then 77, 91, 114 and 118.

| Area | What the checks prove |
|---|---|
| Accounts | weak password, wrong OTP, unverified login and bad Aadhaar digits rejected; OTP verify, password reset, old tokens invalidated; name and Aadhaar last 4 taken at registration; twelve failed logins end in 429 |
| AI pipeline | five complaints in Tamil, Hindi, English, Tanglish and Hinglish get the right department, urgency, rules and review decision; evidence spans quoted verbatim; English summary; district office and due time; second opinion stored |
| Evidence | JPEG with GPS EXIF resolved to Gandhipuram; the vision model describes the pothole; up to three photos reach the model; media served only to the owner and staff |
| Duplicates and PII | a repeated complaint flagged at similarity 1.00 and sent to review; phone and Aadhaar-like numbers masked before the model, the map visible to staff only |
| Roles | department admin sees only its department and district (403 elsewhere); district admin creates department admins for its district only; disabled accounts are locked out |
| Decisions | accept, reassign, merge, request info, resolve, close with mandatory reasons; citizen reply resumes an awaiting-info case; resolution proof; rating, reopen; me-too support with priority boost; queue search; map scope |
| Mail and SLA | citizen, department admin and district admin mails for routing, review, reply, resolution and overdue; an English resolve note reaches a Tamil citizen translated; overdue cases escalate exactly once |

**Gold set** (`scripts/run_eval.py`, 12 hand-labelled complaints, replayed after every training round):

| Metric | Gemma 3 4B alone | Whole system (model + rules) |
|---|---|---|
| Department accuracy | 0.83 | **1.00** |
| Urgency exact | 0.83 | **0.92** (every miss within one level) |
| Critical recall | 0.75 | **1.00** |
| Language identification | 0.92 | 0.92 |
| Mean time per complaint | 12.4 s | same |

**Second-opinion classifier** (NumPy softmax regression on bge-m3 embeddings, held-out split of the locally generated set):

| Round | Synthetic rows | Department | Urgency |
|---|---|---|---|
| 1 | 460 | 0.869 | 0.479 |
| 2 | 940 | 0.846 | 0.550 |
| 3 | 1,169 | 0.875 | 0.555 |
| 4 | 1,644 | 0.845 (en 0.89, hi-en 0.88, ta-en 0.87, hi 0.80, ta 0.76) | 0.563 |

Department accuracy has settled between 85% and 88%: more synthetic data from the same generator does not move it, so officer corrections are the next source of labels. Urgency stays with the model and the rules; the classifier only votes on the department.

**Performance and delivery:** tracking ID in under 1 s; full analysis of text and photos in 12 to 20 s with the GPU free; 70 mails through one outbox connection in a single suite run with none failed. The browser walk-through and the recorded demo (`docs/demo/`) cover every screen in all three interface languages.

## Roles and accounts

| Role | Scope | Seed account |
|---|---|---|
| Super admin | everything, creates district admins | `admin@synapse.local` |
| District admin | one district: review queue, map, adds department admins | `district.coimbatore@synapse.local`; `scripts\demo_data.py --districts` adds one for each of the 38 districts (`district.<district>@synapse.local`) |
| Department admin | one department in one district: works only those complaints | `officer.water@synapse.local`, `officer.roads@synapse.local` |
| Citizen | own complaints | `citizen@synapse.local` |

Passwords come from `SEED_PASSWORD` in `.env`. Staff accounts are created from the Admin page (`/admin`); the generated password is shown once.

## Evidence limits

Photos up to 25 MB, videos up to 100 MB and 5 minutes (in-app recording stops automatically). The complainant's name and the last four digits of their Aadhaar number are taken once at registration; every complaint carries them for the office, and the model never sees them.

## One-command start and demo data

```bash
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Starts Postgres and Mailpit, the API on :8000 and the app on :5173 in their own windows. Add `-Https` to serve both over HTTPS on the laptop's LAN address so phones can use the camera and GPS (self-signed certificate from `scripts\make_cert.py`; accept the warning once on `https://<ip>:8000/health`).

```bash
python scripts\demo_data.py --reset --districts --staff --seed
```

Wipes complaints and test accounts, creates a district admin for every Tamil Nadu district plus the Chennai and Madurai demo staff, files ten showcase complaints through the real pipeline and sets one past its due time so the escalation shows. The demo click path is in `docs/07-demo-runbook.md`.

## Demo video

`docs/demo/vindex_demo_subtitled.mp4` walks through every feature with captions; `docs/demo/vindex_demo.mp4` is the same recording without them, and `docs/demo/vindex_demo.srt` the caption track. Re-record with `python scripts\record_demo.py` (Playwright drives Chrome through the real app; ffmpeg renders both files).

## What happens after filing

The citizen can answer a request for information or add photos and videos from the Track page; the department holding the case is emailed, and so is the district admin whenever a case needs a human decision. Open complaints past their due time are escalated once to the district admin and carry an overdue flag in the queue.

## Closing the loop with the citizen

After a resolution the citizen rates it or reopens it within seven days; the office can attach proof photos of the completed work. A citizen who finds an open complaint nearby can support it instead of filing a duplicate, and enough supporters raise its priority. Staff see every located complaint on a district map, search the queue by ID, name or words, and officer notes reach Tamil and Hindi citizens translated by the local model. Login, registration and OTP endpoints are rate limited.
