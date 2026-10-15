from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from datetime import timedelta

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


async def _save_uploads(db: Session, c: models.Complaint, files: list[UploadFile] | None, captured_in_app: bool,
                        role: str = "evidence", uploaded_by=None) -> int:
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
                exif_lat=exif_lat, exif_lng=exif_lng, captured_in_app=captured_in_app, role=role, uploaded_by=uploaded_by,
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
                district=c.district, office_name=c.office_name, due_at=c.due_at, supporters=c.supporters or 0, rating=c.rating,
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
        rating=c.rating, rating_note=c.rating_note, reopen_count=c.reopen_count or 0, supporters=c.supporters or 0,
        can_reopen_until=_reopen_deadline(c),
        created_at=c.created_at,
        media=[schemas.MediaOut(id=m.id, kind=m.kind, url=f"/media/{m.id}", role=m.role or "evidence") for m in c.media],
        analysis=analysis,
        decision=schemas.DecisionOut(queue=d.queue, reasons=d.reasons or []) if d else None,
        timeline=[schemas.TimelineOut(from_status=e.from_status, to_status=e.to_status, actor_type=e.actor_type, note=e.note, created_at=e.created_at) for e in c.events],
    )


def _reopen_deadline(c: models.Complaint):
    """Until when the complainant may rate or reopen: REOPEN_WINDOW_DAYS after the last resolve/close."""
    if c.status not in ("resolved", "closed"):
        return None
    last = next((e.created_at for e in reversed(c.events) if e.to_status in ("resolved", "closed")), None)
    return (last + timedelta(days=settings.REOPEN_WINDOW_DAYS)) if last else None


def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    from math import asin, cos, radians, sin, sqrt

    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lng2 - lng1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _load_for(db: Session, complaint_id: str, user: models.User) -> models.Complaint:
    c = db.get(models.Complaint, as_uuid(complaint_id))
    if c is None:
        raise HTTPException(404, "Complaint not found")
    if user.role == "complainant" and c.user_id != user.id:
        raise HTTPException(403, "Not your complaint")
    if user.role in STAFF_ROLES and not can_access(c, user):
        raise HTTPException(403, "Outside your district or department")
    return c


@router.get("/complaints/nearby", response_model=list[schemas.NearbyItem])
def nearby(lat: float, lng: float, km: float | None = None, limit: int = 5, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """Open complaints with coordinates within km of a point, nearest first, without any personal data."""
    radius = km or settings.NEARBY_KM
    span = radius / 100.0  # rough degree box; the haversine below does the real filtering
    rows = db.execute(
        select(models.Complaint).where(
            models.Complaint.status.in_(OPEN_FOR_SUPPORT), models.Complaint.lat.is_not(None), models.Complaint.lng.is_not(None),
            models.Complaint.lat.between(lat - span, lat + span), models.Complaint.lng.between(lng - span, lng + span),
            models.Complaint.user_id != user.id,
        )
    ).scalars().all()
    mine = {s.complaint_id for s in db.execute(select(models.Support).where(models.Support.user_id == user.id)).scalars()}
    out = []
    for c in rows:
        d = _haversine_km(lat, lng, c.lat, c.lng)
        if d > radius:
            continue
        a = c.analyses[-1] if c.analyses else None
        out.append(schemas.NearbyItem(
            id=c.id, tracking_id=c.tracking_id, status=c.status, department=dept_out(db.get(models.Department, c.department_id)) if c.department_id else None,
            urgency=c.urgency, summary_en=a.summary_en if a else None, supporters=c.supporters or 0, supported=c.id in mine,
            distance_km=round(d, 2), created_at=c.created_at,
        ))
    # nearest first; at the same spot the most supported, then the newest
    out.sort(key=lambda i: (i.distance_km, -i.supporters, -i.created_at.timestamp()))
    return out[:max(1, min(limit, 20))]


@router.get("/complaints/supported", response_model=list[schemas.ComplaintSummary])
def supported(user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(models.Complaint).join(models.Support, models.Support.complaint_id == models.Complaint.id)
        .where(models.Support.user_id == user.id).order_by(models.Support.created_at.desc())
    ).scalars().all()
    out = []
    for c in rows:
        a = c.analyses[-1] if c.analyses else None
        out.append(schemas.ComplaintSummary(
            id=c.id, tracking_id=c.tracking_id, status=c.status, department=dept_out(db.get(models.Department, c.department_id)) if c.department_id else None,
            urgency=c.urgency, created_at=c.created_at, summary_en=a.summary_en if a else None, district=c.district, office_name=c.office_name,
            due_at=c.due_at, supporters=c.supporters or 0, rating=c.rating,
        ))
    return out


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


OPEN_FOR_SUPPORT = ("received", "analysing", "under_review", "routed", "in_progress", "awaiting_info")


@router.post("/complaints/{complaint_id}/feedback")
def feedback(complaint_id: str, body: schemas.FeedbackIn, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """After a resolution the complainant either confirms it with a rating, or reopens it.
    Both are allowed for REOPEN_WINDOW_DAYS after the resolve/close event."""
    c = _load_for(db, complaint_id, user)
    if c.user_id != user.id:
        raise HTTPException(403, "Only the complainant can give feedback")
    deadline = _reopen_deadline(c)
    if deadline is None:
        raise HTTPException(409, "Feedback is possible once the complaint is resolved")
    if datetime.now(timezone.utc) > deadline:
        raise HTTPException(409, "The feedback window has closed")
    note = " ".join((body.note or "").split())[:500]
    if body.reopen:
        c.reopen_count = (c.reopen_count or 0) + 1
        _set_status(db, c, "in_progress", "complainant", user.id, ("reopened: " + note) if note else "reopened: not fixed")
        notify_staff(db, c, "department", "staff_reopen", text=note or "not fixed")
        notify(db, user, "status", complaint_id=c.id, tracking_id=c.tracking_id, status=STATUS_LABEL.get(c.status, c.status),
               note="Your complaint was reopened and sent back to the department.")
    else:
        if body.rating is None:
            raise HTTPException(400, "Give a rating from 1 to 5, or reopen the complaint")
        c.rating, c.rating_note, c.rated_at = body.rating, note or None, datetime.now(timezone.utc)
        db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="complainant", actor_id=user.id,
                                  note=f"rated {body.rating}/5" + (f": {note}" if note else "")))
    db.commit()
    return {"ok": True, "status": c.status, "rating": c.rating, "reopen_count": c.reopen_count}


@router.post("/complaints/{complaint_id}/support")
def support(complaint_id: str, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """'Me too': back an existing open complaint instead of filing a duplicate. Enough supporters raise its urgency one level."""
    c = db.get(models.Complaint, as_uuid(complaint_id))
    if c is None:
        raise HTTPException(404, "Complaint not found")
    if c.user_id == user.id:
        raise HTTPException(400, "You filed this complaint")
    if c.status not in OPEN_FOR_SUPPORT:
        raise HTTPException(409, "This complaint is no longer open")
    exists = db.execute(select(models.Support).where(models.Support.complaint_id == c.id, models.Support.user_id == user.id)).scalar_one_or_none()
    if exists is None:
        db.add(models.Support(complaint_id=c.id, user_id=user.id))
        c.supporters = (c.supporters or 0) + 1
        db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="system",
                                  note=f"supported by another citizen ({c.supporters} supporter{'s' if c.supporters != 1 else ''})"))
        order = ["low", "medium", "high", "critical"]
        if c.supporters == settings.SUPPORT_BOOST_AT and c.urgency in ("low", "medium"):
            c.urgency = order[order.index(c.urgency) + 1]
            db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="system",
                                      note=f"urgency raised to {c.urgency}: {c.supporters} citizens support this complaint"))
        db.commit()
    return {"ok": True, "supporters": c.supporters, "supported": True, "urgency": c.urgency}
