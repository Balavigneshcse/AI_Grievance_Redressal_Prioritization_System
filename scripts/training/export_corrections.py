"""Export the labels officers have confirmed as training rows for the second-opinion classifier.

A complaint counts as confirmed once an officer accepted its routing or reassigned it (an `overrides`
row with action accept or reassign). Each confirmed complaint becomes one row in the format of
data/synthetic/*.jsonl:

  text        the complaint as the citizen wrote it, in their language (raw_text), with phone numbers,
              emails, Aadhaar, PAN and PIN codes masked by the pipeline's own mask_pii
  department  to_department and urgency to_urgency of the latest accept or reassign
  urgency
  language    Tamil script -> ta, Devanagari -> hi; for English letters the language of the latest
              analysis in the training codes (Tamil or Hindi typed in English letters becomes ta-en /
              hi-en); without an analysis, the complaint's script hint
  source      "officer"; also action, group (the original complaint, so a merged duplicate is held out
              with it), confirmed_at, model_department / second_opinion (what the system said), and
              pipeline_text: what the pipeline embeds for the second opinion at runtime (English summary +
              resolved place), so the trainer can score the input the live model really sees

De-duplication: one row per complaint (its latest accept or reassign wins) and one row per text (the
same words filed twice keep the later decision). Guard: with fewer than --min-rows rows nothing is
written, since a handful of labels weighted above the synthetic set would only teach the classifier
those few complaints.

The database is opened read-only. DATABASE_URL is read from the environment first, then .env, as
tests/test_api_e2e.py does.

Run:  python scripts/training/export_corrections.py
      python scripts/training/export_corrections.py --out data/corrections/officer_labels.jsonl --min-rows 30
Then: python scripts/training/train_second_opinion.py --corrections
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))  # home of the shared common.py
sys.path.insert(0, str(ROOT / "backend"))  # app.services.pii, the masker the pipeline uses
from common import DATA, LANGUAGES, department_ids, detect_language, urgency_ids
from app.services.pii import mask_pii

OUT = DATA / "corrections" / "officer_labels.jsonl"
HINT_LANGUAGE = {"ta": "ta", "hi": "hi", "latin-ta": "ta-en", "latin-hi": "hi-en", "latin-en": "en"}

QUERY = """
WITH confirmed AS (
    SELECT DISTINCT ON (complaint_id) complaint_id, action, to_department, to_urgency, created_at
    FROM overrides
    WHERE action IN ('accept', 'reassign')
    ORDER BY complaint_id, created_at DESC
), latest AS (
    SELECT DISTINCT ON (complaint_id) complaint_id, language_primary, department_id, urgency, second_opinion_department, summary_en
    FROM analyses
    ORDER BY complaint_id, created_at DESC
)
SELECT c.id, c.raw_text, c.language_hint, c.duplicate_of, c.resolved_place, f.action, f.to_department, f.to_urgency, f.created_at,
       a.language_primary, a.department_id, a.urgency, a.second_opinion_department, a.summary_en
FROM confirmed f
JOIN complaints c ON c.id = f.complaint_id
LEFT JOIN latest a ON a.complaint_id = c.id
ORDER BY f.created_at
"""


def env(key: str, default: str = "") -> str:
    # A variable set in the environment wins over .env, so an export aimed at a test copy never reads the demo database.
    if key in os.environ:
        return os.environ[key]
    dotenv = ROOT / ".env"
    for line in dotenv.read_text(encoding="utf-8").splitlines() if dotenv.exists() else []:
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return default


def training_language(primary: str | None, text: str, hint: str | None) -> str:
    """Tamil or Devanagari script decides by itself: the model has called Hindi in Devanagari "ta" (10 of 22
    on the 16 Oct test run). For English letters the analysis decides; it records Tanglish as primary ta
    (secondary en) and Hinglish as hi, which the training rows call ta-en and hi-en."""
    script = detect_language(text)[0]
    if script in ("ta", "hi"):
        return script
    p = (primary or "").strip().lower()
    if p in ("ta", "hi"):
        return p + "-en"
    if p in LANGUAGES:
        return p
    return HINT_LANGUAGE.get(hint or "", "unknown")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT, help=f"JSONL to write (default {OUT.relative_to(ROOT)})")
    ap.add_argument("--min-rows", type=int, default=30, help="write nothing below this many confirmed complaints (default 30)")
    args = ap.parse_args()

    import psycopg

    url = env("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/synapse").replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, options="-c default_transaction_read_only=on") as conn:
        found = conn.execute(QUERY).fetchall()
    print(f"database {url.rsplit('/', 1)[-1]}: {len(found)} complaints with an accept or reassign")

    departments, urgencies = set(department_ids()), set(urgency_ids())
    by_text: dict[str, dict] = {}
    unknown_dept, language_from = 0, {}
    for cid, raw, hint, dup_of, place, action, dept, urg, at, lang, model_dept, model_urg, second, summary in found:
        if dept not in departments:
            unknown_dept += 1
            continue
        text = mask_pii((raw or "").strip())[0]
        # What the pipeline embeds for duplicates and the second opinion (pipeline.py step 5): summary + place
        pipeline_text = (summary or text) + (f" | {place}" if place else "")
        language = training_language(lang, text, hint)
        if not lang:
            language_from[f"officer-{cid}"] = "hint"
        elif language in ("ta", "hi") and language != lang:
            language_from[f"officer-{cid}"] = "script"
        row = {
            "id": f"officer-{cid}", "text": text, "language": language, "department": dept,
            "urgency": urg if urg in urgencies else None, "source": "officer", "action": action,
            "group": f"officer-{dup_of or cid}", "confirmed_at": at.isoformat(),
            "model_department": model_dept, "model_urgency": model_urg, "second_opinion": second, "pipeline_text": pipeline_text,
        }
        by_text[" ".join(text.lower().split())] = row  # ordered by decision time, so a repeated text keeps the later one
    rows = list(by_text.values())

    repeated = len(found) - unknown_dept - len(rows)
    print(f"rows: {len(rows)} (one per complaint and per text; {repeated} repeated texts and {unknown_dept} unknown departments dropped)")
    if rows:
        print("  department:", dict(Counter(r["department"] for r in rows).most_common()))
        print("  urgency:   ", dict(Counter(r["urgency"] or "-" for r in rows).most_common()))
        source = Counter(language_from.get(r["id"], "analysis") for r in rows)
        print("  language:  ", dict(Counter(r["language"] for r in rows).most_common()),
              f"({source['script']} set by the script against the analysis, {source['hint']} from the script hint without an analysis)")
        print("  action:    ", dict(Counter(r["action"] for r in rows).most_common()))
        for field, name in (("model_department", "model (Gemma)"), ("second_opinion", "second opinion")):
            seen = [r for r in rows if r[field]]
            if seen:
                agree = sum(r[field] == r["department"] for r in seen) / len(seen)
                print(f"  {name} department agreed with the officers on {agree:.3f} of {len(seen)}")
    if len(rows) < args.min_rows:
        kept = f" The earlier export in {args.out} is left as it was." if args.out.exists() else ""
        raise SystemExit(f"Only {len(rows)} confirmed complaints, fewer than --min-rows {args.min_rows}: nothing written.{kept}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(args.out)  # whole snapshot each run, never a half-written file
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
