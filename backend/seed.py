"""Create the demo accounts. Password for all of them comes from SEED_PASSWORD in .env
(default in app/config.py). Run from the backend folder:  python seed.py"""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app import models
from app.security import hash_password

ACCOUNTS = [
    ("admin@synapse.local", "9000000001", "admin", None, "en"),
    ("officer.water@synapse.local", "9000000002", "officer", "water", "ta"),
    ("officer.roads@synapse.local", "9000000003", "officer", "roads", "en"),
    ("citizen@synapse.local", "9000000004", "complainant", None, "ta"),
]


def main() -> None:
    init_db()
    with SessionLocal() as db:
        for email, mobile, role, dept, lang in ACCOUNTS:
            u = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
            if u is None:
                u = models.User(email=email, mobile=mobile, password_hash=hash_password(settings.SEED_PASSWORD), role=role, department_id=dept, preferred_language=lang, is_verified=True)
                db.add(u)
                print("created", role, email)
            else:
                u.role, u.department_id, u.is_verified = role, dept, True
                print("exists ", role, email)
        db.commit()
    print("Password for all seed accounts: the SEED_PASSWORD value in .env")


if __name__ == "__main__":
    main()
