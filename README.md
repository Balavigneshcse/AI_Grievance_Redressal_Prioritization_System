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

## Roles and accounts

| Role | Scope | Seed account |
|---|---|---|
| Super admin | everything, creates district admins | `admin@synapse.local` |
| District admin | one district: review queue, adds department admins | `district.coimbatore@synapse.local` |
| Department admin | one department in one district: works only those complaints | `officer.water@synapse.local`, `officer.roads@synapse.local` |
| Citizen | own complaints | `citizen@synapse.local` |

Passwords come from `SEED_PASSWORD` in `.env`. Staff accounts are created from the Admin page (`/admin`); the generated password is shown once.

## Evidence limits

Photos up to 25 MB, videos up to 100 MB and 5 minutes (in-app recording stops automatically). Every complaint records the complainant's name and the last four digits of their Aadhaar number for the office; the model never sees them.
