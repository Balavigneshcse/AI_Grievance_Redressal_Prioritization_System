"""Email notifications in the complainant's language through SMTP.

A send never runs inside a request or inside the analysis worker: notify() only
writes a 'queued' row to the notifications table and wakes the outbox thread,
which delivers the queue through one persistent SMTP connection (Gmail or the
local Mailpit). Every row ends as sent, or failed with the reason appended."""
from __future__ import annotations

import logging
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from .. import models

log = logging.getLogger("synapse.mail")

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
    n = models.Notification(
        user_id=user.id, complaint_id=complaint_id, channel="email", template=template,
        language=lang, subject=subject, body=body, status="queued",
    )
    db.add(n)
    _wake.set()
    return n


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
        for n in rows:
            user = db.get(models.User, n.user_id)
            if user is None:
                n.status = "failed"
                db.commit()
                continue
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
