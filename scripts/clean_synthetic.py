"""Remove synthetic rows whose text is not in the script their language label
promises (the LLM occasionally answers in the wrong language), and exact
duplicate texts. Keeps a backup next to the file.

Run:  python scripts/clean_synthetic.py
      python scripts/clean_synthetic.py --file data/synthetic/complaints.jsonl
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from common import DATA, detect_language

EXPECTED_SCRIPT = {"ta": "ta", "hi": "hi", "en": "latin", "ta-en": "latin", "hi-en": "latin"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DATA / "synthetic" / "complaints.jsonl"))
    args = ap.parse_args()
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"{path} not found")

    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    before = Counter(r["language"] for r in rows)

    keep, seen, dropped = [], set(), Counter()
    for r in rows:
        lang = r.get("language", "")
        if lang not in EXPECTED_SCRIPT or detect_language(r["text"])[0] != EXPECTED_SCRIPT[lang]:
            dropped[f"{lang}: wrong script"] += 1
            continue
        key = r["text"].strip().lower()
        if key in seen:
            dropped[f"{lang}: duplicate"] += 1
            continue
        seen.add(key)
        keep.append(r)

    backup = path.with_suffix(".jsonl.bak")
    shutil.copy(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    after = Counter(r["language"] for r in keep)
    print(f"before: {len(rows)} rows {dict(before)}")
    print(f"after : {len(keep)} rows {dict(after)}")
    print(f"dropped: {dict(dropped) or 'none'}")
    print(f"backup at {backup}")
    print("Dropped combos are regenerated automatically on the next make_synthetic.py run.")


if __name__ == "__main__":
    main()
