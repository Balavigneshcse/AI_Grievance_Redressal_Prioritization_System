from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, Header, Request
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import models, schemas
from ..services import notifier, worker
from .deps import STAFF_ROLES, current_user
from scripts.common import MODELS, nearest_place

router = APIRouter(tags=["misc"])


@router.post("/geo/reverse")
def reverse(body: schemas.GeoIn):
    return nearest_place(body.lat, body.lng)


def _on_this_machine(request: Request) -> bool:
    """The caller is on the API's own machine and did not come through a proxy (a proxy on the same
    machine would make every outside caller look local, so a forwarded request never counts)."""
    if not request.client or request.headers.get("x-forwarded-for") or request.headers.get("forwarded"):
        return False
    try:
        ip = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or bool(mapped and mapped.is_loopback)


def _is_staff(authorization: str | None, db: Session) -> bool:
    if not authorization:
        return False
    try:
        return current_user(authorization, db).role in STAFF_ROLES
    except Exception:  # no valid login: the caller is simply not staff
        db.rollback()
        return False


@router.get("/health")
def health(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Anyone gets {"status": "ok"} or {"status": "degraded"}. Queue depth, outbox backlog, model latency,
    overdue count and the model list go only to a staff login or to a caller on this machine itself."""
    detailed = _on_this_machine(request) or _is_staff(authorization, db)
    out = {"status": "ok", "db": "down", "ollama": "down", "models": {}, "queue_depth": worker.depth()}
    try:
        db.execute(text("SELECT 1"))
        out["db"] = "ok"
        if detailed:
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
    out["status"] = "ok" if out["db"] == "ok" and out["ollama"] == "ok" else "degraded"
    return out if detailed else {"status": out["status"]}
