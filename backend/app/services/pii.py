"""PII masking for Indian identifiers. Deterministic, auditable, no model.
Returns the masked text and a map from placeholder to the original value;
the map is stored with officer-only visibility."""
from __future__ import annotations

import re

PATTERNS = [
    # Not right after a "+": "+919876543210" is a phone with its country code, not twelve Aadhaar digits.
    ("AADHAAR", re.compile(r"(?<!\+)\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Ten digits from 6-9, with a space or dash anywhere ("98765 43210", "98765-43210", "9876 543 210"),
    # after +91, 0091, "91 " or 0 or nothing.
    ("PHONE", re.compile(r"(?<!\d)(?:(?:\+|00)91[\s-]?|91[\s-]|0)?[6-9](?:[\s-]?\d){9}(?!\d)")),
    # Six-digit PIN code ("641012", "641 012"); runs last, once the longer numbers are masked.
    ("PIN", re.compile(r"(?<!\d)[1-9]\d{2}\s?\d{3}(?!\d)")),
]


def mask_pii(text: str) -> tuple[str, dict[str, str]]:
    pii: dict[str, str] = {}
    masked = text
    for label, pat in PATTERNS:
        n = 0
        def repl(m: re.Match) -> str:
            nonlocal n
            n += 1
            key = f"[{label}_{n}]"
            pii[key] = m.group(0)
            return key
        masked = pat.sub(repl, masked)
    return masked, pii
