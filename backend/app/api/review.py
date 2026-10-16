from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models, schemas
from ..services.notifier import STATUS_LABEL, notify, notify_staff
from ..services.pipeline import _set_status
from .complaints import _save_uploads, complaint_detail
from .deps import STAFF_ROLES, as_uuid, can_access, require_role, scope_complaints

router = APIRouter(tags=["review"])

URGENCY_ORDER = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=models.Complaint.urgency, else_=4)
OPEN_FOR_SLA = ("routed", "in_progress", "awaiting_info", "under_review")
# Queue views: what a staff member is looking at.
VIEWS = {
    "review": ("under_review",),
    "active": ("routed", "in_progress", "awaiting_info"),
    "resolved": ("resolved", "closed", "merged"),
    "all": None,
}
ROLE_LABEL = {"super_admin": "super admin", "district_admin": "district admin", "dept_admin": "department admin"}
WORKABLE = ("under_review", "routed", "in_progress", "awaiting_info")
# The statuses each decision may be taken from; DecisionBar.tsx allowedActions offers the same. Received and
# analysing cases wait for the model, closed and merged ones take no more work, only a finished case reopens.
ALLOWED_FROM = {
    "accept": ("under_review", "routed"),
    "reassign": WORKABLE,
    "merge": WORKABLE,
    "resolve": WORKABLE,
    "request_info": ("under_review", "routed", "in_progress"),
    "close": ("resolved",),
    "reopen": ("resolved", "closed"),
}


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
    if c.due_at and c.status in OPEN_FOR_SLA and c.due_at < datetime.now(timezone.utc):
        flags.append("overdue")
    if (c.supporters or 0) >= 3:
        flags.append("popular")
    return sorted(set(flags))


def _item(c: models.Complaint) -> schemas.QueueItem:
    a = c.analyses[-1] if c.analyses else None
    return schemas.QueueItem(
        id=c.id, tracking_id=c.tracking_id, status=c.status, urgency=c.urgency, department=c.department_id,
        language_primary=a.language_primary if a else c.language_hint, summary_en=a.summary_en if a else None,
        flags=_flags(c), confidence=a.confidence if a else None, created_at=c.created_at,
        district=c.district, office_name=c.office_name, due_at=c.due_at, complainant_name=c.complainant_name, supporters=c.supporters or 0,
    )


def _load(db: Session, complaint_id: str, user: models.User, lock: bool = False) -> models.Complaint:
    # lock: hold the row until commit, so a second decision on the same case waits and sees the new status
    c = db.get(models.Complaint, as_uuid(complaint_id), with_for_update=True if lock else None)
    if c is None:
        raise HTTPException(404, "Complaint not found")
    if not can_access(c, user):
        raise HTTPException(403, "Outside your district or department")
    return c


@router.get("/review/queue", response_model=list[schemas.QueueItem])
def review_queue(
    view: str | None = Query(None, description="review | active | resolved | all"),
    department: str | None = Query(None), urgency: str | None = Query(None), language: str | None = Query(None),
    district: str | None = Query(None), q_search: str | None = Query(None, alias="q", description="tracking id, name or words from the complaint"),
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
    if q_text := (q_search or "").strip():
        like = f"%{q_text}%"
        q = q.where(or_(models.Complaint.tracking_id.ilike(like), models.Complaint.complainant_name.ilike(like), models.Complaint.raw_text.ilike(like),
                        models.Complaint.manual_address.ilike(like), models.Complaint.resolved_place.ilike(like)))
    rows = db.execute(q.order_by(URGENCY_ORDER, models.Complaint.supporters.desc(), models.Complaint.created_at.desc()).limit(300)).scalars().all()
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
    c = _load(db, complaint_id, user, lock=True)
    if c.status not in ALLOWED_FROM[body.action]:
        raise HTTPException(409, f"Cannot {body.action.replace('_', ' ')} from status {c.status}")
    if body.action == "accept" and c.status == "routed" and user.role != "dept_admin":
        # Accept on a routed case is the department admin's Start work. A reviewer's would only add a second
        # Routed entry and send the routed mails again (DecisionBar.tsx offers it to department admins only).
        raise HTTPException(409, "Already routed: the department admin starts the work")
    owner = db.get(models.User, c.user_id)
    ov = models.Override(
        complaint_id=c.id, officer_id=user.id, action=body.action, from_department=c.department_id, to_department=c.department_id,
        from_urgency=c.urgency, to_urgency=c.urgency, reason=body.reason,
    )
    note = f"{body.action} by {ROLE_LABEL.get(user.role, 'officer')}: {body.reason}"

    if body.action == "accept":
        # A department admin's accept starts the work (from routed, or straight from review); a
        # reviewer's accept confirms the routing and hands the case to the department.
        target = "in_progress" if user.role == "dept_admin" else "routed"
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
        _set_status(db, c, "closed", "officer", user.id, note)
    elif body.action == "reopen":
        _set_status(db, c, "under_review", "officer", user.id, note)

    db.add(ov)
    dept = db.get(models.Department, c.department_id) if c.department_id else None
    dept_name = {"en": dept.name_en, "ta": dept.name_ta, "hi": dept.name_hi}.get(owner.preferred_language, dept.name_en) if dept else ""
    # Hand-over emails: a case that lands in a department (reassigned, or confirmed by a reviewer) tells that
    # department; a reopened case tells the district admin.
    if c.status == "routed" and (body.action == "reassign" or (body.action == "accept" and user.role != "dept_admin")):
        a = c.analyses[-1] if c.analyses else None
        due = c.due_at.astimezone(timezone.utc).strftime("%d %b %H:%M UTC") if c.due_at else "-"
        notify_staff(db, c, "department", "staff_routed", department=dept.name_en if dept else (c.department_id or "-"),
                     urgency=c.urgency or "-", summary=((a.summary_en if a else "") or "")[:300], due=due)
    elif c.status == "under_review" and body.action == "reopen":
        notify_staff(db, c, "district", "staff_review", district=c.district or "unknown district", reasons=body.reason[:300])
    if c.status == "routed":
        notify(db, owner, "routed", complaint_id=c.id, tracking_id=c.tracking_id, department=dept_name, urgency=c.urgency)
    else:
        proof = any(m.role == "resolution" for m in c.media) if body.action == "resolve" else False
        note = body.reason if body.action in ("request_info", "resolve") else ""
        if proof:
            note = (note + " " if note else "") + "A photo of the completed work is on your tracking page."
        notify(db, owner, "status", complaint_id=c.id, tracking_id=c.tracking_id, status=STATUS_LABEL.get(c.status, c.status), note=note)
    db.commit()
    return {"ok": True, "status": c.status}


@router.post("/review/{complaint_id}/attachments")
async def add_attachments(
    complaint_id: str, files: list[UploadFile] = File(default=[]),
    user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db),
):
    """Resolution proof from the office: photos or videos shown to the citizen on the tracking page."""
    c = _load(db, complaint_id, user)
    saved = await _save_uploads(db, c, files, captured_in_app=False, role="resolution", uploaded_by=user.id)
    if not saved:
        raise HTTPException(400, "Attach at least one photo or video")
    db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="officer", actor_id=user.id,
                              note=f"resolution proof added ({saved} file{'s' if saved != 1 else ''})"))
    db.commit()
    return {"ok": True, "attachments": saved, "media": [{"id": str(m.id), "kind": m.kind, "url": f"/media/{m.id}", "role": m.role} for m in c.media if m.role == "resolution"]}
