"""Send one complaint (and optionally a photo) through the real analysis prompt
and JSON schema on the local LLM. Prints the structured result and the time taken.

Run:  python scripts/evaluation/smoke_test_llm.py
      python scripts/evaluation/smoke_test_llm.py --text "road la periya kuzhi, bike skid aagudhu, Gandhipuram"
      python scripts/evaluation/smoke_test_llm.py --image photo.jpg --text "see this"
"""
from __future__ import annotations

import argparse
import json
import time

import ollama

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # scripts/, home of the shared common.py
from common import DEFAULT_LLM, analysis_system_prompt, complaint_user_message, detect_language, language_hint_code, load_schema

DEFAULT_TEXT = (
    "thanni 3 days ah varala sir. veetla 2 kids irukanga, rendu perum vomiting and fever. "
    "Anna Nagar 4th street, near the bus stop. corporation ku already call pannen, no response. please do something fast"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_LLM)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--image", default=None, help="path to a jpg/png")
    ap.add_argument("--num-ctx", type=int, default=2048, help="context window; 2048 fits the prompt and keeps more layers on the GPU")
    args = ap.parse_args()

    hint = language_hint_code(args.text)
    print("language hint:", detect_language(args.text), "->", hint)
    user = {"role": "user", "content": complaint_user_message(args.text, hint, has_photo=bool(args.image))}
    if args.image:
        user["images"] = [args.image]

    t0 = time.time()
    resp = ollama.chat(
        model=args.model,
        messages=[{"role": "system", "content": analysis_system_prompt()}, user],
        format=load_schema(),
        options={"temperature": 0, "num_ctx": args.num_ctx, "num_predict": 400},
    )
    dt = time.time() - t0
    result = json.loads(resp.message.content)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    gen = getattr(resp, "eval_count", 0) or 0
    gen_s = (getattr(resp, "eval_duration", 0) or 0) / 1e9
    load_s = (getattr(resp, "load_duration", 0) or 0) / 1e9
    print(f"\n{args.model}: {dt:.1f}s total (load {load_s:.1f}s), {gen} output tokens at {gen / gen_s if gen_s else 0:.1f} tok/s")


if __name__ == "__main__":
    main()
