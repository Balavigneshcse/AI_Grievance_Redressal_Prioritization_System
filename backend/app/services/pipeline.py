"""The analysis pipeline for one complaint, run by the worker:
language hint -> PII mask -> geo resolve -> Gemma (text + photo) -> embedding ->
duplicates (pgvector) -> second opinion -> rules -> decision -> status + email."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from sqlalchemy import bindparam, select, text as sql
from sqlalchemy.orm import Session

from ..config import settings
from .. import models
from . import rules as rules_engine
from .notifier import notify
from .pii import mask_pii

from scripts.common import MODELS, SoftmaxRegression, analysis_system_prompt, detect_language, embed, load_schema, nearest_place

URGENCY_RANK = rules_engine.URGENCY_RANK
OPEN_STATUSES = ("received", "analysing", "under_review", "routed", "in_progress", "awaiting_info")

_second = {"loaded": False, "dept": None, "urg": None}


def _second_opinion_models():
    if not _second["loaded"]:
        d = MODELS / "second_opinion_department.npz"
        u = MODELS / "second_opinion_urgency.npz"
        _second["dept"] = SoftmaxRegression.load(d) if d.exists() else None
        _second["urg"] = SoftmaxRegression.load(u) if u.exists() else None
        _second["loaded"] = True
    return _second["dept"], _second["urg"]


def reload_second_opinion() -> None:
    _second["loaded"] = False


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def _llm_analyse(masked_text: str, image_path: str | None) -> tuple[dict, int]:
    import ollama

    client = ollama.Client(host=settings.OLLAMA_HOST, timeout=settings.LLM_TIMEOUT_S)
    user = {"role": "user", "content": "Complaint:\n" + masked_text}
    if image_path:
        user["images"] = [image_path]
        user["content"] += "\n\nA photo is attached."
    t0 = time.time()
    resp = client.chat(
        model=settings.LLM,
        messages=[{"role": "system", "content": analysis_system_prompt()}, user],
        format=load_schema(),
        options={"temperature": 0, "num_ctx": 2048, "num_predict": 400},
    )
    return json.loads(resp.message.content), int((time.time() - t0) * 1000)


def _set_status(db: Session, c: models.Complaint, to: str, actor_type: str = "system", actor_id=None, note: str | None = None) -> None:
    db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=to, actor_type=actor_type, actor_id=actor_id, note=note))
    c.status = to


def run_analysis(db: Session, complaint_id) -> models.Analysis:
    c = db.get(models.Complaint, complaint_id)
    user = db.get(models.User, c.user_id)
    analysis = models.Analysis(complaint_id=c.id, model_text=settings.LLM, model_embed=settings.EMBED)
    reasons: list[str] = []

    # 1. language hint
    hint, _ = detect_language(c.raw_text)
    c.language_hint = hint

    # 2. PII mask
    masked, pii = mask_pii(c.raw_text)
    analysis.masked_text, analysis.pii_map = masked, pii

    # 3. geo resolve (EXIF fallback when the form sent no coordinates)
    if c.lat is None:
        for m in c.media:
            if m.exif_lat is not None:
                c.lat, c.lng, c.location_source = m.exif_lat, m.exif_lng, "exif"
                break
    if c.lat is not None and c.lng is not None:
        place = nearest_place(c.lat, c.lng)
        c.resolved_place = f"{place['name']}, {place['area']}" + (f" (~{place['distance_km']} km)" if place["distance_km"] > 1 else "")

    # 4. LLM (first photo, if any, goes in as an image)
    image_path = next((m.file_path for m in c.media if m.kind == "photo"), None)
    llm: dict | None = None
    try:
        llm, analysis.latency_ms = _llm_analyse(masked, image_path)
    except Exception as exc:
        analysis.error = f"LLM failed: {exc}"[:500]

    if llm:
        analysis.language_primary = llm.get("language_primary")
        analysis.language_secondary = llm.get("language_secondary") or None
        analysis.department_id = llm.get("department")
        analysis.urgency = llm.get("urgency")
        analysis.confidence = float(llm.get("confidence") or 0)
        analysis.summary_en = llm.get("summary_en")
        analysis.evidence_spans = [s for s in llm.get("evidence_spans", []) if isinstance(s, str)][:5]
        analysis.entities = llm.get("entities") or {}
        analysis.image_findings = llm.get("image_findings") or None
        analysis.image_matches_text = llm.get("image_matches_text")
        if image_path and analysis.image_matches_text is False:
            reasons.append("photo does not match the text")

    # 5. embedding (English summary + place) and 6. duplicates via pgvector
    try:
        basis = (analysis.summary_en or masked) + (f" | {c.resolved_place}" if c.resolved_place else "")
        vec = embed([basis], gpu=False)[0]
        analysis.embedding = vec.tolist()
        rows = db.execute(
            sql(
                """
                SELECT c.id, c.tracking_id, c.lat, c.lng, 1 - (a.embedding <=> CAST(:v AS vector)) AS score
                FROM analyses a
                JOIN complaints c ON c.id = a.complaint_id
                WHERE a.embedding IS NOT NULL AND c.id <> :cid AND c.status IN :open
                  AND a.id = (SELECT id FROM analyses WHERE complaint_id = c.id ORDER BY created_at DESC LIMIT 1)
                ORDER BY a.embedding <=> CAST(:v AS vector)
                LIMIT 5
                """
            ).bindparams(bindparam("open", expanding=True)),
            {"v": json.dumps([float(x) for x in vec]), "cid": c.id, "open": list(OPEN_STATUSES)},
        ).all()
        cands = []
        for rid, tid, lat, lng, score in rows:
            score = float(score)
            if score < settings.DUPLICATE_SCORE_THRESHOLD - 0.10:
                continue
            if c.lat is not None and lat is not None and _haversine_km(c.lat, c.lng, lat, lng) > settings.DUPLICATE_MAX_KM:
                continue
            cands.append({"complaint_id": str(rid), "tracking_id": tid, "score": round(score, 3)})
        analysis.duplicate_candidates = cands
        if cands and cands[0]["score"] >= settings.DUPLICATE_SCORE_THRESHOLD:
            reasons.append(f"possible duplicate of {cands[0]['tracking_id']} (similarity {cands[0]['score']:.2f})")
    except Exception as exc:
        analysis.error = ((analysis.error or "") + f" | embedding/dedup failed: {exc}")[:800]
        vec = None

    # 7. second opinion
    dept_model, urg_model = _second_opinion_models()
    if vec is not None and dept_model is not None:
        X = np.asarray([vec], dtype=np.float32)
        probs = dept_model.predict_proba(X)[0]
        i = int(probs.argmax())
        analysis.second_opinion_department = dept_model.labels[i]
        analysis.second_opinion_prob = float(probs[i])
        if urg_model is not None:
            analysis.second_opinion_urgency = urg_model.predict(X)[0]
        if llm and analysis.second_opinion_department != analysis.department_id and analysis.second_opinion_prob >= 0.6:
            reasons.append(f"second opinion says {analysis.second_opinion_department} ({analysis.second_opinion_prob:.2f}), model says {analysis.department_id}")

    # 8. rules
    rr = rules_engine.evaluate(c.raw_text, analysis.language_primary, c.ward)
    analysis.matched_rule_ids = rr.matched_ids
    reasons.extend(rr.notes)

    # 9. decision
    urgency = analysis.urgency or "medium"
    if rr.urgency_floor and URGENCY_RANK[rr.urgency_floor] > URGENCY_RANK.get(urgency, 0):
        urgency = rr.urgency_floor
    department = rr.department or analysis.department_id or "general"
    if rr.department and llm and rr.department != analysis.department_id:
        reasons.append(f"rule department {rr.department} overrides model department {analysis.department_id}")

    review = False
    if not llm:
        review = True
        reasons.append("awaiting analysis: model unavailable")
    if rr.force_review:
        review = True
    if urgency == "critical":
        review = True
        reasons.append("critical urgency always gets a human check")
    if llm and analysis.confidence is not None and analysis.confidence < settings.REVIEW_CONFIDENCE_THRESHOLD:
        review = True
        reasons.append(f"low confidence {analysis.confidence:.2f}")
    if any(r.startswith("second opinion") or r.startswith("rule department") or r.startswith("possible duplicate") for r in reasons):
        review = True
    if c.contact_incomplete:
        reasons.append("contact details incomplete")

    db.add(analysis)
    db.flush()
    decision = models.Decision(
        complaint_id=c.id, analysis_id=analysis.id, queue="review" if review else "department",
        department_id=department, urgency=urgency, reasons=reasons,
    )
    db.add(decision)

    c.department_id = department
    c.urgency = urgency
    new_status = "under_review" if review else "routed"
    _set_status(db, c, new_status, note="; ".join(reasons) if reasons else "confident, routed automatically")

    dept = db.get(models.Department, department)
    dept_name = {"en": dept.name_en, "ta": dept.name_ta, "hi": dept.name_hi}.get(user.preferred_language, dept.name_en) if dept else department
    if new_status == "routed":
        notify(db, user, "routed", complaint_id=c.id, tracking_id=c.tracking_id, department=dept_name, urgency=urgency)
    else:
        notify(db, user, "under_review", complaint_id=c.id, tracking_id=c.tracking_id)
    return analysis
