"""Email notifications in the recipient's language through SMTP.

A send never runs inside a request or inside the analysis worker: notify() only
writes a 'queued' row to the notifications table and wakes the outbox thread,
which delivers the queue through one persistent SMTP connection (Gmail or the
local Mailpit). Every row ends as sent, or failed with the reason appended.

Citizens get otp / ack / routed / under_review / status mails; staff get
staff_routed (department admins), staff_review (district admins), staff_reply
(whoever holds the case) and overdue (both) through notify_staff()."""
from __future__ import annotations

import logging
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from .. import models

log = logging.getLogger("synapse.mail")

STATUS_LABEL = {
    "routed": "sent to department", "in_progress": "in progress", "resolved": "resolved", "closed": "closed",
    "merged": "merged with an earlier complaint", "awaiting_info": "waiting for your reply", "under_review": "under review",
}

TEMPLATES = {
    "otp": {
        "en": ("Your SYNAPSE verification code", "Your one-time code is {code}. It expires in {minutes} minutes."),
        "ta": ("உங்கள் SYNAPSE சரிபார்ப்பு குறியீடு", "உங்கள் ஒருமுறை குறியீடு {code}. இது {minutes} நிமிடங்களில் காலாவதியாகும்."),
        "hi": ("आपका SYNAPSE सत्यापन कोड", "आपका एक बार का कोड {code} है। यह {minutes} मिनट में समाप्त हो जाएगा।"),
    },
    "ack": {
        "en": ("Complaint received: {tracking_id}", "We received your complaint. Tracking ID: {tracking_id}. We will update you at every step."),
        "ta": ("புகார் பெறப்பட்டது: {tracking_id}", "உங்கள் புகார் பெறப்பட்டது. கண்காணிப்பு எண்: {tracking_id}. ஒவ்வொரு படியிலும் உங்களுக்குத் தகவல் தருவோம்."),
        "hi": ("शिकायत प्राप्त हुई: {tracking_id}", "आपकी शिकायत प्राप्त हो गई है। ट्रैकिंग आईडी: {tracking_id}. हम हर कदम पर आपको सूचित करेंगे।"),
    },
    "routed": {
        "en": ("Complaint {tracking_id} sent to {department}", "Your complaint {tracking_id} has been sent to {department} with {urgency} priority."),
        "ta": ("புகார் {tracking_id} {department} துறைக்கு அனுப்பப்பட்டது", "உங்கள் புகார் {tracking_id} {department} துறைக்கு {urgency} முன்னுரிமையுடன் அனுப்பப்பட்டது."),
        "hi": ("शिकायत {tracking_id} {department} को भेजी गई", "आपकी शिकायत {tracking_id} {department} को {urgency} प्राथमिकता के साथ भेजी गई है।"),
    },
    "under_review": {
        "en": ("Complaint {tracking_id} is being reviewed", "An officer is reviewing your complaint {tracking_id} to make sure it reaches the right team quickly."),
        "ta": ("புகார் {tracking_id} ஆய்வில் உள்ளது", "உங்கள் புகார் {tracking_id} சரியான குழுவிற்கு விரைவாகச் செல்ல ஒரு அதிகாரி ஆய்வு செய்கிறார்."),
        "hi": ("शिकायत {tracking_id} की समीक्षा हो रही है", "एक अधिकारी आपकी शिकायत {tracking_id} की समीक्षा कर रहा है ताकि यह सही टीम तक जल्दी पहुँचे।"),
    },
    "status": {
        "en": ("Complaint {tracking_id}: {status}", "Update on your complaint {tracking_id}: status is now {status}. {note}"),
        "ta": ("புகார் {tracking_id}: {status}", "உங்கள் புகார் {tracking_id} நிலை: {status}. {note}"),
        "hi": ("शिकायत {tracking_id}: {status}", "आपकी शिकायत {tracking_id} की स्थिति अब {status} है। {note}"),
    },
    "account": {
        "en": (
            "Your Vindex staff account",
            "An account was created for you on the Vindex grievance portal.\nRole: {role}\nDistrict: {district}\n"
            "Department: {department}\nLogin: {url}\nYour administrator will give you the temporary password; "
            "change it with 'Forgot password' after the first login.",
        ),
        "ta": (
            "உங்கள் Vindex பணியாளர் கணக்கு",
            "Vindex குறைதீர்ப்பு தளத்தில் உங்களுக்காக ஒரு கணக்கு உருவாக்கப்பட்டது.\nபங்கு: {role}\nமாவட்டம்: {district}\n"
            "துறை: {department}\nஉள்நுழைவு: {url}\nதற்காலிக கடவுச்சொல்லை உங்கள் நிர்வாகி தருவார்; முதல் உள்நுழைவுக்குப் பிறகு "
            "'கடவுச்சொல் மறந்துவிட்டதா' மூலம் மாற்றவும்.",
        ),
        "hi": (
            "आपका Vindex स्टाफ खाता",
            "Vindex शिकायत पोर्टल पर आपके लिए एक खाता बनाया गया है।\nभूमिका: {role}\nज़िला: {district}\nविभाग: {department}\n"
            "लॉगिन: {url}\nअस्थायी पासवर्ड आपका प्रशासक देगा; पहले लॉगिन के बाद 'पासवर्ड भूल गए' से इसे बदल लें।",
        ),
    },
    # ---- staff
    "staff_routed": {
        "en": (
            "New complaint {tracking_id} for {department} ({urgency})",
            "A complaint was routed to your department.\nTracking ID: {tracking_id}\nUrgency: {urgency}\nSummary: {summary}\n"
            "Due: {due}\nOpen: {url}",
        ),
        "ta": (
            "புதிய புகார் {tracking_id}: {department} ({urgency})",
            "உங்கள் துறைக்கு ஒரு புகார் அனுப்பப்பட்டது.\nகண்காணிப்பு எண்: {tracking_id}\nஅவசரம்: {urgency}\nசுருக்கம்: {summary}\n"
            "கெடு: {due}\nதிறக்க: {url}",
        ),
        "hi": (
            "नई शिकायत {tracking_id}: {department} ({urgency})",
            "आपके विभाग को एक शिकायत भेजी गई है।\nट्रैकिंग आईडी: {tracking_id}\nप्राथमिकता: {urgency}\nसारांश: {summary}\n"
            "समय सीमा: {due}\nखोलें: {url}",
        ),
    },
    "staff_review": {
        "en": (
            "Complaint {tracking_id} needs a review decision",
            "A complaint in {district} needs a human decision.\nReasons: {reasons}\nOpen: {url}",
        ),
        "ta": (
            "புகார் {tracking_id}: ஆய்வு முடிவு தேவை",
            "{district} மாவட்டப் புகார் ஒன்றுக்கு மனித முடிவு தேவை.\nகாரணங்கள்: {reasons}\nதிறக்க: {url}",
        ),
        "hi": (
            "शिकायत {tracking_id}: समीक्षा निर्णय ज़रूरी",
            "{district} की एक शिकायत को मानवीय निर्णय चाहिए।\nकारण: {reasons}\nखोलें: {url}",
        ),
    },
    "staff_reply": {
        "en": (
            "Citizen replied on {tracking_id}",
            "The complainant added information to {tracking_id}:\n\"{text}\"\nOpen: {url}",
        ),
        "ta": (
            "{tracking_id}: குடிமகன் பதில்",
            "புகார்தாரர் {tracking_id} புகாருக்கு தகவல் சேர்த்தார்:\n\"{text}\"\nதிறக்க: {url}",
        ),
        "hi": (
            "{tracking_id}: नागरिक का उत्तर",
            "शिकायतकर्ता ने {tracking_id} में जानकारी जोड़ी:\n\"{text}\"\nखोलें: {url}",
        ),
    },
    "staff_reopen": {
        "en": ("Citizen reopened {tracking_id}", "The complainant says {tracking_id} is not fixed:\n\"{text}\"\nIt is back in your active work.\nOpen: {url}"),
        "ta": ("{tracking_id}: குடிமகன் மீண்டும் திறந்தார்", "புகார்தாரர் {tracking_id} சரிசெய்யப்படவில்லை என்கிறார்:\n\"{text}\"\nஇது மீண்டும் உங்கள் நடப்பு பணிகளில் உள்ளது.\nதிறக்க: {url}"),
        "hi": ("{tracking_id}: नागरिक ने फिर खोला", "शिकायतकर्ता का कहना है कि {tracking_id} ठीक नहीं हुआ:\n\"{text}\"\nयह फिर से आपके सक्रिय काम में है।\nखोलें: {url}"),
    },
    "overdue": {
        "en": (
            "Overdue: {tracking_id} ({department}, {urgency})",
            "Complaint {tracking_id} passed its due time ({due}) and is still '{status}'. It has been escalated to the "
            "district admin.\nOpen: {url}",
        ),
        "ta": (
            "கெடு கடந்தது: {tracking_id} ({department}, {urgency})",
            "புகார் {tracking_id} அதன் கெடுவை ({due}) கடந்தும் '{status}' நிலையில் உள்ளது. மாவட்ட நிர்வாகிக்கு "
            "அனுப்பப்பட்டது.\nதிறக்க: {url}",
        ),
        "hi": (
            "समय सीमा पार: {tracking_id} ({department}, {urgency})",
            "शिकायत {tracking_id} की समय सीमा ({due}) बीत चुकी है और यह अब भी '{status}' है। इसे ज़िला प्रशासक को "
            "भेज दिया गया है।\nखोलें: {url}",
        ),
    },
}

MAX_ATTEMPTS = 3
_wake = threading.Event()
_thread: threading.Thread | None = None
_attempts: dict[str, int] = {}
_backoff_until = 0.0


class Mailer:
    """One SMTP connection, reopened when it sat idle too long or the server dropped it."""

    IDLE_RECONNECT_S = 240

    def __init__(self) -> None:
        self.conn: smtplib.SMTP | None = None
        self.last_used = 0.0

    def connect(self) -> None:
        self.close()
        t0 = time.time()
        s = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        s.ehlo()
        # Upgrade to TLS when asked and the server offers it (Gmail does, Mailpit does not).
        if settings.SMTP_TLS and s.has_extn("STARTTLS"):
            s.starttls()
            s.ehlo()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        self.conn = s
        self.last_used = time.time()
        log.info("connected to %s:%s in %.1f s", settings.SMTP_HOST, settings.SMTP_PORT, time.time() - t0)

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:
                pass
            self.conn = None

    def send(self, msg: EmailMessage) -> None:
        if self.conn is None or time.time() - self.last_used > self.IDLE_RECONNECT_S:
            self.connect()
        try:
            self.conn.send_message(msg)
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPResponseException, OSError):
            # The server closed the idle connection: open a fresh one and retry once.
            self.connect()
            self.conn.send_message(msg)
        self.last_used = time.time()


def build_message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def notify(db: Session, user: models.User, template: str, complaint_id=None, **kw) -> models.Notification:
    """Queue an email in the user's language. Delivered by the outbox thread after the caller commits."""
    lang = user.preferred_language if user.preferred_language in ("en", "ta", "hi") else "en"
    subject_t, body_t = TEMPLATES[template][lang]
    kw.setdefault("note", "")
    subject, body = subject_t.format(**kw), body_t.format(**kw)
    # An English officer note inside a Tamil or Hindi mail is translated by the outbox before sending.
    note_en = kw.get("note") if (template == "status" and lang != "en" and settings.TRANSLATE_NOTES and kw.get("note")) else None
    n = models.Notification(
        user_id=user.id, complaint_id=complaint_id, channel="email", template=template,
        language=lang, subject=subject, body=body, status="queued", note_en=note_en,
    )
    db.add(n)
    _wake.set()
    return n


def staff_for(db: Session, c: models.Complaint, kind: str) -> list[models.User]:
    """Who holds a complaint: 'department' = active department admins of its department (in its
    district, or district-less ones); 'district' = active district admins of its district, falling
    back to the super admins when the district is unknown or has no admin yet."""
    active = models.User.is_active.is_(True)
    if kind == "department":
        if not c.department_id:
            return []
        q = select(models.User).where(active, models.User.role == "dept_admin", models.User.department_id == c.department_id)
        if c.district:
            q = q.where(or_(models.User.district == c.district, models.User.district.is_(None)))
        return list(db.execute(q).scalars().all())
    users: list[models.User] = []
    if c.district:
        users = list(db.execute(select(models.User).where(active, models.User.role == "district_admin", models.User.district == c.district)).scalars().all())
    if not users:
        users = list(db.execute(select(models.User).where(active, models.User.role == "super_admin")).scalars().all())
    return users


def notify_staff(db: Session, c: models.Complaint, kind: str, template: str, **kw) -> int:
    """Queue one staff email per holder of the complaint. Returns how many were queued."""
    kw.setdefault("url", f"{settings.APP_URL}/officer/c/{c.id}")
    kw.setdefault("tracking_id", c.tracking_id)
    users = staff_for(db, c, kind)
    for u in users:
        notify(db, u, template, complaint_id=c.id, **kw)
    return len(users)


DEMO_DOMAIN_SUFFIXES = (".local", ".test", ".invalid", ".localhost", ".example")
DEMO_DOMAINS = ("example.com", "example.org", "example.net")
LOCAL_SMTP = ("localhost", "127.0.0.1", "::1", "mailpit")


def undeliverable(email: str) -> bool:
    """True when a real mail server (not the local Mailpit) would bounce the address:
    the seeded demo accounts live on synapse.local, which does not exist."""
    if settings.SMTP_HOST.lower() in LOCAL_SMTP:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return domain.endswith(DEMO_DOMAIN_SUFFIXES) or domain in DEMO_DOMAINS


def pending() -> int:
    with SessionLocal() as db:
        return db.execute(select(func.count()).where(models.Notification.status == "queued")).scalar_one()


def _deliver_queued(mailer: Mailer) -> int:
    """Send the queued rows in order. Stops at the first failure so the order is kept
    and the next tick retries; a row is marked failed after MAX_ATTEMPTS."""
    global _backoff_until
    sent = 0
    with SessionLocal() as db:
        rows = db.execute(
            select(models.Notification).where(models.Notification.status == "queued").order_by(models.Notification.sent_at)
        ).scalars().all()
        # Mails that need a model translation go last, so staff and OTP mails are never held up by Gemma.
        rows = sorted(rows, key=lambda n: 1 if n.note_en else 0)
        for n in rows:
            user = db.get(models.User, n.user_id)
            if user is None:
                n.status = "failed"
                db.commit()
                continue
            if undeliverable(user.email):
                n.status = "skipped"
                n.body = n.body + "\n\n[not sent: demo address, the mail server would bounce it]"
                db.commit()
                log.info("email %s to %s skipped: demo address on a real mail server", n.template, user.email)
                continue
            if n.note_en and n.note_en in n.body:
                from .translate import translate

                translated = translate(n.note_en, n.language)
                if translated:
                    n.body = n.body.replace(n.note_en, translated)
                n.note_en = None
            try:
                mailer.send(build_message(user.email, n.subject, n.body))
            except Exception as exc:
                key = str(n.id)
                _attempts[key] = _attempts.get(key, 0) + 1
                log.warning("email %s to %s FAILED (attempt %d) via %s:%s: %s: %s", n.template, user.email, _attempts[key],
                            settings.SMTP_HOST, settings.SMTP_PORT, type(exc).__name__, exc)
                mailer.close()
                if _attempts[key] >= MAX_ATTEMPTS:
                    n.status = "failed"
                    n.body = n.body + f"\n\n[send failed: {exc}]"
                    _attempts.pop(key, None)
                    db.commit()
                    continue
                _backoff_until = time.time() + 5 * _attempts[key]
                db.commit()
                break
            n.status = "sent"
            n.sent_at = datetime.now(timezone.utc)
            _attempts.pop(str(n.id), None)
            db.commit()
            sent += 1
            log.info("email %s sent to %s via %s:%s", n.template, user.email, settings.SMTP_HOST, settings.SMTP_PORT)
    return sent


def _loop() -> None:
    mailer = Mailer()
    while True:
        _wake.wait(timeout=2.0)
        _wake.clear()
        if time.time() < _backoff_until:
            continue
        try:
            _deliver_queued(mailer)
        except Exception:
            log.exception("outbox loop error")
            mailer.close()
            time.sleep(2)


def start() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="synapse-outbox", daemon=True)
        _thread.start()
