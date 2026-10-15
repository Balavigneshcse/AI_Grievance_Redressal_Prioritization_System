"""SQLAlchemy models. One table per entity in docs/04-database-and-ui.md."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    mobile: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_version: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(20), default="complainant")  # complainant | dept_admin | district_admin | super_admin
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)  # dept_admin only
    district: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)  # district_admin and dept_admin
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_language: Mapped[str] = mapped_column(String(5), default="en")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Otp(Base):
    __tablename__ = "otps"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # register | reset
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_ta: Mapped[str] = mapped_column(String(100))
    name_hi: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[uuid.UUID] = uuid_pk()
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)  # never updated
    language_hint: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="received", index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    urgency: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String(20), default="none")
    manual_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    complainant_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aadhaar_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)  # identity check for the office, never shown to the model
    resolved_place: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ward: Mapped[str | None] = mapped_column(String(50), nullable=True)
    district: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    office_department_id: Mapped[str | None] = mapped_column(String(10), nullable=True)
    office_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # SLA breach handled once
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)
    contact_incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    media: Mapped[list["Media"]] = relationship(back_populates="complaint", order_by="Media.created_at")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="complaint", order_by="Analysis.created_at")
    events: Mapped[list["StatusEvent"]] = relationship(back_populates="complaint", order_by="StatusEvent.created_at")
    decisions: Mapped[list["Decision"]] = relationship(order_by="Decision.created_at")


class Media(Base):
    __tablename__ = "media"
    id: Mapped[uuid.UUID] = uuid_pk()
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # photo | video
    file_path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    exif_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    exif_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_in_app: Mapped[bool] = mapped_column(Boolean, default=False)
    key_frame_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    complaint: Mapped[Complaint] = relationship(back_populates="media")


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[uuid.UUID] = uuid_pk()
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id"), index=True)
    model_text: Mapped[str] = mapped_column(String(60))
    model_embed: Mapped[str] = mapped_column(String(60))
    language_primary: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language_secondary: Mapped[str | None] = mapped_column(String(10), nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_spans: Mapped[list] = mapped_column(JSONB, default=list)
    entities: Mapped[dict] = mapped_column(JSONB, default=dict)
    image_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_matches_text: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    masked_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    pii_map: Mapped[dict] = mapped_column(JSONB, default=dict)  # restricted to officer/admin
    embedding = mapped_column(Vector(1024), nullable=True)
    second_opinion_department: Mapped[str | None] = mapped_column(String(30), nullable=True)
    second_opinion_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_opinion_urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    matched_rule_ids: Mapped[list] = mapped_column(JSONB, default=list)
    duplicate_candidates: Mapped[list] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    complaint: Mapped[Complaint] = relationship(back_populates="analyses")


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id"), index=True)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analyses.id"), nullable=True)
    queue: Mapped[str] = mapped_column(String(20))  # department | review
    department_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Override(Base):
    __tablename__ = "overrides"
    id: Mapped[uuid.UUID] = uuid_pk()
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id"), index=True)
    officer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    from_department: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_department: Mapped[str | None] = mapped_column(String(30), nullable=True)
    from_urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    to_urgency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StatusEvent(Base):
    __tablename__ = "status_events"
    id: Mapped[uuid.UUID] = uuid_pk()
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    actor_type: Mapped[str] = mapped_column(String(20))  # system | officer | complainant
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    complaint: Mapped[Complaint] = relationship(back_populates="events")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(10), default="email")
    template: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(5))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))  # queued | sent | failed
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RuleChange(Base):
    __tablename__ = "rule_changes"
    id: Mapped[uuid.UUID] = uuid_pk()
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    yaml_before: Mapped[str] = mapped_column(Text)
    yaml_after: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
