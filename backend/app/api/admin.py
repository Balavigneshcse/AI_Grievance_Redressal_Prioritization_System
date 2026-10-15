from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import models, schemas
from ..services import rules as rules_engine
from ..services.pipeline import reload_second_opinion
from .deps import require_role

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/rules")
def get_rules(user: models.User = Depends(require_role("admin", "officer"))):
    return {"yaml": rules_engine.rules_yaml_text(), "rules": rules_engine.load_rules()}


@router.put("/rules")
def put_rules(body: schemas.RulesIn, user: models.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    try:
        rules_engine.validate_rules_yaml(body.yaml)
    except Exception as exc:
        raise HTTPException(400, f"Invalid rules: {exc}")
    before = rules_engine.rules_yaml_text()
    rules_engine.RULES_PATH.write_text(body.yaml, encoding="utf-8")
    db.add(models.RuleChange(admin_id=user.id, yaml_before=before, yaml_after=body.yaml, note=body.note))
    db.commit()
    return {"ok": True, "rules": len(rules_engine.load_rules())}


@router.post("/rules/test")
def test_rules(body: dict, user: models.User = Depends(require_role("admin", "officer"))):
    r = rules_engine.evaluate(body.get("text", ""), body.get("language"), body.get("ward"))
    return {"matched": r.matched_ids, "department": r.department, "urgency_floor": r.urgency_floor, "force_review": r.force_review, "notes": r.notes}


@router.post("/models/reload")
def reload_models(user: models.User = Depends(require_role("admin"))):
    reload_second_opinion()
    return {"ok": True}


@router.get("/metrics")
def metrics(user: models.User = Depends(require_role("admin", "officer")), db: Session = Depends(get_db)):
    by_status = {str(k): v for k, v in db.execute(select(models.Complaint.status, func.count()).group_by(models.Complaint.status)).all()}
    by_dept = {str(k): v for k, v in db.execute(select(models.Complaint.department_id, func.count()).group_by(models.Complaint.department_id)).all()}
    open_statuses = ("received", "analysing", "under_review", "routed", "in_progress", "awaiting_info")
    critical_open = db.execute(select(func.count()).where(models.Complaint.urgency == "critical", models.Complaint.status.in_(open_statuses))).scalar_one()
    total = db.execute(select(func.count(models.Complaint.id))).scalar_one()
    reviewed = db.execute(select(func.count()).where(models.Decision.queue == "review")).scalar_one()
    decisions = db.execute(select(func.count(models.Decision.id))).scalar_one()
    latency = db.execute(select(func.avg(models.Analysis.latency_ms))).scalar_one()

    # Live accuracy: officer corrections are ground truth for the analysis they corrected.
    corrections = db.execute(select(models.Override).where(models.Override.action == "reassign")).scalars().all()
    hits, totals = defaultdict(int), defaultdict(int)
    for ov in corrections:
        c = db.get(models.Complaint, ov.complaint_id)
        a = c.analyses[-1] if c and c.analyses else None
        if not a:
            continue
        lang = (a.language_primary or "unknown")
        totals[lang] += 1
        hits[lang] += int(ov.to_department == a.department_id)
    live = {l: {"n": totals[l], "accuracy": round(hits[l] / totals[l], 3)} for l in totals}

    evals = {}
    for p in (settings.ROOT / "data" / "eval").glob("summary_*.json"):
        try:
            evals[p.stem.replace("summary_", "")] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    report = settings.ROOT / "models" / "second_opinion_report.json"
    second = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None

    return {
        "totals": {"complaints": total, "critical_open": critical_open, "review_rate": round(reviewed / decisions, 3) if decisions else None, "auto_closed": 0,
                   "mean_latency_ms": int(latency) if latency else None},
        "by_status": by_status, "by_department": by_dept, "live_accuracy_by_language": live,
        "eval_runs": evals, "second_opinion": second,
    }
