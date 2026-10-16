from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..errors import ApiError
from .. import models, schemas
from ..security import EMAIL_RE, MOBILE_RE, check_password, create_token, hash_otp, hash_password, new_otp, otp_matches, verify_password
from ..services.notifier import notify
from ..services.ratelimit import client_ip, hit
from .deps import current_user, user_out

router = APIRouter(prefix="/auth", tags=["auth"])
AADHAAR4_RE = re.compile(r"[0-9]{4}")


def _issue_otp(db: Session, user: models.User, purpose: str) -> None:
    code = new_otp()
    db.add(
        models.Otp(
            user_id=user.id, purpose=purpose, code_hash=hash_otp(code),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        )
    )
    notify(db, user, "otp", code=code, minutes=settings.OTP_EXPIRE_MINUTES)


def _check_otp(db: Session, user: models.User | None, purpose: str, code: str) -> None:
    # One answer (code_invalid) for a wrong, expired or missing code and for an email with no account, so verify-otp and
    # reset never tell whether an address is registered (forgot and resend-otp are generic for the same reason).
    if user is None:
        raise ApiError(400, "code_invalid")
    otp = db.execute(
        select(models.Otp).where(models.Otp.user_id == user.id, models.Otp.purpose == purpose, models.Otp.consumed_at.is_(None))
        .order_by(models.Otp.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if otp is None or otp.expires_at < datetime.now(timezone.utc):
        raise ApiError(400, "code_invalid")
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise ApiError(429, "code_attempts_exceeded")
    otp.attempts += 1
    if not otp_matches(code, otp.code_hash):
        db.commit()
        raise ApiError(400, "code_invalid")
    otp.consumed_at = datetime.now(timezone.utc)


def _token(user: models.User) -> schemas.TokenOut:
    return schemas.TokenOut(
        access_token=create_token(str(user.id), user.role, user.password_version),
        user=user_out(user),
    )


def _clean_name(value: str | None) -> str:
    """Collapse whitespace; 400 unless 2 to 120 characters remain."""
    name = " ".join((value or "").split())
    if not 2 <= len(name) <= 120:
        raise ApiError(400, "name_invalid")
    return name


def _clean_aadhaar(value: str | None) -> str:
    """Exactly the last four digits of the Aadhaar number, never more."""
    digits = (value or "").strip()
    if not AADHAAR4_RE.fullmatch(digits):
        raise ApiError(400, "aadhaar_invalid")
    return digits


@router.post("/register", status_code=201)
def register(body: schemas.RegisterIn, request: Request, db: Session = Depends(get_db)):
    hit(f"register:{client_ip(request)}", 20, 600)
    email = body.email.strip().lower()
    mobile = body.mobile.strip().replace(" ", "").removeprefix("+91")
    if not MOBILE_RE.match(mobile):
        raise ApiError(400, "mobile_invalid")
    if not EMAIL_RE.match(email):
        raise ApiError(400, "email_invalid")
    check_password(body.password)
    full_name, aadhaar_last4 = _clean_name(body.full_name), _clean_aadhaar(body.aadhaar_last4)

    user = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
    if user and user.is_verified:
        raise ApiError(409, "email_taken")
    other = db.execute(select(models.User).where(models.User.mobile == mobile)).scalar_one_or_none()
    if other and other.id != (user.id if user else None):
        raise ApiError(409, "mobile_taken")

    if user is None:
        user = models.User(mobile=mobile, email=email, password_hash=hash_password(body.password), preferred_language=body.preferred_language,
                           full_name=full_name, aadhaar_last4=aadhaar_last4)
        db.add(user)
        db.flush()
    else:  # unverified: refresh details and resend
        user.mobile, user.password_hash, user.preferred_language = mobile, hash_password(body.password), body.preferred_language
        user.full_name, user.aadhaar_last4 = full_name, aadhaar_last4
    _issue_otp(db, user, "register")
    db.commit()
    return {"user_id": str(user.id), "message": "Verification code sent to your email"}


@router.post("/verify-otp", response_model=schemas.TokenOut)
def verify_otp(body: schemas.VerifyOtpIn, request: Request, db: Session = Depends(get_db)):
    hit(f"verify:{body.email.strip().lower()}", 10, 600)
    user = db.execute(select(models.User).where(models.User.email == body.email.strip().lower())).scalar_one_or_none()
    _check_otp(db, user, "register", body.code)
    user.is_verified = True
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return _token(user)


@router.post("/resend-otp")
def resend_otp(body: schemas.ForgotIn, request: Request, db: Session = Depends(get_db)):
    hit(f"otp:{body.email.strip().lower()}", 3, 600)
    hit(f"otp:{client_ip(request)}", 10, 600)
    user = db.execute(select(models.User).where(models.User.email == body.email.strip().lower())).scalar_one_or_none()
    if user and not user.is_verified:
        _issue_otp(db, user, "register")
        db.commit()
    return {"message": "If the account exists, a new code was sent"}


@router.post("/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    hit(f"login:{client_ip(request)}", 30, 60)
    hit(f"login:{body.email.strip().lower()}", 10, 60)
    user = db.execute(select(models.User).where(models.User.email == body.email.strip().lower())).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "login_failed")
    if not user.is_verified:
        raise ApiError(403, "account_not_verified")
    if not user.is_active:
        raise ApiError(403, "account_disabled")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return _token(user)


@router.post("/forgot")
def forgot(body: schemas.ForgotIn, request: Request, db: Session = Depends(get_db)):
    hit(f"otp:{body.email.strip().lower()}", 3, 600)
    hit(f"otp:{client_ip(request)}", 10, 600)
    user = db.execute(select(models.User).where(models.User.email == body.email.strip().lower())).scalar_one_or_none()
    if user:
        _issue_otp(db, user, "reset")
        db.commit()
    return {"message": "If the account exists, a reset code was sent"}


@router.post("/reset")
def reset(body: schemas.ResetIn, db: Session = Depends(get_db)):
    check_password(body.new_password)  # before the account lookup: the same answer either way
    user = db.execute(select(models.User).where(models.User.email == body.email.strip().lower())).scalar_one_or_none()
    _check_otp(db, user, "reset", body.code)
    user.password_hash = hash_password(body.new_password)
    user.password_version += 1  # invalidates every existing token
    user.is_verified = True
    db.commit()
    return {"message": "Password updated. Please log in."}


@router.patch("/me", response_model=schemas.UserOut)
def update_me(body: schemas.ProfileIn, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """Complete or correct the details every complaint carries (name, Aadhaar last 4) and the mail language."""
    if body.full_name is not None:
        user.full_name = _clean_name(body.full_name)
    if body.aadhaar_last4 is not None:
        user.aadhaar_last4 = _clean_aadhaar(body.aadhaar_last4)
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(current_user)):
    return user_out(user)
