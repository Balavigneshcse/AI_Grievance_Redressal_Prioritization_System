"""Train the second-opinion classifiers: softmax regression (NumPy) on bge-m3
embeddings served by Ollama, one model for department and one for urgency.

Data used (whatever exists):
  data/synthetic/complaints.jsonl     generated locally by make_synthetic.py
  data/eval/complaints.jsonl          hand-labelled gold set
  data/raw/nyc311_sample.csv          English civic complaint types mapped to our departments (department model only)
  data/corrections/officer_labels.jsonl   with --corrections: labels officers confirmed (export_corrections.py)

Officer rows weigh --officer-weight times a synthetic row and are held out by complaint: they are split
into --folds folds by their complaint (a merged duplicate stays with its original), and each fold is
predicted by a model trained on the synthetic training split plus the other folds. "before" is the same
synthetic training split without officer rows, so the before/after numbers per language compare like
with like. They are reported twice: on the complaint text (what training embeds) and on the row's
pipeline_text (what the API embeds at runtime: the English summary + place). A synthetic row with the
same text as an officer row is dropped; the officer label wins.

Outputs (in --out, default models/):
  second_opinion_department.npz
  second_opinion_urgency.npz
  second_opinion_report.json   held-out accuracy overall and per language (and before/after on officer rows)
Embeddings are cached by text in --cache (default models/embeddings_cache.npz), so a retrain only embeds
new rows; --no-cache embeds everything again.

Run:  python scripts/training/train_second_opinion.py
      python scripts/training/train_second_opinion.py --no-nyc
      python scripts/training/train_second_opinion.py --cpu      (leave the GPU alone while embedding)
      python scripts/training/train_second_opinion.py --corrections --officer-weight 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # scripts/, home of the shared common.py
from common import DATA, EMBED_MODEL, MODELS, SoftmaxRegression, department_ids, embed, read_jsonl, urgency_ids

OFFICER_FILE = DATA / "corrections" / "officer_labels.jsonl"

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


def norm_text(text: str) -> str:
    return " ".join(str(text).lower().split())


def load_rows(use_nyc: bool) -> list[dict]:
    rows = []
    for name in ["synthetic/complaints.jsonl", "eval/complaints.jsonl"]:
        got = read_jsonl(DATA / name)
        print(f"{name}: {len(got)} rows")
        rows += got
    if use_nyc and (DATA / "raw" / "nyc311_sample.csv").exists():
        import pandas as pd

        df = pd.read_csv(DATA / "raw" / "nyc311_sample.csv")
        df = df[df["complaint_type"].isin(NYC_MAP)].copy()
        df["dept"] = df["complaint_type"].map(NYC_MAP)
        # At most 40 rows per department, otherwise NYC noise complaints flood
        # "general" and the English numbers look better than they are.
        df = df.groupby("dept", group_keys=False).head(40)
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


def load_officer_rows(path: Path) -> list[dict]:
    """Rows from export_corrections.py; one per text, the later one winning, should the file have been edited by hand."""
    departments, by_text = set(department_ids()), {}
    for r in read_jsonl(path):
        if r.get("text") and r.get("department") in departments:
            by_text[norm_text(r["text"])] = r
    rows = list(by_text.values())
    print(f"{path}: {len(rows)} officer rows, departments {dict(Counter(r['department'] for r in rows))}")
    return rows


def embed_cached(texts: list[str], cache: Path | None, gpu: bool) -> np.ndarray:
    """bge-m3 vectors, reusing those already in the cache file (keyed by model and text): a retrain after a
    new export embeds only the new rows and holds the one-request-at-a-time model server for seconds."""
    if cache is None:
        print(f"\nEmbedding {len(texts)} texts with bge-m3 via Ollama ({'GPU' if gpu else 'CPU'}) ...")
        return embed(texts, gpu=gpu, progress=True)
    cache = cache if cache.suffix == ".npz" else cache.with_name(cache.name + ".npz")  # np.savez adds the suffix anyway
    keys = [hashlib.sha1(f"{EMBED_MODEL}\n{t}".encode("utf-8")).hexdigest() for t in texts]
    known: dict[str, np.ndarray] = {}
    if cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            known = dict(zip((str(k) for k in z["keys"]), z["X"]))
    missing = {k: t for k, t in zip(keys, texts) if k not in known}
    print(f"\nEmbeddings: {len(texts) - sum(k in missing for k in keys)} of {len(texts)} texts from {cache}, "
          f"{len(missing)} to embed with bge-m3 via Ollama ({'GPU' if gpu else 'CPU'})")
    if missing:
        known.update(zip(missing, embed(list(missing.values()), gpu=gpu, progress=True)))
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, keys=np.array(list(known)), X=np.stack(list(known.values())))
    return np.stack([known[k] for k in keys]).astype(np.float32)


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


def group_folds(groups: list[str], y: list[str], k: int, seed: int = 42) -> list[np.ndarray]:
    """k folds of row indices. Every row of a complaint group lands in the same fold, and each label's
    groups are dealt over the folds in turn, so every fold sees every department."""
    rng = np.random.default_rng(seed)
    label_of: dict[str, str] = {}
    for g, v in zip(groups, y):
        label_of.setdefault(g, v)
    by_label = defaultdict(list)
    for g, v in label_of.items():
        by_label[v].append(g)
    fold_of, n = {}, 0
    for v in sorted(by_label):
        gs = sorted(by_label[v])
        rng.shuffle(gs)
        for g in gs:
            fold_of[g] = n % k
            n += 1
    return [np.array([i for i, g in enumerate(groups) if fold_of[g] == f]) for f in range(k)]


def per_language_accuracy(y_true, y_pred, langs) -> dict:
    hits, totals = defaultdict(int), defaultdict(int)
    for t, p, l in zip(y_true, y_pred, langs):
        totals[l] += 1
        hits[l] += int(t == p)
    return {l: {"n": totals[l], "accuracy": round(hits[l] / totals[l], 3)} for l in sorted(totals)}


def scores(pred: list[str], truth: list[str], langs: list[str], labels: list[str]) -> dict:
    acc = float(np.mean([p == t for p, t in zip(pred, truth)])) if truth else float("nan")
    per_class = {}
    for lab in labels:
        n = sum(t == lab for t in truth)
        if n:
            per_class[lab] = round(sum(p == t == lab for p, t in zip(pred, truth)) / n, 3)
    return {"accuracy": round(acc, 3), "n": len(truth), "per_language": per_language_accuracy(truth, pred, langs), "recall_per_class": per_class}


def print_before_after(title: str, before: dict, after: dict) -> None:
    print(f"\n{title}")
    print(f"  {'':8s} {'n':>4s}  before  after")
    for l, b in before["per_language"].items():
        print(f"  {l:8s} {b['n']:4d}   {b['accuracy']:.3f}  {after['per_language'][l]['accuracy']:.3f}")
    print(f"  {'all':8s} {before['n']:4d}   {before['accuracy']:.3f}  {after['accuracy']:.3f}")
    print("  recall per class:", {c: f"{before['recall_per_class'][c]:.2f} -> {after['recall_per_class'][c]:.2f}" for c in before["recall_per_class"]})


def train_one(name: str, X: np.ndarray, y: list[str], langs: list[str], labels: list[str], officer: dict | None = None,
              weight: float = 3.0, folds: int = 5):
    """officer: {"X", "y", "langs", "groups"} of the officer rows, or None for synthetic data only."""
    print(f"\n=== {name} model: {len(y)} rows, classes {dict(Counter(y))}")
    tr, te = stratified_split(y)
    y_tr, y_te, l_te = [y[i] for i in tr], [y[i] for i in te], [langs[i] for i in te]
    clf = SoftmaxRegression().fit(X[tr], y_tr, labels)
    held = scores(clf.predict(X[te]), y_te, l_te, labels)
    print(f"held-out accuracy: {held['accuracy']:.3f} on {len(te)} rows")
    print("recall per class:", held["recall_per_class"])
    for l, v in held["per_language"].items():
        print(f"  {l:6s} n={v['n']:3d} acc={v['accuracy']:.3f}")
    if not officer:
        final = SoftmaxRegression().fit(X, y, labels)
        return final, {"held_out_accuracy": held["accuracy"], "per_language": held["per_language"], "recall_per_class": held["recall_per_class"], "n": len(y)}

    Xo, yo, lo, go, Xp = officer["X"], officer["y"], officer["langs"], officer["groups"], officer["X_pipeline"]
    k = min(folds, len(set(go)))
    oof: list[str | None] = [None] * len(yo)
    oof_p: list[str | None] = [None] * len(yo)
    for idx in group_folds(go, yo, k):
        rest = np.setdiff1d(np.arange(len(yo)), idx)
        m = SoftmaxRegression().fit(np.vstack([X[tr], Xo[rest]]), y_tr + [yo[i] for i in rest], labels,
                                    sample_weight=[1.0] * len(tr) + [weight] * len(rest))
        for i, p, q in zip(idx, m.predict(Xo[idx]), m.predict(Xp[idx])):
            oof[i], oof_p[i] = p, q
    before, after = scores(clf.predict(Xo), yo, lo, labels), scores(oof, yo, lo, labels)
    before_p, after_p = scores(clf.predict(Xp), yo, lo, labels), scores(oof_p, yo, lo, labels)
    with_all = SoftmaxRegression().fit(np.vstack([X[tr], Xo]), y_tr + yo, labels, sample_weight=[1.0] * len(tr) + [weight] * len(yo))
    held_after = scores(with_all.predict(X[te]), y_te, l_te, labels)
    print_before_after(f"{name}, officer rows held out by complaint ({len(yo)} rows, {k} folds, weight {weight:g}), complaint text:", before, after)
    print_before_after(f"{name}, the same rows as the pipeline embeds them at runtime (English summary + place):", before_p, after_p)
    print(f"  synthetic held-out ({len(te)} rows): before {held['accuracy']:.3f}, after {held_after['accuracy']:.3f}")

    final = SoftmaxRegression().fit(np.vstack([X, Xo]), y + yo, labels, sample_weight=[1.0] * len(y) + [weight] * len(yo))
    return final, {
        "held_out_accuracy": held_after["accuracy"], "per_language": held_after["per_language"],
        "recall_per_class": held_after["recall_per_class"], "n": len(y) + len(yo),
        "officer": {"rows": len(yo), "weight": weight, "folds": k, "before": before, "after": after,
                    "pipeline_input": {"before": before_p, "after": after_p}, "synthetic_held_out_before": held},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-nyc", action="store_true", help="ignore the NYC 311 sample")
    ap.add_argument("--cpu", action="store_true", help="embed on CPU instead of GPU")
    ap.add_argument("--corrections", nargs="?", type=Path, const=OFFICER_FILE, default=None, metavar="JSONL",
                    help=f"add officer-confirmed rows (default file {OFFICER_FILE.relative_to(DATA.parent)})")
    ap.add_argument("--officer-weight", type=float, default=3.0, help="weight of an officer row against a synthetic row (default 3)")
    ap.add_argument("--folds", type=int, default=5, help="folds over the officer rows, split by complaint (default 5)")
    ap.add_argument("--out", type=Path, default=MODELS, help="folder for the models and the report (default models/)")
    ap.add_argument("--cache", type=Path, default=MODELS / "embeddings_cache.npz", help="embedding cache file")
    ap.add_argument("--no-cache", action="store_true", help="embed every text again")
    args = ap.parse_args()

    rows = load_rows(use_nyc=not args.no_nyc)
    if len(rows) < 40:
        raise SystemExit("Not enough data. Run scripts/training/make_synthetic.py first.")
    n_syn = sum(1 for r in rows if str(r.get("source", "")).startswith("synthetic"))
    depts_syn = {r["department"] for r in rows if str(r.get("source", "")).startswith("synthetic")}
    if n_syn < 200 or len(depts_syn) < 8:
        print(
            f"\nWARNING: only {n_syn} synthetic rows covering {len(depts_syn)} of 8 departments. "
            "The models will be weak until make_synthetic.py has finished; rerun this script afterwards.\n"
        )

    officer = []
    if args.corrections:
        if not args.corrections.exists():
            raise SystemExit(f"{args.corrections} not found. Run scripts/training/export_corrections.py first.")
        officer = load_officer_rows(args.corrections)
        if len(officer) < 10:
            raise SystemExit("Fewer than 10 officer rows: too few to weight or to hold out. Train without --corrections.")
        texts = {norm_text(r["text"]) for r in officer}
        n_before = len(rows)
        rows = [r for r in rows if norm_text(r["text"]) not in texts]
        if n_before > len(rows):
            print(f"dropped {n_before - len(rows)} synthetic/gold rows whose text an officer labelled")

    # Officer rows are embedded twice: their text (what training uses) and their pipeline_text (what the API
    # embeds at runtime: English summary + place), so the report shows both; a row without one uses its text.
    pipeline_texts = [r.get("pipeline_text") or r["text"] for r in officer]
    X_all = embed_cached([r["text"] for r in rows + officer] + pipeline_texts, None if args.no_cache else args.cache, gpu=not args.cpu)
    n, n_o = len(rows), len(officer)
    X, Xo, Xp = X_all[:n], X_all[n : n + n_o], X_all[n + n_o :]
    langs = [r.get("language", "en") for r in rows]
    langs_o = [r.get("language") or "unknown" for r in officer]
    groups_o = [r.get("group") or r.get("id") or norm_text(r["text"]) for r in officer]

    def officer_part(idx: list[int], field: str) -> dict | None:
        if not idx:
            return None
        return {"X": Xo[idx], "X_pipeline": Xp[idx], "y": [officer[i][field] for i in idx], "langs": [langs_o[i] for i in idx],
                "groups": [groups_o[i] for i in idx]}

    args.out.mkdir(parents=True, exist_ok=True)
    report = {}

    dept_model, report["department"] = train_one(
        "department", X, [r["department"] for r in rows], langs, department_ids(),
        officer_part(list(range(len(officer))), "department"), args.officer_weight, args.folds,
    )
    dept_model.save(args.out / "second_opinion_department.npz")

    idx = [i for i, r in enumerate(rows) if r.get("urgency")]
    if len(idx) >= 40:
        levels = urgency_ids()
        urg_model, report["urgency"] = train_one(
            "urgency", X[idx], [rows[i]["urgency"] for i in idx], [langs[i] for i in idx], levels,
            officer_part([i for i, r in enumerate(officer) if r.get("urgency") in levels], "urgency"), args.officer_weight, args.folds,
        )
        urg_model.save(args.out / "second_opinion_urgency.npz")
    else:
        print("\nurgency model skipped: not enough rows with urgency labels")

    with open(args.out / "second_opinion_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nSaved models to", args.out)
    if args.out.resolve() == MODELS.resolve():
        print("The running API keeps the old models until POST /admin/models/reload (super admin).")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
