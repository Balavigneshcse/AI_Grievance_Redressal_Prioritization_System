"""Create the demo accounts. Password for all of them comes from SEED_PASSWORD in .env
(default in app/config.py). Run from the backend folder:  python seed.py"""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, init_db
from app import models
from app.security import hash_password

ACCOUNTS = [
    # email, mobile, role, department, language, district, full name, Aadhaar last 4 (citizens only)
    ("admin@synapse.local", "9000000001", "super_admin", None, "en", None, "Super Admin", None),
    ("district.coimbatore@synapse.local", "9000000005", "district_admin", None, "ta", "Coimbatore", "Coimbatore District Admin", None),
    ("officer.water@synapse.local", "9000000002", "dept_admin", "water", "ta", "Coimbatore", "Water Supply Admin, Coimbatore", None),
    ("officer.roads@synapse.local", "9000000003", "dept_admin", "roads", "en", "Coimbatore", "Roads Admin, Coimbatore", None),
    ("citizen@synapse.local", "9000000004", "complainant", None, "ta", None, "Demo Citizen", "4321"),
]


def main() -> None:
    init_db()
    with SessionLocal() as db:
        for email, mobile, role, dept, lang, district, name, aadhaar in ACCOUNTS:
            u = db.execute(select(models.User).where(models.User.email == email)).scalar_one_or_none()
            if u is None:
                u = models.User(email=email, mobile=mobile, password_hash=hash_password(settings.SEED_PASSWORD), role=role, department_id=dept,
                                preferred_language=lang, district=district, full_name=name, aadhaar_last4=aadhaar, is_verified=True, is_active=True)
                db.add(u)
                print("created", role, email)
            else:
                u.role, u.department_id, u.district, u.full_name, u.is_verified, u.is_active = role, dept, district, name, True, True
                u.aadhaar_last4 = aadhaar or u.aadhaar_last4
                print("exists ", role, email)
        db.commit()
    print("Password for all seed accounts: the SEED_PASSWORD value in .env")


if __name__ == "__main__":
    main()
