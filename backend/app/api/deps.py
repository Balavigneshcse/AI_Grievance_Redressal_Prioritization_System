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


def dept_out(d: models.Department | None) -> dict | None:
    if d is None:
        return None
    return {"id": d.id, "name_en": d.name_en, "name_ta": d.name_ta, "name_hi": d.name_hi}
