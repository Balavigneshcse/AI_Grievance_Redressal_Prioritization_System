"""Train the second-opinion classifiers: softmax regression (NumPy) on bge-m3
embeddings served by Ollama, one model for department and one for urgency.

Data used (whatever exists):
  data/synthetic/complaints.jsonl     generated locally by make_synthetic.py
  data/eval/complaints.jsonl          hand-labelled gold set
  data/raw/nyc311_sample.csv          English civic complaint types mapped to our departments (department model only)

Outputs:
  models/second_opinion_department.npz
  models/second_opinion_urgency.npz
  models/second_opinion_report.json   held-out accuracy overall and per language

Run:  python scripts/train_second_opinion.py
      python scripts/train_second_opinion.py --no-nyc
      python scripts/train_second_opinion.py --cpu      (leave the GPU alone while embedding)
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

import numpy as np

from common import DATA, MODELS, SoftmaxRegression, department_ids, embed, read_jsonl, urgency_ids

NYC_MAP = {
    "Street Condition": "roads", "Street Light Condition": "roads", "Traffic Signal Condition": "roads",
    "Sidewalk Condition": "roads", "Highway Condition": "roads", "Curb Condition": "roads",
    "Water System": "water", "Water Quality": "water", "Plumbing": "water",
    "Sewer": "sanitation", "Sanitation Condition": "sanitation", "Dirty Condition": "sanitation",
    "Missed Collection": "sanitation", "Missed Collection (All Materials)": "sanitation",
    "Illegal Dumping": "sanitation", "Overflowing Litter Baskets": "sanitation",
    "Request Large Bulky Item Collection": "sanitation",
    "Dead Animal": "health", "Rodent": "health", "Food Poisoning": "health", "Unsanitary Condition": "health",
    "Mosquitoes": "health", "Air Quality": "health", "Indoor Air Quality": "health",
    "Electric": "electricity", "ELECTRIC": "electricity", "Electrical": "electricity",
    "Gas Leak": "safety", "Fire Alarm": "safety", "Damaged Tree": "safety", "Fallen Tree": "safety",
    "Structural": "safety",
    "Building/Use": "revenue", "Illegal Building": "revenue", "Property": "revenue",
    "DOF Property - Payment Issue": "revenue", "DOF Property - Owner Issue": "revenue",
    "Noise - Residential": "general", "Noise": "general", "Noise - Street/Sidewalk": "general",
    "Noise - Commercial": "general", "Noise - Vehicle": "general", "Blocked Driveway": "general",
    "Illegal Parking": "general", "Graffiti": "general", "Consumer Complaint": "general",
}


def load_rows(use_nyc: bool) -> list[dict]:
    rows = []
    for name in ["synthetic/complaints.jsonl", "eval/complaints.jsonl"]:
        got = read_jsonl(DATA / name)
        print(f"{name}: {len(got)} rows")
        rows += got
    if use_nyc and (DATA / "raw" / "nyc311_sample.csv").exists():
        import pandas as pd

        df = pd.read_csv(DATA / "raw" / "nyc311_sample.csv")
        df = df[df["complaint_type"].isin(NYC_MAP)].head(300)
        for _, r in df.iterrows():
            rows.append(
                {
                    "text": f"{r['complaint_type']}: {r['descriptor']}",
                    "language": "en",
                    "department": NYC_MAP[r["complaint_type"]],
                    "urgency": None,
                    "source": "nyc311",
                }
            )
        print(f"nyc311 mapped: {len(df)} rows (department only)")
    return [r for r in rows if r.get("text") and r.get("department")]


def stratified_split(y: list[str], test_frac: float = 0.2, seed: int = 42):
    rng = np.random.default_rng(seed)
    by_label = defaultdict(list)
    for i, v in enumerate(y):
        by_label[v].append(i)
    train, test = [], []
    for idxs in by_label.values():
        idxs = list(idxs)
        rng.shuffle(idxs)
        n_test = max(1, int(round(len(idxs) * test_frac))) if len(idxs) >= 5 else 0
        test += idxs[:n_test]
        train += idxs[n_test:]
    return np.array(train), np.array(test)


def per_language_accuracy(y_true, y_pred, langs) -> dict:
    hits, totals = defaultdict(int), defaultdict(int)
    for t, p, l in zip(y_true, y_pred, langs):
        totals[l] += 1
        hits[l] += int(t == p)
    return {l: {"n": totals[l], "accuracy": round(hits[l] / totals[l], 3)} for l in sorted(totals)}


def train_one(name: str, X: np.ndarray, y: list[str], langs: list[str], labels: list[str]):
    print(f"\n=== {name} model: {len(y)} rows, classes {dict(Counter(y))}")
    tr, te = stratified_split(y)
    clf = SoftmaxRegression().fit(X[tr], [y[i] for i in tr], labels)
    pred = clf.predict(X[te])
    truth = [y[i] for i in te]
    acc = float(np.mean([p == t for p, t in zip(pred, truth)])) if len(te) else float("nan")
    print(f"held-out accuracy: {acc:.3f} on {len(te)} rows")
    per_class = {}
    for lab in labels:
        n = sum(t == lab for t in truth)
        if n:
            per_class[lab] = round(sum(p == t == lab for p, t in zip(pred, truth)) / n, 3)
    print("recall per class:", per_class)
    by_lang = per_language_accuracy(truth, pred, [langs[i] for i in te])
    for l, v in by_lang.items():
        print(f"  {l:6s} n={v['n']:3d} acc={v['accuracy']:.3f}")
    final = SoftmaxRegression().fit(X, y, labels)
    return final, {"held_out_accuracy": round(acc, 3), "per_language": by_lang, "recall_per_class": per_class, "n": len(y)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-nyc", action="store_true", help="ignore the NYC 311 sample")
    ap.add_argument("--cpu", action="store_true", help="embed on CPU instead of GPU")
    args = ap.parse_args()

    rows = load_rows(use_nyc=not args.no_nyc)
    if len(rows) < 40:
        raise SystemExit("Not enough data. Run scripts/make_synthetic.py first.")

    print(f"\nEmbedding {len(rows)} texts with bge-m3 via Ollama ({'CPU' if args.cpu else 'GPU'}) ...")
    X = embed([r["text"] for r in rows], gpu=not args.cpu, progress=True)
    langs = [r.get("language", "en") for r in rows]

    MODELS.mkdir(parents=True, exist_ok=True)
    report = {}

    dept_model, report["department"] = train_one("department", X, [r["department"] for r in rows], langs, department_ids())
    dept_model.save(MODELS / "second_opinion_department.npz")

    idx = [i for i, r in enumerate(rows) if r.get("urgency")]
    if len(idx) >= 40:
        urg_model, report["urgency"] = train_one(
            "urgency", X[idx], [rows[i]["urgency"] for i in idx], [langs[i] for i in idx], urgency_ids()
        )
        urg_model.save(MODELS / "second_opinion_urgency.npz")
    else:
        print("\nurgency model skipped: not enough rows with urgency labels")

    with open(MODELS / "second_opinion_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nSaved models to", MODELS)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
