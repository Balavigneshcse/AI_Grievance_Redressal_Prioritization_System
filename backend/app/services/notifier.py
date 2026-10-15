"""Email notifications in the complainant's language through SMTP (Mailpit in dev).
Every send is logged in the notifications table, sent or failed."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from ..config import settings
from .. import models

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
}


def _send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
        s.ehlo()
        # Upgrade to TLS when asked and the server offers it (Gmail does, Mailpit does not).
        if settings.SMTP_TLS and s.has_extn("STARTTLS"):
            s.starttls()
            s.ehlo()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        s.send_message(msg)


def notify(db: Session, user: models.User, template: str, complaint_id=None, **kw) -> None:
    lang = user.preferred_language if user.preferred_language in ("en", "ta", "hi") else "en"
    subject_t, body_t = TEMPLATES[template][lang]
    kw.setdefault("note", "")
    subject, body = subject_t.format(**kw), body_t.format(**kw)
    status = "sent"
    try:
        _send(user.email, subject, body)
    except Exception as exc:  # never let email failure break the request
        status = "failed"
        body = body + f"\n\n[send failed: {exc}]"
    db.add(
        models.Notification(
            user_id=user.id, complaint_id=complaint_id, channel="email", template=template,
            language=lang, subject=subject, body=body, status=status,
        )
    )
