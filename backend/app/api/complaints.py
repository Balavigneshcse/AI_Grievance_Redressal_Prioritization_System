from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from .. import models, schemas
from ..services.notifier import STATUS_LABEL, notify, notify_staff
from ..services.pipeline import _set_status
from ..services.worker import enqueue
from .deps import STAFF_ROLES, as_uuid, can_access, current_user, dept_out

router = APIRouter(tags=["complaints"])


def _tracking_id(db: Session) -> str:
    n = db.execute(select(func.count(models.Complaint.id))).scalar_one() + 1
    return f"SYN-{datetime.now(timezone.utc).year}-{n:06d}"


def _exif_gps(path: Path) -> tuple[float | None, float | None]:
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS

        with Image.open(path) as im:
            exif = im.getexif()
            gps_ifd = exif.get_ifd(0x8825) if hasattr(exif, "get_ifd") else None
        if not gps_ifd:
            return None, None
        g = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}

        def to_deg(v, ref):
            d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            return -d if ref in ("S", "W") else d

        return to_deg(g["GPSLatitude"], g.get("GPSLatitudeRef", "N")), to_deg(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))
    except Exception:
        return None, None


@router.get("/departments", response_model=list[schemas.DepartmentOut])
def departments(db: Session = Depends(get_db)):
    return [dept_out(d) for d in db.execute(select(models.Department).where(models.Department.is_active)).scalars()]


async def _save_uploads(db: Session, c: models.Complaint, files: list[UploadFile] | None, captured_in_app: bool) -> int:
    """Validate and stream photos and videos to disk, one Media row each. Returns how many were saved."""
    folder = settings.MEDIA_DIR / str(c.id)
    saved = 0
    for f in files or []:
        if not f.filename:
            continue
        mime = f.content_type or ""
        if not (mime.startswith("image/") or mime.startswith("video/")):
            raise HTTPException(400, f"Unsupported file type {mime}")
        kind = "photo" if mime.startswith("image/") else "video"
        limit_mb = settings.MAX_PHOTO_MB if kind == "photo" else settings.MAX_VIDEO_MB
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(f.filename).suffix.lower() or (".jpg" if kind == "photo" else (".webm" if "webm" in mime else ".mp4"))
        path = folder / f"{uuid.uuid4().hex}{ext}"
        # Stream to disk in 1 MB pieces: a 100 MB video never sits in memory.
        size = 0
        with path.open("wb") as fh:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > limit_mb * 1024 * 1024:
                    fh.close()
                    path.unlink(missing_ok=True)
                    raise HTTPException(413, f"{f.filename} is larger than {limit_mb} MB ({kind} limit)")
                fh.write(chunk)
        exif_lat, exif_lng = _exif_gps(path) if kind == "photo" else (None, None)
        db.add(
            models.Media(
                complaint_id=c.id, kind=kind, file_path=str(path), mime=mime, size_bytes=size,
                exif_lat=exif_lat, exif_lng=exif_lng, captured_in_app=captured_in_app,
            )
        )
        saved += 1
    return saved


@router.post("/complaints", status_code=202, response_model=schemas.ComplaintAccepted)
async def create_complaint(
    text: str = Form(...),
    complainant_name: str = Form(...),
    aadhaar_last4: str = Form(...),
    language_hint: str | None = Form(None),
    lat: float | None = Form(None),
    lng: float | None = Form(None),
    location_source: str = Form("none"),
    manual_address: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    text = (text or "").strip()
    if len(text) < 10:
        raise HTTPException(400, "Please describe the problem in at least a few words")
    if location_source not in ("camera_gps", "exif", "browser", "manual", "none"):
        location_source = "none"
    complainant_name = " ".join((complainant_name or "").split())
    if not 2 <= len(complainant_name) <= 120:
        raise HTTPException(400, "Please enter your name")
    aadhaar_last4 = (aadhaar_last4 or "").strip()
    if not re.fullmatch(r"\d{4}", aadhaar_last4):
        raise HTTPException(400, "Enter the last 4 digits of your Aadhaar number")

    c = models.Complaint(
        tracking_id=_tracking_id(db), user_id=user.id, raw_text=text, language_hint=language_hint,
        complainant_name=complainant_name, aadhaar_last4=aadhaar_last4,
        lat=lat, lng=lng, location_source=location_source if (lat is not None or manual_address) else "none",
        manual_address=manual_address, contact_incomplete=not (user.mobile and user.email),
    )
    db.add(c)
    db.flush()

    await _save_uploads(db, c, files, captured_in_app=(location_source == "camera_gps"))

    db.add(models.StatusEvent(complaint_id=c.id, from_status=None, to_status="received", actor_type="complainant", actor_id=user.id, note="submitted"))
    notify(db, user, "ack", complaint_id=c.id, tracking_id=c.tracking_id)
    db.commit()
    enqueue(c.id)
    return schemas.ComplaintAccepted(id=c.id, tracking_id=c.tracking_id, status=c.status)


@router.get("/complaints/mine", response_model=list[schemas.ComplaintSummary])
def my_complaints(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(models.Complaint).where(models.Complaint.user_id == user.id).order_by(models.Complaint.created_at.desc())).scalars().all()
    out = []
    for c in rows:
        a = c.analyses[-1] if c.analyses else None
        out.append(
            schemas.ComplaintSummary(
                id=c.id, tracking_id=c.tracking_id, status=c.status, department=dept_out(db.get(models.Department, c.department_id)) if c.department_id else None,
                urgency=c.urgency, created_at=c.created_at, summary_en=a.summary_en if a else None,
                district=c.district, office_name=c.office_name, due_at=c.due_at,
            )
        )
    return out


def complaint_detail(db: Session, c: models.Complaint, viewer: models.User) -> schemas.ComplaintDetail:
    staff = viewer.role in STAFF_ROLES
    a = c.analyses[-1] if c.analyses else None
    d = c.decisions[-1] if c.decisions else None
    analysis = None
    if a:
        analysis = schemas.AnalysisOut(
            language_primary=a.language_primary, language_secondary=a.language_secondary, department=a.department_id, urgency=a.urgency,
            confidence=a.confidence, summary_en=a.summary_en, evidence_spans=a.evidence_spans or [], entities=a.entities or {},
            image_findings=a.image_findings, image_matches_text=a.image_matches_text,
            second_opinion_department=a.second_opinion_department if staff else None, second_opinion_prob=a.second_opinion_prob if staff else None,
            matched_rule_ids=a.matched_rule_ids or [], duplicate_candidates=a.duplicate_candidates or [] if staff else [],
            latency_ms=a.latency_ms, masked_text=a.masked_text if staff else None, pii_map=a.pii_map if staff else None, error=a.error if staff else None,
        )
    return schemas.ComplaintDetail(
        id=c.id, tracking_id=c.tracking_id, status=c.status, raw_text=c.raw_text, language_hint=c.language_hint,
        department=dept_out(db.get(models.Department, c.department_id)) if c.department_id else None, urgency=c.urgency,
        lat=c.lat, lng=c.lng, location_source=c.location_source, manual_address=c.manual_address, resolved_place=c.resolved_place,
        complainant_name=c.complainant_name, aadhaar_last4=c.aadhaar_last4,
        district=c.district, office_name=c.office_name, office_department_id=c.office_department_id, due_at=c.due_at,
        escalated_at=c.escalated_at,
        created_at=c.created_at,
        media=[schemas.MediaOut(id=m.id, kind=m.kind, url=f"/media/{m.id}") for m in c.media],
        analysis=analysis,
        decision=schemas.DecisionOut(queue=d.queue, reasons=d.reasons or []) if d else None,
        timeline=[schemas.TimelineOut(from_status=e.from_status, to_status=e.to_status, actor_type=e.actor_type, note=e.note, created_at=e.created_at) for e in c.events],
    )


def _load_for(db: Session, complaint_id: str, user: models.User) -> models.Complaint:
    c = db.get(models.Complaint, as_uuid(complaint_id))
    if c is None:
        raise HTTPException(404, "Complaint not found")
    if user.role == "complainant" and c.user_id != user.id:
        raise HTTPException(403, "Not your complaint")
    if user.role in STAFF_ROLES and not can_access(c, user):
        raise HTTPException(403, "Outside your district or department")
    return c


@router.get("/complaints/track/{tracking_id}", response_model=schemas.ComplaintDetail)
def track(tracking_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.execute(select(models.Complaint).where(models.Complaint.tracking_id == tracking_id.upper())).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "Complaint not found")
    return complaint_detail(db, _load_for(db, str(c.id), user), user)


@router.get("/complaints/{complaint_id}", response_model=schemas.ComplaintDetail)
def get_complaint(complaint_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    return complaint_detail(db, _load_for(db, complaint_id, user), user)


@router.get("/complaints/{complaint_id}/timeline", response_model=list[schemas.TimelineOut])
def timeline(complaint_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    c = _load_for(db, complaint_id, user)
    return [schemas.TimelineOut(from_status=e.from_status, to_status=e.to_status, actor_type=e.actor_type, note=e.note, created_at=e.created_at) for e in c.events]


@router.get("/media/{media_id}")
def media(media_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(models.Media, as_uuid(media_id))
    if m is None:
        raise HTTPException(404, "Media not found")
    _load_for(db, str(m.complaint_id), user)
    return FileResponse(m.file_path, media_type=m.mime)


@router.post("/complaints/{complaint_id}/reply")
async def reply(
    complaint_id: str,
    text: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The complainant answers a request for information or adds details and evidence.
    An awaiting-info case goes back to where it was; the office holding the case is emailed."""
    c = _load_for(db, complaint_id, user)
    if c.user_id != user.id:
        raise HTTPException(403, "Only the complainant can reply")
    if c.status in ("closed", "merged"):
        raise HTTPException(409, "This complaint is closed")
    text = " ".join((text or "").split())
    if len(text) < 2 and not any(f.filename for f in files or []):
        raise HTTPException(400, "Write a reply or attach a photo or video")
    saved = await _save_uploads(db, c, files, captured_in_app=False)
    note = (f"reply: {text}" if text else "reply with attachments") + (f" (+{saved} file{'s' if saved != 1 else ''})" if saved and text else "")
    if c.status == "awaiting_info":
        prev = next((e.from_status for e in reversed(c.events) if e.to_status == "awaiting_info"), None)
        target = prev if prev in ("routed", "in_progress", "under_review") else "in_progress"
        _set_status(db, c, target, "complainant", user.id, note[:1000])
    else:
        db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="complainant", actor_id=user.id, note=note[:1000]))
    holder = "district" if c.status == "under_review" else "department"
    notify_staff(db, c, holder, "staff_reply", text=(text or f"{saved} attachment(s)")[:500])
    notify(db, user, "status", complaint_id=c.id, tracking_id=c.tracking_id, status=STATUS_LABEL.get(c.status, c.status), note="Thank you, your reply was received.")
    db.commit()
    return {"ok": True, "status": c.status, "attachments": saved}
