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
| Training and evaluation commands | [docs/training-commands.md](docs/training-commands.md) |

## Stack

Backend: Python 3.12, FastAPI, SQLAlchemy. Database: PostgreSQL 16 with pgvector, via Docker Compose. Frontend: React + Vite, shadcn/ui, lucide icons. Models: all local through Ollama.

## Models

Single model for text and photos: Gemma 3 4B served by Ollama. Embeddings: bge-m3 served by Ollama. Second opinion: softmax regression in NumPy. See the models document for measurements on the build laptop (RTX 3050, 4 GB).

## Status

Phase 1 and Phase 2 complete. Pipeline scripts (`scripts/`), config (`config/`), prompts and the gold evaluation set (`data/eval/`) are in place; the web app starts in Phase 4.
