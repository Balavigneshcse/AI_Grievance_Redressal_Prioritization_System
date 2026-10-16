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
import re
import unicodedata
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
EMBED_TIMEOUT_S = 120  # a wedged Ollama must never block the analysis worker forever


def embed(texts: list[str], batch_size: int = 16, gpu: bool = False, progress: bool = False) -> np.ndarray:
    """bge-m3 served by Ollama. gpu=False passes num_gpu=0 so the embedding model
    runs on CPU and Gemma keeps the 4 GB card; use gpu=True for offline training.
    Returns L2-normalised float32 vectors (1024-dim)."""
    import ollama

    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = ollama.Client(timeout=EMBED_TIMEOUT_S).embed(model=EMBED_MODEL, input=chunk, options={"num_gpu": -1 if gpu else 0})
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


# Common function words of romanised Hindi and romanised Tamil. For Latin-script
# text this separates Hinglish from Tanglish far better than a 4B model guesses.
_HI_ROMAN = {"hai", "hain", "nahi", "nahin", "ka", "ki", "ke", "ko", "se", "mein", "me", "raha", "rahi", "rahe", "kar", "karo", "kya", "aur",
             "bhi", "par", "hum", "humari", "humare", "hamara", "kal", "aaj", "paani", "pani", "bijli", "jaldi", "bahut", "bhejo", "din", "ghar",
             "wala", "wali", "ke paas", "sadak", "kachra", "band", "lagta", "lagti", "hota", "hoti", "kripya", "karein", "toh", "abhi", "subah", "raat"}
_TA_ROMAN = {"illa", "illai", "irukku", "iruku", "irukkanga", "irukanga", "pannen", "panna", "pannunga", "enga", "inga", "romba", "vara", "varala",
             "varalai", "aagudhu", "aguthu", "kuzhi", "thanni", "thanneer", "sir", "nalla", "seri", "ungal", "enga", "veetla", "veedu", "theru",
             "pakkam", "naal", "naala", "ah", "la", "ku", "nu", "da", "dhaan", "thaan", "podunga", "seiyunga", "venum", "vendum", "mudiyala",
             "nethu", "innaiku", "innum", "oru", "rendu", "moonu", "periya", "chinna", "kaayam", "vizhundhuchu", "odudhu", "varudhu"}


def romanised_language_guess(text: str) -> str | None:
    """For Latin-script text: 'hi' if it reads like Hinglish, 'ta' if Tanglish, 'en' if
    neither set of function words appears, None if the text is not Latin script."""
    if detect_language(text)[0] != "latin":
        return None
    words = re.findall(r"[a-z]+", (text or "").lower())
    hi = sum(w in _HI_ROMAN for w in words)
    ta = sum(w in _TA_ROMAN for w in words)
    if hi == 0 and ta == 0:
        return "en"
    if hi >= 2 and hi > ta:
        return "hi"
    if ta >= 2 and ta > hi:
        return "ta"
    return "hi" if hi > ta else ("ta" if ta > hi else "en")


LANGUAGE_HINT_TEXT = {
    "ta": "Script analysis: Tamil script.",
    "hi": "Script analysis: Devanagari script (Hindi).",
    "latin-hi": "Script analysis: Latin letters; the function words (hai, nahi, ke, se, mein ...) read as Hinglish, Hindi written in English letters. language_primary should be hi.",
    "latin-ta": "Script analysis: Latin letters; the function words (illa, irukku, pannen, romba ...) read as Tanglish, Tamil written in English letters. language_primary should be ta.",
    "latin-en": "Script analysis: Latin letters with no Hindi or Tamil function words; most likely English.",
}


def language_hint_code(text: str) -> str:
    """'ta', 'hi', 'latin-hi', 'latin-ta', 'latin-en' or 'unknown'."""
    code, _ = detect_language(text)
    if code == "latin":
        return "latin-" + (romanised_language_guess(text) or "en")
    return code


def complaint_user_message(masked_text: str, hint_code: str | None = None, has_photo: bool = False) -> str:
    """The user turn sent to the LLM: complaint text, script hint, photo note."""
    msg = "Complaint:\n" + masked_text
    if hint_code in LANGUAGE_HINT_TEXT:
        msg += "\n\n" + LANGUAGE_HINT_TEXT[hint_code]
    if has_photo:
        msg += "\n\nA photo is attached."
    return msg


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
    """config/tn_mapping.json produced by scripts/setup/import_tn_mapping.py from the
    Tamil Nadu district / department spreadsheet. Empty dict if absent."""
    global _tn
    if _tn is None:
        p = CONFIG / "tn_mapping.json"
        _tn = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _tn


def _word_char(ch: str) -> bool:
    """Letters, combining marks (Tamil and Devanagari vowel signs, pulli, virama) and digits."""
    return unicodedata.category(ch)[0] in ("L", "M", "N")


def _base_letters(word: str) -> int:
    return sum(1 for ch in word if unicodedata.category(ch)[0] in ("L", "N"))


# Grammatical endings a short Tamil or Hindi keyword may carry and still count as that word:
# Tamil plural and case endings after a vowel (குப்பைகள், தீயில், பள்ளிக்கு, டெங்குவால்) and the
# Hindi oblique plural (सांपों). Anything else glued on makes it a different word:
# தீர்வு (solution) is not தீ (fire), आगे / आग्रह are not आग, नागरिक (citizen) is not नाग (cobra).
INDIC_SUFFIXES = (
    "கள்", "களை", "களில்", "களுக்கு", "களின்", "களால்", "களும்",
    "யை", "யில்", "யின்", "யால்", "யும்", "யிலும்", "க்கு", "வை", "வில்", "வின்", "வால்", "வும்", "வுக்கு",
    "ों", "ें",
)


def keyword_in(keyword: str, text_lower: str) -> bool:
    """Does the keyword occur in the (lower-cased) text as a word?

    ASCII keywords match whole words only ('fire' not 'fired', 'land' not 'landmark').
    Tamil and Devanagari keywords must start a word. A short one-word keyword (three letters or
    fewer, e.g. தீ, आग, नाग, பட்டா) must be the whole word, optionally with one of INDIC_SUFFIXES;
    longer keywords and phrases may run on into the suffixes Tamil and Hindi attach
    (குழந்தைகள், தண்ணீரே, बच्चा गिरा)."""
    k = (keyword or "").strip().lower()
    if not k:
        return False
    if k.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text_lower) is not None
    short_word = " " not in k and _base_letters(k) <= 3
    start = 0
    while (i := text_lower.find(k, start)) >= 0:
        start = i + 1
        if i > 0 and _word_char(text_lower[i - 1]):
            continue  # inside another word
        if not short_word:
            return True
        j = i + len(k)
        end = j
        while end < len(text_lower) and _word_char(text_lower[end]):
            end += 1
        if text_lower[j:end] in ("",) + INDIC_SUFFIXES:
            return True
    return False


# ------------------------------------------------------------ district names ---
_district_names: list[tuple[str, str]] | None = None
COMMON_WORD_DISTRICTS = {"erode"}  # also an English verb: in free text only "Erode" with a capital counts


def _district_patterns() -> list[tuple[str, str]]:
    """(name as written, district) for every district name and alias: English names and aliases
    from config/district_names.json and the Tamil and Hindi spellings there. Town names are left
    out on purpose: many are also people's names (Palani, Bhavani) or exist in every district
    (Anna Nagar); towns are only used for GPS through config/places_tn.csv."""
    global _district_names
    if _district_names is None:
        pats: list[tuple[str, str]] = []
        p = CONFIG / "district_names.json"
        names = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        for d in load_tn_mapping().get("districts", []):
            entry = names.get(d["name"], {})
            for n in [d["name"], *entry.get("en", []), *entry.get("ta", []), *entry.get("hi", [])]:
                pats.append((n.lower(), d["name"]))
        _district_names = pats
    return _district_names


def _tamil_stems(name: str) -> list[str]:
    """Match forms for a Tamil place name: the name without its final pulli or u-sign, so case
    endings still match (கோயம்புத்தூர் -> கோயம்புத்தூரில், ஈரோடு -> ஈரோட்டில்), plus the -த்
    stem of names ending in -ம் (சேலம் -> சேலத்தில்)."""
    stems = [name.rstrip("்ு") or name]
    if name.endswith("ம்"):
        stems.append(name[:-2] + "த்")
    return stems


def district_for(text: str | None, free_text: bool = False) -> str | None:
    """District that a district name in the text (a resolved place, a typed address or, with
    free_text=True, the complaint itself) refers to, or None. Names match as whole words in
    English, Tamil or Hindi, so 'eroded' is not Erode and an address typed in Tamil script still
    resolves. When several districts are named, the last one counts: addresses end with it."""
    if not text:
        return None
    low = text.lower()
    best: tuple[int, str | None] = (-1, None)
    for name, district in _district_patterns():
        if name.isascii():
            for m in re.finditer(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low):
                if free_text and name in COMMON_WORD_DISTRICTS and not text[m.start()].isupper():
                    continue
                if m.start() >= best[0]:
                    best = (m.start(), district)
        else:
            for stem in _tamil_stems(name) if re.search(r"[஀-௿]", name) else [name]:
                start = 0
                while (i := low.find(stem, start)) >= 0:
                    start = i + 1
                    if i > 0 and _word_char(low[i - 1]):
                        continue
                    if i >= best[0]:
                        best = (i, district)
    return best[1]


def office_hint(text: str) -> dict | None:
    """First spreadsheet keyword rule that matches the complaint text -> {department_id, priority, rule_id}."""
    low = (text or "").lower()
    for r in load_tn_mapping().get("keyword_rules", []):
        if keyword_in(r["keyword"], low):
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

    def fit(self, X: np.ndarray, y: list[str], labels: list[str], sample_weight=None) -> "SoftmaxRegression":
        """sample_weight: optional weight per row (officer-confirmed rows above synthetic ones); classes
        stay balanced on the weighted counts. Without it every row weighs 1."""
        self.labels = list(labels)
        idx = {l: i for i, l in enumerate(self.labels)}
        yi = np.array([idx[v] for v in y])
        n, d, k = X.shape[0], X.shape[1], len(self.labels)
        Y = np.zeros((n, k), dtype=np.float32)
        Y[np.arange(n), yi] = 1.0
        sw = np.ones(n, dtype=np.float32) if sample_weight is None else np.asarray(sample_weight, dtype=np.float32)
        total = float(sw.sum())
        counts = np.bincount(yi, weights=sw, minlength=k).astype(np.float32)
        w = (sw * total / (k * np.maximum(counts, 1e-6))[yi])[:, None]  # balanced classes, row weights within them
        self.W = np.zeros((d, k), dtype=np.float32)
        self.b = np.zeros(k, dtype=np.float32)
        for _ in range(self.epochs):
            P = self._softmax(X @ self.W + self.b)
            G = (P - Y) * w / total
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
