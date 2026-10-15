"""Send one test email with the SMTP settings in .env, to confirm real delivery
(for example a Gmail App Password) works before the demo.

Run from the project root:  python scripts/test_email.py you@example.com
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/test_email.py recipient@example.com")
    to = sys.argv[1]
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "1025"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user or "grievance@synapse.local")
    tls = os.getenv("SMTP_TLS", "false").strip().lower() in ("1", "true", "yes", "on")

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to, "Vindex test email"
    msg.set_content("If you can read this, the grievance portal can send email through " + host + ".")

    print(f"connecting to {host}:{port} tls={tls} user={'set' if user else 'none'}")
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.ehlo()
        if tls and s.has_extn("STARTTLS"):
            s.starttls()
            s.ehlo()
        elif tls:
            print("note: server does not offer STARTTLS, continuing without it")
        if user:
            s.login(user, password)
        s.send_message(msg)
    print("sent to", to)
    if host == "localhost":
        print("Mailpit mode: open http://localhost:8025 to see it")


if __name__ == "__main__":
    main()
