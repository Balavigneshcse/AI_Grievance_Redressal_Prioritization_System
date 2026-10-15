"""Download every model SYNAPSE needs. Both go through Ollama, both run locally.

1. Gemma 3 4B  (text + vision, the GPU model)     ~3.3 GB   ollama tag gemma3:4b
2. bge-m3      (multilingual embeddings)          ~1.2 GB   ollama tag bge-m3

Then it smoke-tests embeddings, the language hint and the offline geocoder.

Run:  python scripts/download_models.py
"""
from __future__ import annotations

import sys
import time

import ollama

from common import DEFAULT_LLM, EMBED_MODEL, detect_language, embed, nearest_place


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def ensure(model: str) -> None:
    try:
        present = [m.model for m in ollama.list().models]
    except Exception as exc:
        print("Ollama is not reachable:", exc)
        print("Start the Ollama app, then rerun this script.")
        sys.exit(1)
    if any(name == model or name.startswith(model + ":") for name in present):
        print("already present:", model)
        return
    print("pulling", model)
    last = -1
    for chunk in ollama.pull(model, stream=True):
        total = getattr(chunk, "total", None)
        done = getattr(chunk, "completed", None)
        status = getattr(chunk, "status", "")
        if total and done:
            pct = int(done * 100 / total)
            if pct != last:
                print(f"\r{status} {pct:3d}%", end="", flush=True)
                last = pct
    print("\npulled", model)


step(f"1/2 LLM {DEFAULT_LLM} (text + vision)")
ensure(DEFAULT_LLM)

step(f"2/2 Embedding model {EMBED_MODEL}")
ensure(EMBED_MODEL)

step("Checks")
t0 = time.time()
vec = embed(["thanni 3 days ah varala", "no water supply for three days", "property tax is too high"], gpu=False)
print(f"embeddings on CPU: {vec.shape[1]}-dim, {time.time()-t0:.1f}s for 3 texts")
print(f"  cosine(tanglish water, english water) = {float(vec[0] @ vec[1]):.3f}")
print(f"  cosine(tanglish water, property tax)  = {float(vec[0] @ vec[2]):.3f}")
print("language hint Tamil script :", detect_language("தண்ணீர் மூன்று நாளாக வரவில்லை"))
print("language hint Devanagari   :", detect_language("तीन दिन से पानी नहीं आ रहा"))
print("language hint Tanglish     :", detect_language("thanni 3 days ah varala"), "(latin = LLM decides)")
print("offline geocoder           :", nearest_place(11.0183, 76.9674))
print("\nAll models ready.")
