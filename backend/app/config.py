"""Settings from .env at the project root. Also puts the project root on sys.path so
the backend can import the pipeline helpers in scripts/common.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bool(v: str | None, default: bool = False) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    ROOT = ROOT
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/synapse")

    SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "grievance@synapse.local")
    SMTP_TLS = _bool(os.getenv("SMTP_TLS"), False)

    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    LLM = os.getenv("SYNAPSE_LLM", "gemma3:4b")
    EMBED = os.getenv("SYNAPSE_EMBED", "bge-m3")
    LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "180"))

    JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
    OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))
    OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))

    REVIEW_CONFIDENCE_THRESHOLD = float(os.getenv("REVIEW_CONFIDENCE_THRESHOLD", "0.70"))
    DUPLICATE_SCORE_THRESHOLD = float(os.getenv("DUPLICATE_SCORE_THRESHOLD", "0.85"))
    DUPLICATE_MAX_KM = float(os.getenv("DUPLICATE_MAX_KM", "2.0"))
    MEDIA_DIR = ROOT / os.getenv("MEDIA_DIR", "media")
    MAX_PHOTO_MB = int(os.getenv("MAX_PHOTO_MB", "25"))
    MAX_VIDEO_MB = int(os.getenv("MAX_VIDEO_MB", "100"))
    MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "300"))
    MAX_FILES = int(os.getenv("MAX_FILES", "6"))  # photos and videos per request, as on the complaint form
    MAX_COMPLAINT_CHARS = int(os.getenv("MAX_COMPLAINT_CHARS", "5000"))  # complaint text; the model reads about 2,048 tokens
    LLM_KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "2h")  # keep Gemma loaded between complaints
    APP_URL = os.getenv("APP_URL", "http://localhost:5173")
    REOPEN_WINDOW_DAYS = int(os.getenv("REOPEN_WINDOW_DAYS", "7"))  # citizen may reopen or rate within this
    SUPPORT_BOOST_AT = int(os.getenv("SUPPORT_BOOST_AT", "5"))  # supporters that raise urgency one level
    NEARBY_KM = float(os.getenv("NEARBY_KM", "2.0"))
    # A GPS point further than this from every known place (config/places_tn.csv) gets no district:
    # outside Tamil Nadu or a bad coordinate goes to review instead of the nearest wrong district.
    MAX_PLACE_KM = float(os.getenv("MAX_PLACE_KM", "30"))
    TRANSLATE_NOTES = _bool(os.getenv("TRANSLATE_NOTES"), True)  # officer notes translated in citizen mails

    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")]
    SEED_PASSWORD = os.getenv("SEED_PASSWORD", "Synapse@123")


settings = Settings()
settings.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
