from __future__ import annotations

from fastapi import APIRouter, Depends
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import models, schemas
from ..services import notifier, worker
from scripts.common import MODELS, nearest_place

router = APIRouter(tags=["misc"])


@router.post("/geo/reverse")
def reverse(body: schemas.GeoIn):
    return nearest_place(body.lat, body.lng)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    out = {"db": "down", "ollama": "down", "models": {}, "queue_depth": worker.depth()}
    try:
        db.execute(text("SELECT 1"))
        out["db"] = "ok"
        recent = db.execute(select(models.Analysis.latency_ms).where(models.Analysis.latency_ms.is_not(None)).order_by(models.Analysis.created_at.desc()).limit(10)).scalars().all()
        out["model_latency_ms"] = {"last": recent[0] if recent else None, "mean_last_10": int(sum(recent) / len(recent)) if recent else None}
        out["outbox_pending"] = db.execute(select(func.count()).where(models.Notification.status == "queued")).scalar_one()
        out["overdue_open"] = db.execute(select(func.count()).where(models.Complaint.due_at < datetime.now(timezone.utc), models.Complaint.status.in_(("routed", "in_progress", "awaiting_info", "under_review")))).scalar_one()
    except Exception as exc:
        out["db"] = f"down: {exc}"[:120]
    try:
        import ollama

        names = [m.model for m in ollama.Client(host=settings.OLLAMA_HOST, timeout=5).list().models]
        out["ollama"] = "ok"
        out["models"] = {
            settings.LLM: any(n.startswith(settings.LLM) for n in names),
            settings.EMBED: any(n.startswith(settings.EMBED) for n in names),
            "second_opinion": (MODELS / "second_opinion_department.npz").exists(),
        }
    except Exception as exc:
        out["ollama"] = f"down: {exc}"[:120]
    return out
