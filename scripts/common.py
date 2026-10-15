"""Shared helpers for the SYNAPSE scripts: paths, config loading, prompt building,
embeddings (bge-m3 through Ollama), language hints and offline geocoding.

Everything runs locally. The Python side is pure Python plus NumPy, pandas and
Pillow: Windows Application Control on the build laptop blocks unsigned native
DLLs (torch, scipy), so every model is served by Ollama instead."""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
MODELS = ROOT / "models"
PROMPTS = ROOT / "prompts"

DEFAULT_LLM = os.environ.get("SYNAPSE_LLM", "gemma3:4b")
EMBED_MODEL = os.environ.get("SYNAPSE_EMBED", "bge-m3")

# Language codes used across the project. The description is what the
# synthetic generator tells the LLM to write in.
LANGUAGES = {
    "en": "English",
    "ta": "Tamil, written in Tamil script",
    "hi": "Hindi, written in Devanagari script",
    "ta-en": "Tanglish: Tamil words typed in English letters, mixed with English words, the way people type on WhatsApp",
    "hi-en": "Hinglish: Hindi words typed in English letters, mixed with English words",
}


# ---------------------------------------------------------------- config ---
def load_yaml(name: str) -> dict:
    with open(CONFIG / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_taxonomy() -> list[dict]:
    return load_yaml("taxonomy.yaml")["departments"]


def load_urgency() -> dict:
    return load_yaml("urgency.yaml")


def load_schema() -> dict:
    with open(CONFIG / "analysis_schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


def department_ids() -> list[str]:
    return [d["id"] for d in load_taxonomy()]


def urgency_ids() -> list[str]:
    return [u["id"] for u in load_urgency()["levels"]]


def taxonomy_text() -> str:
    return "\n".join(f"- {d['id']} ({d['name']}): " + "; ".join(d["examples"]) for d in load_taxonomy())


def urgency_text() -> str:
    return "\n".join(f"- {u['id']} ({u['name']}): {u['criteria'].strip()}" for u in load_urgency()["levels"])


def analysis_system_prompt() -> str:
    template = (PROMPTS / "analysis_system.txt").read_text(encoding="utf-8")
    return (
        template.replace("{taxonomy}", taxonomy_text())
        .replace("{urgency}", urgency_text())
        .replace("{not_signals}", load_urgency()["not_signals"].strip())
    )


# ----------------------------------------------------------------- jsonl ---
def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------ embeddings ---
def embed(texts: list[str], batch_size: int = 16, gpu: bool = False, progress: bool = False) -> np.ndarray:
    """bge-m3 served by Ollama. gpu=False passes num_gpu=0 so the embedding model
    runs on CPU and Gemma keeps the 4 GB card; use gpu=True for offline training.
    Returns L2-normalised float32 vectors (1024-dim)."""
    import ollama

    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = ollama.embed(model=EMBED_MODEL, input=chunk, options={"num_gpu": -1 if gpu else 0})
        out.extend(resp.embeddings)
        if progress:
            print(f"\r  embedded {min(i + batch_size, len(texts))}/{len(texts)}", end="", flush=True)
    if progress:
        print()
    X = np.asarray(out, dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    return X


# ------------------------------------------------------ language detect ---
def detect_language(text: str) -> tuple[str, float]:
    """Script-based hint, pure Python. Tamil script -> ta, Devanagari -> hi,
    Latin letters -> 'latin' (English or romanised Tamil/Hindi; the LLM decides)."""
    tamil = sum("஀" <= c <= "௿" for c in text)
    deva = sum("ऀ" <= c <= "ॿ" for c in text)
    latin = sum(c.isascii() and c.isalpha() for c in text)
    total = tamil + deva + latin
    if total == 0:
        return "unknown", 0.0
    if tamil / total >= 0.3:
        return "ta", round(tamil / total, 2)
    if deva / total >= 0.3:
        return "hi", round(deva / total, 2)
    return "latin", round(latin / total, 2)


# ---------------------------------------------------------- geocoding ---
_places: list[dict] | None = None


def _load_places() -> list[dict]:
    global _places
    if _places is None:
        with open(CONFIG / "places_tn.csv", "r", encoding="utf-8") as f:
            _places = [{**r, "lat": float(r["lat"]), "lng": float(r["lng"])} for r in csv.DictReader(f)]
    return _places


def nearest_place(lat: float, lng: float) -> dict:
    """Offline reverse geocoding: nearest known locality by haversine distance."""
    places = _load_places()
    lat1, lng1 = math.radians(lat), math.radians(lng)
    best, best_km = None, float("inf")
    for p in places:
        lat2, lng2 = math.radians(p["lat"]), math.radians(p["lng"])
        a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
        km = 2 * 6371 * math.asin(math.sqrt(a))
        if km < best_km:
            best, best_km = p, km
    return {"name": best["name"], "area": best["area"], "distance_km": round(best_km, 2)}


# ------------------------------------------ district / office routing (TN) ---
_tn: dict | None = None

URGENCY_SLA_FACTOR = {"critical": 0.25, "high": 0.5, "medium": 1.0, "low": 3.0}


def load_tn_mapping() -> dict:
    """config/tn_mapping.json produced by scripts/import_tn_mapping.py from the
    Tamil Nadu district / department spreadsheet. Empty dict if absent."""
    global _tn
    if _tn is None:
        p = CONFIG / "tn_mapping.json"
        _tn = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _tn


def district_for(text: str | None) -> str | None:
    """District name if the text (a locality area or a manual address) mentions one."""
    if not text:
        return None
    low = text.lower()
    for d in load_tn_mapping().get("districts", []):
        if d["name"].lower() in low:
            return d["name"]
    return None


def office_hint(text: str) -> dict | None:
    """First spreadsheet keyword rule that matches the complaint text -> {department_id, priority, rule_id}."""
    low = (text or "").lower()
    for r in load_tn_mapping().get("keyword_rules", []):
        if r["keyword"] and r["keyword"] in low:
            return {"department_id": r["department_id"], "priority": r["priority"], "rule_id": r["id"]}
    return None


def category_of_department(department_id: str | None) -> str | None:
    """SYNAPSE category that a spreadsheet department (DEP01..DEP20) maps to."""
    for d in load_tn_mapping().get("departments", []):
        if d["id"] == department_id:
            return d["category"]
    return None


def office_for(district: str | None, category: str, hint_department_id: str | None = None) -> dict | None:
    """The district office for a complaint: the hinted spreadsheet department if it
    belongs to the same category, else the category's default department."""
    m = load_tn_mapping()
    if not m or not district or district not in m.get("offices", {}):
        return None
    cat_of = {d["id"]: d["category"] for d in m["departments"]}
    name_of = {d["id"]: d["name"] for d in m["departments"]}
    dep = hint_department_id if (hint_department_id and cat_of.get(hint_department_id) == category) else m["category_default_department"].get(category)
    office = m["offices"][district].get(dep)
    if not office:
        return None
    return {"district": district, "department_id": dep, "department_name": name_of.get(dep, dep), **office}


# ------------------------------------------------- numpy softmax classifier ---
class SoftmaxRegression:
    """Multinomial logistic regression in NumPy (no scikit-learn, no scipy).
    Balanced class weights, L2 penalty, full-batch gradient descent."""

    def __init__(self, lr: float = 1.0, epochs: int = 400, l2: float = 1e-3):
        self.lr, self.epochs, self.l2 = lr, epochs, l2
        self.W: np.ndarray | None = None
        self.b: np.ndarray | None = None
        self.labels: list[str] = []

    def fit(self, X: np.ndarray, y: list[str], labels: list[str]) -> "SoftmaxRegression":
        self.labels = list(labels)
        idx = {l: i for i, l in enumerate(self.labels)}
        yi = np.array([idx[v] for v in y])
        n, d, k = X.shape[0], X.shape[1], len(self.labels)
        Y = np.zeros((n, k), dtype=np.float32)
        Y[np.arange(n), yi] = 1.0
        counts = np.bincount(yi, minlength=k).astype(np.float32)
        w = (n / (k * np.maximum(counts, 1)))[yi][:, None]  # balanced sample weights
        self.W = np.zeros((d, k), dtype=np.float32)
        self.b = np.zeros(k, dtype=np.float32)
        for _ in range(self.epochs):
            P = self._softmax(X @ self.W + self.b)
            G = (P - Y) * w / n
            self.W -= self.lr * (X.T @ G + self.l2 * self.W)
            self.b -= self.lr * G.sum(axis=0)
        return self

    @staticmethod
    def _softmax(z: np.ndarray) -> np.ndarray:
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._softmax(X @ self.W + self.b)

    def predict(self, X: np.ndarray) -> list[str]:
        return [self.labels[i] for i in self.predict_proba(X).argmax(axis=1)]

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, W=self.W, b=self.b, labels=np.array(self.labels))

    @classmethod
    def load(cls, path: Path) -> "SoftmaxRegression":
        z = np.load(path, allow_pickle=False)
        m = cls()
        m.W, m.b, m.labels = z["W"], z["b"], [str(l) for l in z["labels"]]
        return m
