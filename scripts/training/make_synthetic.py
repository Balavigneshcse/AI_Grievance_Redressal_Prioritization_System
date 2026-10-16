"""Generate a labelled synthetic complaint set with the local LLM (Gemma 3 via
Ollama). Covers every department x urgency x language combination.

Resumable: rerun and it skips combinations already in the output file.

Run:  python scripts/training/make_synthetic.py                 (3 per combo = 480 complaints)
      python scripts/training/make_synthetic.py --per-combo 2   (faster first pass)
      python scripts/training/make_synthetic.py --langs en,ta-en (subset of languages)
"""
from __future__ import annotations

import argparse
import json
import time
import uuid

import ollama

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # scripts/, home of the shared common.py
from common import DATA, DEFAULT_LLM, LANGUAGES, append_jsonl, detect_language, load_taxonomy, load_urgency, read_jsonl

OUT = DATA / "synthetic" / "complaints.jsonl"

# Script the generated text must be in for each language code. The LLM sometimes
# ignores the language instruction (about 7% of rows in the first run), so rows
# in the wrong script are dropped and the combo is retried on the next run.
EXPECTED_SCRIPT = {"ta": "ta", "hi": "hi", "en": "latin", "ta-en": "latin", "hi-en": "latin"}


def script_ok(text: str, language: str) -> bool:
    return detect_language(text)[0] == EXPECTED_SCRIPT[language]

SCHEMA = {
    "type": "object",
    "properties": {
        "complaints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "formality": {"type": "string", "enum": ["formal", "informal"]},
                    "evidence_phrase": {"type": "string"},
                    "location_hint": {"type": "string"},
                },
                "required": ["text", "formality", "evidence_phrase", "location_hint"],
            },
        }
    },
    "required": ["complaints"],
}

SYSTEM = (
    "You write realistic citizen complaints for a municipal grievance portal in Tamil Nadu, India. "
    "You output JSON only."
)


SCRIPT_RULE = {
    "ta": "Write ONLY in Tamil script (தமிழ் எழுத்துகள்). Do not use English letters except for a place name. Example start: 'எங்கள் தெருவில் ...'",
    "hi": "Write ONLY in Devanagari script (हिंदी अक्षर). Do not write Hindi in English letters and do not use Urdu or Tamil script. Example start: 'हमारे इलाके में ...'",
    "en": "Write in English only.",
    "ta-en": "Write Tamil words in English letters (Tanglish), mixed with English. No Tamil script.",
    "hi-en": "Write Hindi words in English letters (Hinglish), mixed with English. No Devanagari script.",
}


def build_prompt(n: int, dept: dict, urg: dict, lang_desc: str, lang: str = "en") -> str:
    return f"""Write {n} different citizen complaints.

Department the complaint belongs to: {dept['name']}. Typical issues: {"; ".join(dept['examples'])}.
Urgency level: {urg['name']}. Meaning: {urg['criteria'].strip()}
Language: {lang_desc}
Script rule: {SCRIPT_RULE.get(lang, "")}

Requirements:
- Each complaint is 2 to 5 sentences, 20 to 80 words, written by a different person.
- Make the first one formal and the rest informal (lowercase, typos, missing punctuation, chat style).
- Mention a street, area, landmark or ward in Tamil Nadu (vary them).
- Do NOT name the department and do NOT use the words critical, high, medium or low.
- The urgency must be clear from the content only. For higher urgency, sometimes bury the key detail in the middle of the text.
- evidence_phrase: the exact phrase from the text that shows the urgency.
- location_hint: the place mentioned.
Return JSON with a "complaints" array."""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_LLM)
    ap.add_argument("--per-combo", type=int, default=3)
    ap.add_argument("--langs", default="all", help="comma list of codes, e.g. en,ta,hi,ta-en,hi-en")
    ap.add_argument("--depts", default="all")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    langs = list(LANGUAGES) if args.langs == "all" else args.langs.split(",")
    depts = load_taxonomy()
    if args.depts != "all":
        keep = set(args.depts.split(","))
        depts = [d for d in depts if d["id"] in keep]
    urgencies = load_urgency()["levels"]

    done = {r["combo"] for r in read_jsonl(args.out)}
    combos = [(d, u, l) for d in depts for u in urgencies for l in langs]
    todo = [c for c in combos if f"{c[0]['id']}|{c[1]['id']}|{c[2]}" not in done]
    print(f"{len(combos)} combos, {len(todo)} to do, {args.per_combo} complaints each -> ~{len(todo)*args.per_combo} new rows")
    print(f"model {args.model}, output {args.out}\n")

    t_start = time.time()
    for i, (d, u, l) in enumerate(todo, 1):
        key = f"{d['id']}|{u['id']}|{l}"
        t0 = time.time()
        items = None
        # One retry at a lower temperature: Ollama aborts a call when the model
        # starts repeating itself ("token repeat limit"), and a second sample
        # usually succeeds.
        for attempt, temperature in enumerate((0.9, 0.6), 1):
            try:
                resp = ollama.chat(
                    model=args.model,
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": build_prompt(args.per_combo, d, u, LANGUAGES[l], l)},
                    ],
                    format=SCHEMA,
                    options={"temperature": temperature, "num_ctx": 2048, "num_predict": 900, "repeat_penalty": 1.15},
                )
                items = json.loads(resp.message.content)["complaints"]
                break
            except Exception as exc:
                if attempt == 2:
                    print(f"[{i}/{len(todo)}] {key} FAILED twice: {str(exc)[:80]}")
        if items is None:
            continue

        rows = []
        dropped = 0
        for it in items[: args.per_combo]:
            text = (it.get("text") or "").strip()
            if len(text) < 15:
                continue
            if not script_ok(text, l):
                dropped += 1
                continue
            rows.append(
                {
                    "id": f"syn-{uuid.uuid4().hex[:10]}",
                    "text": text,
                    "language": l,
                    "department": d["id"],
                    "urgency": u["id"],
                    "formality": it.get("formality", "informal"),
                    "evidence_phrase": it.get("evidence_phrase", ""),
                    "location_hint": it.get("location_hint", ""),
                    "source": f"synthetic-{args.model}",
                    "combo": key,
                }
            )
        append_jsonl(args.out, rows)
        dt = time.time() - t0
        elapsed = time.time() - t_start
        eta = elapsed / i * (len(todo) - i)
        note = f", {dropped} dropped (wrong script)" if dropped else ""
        print(f"[{i}/{len(todo)}] {key}: {len(rows)} rows in {dt:4.1f}s{note}  (ETA {eta/60:4.1f} min)")

    total = len(read_jsonl(args.out))
    print(f"\nDone. {total} rows in {args.out}")


if __name__ == "__main__":
    main()
