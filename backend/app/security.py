"""Password hashing (argon2), password policy, JWT, OTP generation and hashing."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .config import settings
from .errors import ApiError

_ph = PasswordHasher()

PASSWORD_RULES = [  # (rule id, translated by the app as password.missing.<id>; pattern; English words)
    ("min_length", r".{8,}", "at least 8 characters"),
    ("uppercase", r"[A-Z]", "an uppercase letter"),
    ("lowercase", r"[a-z]", "a lowercase letter"),
    ("digit", r"[0-9]", "a digit"),
    ("symbol", r"[^A-Za-z0-9]", "a symbol"),
]


def password_problems(pw: str) -> list[tuple[str, str]]:
    """(rule id, English words) of every rule the password misses; empty when it is strong enough."""
    return [(rule, words) for rule, pat, words in PASSWORD_RULES if not re.search(pat, pw or "")]


def check_password(pw: str) -> None:
    """400 password_weak unless the password meets every rule: the ids of the missing rules in the
    parameters, for the app to name them in the user's language, and their English words in the message."""
    problems = password_problems(pw)
    if problems:
        raise ApiError(400, "password_weak", message="Password needs " + ", ".join(words for _, words in problems),
                       missing=[rule for rule, _ in problems])


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_token(user_id: str, role: str, password_version: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "role": role, "pv": password_version, "exp": exp}, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hmac.new(settings.JWT_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def otp_matches(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), code_hash)


MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
