from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..errors import ApiError
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


# The only media the API stores, recognised by their first bytes, never by the name or type the
# browser declares: an SVG or HTML file carries script, and a renamed text file breaks the model.
MEDIA_TYPES = {
    "image/jpeg": ("photo", ".jpg"), "image/png": ("photo", ".png"), "image/webp": ("photo", ".webp"),
    "video/webm": ("video", ".webm"), "video/mp4": ("video", ".mp4"), "video/quicktime": ("video", ".mov"),
}
SAFE_MEDIA_TYPES = set(MEDIA_TYPES)


def _sniff(head: bytes) -> str | None:
    """Media type from the file signature, or None for anything not on the list."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"):
            return None  # HEIC / AVIF stills share the container but neither the model nor most browsers read them
        return "video/quicktime" if brand.startswith(b"qt") else "video/mp4"
    return None


async def _save_uploads(db: Session, c: models.Complaint, files: list[UploadFile] | None, captured_in_app: bool,
                        role: str = "evidence", uploaded_by=None) -> int:
    """Validate and stream photos and videos to disk, one Media row each. Returns how many were saved.
    Any refused file refuses the whole request, and files already written for it are removed."""
    files = [f for f in files or [] if f.filename]
    if len(files) > settings.MAX_FILES:
        raise ApiError(400, "too_many_files", max=settings.MAX_FILES)
    folder = settings.MEDIA_DIR / str(c.id)
    written: list[Path] = []
    saved = 0
    try:
        for f in files:
            first = await f.read(1024 * 1024)
            mime = _sniff(first[:16])
            if mime is None:
                raise ApiError(400, "file_type_refused", name=f.filename)
            kind, ext = MEDIA_TYPES[mime]
            limit_mb = settings.MAX_PHOTO_MB if kind == "photo" else settings.MAX_VIDEO_MB
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{uuid.uuid4().hex}{ext}"
            written.append(path)
            # Stream to disk in 1 MB pieces: a 100 MB video never sits in memory.
            size = 0
            with path.open("wb") as fh:
                chunk = first
                while chunk:
                    size += len(chunk)
                    if size > limit_mb * 1024 * 1024:
                        raise ApiError(413, "file_too_large", name=f.filename, max=limit_mb, kind=kind)
                    fh.write(chunk)
                    chunk = await f.read(1024 * 1024)
            exif_lat, exif_lng = _exif_gps(path) if kind == "photo" else (None, None)
            db.add(
                models.Media(
                    complaint_id=c.id, kind=kind, file_path=str(path), mime=mime, size_bytes=size,
                    exif_lat=exif_lat, exif_lng=exif_lng, captured_in_app=captured_in_app, role=role, uploaded_by=uploaded_by,
                )
            )
            saved += 1
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)
        raise
    return saved


@router.post("/complaints", status_code=202, response_model=schemas.ComplaintAccepted)
async def create_complaint(
    text: str = Form(...),
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
        raise ApiError(400, "complaint_too_short")
    if len(text) > settings.MAX_COMPLAINT_CHARS:
        raise ApiError(400, "complaint_too_long", max=settings.MAX_COMPLAINT_CHARS)
    if location_source not in ("camera_gps", "exif", "browser", "manual", "none"):
        location_source = "none"
    if (lat is None) != (lng is None):
        raise ApiError(400, "location_incomplete")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):  # written this way it also refuses NaN
        raise ApiError(400, "location_out_of_range")
    # Name and Aadhaar last 4 are taken once, at registration (or PATCH /auth/me); every complaint carries them for the office.
    if not (user.full_name and user.aadhaar_last4):
        raise ApiError(400, "profile_incomplete")

    c = models.Complaint(
        tracking_id=_tracking_id(db), user_id=user.id, raw_text=text, language_hint=language_hint,
        complainant_name=user.full_name, aadhaar_last4=user.aadhaar_last4,
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
        raise ApiError(404, "complaint_not_found")
    if user.role == "complainant" and c.user_id != user.id:
        raise ApiError(403, "not_your_complaint")
    if user.role in STAFF_ROLES and not can_access(c, user):
        raise ApiError(403, "outside_scope")
    return c


NEARBY_MAX_ITEMS = 20


@router.get("/complaints/nearby", response_model=list[schemas.NearbyItem])
def nearby(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), km: float | None = Query(None, gt=0), limit: int = 5,
           user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """Open complaints with coordinates near a point, nearest first, without any personal data. The radius is
    at most NEARBY_KM (the distance from which a citizen may support a complaint) and the list at most
    NEARBY_MAX_ITEMS long, whatever the caller asks for: never a statewide list of summaries."""
    radius = min(km or settings.NEARBY_KM, settings.NEARBY_KM)
    limit = max(1, min(limit, NEARBY_MAX_ITEMS))
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
    return out[:limit]


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
    # Tracking IDs are sequential: someone else's complaint answers exactly like a missing one, so the
    # lookup never confirms that an ID exists.
    c = db.execute(select(models.Complaint).where(models.Complaint.tracking_id == tracking_id.upper())).scalar_one_or_none()
    if c is None or not can_access(c, user):
        raise ApiError(404, "complaint_not_found")
    return complaint_detail(db, c, user)


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
        raise ApiError(404, "media_not_found")
    _load_for(db, str(m.complaint_id), user)
    # Files stored before the upload check existed may be anything: hand those out as a download only.
    safe = m.mime in SAFE_MEDIA_TYPES
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"}
    if not safe:
        headers["Content-Disposition"] = "attachment"
    return FileResponse(m.file_path, media_type=m.mime if safe else "application/octet-stream", headers=headers)


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
        raise ApiError(403, "reply_not_owner")
    if c.status in ("closed", "merged"):
        raise ApiError(409, "complaint_closed")
    text = " ".join((text or "").split())
    if len(text) < 2 and not any(f.filename for f in files or []):
        raise ApiError(400, "reply_empty")
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
        raise ApiError(403, "feedback_not_owner")
    deadline = _reopen_deadline(c)
    if deadline is None:
        raise ApiError(409, "feedback_not_resolved")
    if datetime.now(timezone.utc) > deadline:
        raise ApiError(409, "feedback_window_closed")
    note = " ".join((body.note or "").split())[:500]
    if body.reopen:
        c.reopen_count = (c.reopen_count or 0) + 1
        _set_status(db, c, "in_progress", "complainant", user.id, ("reopened: " + note) if note else "reopened: not fixed")
        notify_staff(db, c, "department", "staff_reopen", text=note or "not fixed")
        notify(db, user, "status", complaint_id=c.id, tracking_id=c.tracking_id, status=STATUS_LABEL.get(c.status, c.status),
               note="Your complaint was reopened and sent back to the department.")
    else:
        if body.rating is None:
            raise ApiError(400, "rating_required")
        c.rating, c.rating_note, c.rated_at = body.rating, note or None, datetime.now(timezone.utc)
        db.add(models.StatusEvent(complaint_id=c.id, from_status=c.status, to_status=c.status, actor_type="complainant", actor_id=user.id,
                                  note=f"rated {body.rating}/5" + (f": {note}" if note else "")))
    db.commit()
    return {"ok": True, "status": c.status, "rating": c.rating, "reopen_count": c.reopen_count}


@router.post("/complaints/{complaint_id}/support")
def support(complaint_id: str, body: schemas.SupportIn | None = None, user: models.User = Depends(current_user), db: Session = Depends(get_db)):
    """'Me too': back an existing open complaint instead of filing a duplicate. Enough supporters raise its urgency one level.
    Citizens only, and only from near the complaint: the point they send must be within NEARBY_KM of it, as in the nearby list."""
    if user.role != "complainant":
        raise ApiError(403, "support_citizens_only")
    # Row lock until commit: simultaneous clicks queue up here, so the second sees the first's support row
    # (no unique-constraint error) and two citizens' counts never overwrite each other.
    c = db.get(models.Complaint, as_uuid(complaint_id), with_for_update=True)
    if c is None:
        raise ApiError(404, "complaint_not_found")
    if c.user_id == user.id:
        raise ApiError(400, "support_own_complaint")
    if c.status not in OPEN_FOR_SUPPORT:
        raise ApiError(409, "complaint_not_open")
    if body is None:
        raise ApiError(400, "support_location_required")
    if c.lat is None or c.lng is None or _haversine_km(body.lat, body.lng, c.lat, c.lng) > settings.NEARBY_KM:
        raise ApiError(403, "support_too_far", km=settings.NEARBY_KM)
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
