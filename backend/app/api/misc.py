from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import schemas
from ..services import worker
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
