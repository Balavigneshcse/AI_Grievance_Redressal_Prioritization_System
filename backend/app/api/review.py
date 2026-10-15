from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas
from ..services.notifier import notify
from ..services.pipeline import _set_status
from .complaints import complaint_detail
from .deps import STAFF_ROLES, as_uuid, can_access, require_role, scope_complaints

router = APIRouter(tags=["review"])

URGENCY_ORDER = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=models.Complaint.urgency, else_=4)
STATUS_LABEL = {
    "routed": "sent to department", "in_progress": "in progress", "resolved": "resolved", "closed": "closed",
    "merged": "merged with an earlier complaint", "awaiting_info": "waiting for your reply", "under_review": "under review",
}
# Queue views: what a staff member is looking at.
VIEWS = {
    "review": ("under_review",),
    "active": ("routed", "in_progress", "awaiting_info"),
    "resolved": ("resolved", "closed", "merged"),
    "all": None,
}
ROLE_LABEL = {"super_admin": "super admin", "district_admin": "district admin", "dept_admin": "department admin"}


def _flags(c: models.Complaint) -> list[str]:
    a = c.analyses[-1] if c.analyses else None
    d = c.decisions[-1] if c.decisions else None
    flags = []
    if c.urgency == "critical":
        flags.append("critical")
    if a and a.confidence is not None and a.confidence < 0.7:
        flags.append("low_confidence")
    if d:
        for r in d.reasons or []:
            if r.startswith("second opinion") or r.startswith("rule department") or " suggests " in r:
                flags.append("disagreement")
            elif r.startswith("possible duplicate"):
                flags.append("duplicate")
            elif r.startswith("awaiting analysis") or r.startswith("analysis failed"):
                flags.append("awaiting_analysis")
            elif r.startswith("photo does not match"):
                flags.append("photo_mismatch")
    if c.contact_incomplete:
        flags.append("contact_incomplete")
    return sorted(set(flags))


def _item(c: models.Complaint) -> schemas.QueueItem:
    a = c.analyses[-1] if c.analyses else None
    return schemas.QueueItem(
        id=c.id, tracking_id=c.tracking_id, status=c.status, urgency=c.urgency, department=c.department_id,
        language_primary=a.language_primary if a else c.language_hint, summary_en=a.summary_en if a else None,
        flags=_flags(c), confidence=a.confidence if a else None, created_at=c.created_at,
        district=c.district, office_name=c.office_name, due_at=c.due_at, complainant_name=c.complainant_name,
    )


def _load(db: Session, complaint_id: str, user: models.User) -> models.Complaint:
    c = db.get(models.Complaint, as_uuid(complaint_id))
    if c is None:
        raise HTTPException(404, "Complaint not found")
    if not can_access(c, user):
        raise HTTPException(403, "Outside your district or department")
    return c


@router.get("/review/queue", response_model=list[schemas.QueueItem])
def review_queue(
    view: str | None = Query(None, description="review | active | resolved | all"),
    department: str | None = Query(None), urgency: str | None = Query(None), language: str | None = Query(None),
    district: str | None = Query(None),
    user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db),
):
    """Complaints the caller may work on. Department admins default to their active work,
    district and super admins to the cases waiting for a human decision."""
    if view not in VIEWS:
        view = "active" if user.role == "dept_admin" else "review"
    q = scope_complaints(select(models.Complaint), user)
    statuses = VIEWS[view]
    if statuses:
        q = q.where(models.Complaint.status.in_(statuses))
    if department:
        q = q.where(models.Complaint.department_id == department)
    if urgency:
        q = q.where(models.Complaint.urgency == urgency)
    if district and user.role == "super_admin":
        q = q.where(models.Complaint.district == district)
    rows = db.execute(q.order_by(URGENCY_ORDER, models.Complaint.created_at.desc()).limit(300)).scalars().all()
    items = [_item(c) for c in rows]
    if language:
        items = [i for i in items if (i.language_primary or "").startswith(language)]
    return items


@router.get("/departments/{dept}/queue", response_model=list[schemas.QueueItem])
def department_queue(dept: str, user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db)):
    if user.role == "dept_admin" and user.department_id != dept:
        raise HTTPException(403, "Not your department")
    q = scope_complaints(select(models.Complaint), user).where(
        models.Complaint.department_id == dept, models.Complaint.status.in_(("routed", "in_progress", "awaiting_info"))
    )
    rows = db.execute(q.order_by(URGENCY_ORDER, models.Complaint.created_at)).scalars().all()
    return [_item(c) for c in rows]


@router.get("/review/{complaint_id}", response_model=schemas.ComplaintDetail)
def review_detail(complaint_id: str, user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db)):
    return complaint_detail(db, _load(db, complaint_id, user), user)


@router.post("/review/{complaint_id}/decision")
def decide(complaint_id: str, body: schemas.DecisionIn, user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db)):
    c = _load(db, complaint_id, user)
    owner = db.get(models.User, c.user_id)
    ov = models.Override(
        complaint_id=c.id, officer_id=user.id, action=body.action, from_department=c.department_id, to_department=c.department_id,
        from_urgency=c.urgency, to_urgency=c.urgency, reason=body.reason,
    )
    note = f"{body.action} by {ROLE_LABEL.get(user.role, 'officer')}: {body.reason}"

    if body.action == "accept":
        if c.status not in ("under_review", "routed"):
            raise HTTPException(409, f"Cannot accept from status {c.status}")
        # A department admin accepting its own routed case starts the work; a reviewer accepting
        # a flagged case confirms the routing.
        target = "in_progress" if (user.role == "dept_admin" and c.status == "routed") else "routed"
        _set_status(db, c, target, "officer", user.id, note)
    elif body.action == "reassign":
        if not body.department and not body.urgency:
            raise HTTPException(400, "reassign needs a department or an urgency")
        if body.department:
            if db.get(models.Department, body.department) is None:
                raise HTTPException(400, "Unknown department")
            c.department_id = ov.to_department = body.department
        if body.urgency:
            c.urgency = ov.to_urgency = body.urgency
        _set_status(db, c, "routed", "officer", user.id, note)
    elif body.action == "merge":
        if not body.merged_into:
            raise HTTPException(400, "merge needs merged_into")
        target = db.execute(select(models.Complaint).where(models.Complaint.tracking_id == body.merged_into.upper())).scalar_one_or_none()
        if target is None:
            try:
                target = db.get(models.Complaint, as_uuid(body.merged_into))
            except HTTPException:
                target = None
        if target is None or target.id == c.id:
            raise HTTPException(400, "Target complaint not found")
        if target.duplicate_of is not None:
            raise HTTPException(400, "Target is itself a duplicate; merge into the original")
        c.duplicate_of = target.id
        ov.merged_into = target.id
        _set_status(db, c, "merged", "officer", user.id, note + f" (into {target.tracking_id})")
    elif body.action == "request_info":
        _set_status(db, c, "awaiting_info", "officer", user.id, note)
    elif body.action == "resolve":
        _set_status(db, c, "resolved", "officer", user.id, note)
    elif body.action == "close":
        if c.status != "resolved":
            raise HTTPException(409, "Only resolved complaints can be closed")
        _set_status(db, c, "closed", "officer", user.id, note)
    elif body.action == "reopen":
        _set_status(db, c, "under_review", "officer", user.id, note)

    db.add(ov)
    dept = db.get(models.Department, c.department_id) if c.department_id else None
    dept_name = {"en": dept.name_en, "ta": dept.name_ta, "hi": dept.name_hi}.get(owner.preferred_language, dept.name_en) if dept else ""
    if c.status == "routed":
        notify(db, owner, "routed", complaint_id=c.id, tracking_id=c.tracking_id, department=dept_name, urgency=c.urgency)
    else:
        notify(db, owner, "status", complaint_id=c.id, tracking_id=c.tracking_id, status=STATUS_LABEL.get(c.status, c.status), note=body.reason if body.action == "request_info" else "")
    db.commit()
    return {"ok": True, "status": c.status}
