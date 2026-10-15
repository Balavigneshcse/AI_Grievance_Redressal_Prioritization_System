from __future__ import annotations

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
from ..services.notifier import notify
from ..services.worker import enqueue
from .deps import as_uuid, current_user, dept_out

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
        raise HTTPException(400, "Please describe the problem in at least a few words")
    if location_source not in ("camera_gps", "exif", "browser", "manual", "none"):
        location_source = "none"

    c = models.Complaint(
        tracking_id=_tracking_id(db), user_id=user.id, raw_text=text, language_hint=language_hint,
        lat=lat, lng=lng, location_source=location_source if (lat is not None or manual_address) else "none",
        manual_address=manual_address, contact_incomplete=not (user.mobile and user.email),
    )
    db.add(c)
    db.flush()

    folder = settings.MEDIA_DIR / str(c.id)
    for f in files or []:
        if not f.filename:
            continue
        mime = f.content_type or ""
        if not (mime.startswith("image/") or mime.startswith("video/")):
            raise HTTPException(400, f"Unsupported file type {mime}")
        data = await f.read()
        if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} is larger than {settings.MAX_UPLOAD_MB} MB")
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(f.filename).suffix.lower() or (".jpg" if mime.startswith("image/") else ".mp4")
        path = folder / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(data)
        kind = "photo" if mime.startswith("image/") else "video"
        exif_lat, exif_lng = _exif_gps(path) if kind == "photo" else (None, None)
        db.add(
            models.Media(
                complaint_id=c.id, kind=kind, file_path=str(path), mime=mime, size_bytes=len(data),
                exif_lat=exif_lat, exif_lng=exif_lng, captured_in_app=(location_source == "camera_gps"),
            )
        )

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
    staff = viewer.role in ("officer", "admin")
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
        district=c.district, office_name=c.office_name, office_department_id=c.office_department_id, due_at=c.due_at,
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
