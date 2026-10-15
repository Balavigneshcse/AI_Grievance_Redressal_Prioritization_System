"""Staff accounts for the role hierarchy.

super_admin        -> runs everything, creates district admins (and any staff account)
district_admin     -> one Tamil Nadu district; adds departments by creating their department admins
dept_admin         -> one department in one district; sees and works only that department's complaints
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import models, schemas
from ..security import EMAIL_RE, MOBILE_RE, hash_password, password_problems
from ..services.notifier import notify
from .deps import ADMIN_ROLES, STAFF_ROLES, as_uuid, dept_out, require_role, scope_complaints
from scripts.common import load_tn_mapping

router = APIRouter(prefix="/admin", tags=["staff"])

ROLE_LABEL = {"super_admin": "Super admin", "district_admin": "District admin", "dept_admin": "Department admin"}


def districts() -> list[dict]:
    return [{"id": d["id"], "name": d["name"]} for d in load_tn_mapping().get("districts", [])]


def _district_ok(name: str | None) -> bool:
    return bool(name) and any(d["name"] == name for d in districts())


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "Vx" + "".join(secrets.choice(alphabet) for _ in range(8)) + "!" + secrets.choice(string.digits)
        if not password_problems(pw):
            return pw


def _staff_out(u: models.User, db: Session) -> schemas.StaffOut:
    return schemas.StaffOut(
        id=u.id, email=u.email, role=u.role, preferred_language=u.preferred_language, department_id=u.department_id,
        district=u.district, full_name=u.full_name, is_active=u.is_active, mobile=u.mobile,
        department=dept_out(db.get(models.Department, u.department_id)) if u.department_id else None,
        created_at=u.created_at, last_login_at=u.last_login_at,
    )


@router.get("/districts")
def list_districts(user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db)):
    """The 38 districts from the Tamil Nadu mapping, with the number of staff accounts in each."""
    counts = dict(
        db.execute(
            select(models.User.district, func.count()).where(models.User.role.in_(("district_admin", "dept_admin"))).group_by(models.User.district)
        ).all()
    )
    return [{**d, "staff": counts.get(d["name"], 0)} for d in districts()]


@router.get("/users", response_model=list[schemas.StaffOut])
def list_staff(district: str | None = None, user: models.User = Depends(require_role(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    q = select(models.User).where(models.User.role.in_(STAFF_ROLES))
    if user.role == "district_admin":
        q = q.where(models.User.district == user.district, models.User.role == "dept_admin")
    elif district:
        q = q.where(models.User.district == district)
    rows = db.execute(q.order_by(models.User.role, models.User.district, models.User.department_id, models.User.email)).scalars().all()
    return [_staff_out(u, db) for u in rows]


@router.post("/users", response_model=schemas.StaffCreated, status_code=201)
def create_staff(body: schemas.StaffCreateIn, user: models.User = Depends(require_role(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    if user.role == "district_admin":
        if body.role != "dept_admin":
            raise HTTPException(403, "A district admin can only create department admins")
        district = user.district
    else:
        district = body.district
    if not _district_ok(district):
        raise HTTPException(400, "Choose a Tamil Nadu district")
    department_id = None
    if body.role == "dept_admin":
        if not body.department_id or db.get(models.Department, body.department_id) is None:
            raise HTTPException(400, "Choose a department")
        department_id = body.department_id

    email = body.email.strip().lower()
    mobile = body.mobile.strip().replace(" ", "").removeprefix("+91")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")
    if not MOBILE_RE.match(mobile):
        raise HTTPException(400, "Mobile number must be 10 digits starting with 6-9")
    if db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none():
        raise HTTPException(409, "An account with this email already exists")
    if db.execute(select(models.User).where(models.User.mobile == mobile)).scalar_one_or_none():
        raise HTTPException(409, "An account with this mobile number already exists")
    if body.password:
        problems = password_problems(body.password)
        if problems:
            raise HTTPException(400, "Password needs " + ", ".join(problems))
    password = body.password or _generate_password()

    u = models.User(
        email=email, mobile=mobile, password_hash=hash_password(password), role=body.role, district=district,
        department_id=department_id, full_name=body.full_name.strip(), preferred_language=body.preferred_language,
        is_verified=True, is_active=True,
    )
    db.add(u)
    db.flush()
    dept = db.get(models.Department, department_id) if department_id else None
    notify(db, u, "account", role=ROLE_LABEL[body.role], district=district, department=dept.name_en if dept else "-", url=settings.APP_URL)
    db.commit()
    return schemas.StaffCreated(user=_staff_out(u, db), password=password)


@router.patch("/users/{user_id}", response_model=schemas.StaffOut)
def update_staff(user_id: str, body: schemas.StaffPatchIn, user: models.User = Depends(require_role(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    target = db.get(models.User, as_uuid(user_id))
    if target is None or target.role not in STAFF_ROLES:
        raise HTTPException(404, "Staff account not found")
    if target.role == "super_admin" and target.id != user.id:
        raise HTTPException(403, "Another super admin cannot be changed")
    if user.role == "district_admin" and not (target.role == "dept_admin" and target.district == user.district):
        raise HTTPException(403, "Outside your district")

    if body.is_active is not None:
        if target.id == user.id and not body.is_active:
            raise HTTPException(400, "You cannot disable your own account")
        target.is_active = body.is_active
        if not body.is_active:
            target.password_version += 1  # ends every open session
    if body.email is not None:
        email = body.email.strip().lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(400, "Invalid email address")
        clash = db.execute(select(models.User).where(models.User.email == email, models.User.id != target.id)).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(409, "An account with this email already exists")
        target.email = email
    if body.full_name is not None:
        target.full_name = body.full_name.strip() or None
    if body.department_id is not None:
        if target.role != "dept_admin" or db.get(models.Department, body.department_id) is None:
            raise HTTPException(400, "Unknown department")
        target.department_id = body.department_id
    if body.district is not None:
        if user.role != "super_admin" or not _district_ok(body.district):
            raise HTTPException(400, "Unknown district")
        target.district = body.district
    if body.preferred_language is not None:
        target.preferred_language = body.preferred_language
    if body.password:
        problems = password_problems(body.password)
        if problems:
            raise HTTPException(400, "Password needs " + ", ".join(problems))
        target.password_hash = hash_password(body.password)
        target.password_version += 1
    db.commit()
    return _staff_out(target, db)


@router.get("/overview")
def overview(user: models.User = Depends(require_role(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """Complaint counts per district and department for the admin dashboard, scoped to the caller."""
    q = select(models.Complaint.district, models.Complaint.department_id, models.Complaint.status, func.count())
    if user.role == "district_admin":
        q = q.where(models.Complaint.district == user.district)
    rows = db.execute(q.group_by(models.Complaint.district, models.Complaint.department_id, models.Complaint.status)).all()
    out: dict[str, dict] = {}
    for district, dept, status, n in rows:
        d = out.setdefault(district or "unknown", {"total": 0, "open": 0, "by_department": {}})
        d["total"] += n
        if status in ("received", "analysing", "under_review", "routed", "in_progress", "awaiting_info"):
            d["open"] += n
        d["by_department"][dept or "unassigned"] = d["by_department"].get(dept or "unassigned", 0) + n
    return {"generated_at": datetime.now(timezone.utc), "districts": out}


@router.get("/map", response_model=list[schemas.MapPoint])
def complaint_map(view: str = "open", user: models.User = Depends(require_role(*STAFF_ROLES)), db: Session = Depends(get_db)):
    """Complaints with coordinates in the caller's scope, for the district map."""
    q = scope_complaints(select(models.Complaint), user).where(models.Complaint.lat.is_not(None), models.Complaint.lng.is_not(None))
    open_statuses = ("received", "analysing", "under_review", "routed", "in_progress", "awaiting_info")
    if view != "all":
        q = q.where(models.Complaint.status.in_(open_statuses))
    rows = db.execute(q.order_by(models.Complaint.created_at.desc()).limit(500)).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for c in rows:
        a = c.analyses[-1] if c.analyses else None
        out.append(schemas.MapPoint(
            id=c.id, tracking_id=c.tracking_id, lat=c.lat, lng=c.lng, status=c.status, urgency=c.urgency, department=c.department_id,
            district=c.district, summary_en=a.summary_en if a else None, supporters=c.supporters or 0,
            overdue=bool(c.due_at and c.status in open_statuses and c.due_at < now), created_at=c.created_at,
        ))
    return out
