"""Request and response shapes (the API contract shared with the frontend)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    mobile: str
    email: str
    password: str
    preferred_language: Literal["en", "ta", "hi"] = "en"


class VerifyOtpIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


class LoginIn(BaseModel):
    email: str
    password: str


class ForgotIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    email: str
    code: str
    new_password: str


class UserOut(BaseModel):
    id: UUID
    email: str
    role: str  # complainant | dept_admin | district_admin | super_admin
    preferred_language: str
    department_id: str | None = None
    district: str | None = None
    full_name: str | None = None
    is_active: bool = True


class StaffOut(UserOut):
    mobile: str
    department: "DepartmentOut | None" = None
    created_at: datetime
    last_login_at: datetime | None = None


class StaffCreateIn(BaseModel):
    email: str
    mobile: str
    full_name: str = Field(min_length=2, max_length=120)
    role: Literal["district_admin", "dept_admin"]
    district: str | None = None
    department_id: str | None = None
    preferred_language: Literal["en", "ta", "hi"] = "en"
    password: str | None = None  # generated when omitted; returned once


class StaffCreated(BaseModel):
    user: StaffOut
    password: str


class StaffPatchIn(BaseModel):
    is_active: bool | None = None
    full_name: str | None = None
    department_id: str | None = None
    district: str | None = None
    preferred_language: Literal["en", "ta", "hi"] | None = None
    password: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class DepartmentOut(BaseModel):
    id: str
    name_en: str
    name_ta: str
    name_hi: str


class ComplaintAccepted(BaseModel):
    id: UUID
    tracking_id: str
    status: str


class ComplaintSummary(BaseModel):
    id: UUID
    tracking_id: str
    status: str
    department: DepartmentOut | None
    urgency: str | None
    created_at: datetime
    summary_en: str | None
    district: str | None = None
    office_name: str | None = None
    due_at: datetime | None = None


class MediaOut(BaseModel):
    id: UUID
    kind: str
    url: str


class AnalysisOut(BaseModel):
    language_primary: str | None
    language_secondary: str | None
    department: str | None
    urgency: str | None
    confidence: float | None
    summary_en: str | None
    evidence_spans: list[str]
    entities: dict[str, Any]
    image_findings: str | None
    image_matches_text: bool | None
    second_opinion_department: str | None = None
    second_opinion_prob: float | None = None
    matched_rule_ids: list[str]
    duplicate_candidates: list[dict[str, Any]]
    latency_ms: int | None
    masked_text: str | None = None  # officer/admin only
    pii_map: dict[str, Any] | None = None  # officer/admin only
    error: str | None = None


class DecisionOut(BaseModel):
    queue: str
    reasons: list[str]


class TimelineOut(BaseModel):
    from_status: str | None
    to_status: str
    actor_type: str
    note: str | None
    created_at: datetime


class ComplaintDetail(BaseModel):
    id: UUID
    tracking_id: str
    status: str
    raw_text: str
    language_hint: str | None
    department: DepartmentOut | None
    urgency: str | None
    lat: float | None
    lng: float | None
    location_source: str
    manual_address: str | None
    resolved_place: str | None
    complainant_name: str | None = None
    aadhaar_last4: str | None = None
    district: str | None = None
    office_name: str | None = None
    office_department_id: str | None = None
    due_at: datetime | None = None
    escalated_at: datetime | None = None
    created_at: datetime
    media: list[MediaOut]
    analysis: AnalysisOut | None
    decision: DecisionOut | None
    timeline: list[TimelineOut]


class GeoIn(BaseModel):
    lat: float
    lng: float


class QueueItem(BaseModel):
    id: UUID
    tracking_id: str
    status: str
    urgency: str | None
    department: str | None
    language_primary: str | None
    summary_en: str | None
    flags: list[str]
    confidence: float | None
    created_at: datetime
    district: str | None = None
    office_name: str | None = None
    due_at: datetime | None = None
    complainant_name: str | None = None


class DecisionIn(BaseModel):
    action: Literal["accept", "reassign", "merge", "request_info", "resolve", "close", "reopen"]
    department: str | None = None
    urgency: Literal["critical", "high", "medium", "low"] | None = None
    merged_into: str | None = None  # tracking id or uuid
    reason: str = Field(min_length=3)


class RulesIn(BaseModel):
    yaml: str
    note: str | None = None
