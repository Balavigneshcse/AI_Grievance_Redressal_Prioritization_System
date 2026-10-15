"""Officer notes are written in English; the citizen's status mail is in Tamil or Hindi.
The outbox thread translates the note with the local model before sending, keeping
tracking IDs, numbers and names unchanged. Falls back to English on any failure."""
from __future__ import annotations

import logging
import re

from ..config import settings

log = logging.getLogger("synapse.translate")
LANG = {"ta": ("Tamil", re.compile(r"[஀-௿]")), "hi": ("Hindi", re.compile(r"[ऀ-ॿ]"))}
_cache: dict[tuple[str, str], str] = {}


def translate(text: str, lang: str) -> str | None:
    """Translation in the target script, or None when the language is English/unknown,
    the model is unavailable, or the answer is not in the expected script."""
    text = (text or "").strip()
    if lang not in LANG or len(text) < 2:
        return None
    key = (text, lang)
    if key in _cache:
        return _cache[key]
    name, script = LANG[lang]
    try:
        import ollama

        client = ollama.Client(host=settings.OLLAMA_HOST, timeout=45)
        resp = client.chat(
            model=settings.LLM,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate the message from a municipal grievance office to a citizen into {name}, in {name} script. "
                        "Keep tracking IDs, numbers, dates, names and addresses exactly as they are. Reply with the translation only."
                    ),
                },
                {"role": "user", "content": text},
            ],
            options={"temperature": 0, "num_ctx": 1024, "num_predict": 220},
            keep_alive=settings.LLM_KEEP_ALIVE,
        )
        out = (resp.message.content or "").strip().strip('"').strip()
        if not out or not script.search(out):
            log.info("translation to %s rejected (wrong script or empty)", lang)
            return None
        _cache[key] = out
        return out
    except Exception as exc:
        log.warning("translation to %s failed: %s", lang, exc)
        return None
