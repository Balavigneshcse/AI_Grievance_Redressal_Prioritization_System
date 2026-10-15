"""SYNAPSE API. Run from the backend folder:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .services import notifier, pipeline, worker
from .api import admin, auth, complaints, misc, review, staff

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logging.getLogger("synapse.mail").info(
        "mail via %s:%s tls=%s auth=%s from=%s", settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_TLS,
        "yes" if settings.SMTP_USER else "no", settings.SMTP_FROM,
    )
    worker.start()
    notifier.start()  # outbox thread: requests never wait for the mail server
    threading.Thread(target=pipeline.warm_up, name="synapse-warmup", daemon=True).start()
    yield


app = FastAPI(
    title="SYNAPSE Grievance API",
    version="0.1.0",
    description="Multilingual complaint intake, local-model triage, human review and status updates.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(review.router)
app.include_router(admin.router)
app.include_router(staff.router)
app.include_router(misc.router)


@app.get("/")
def root():
    return {"service": "SYNAPSE", "docs": "/docs", "health": "/health"}
