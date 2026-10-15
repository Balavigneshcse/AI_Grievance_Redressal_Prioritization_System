"""Engine, session factory, schema creation and department seeding."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


DEPARTMENT_NAMES = {
    "water": ("Water Supply", "குடிநீர் வழங்கல்", "जल आपूर्ति"),
    "electricity": ("Electricity", "மின்சாரம்", "बिजली"),
    "roads": ("Roads and Infrastructure", "சாலைகள் மற்றும் உள்கட்டமைப்பு", "सड़क और बुनियादी ढांचा"),
    "sanitation": ("Sanitation and Waste", "துப்புரவு மற்றும் கழிவு மேலாண்மை", "स्वच्छता और कचरा प्रबंधन"),
    "health": ("Public Health", "பொது சுகாதாரம்", "सार्वजनिक स्वास्थ्य"),
    "safety": ("Fire and Safety", "தீயணைப்பு மற்றும் பாதுகாப்பு", "अग्नि और सुरक्षा"),
    "revenue": ("Revenue and Property", "வருவாய் மற்றும் சொத்து", "राजस्व और संपत्ति"),
    "general": ("General / Unclassified", "பொது", "सामान्य"),
}


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Columns added after the first deployment (create_all does not alter existing tables).
        for col, typ in [("district", "VARCHAR(60)"), ("office_department_id", "VARCHAR(10)"), ("office_name", "VARCHAR(200)"), ("due_at", "TIMESTAMPTZ"),
                         ("complainant_name", "VARCHAR(120)"), ("aadhaar_last4", "VARCHAR(4)"), ("escalated_at", "TIMESTAMPTZ")]:
            conn.execute(text(f"ALTER TABLE complaints ADD COLUMN IF NOT EXISTS {col} {typ}"))
        for col, typ in [("district", "VARCHAR(60)"), ("full_name", "VARCHAR(120)"), ("is_active", "BOOLEAN NOT NULL DEFAULT TRUE")]:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typ}"))
        # Role hierarchy introduced on day 1 evening: admin -> super_admin, officer -> dept_admin.
        conn.execute(text("UPDATE users SET role = 'super_admin' WHERE role = 'admin'"))
        conn.execute(text("UPDATE users SET role = 'dept_admin' WHERE role = 'officer'"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_analyses_embedding "
                "ON analyses USING hnsw (embedding vector_cosine_ops)"
            )
        )
    # Seed departments from the taxonomy so routing and UI labels always exist.
    from scripts.common import load_taxonomy

    with SessionLocal() as db:
        existing = {d.id for d in db.query(models.Department).all()}
        for d in load_taxonomy():
            if d["id"] not in existing:
                en, ta, hi = DEPARTMENT_NAMES.get(d["id"], (d["name"], d["name"], d["name"]))
                db.add(models.Department(id=d["id"], name_en=en, name_ta=ta, name_hi=hi, is_active=True))
        db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
