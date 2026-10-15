from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from .. import models
from ..security import decode_token


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(models.User, as_uuid(payload["sub"]))
    if user is None or user.password_version != payload.get("pv"):
        raise HTTPException(401, "Session no longer valid")
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    return user


def as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(404, "Not found")


def require_role(*roles: str):
    def dep(user: models.User = Depends(current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(403, "Not allowed for this role")
        return user
    return dep


STAFF_ROLES = ("super_admin", "district_admin", "dept_admin")
ADMIN_ROLES = ("super_admin", "district_admin")


def scope_complaints(q, user: models.User):
    """Restrict a complaints query to what the staff member may see:
    super admin everything, district admin their district, department admin their department in their district."""
    if user.role == "super_admin":
        return q
    if user.role == "district_admin":
        return q.where(models.Complaint.district == user.district)
    if user.role == "dept_admin":
        q = q.where(models.Complaint.department_id == user.department_id)
        if user.district:
            q = q.where(models.Complaint.district == user.district)
        return q
    return q.where(models.Complaint.user_id == user.id)


def can_access(c: models.Complaint, user: models.User) -> bool:
    if user.role == "super_admin":
        return True
    if user.role == "district_admin":
        return c.district == user.district
    if user.role == "dept_admin":
        return c.department_id == user.department_id and (not user.district or c.district == user.district)
    return c.user_id == user.id


def user_out(u: models.User):
    from .. import schemas

    return schemas.UserOut(
        id=u.id, email=u.email, role=u.role, preferred_language=u.preferred_language, department_id=u.department_id,
        district=u.district, full_name=u.full_name, is_active=u.is_active,
    )


def dept_out(d: models.Department | None) -> dict | None:
    if d is None:
        return None
    return {"id": d.id, "name_en": d.name_en, "name_ta": d.name_ta, "name_hi": d.name_hi}
