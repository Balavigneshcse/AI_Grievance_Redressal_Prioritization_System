"""Replay the gold set through the local LLM and report accuracy per language,
per department and per urgency, plus latency. This is the fairness dashboard's
data source.

Run:  python scripts/evaluation/run_eval.py                       (gemma3:4b, whole gold set)
      python scripts/evaluation/run_eval.py --model qwen3:4b-instruct-2507-q4_K_M
      python scripts/evaluation/run_eval.py --limit 5             (quick check)

Outputs:
  data/eval/results_<model>.jsonl    one row per complaint with prediction and truth
  data/eval/summary_<model>.json     accuracies and timings
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict

import ollama

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # scripts/, home of the shared common.py
from common import DATA, DEFAULT_LLM, ROOT, analysis_system_prompt, complaint_user_message, language_hint_code, load_schema, read_jsonl

# The rules layer is part of the system: report accuracy with and without it.
sys.path.insert(0, str(ROOT / "backend"))
try:
    from app.services.rules import URGENCY_RANK, evaluate as evaluate_rules
except Exception:  # backend deps missing: raw-model numbers only
    evaluate_rules = None
    URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def apply_rules(text: str, dept: str | None, urg: str | None) -> tuple[str | None, str | None, list[str]]:
    if evaluate_rules is None:
        return dept, urg, []
    r = evaluate_rules(text)
    out_dept = r.department or dept
    out_urg = urg
    if r.urgency_floor and URGENCY_RANK[r.urgency_floor] > URGENCY_RANK.get(urg or "low", 0):
        out_urg = r.urgency_floor
    return out_dept, out_urg, r.matched_ids


def analyse(model: str, text: str, system: str, schema: dict) -> tuple[dict, float, int]:
    t0 = time.time()
    resp = ollama.chat(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": complaint_user_message(text, language_hint_code(text))}],
        format=schema,
        options={"temperature": 0, "num_ctx": 2048, "num_predict": 400},
    )
    return json.loads(resp.message.content), time.time() - t0, int(getattr(resp, "eval_count", 0) or 0)


def group_acc(rows: list[dict], key: str, field: str) -> dict:
    hits, totals = defaultdict(int), defaultdict(int)
    for r in rows:
        g = r[key]
        totals[g] += 1
        hits[g] += int(r[f"pred_{field}"] == r[f"true_{field}"])
    return {g: {"n": totals[g], "accuracy": round(hits[g] / totals[g], 3)} for g in sorted(totals)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_LLM)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--gold", default=str(DATA / "eval" / "complaints.jsonl"))
    args = ap.parse_args()

    gold = read_jsonl(args.gold)
    if args.limit:
        gold = gold[: args.limit]
    if not gold:
        raise SystemExit("gold set is empty")

    system = analysis_system_prompt()
    schema = load_schema()
    tag = re.sub(r"[^a-z0-9]+", "_", args.model.lower())
    out_rows = DATA / "eval" / f"results_{tag}.jsonl"
    out_sum = DATA / "eval" / f"summary_{tag}.json"

    results = []
    print(f"model {args.model}, {len(gold)} complaints\n")
    for i, g in enumerate(gold, 1):
        try:
            pred, dt, toks = analyse(args.model, g["text"], system, schema)
        except Exception as exc:
            print(f"[{i}] {g['id']} FAILED: {exc}")
            continue
        sys_dept, sys_urg, rule_ids = apply_rules(g["text"], pred.get("department"), pred.get("urgency"))
        row = {
            "id": g["id"],
            "language": g["language"],
            "formality": g.get("formality", ""),
            "true_department": g["department"],
            "pred_department": pred.get("department"),
            "true_urgency": g["urgency"],
            "pred_urgency": pred.get("urgency"),
            "system_department": sys_dept,
            "system_urgency": sys_urg,
            "matched_rules": rule_ids,
            "confidence": pred.get("confidence"),
            "pred_language": pred.get("language_primary"),
            "evidence_spans": pred.get("evidence_spans", []),
            "summary_en": pred.get("summary_en", ""),
            "seconds": round(dt, 2),
            "gen_tokens": toks,
        }
        results.append(row)
        ok_d = "ok " if row["pred_department"] == row["true_department"] else "DEP"
        ok_u = "ok " if row["pred_urgency"] == row["true_urgency"] else "URG"
        sys_d = "ok " if row["system_department"] == row["true_department"] else "DEP"
        sys_u = "ok " if row["system_urgency"] == row["true_urgency"] else "URG"
        print(f"[{i}/{len(gold)}] {g['id']} {g['language']:5s} model {ok_d} {ok_u}  system {sys_d} {sys_u}  {row['pred_department']:11s} {row['pred_urgency']:8s} -> {row['system_department']}/{row['system_urgency']} rules={rule_ids} conf={row['confidence']}  {dt:4.1f}s")

    if not results:
        raise SystemExit("no results")

    n = len(results)
    summary = {
        "model": args.model,
        "n": n,
        "department_accuracy": round(sum(r["pred_department"] == r["true_department"] for r in results) / n, 3),
        "urgency_accuracy": round(sum(r["pred_urgency"] == r["true_urgency"] for r in results) / n, 3),
        "urgency_within_one_level": round(
            sum(
                abs(["critical", "high", "medium", "low"].index(r["pred_urgency"]) - ["critical", "high", "medium", "low"].index(r["true_urgency"])) <= 1
                for r in results
                if r["pred_urgency"] in ("critical", "high", "medium", "low")
            )
            / n,
            3,
        ),
        "critical_recall": (
            round(
                sum(r["pred_urgency"] == "critical" for r in results if r["true_urgency"] == "critical")
                / max(1, sum(r["true_urgency"] == "critical" for r in results)),
                3,
            )
        ),
        "system_department_accuracy": round(sum(r["system_department"] == r["true_department"] for r in results) / n, 3),
        "system_urgency_accuracy": round(sum(r["system_urgency"] == r["true_urgency"] for r in results) / n, 3),
        "system_critical_recall": round(
            sum(r["system_urgency"] == "critical" for r in results if r["true_urgency"] == "critical")
            / max(1, sum(r["true_urgency"] == "critical" for r in results)),
            3,
        ),
        "language_id_accuracy": round(sum((r["pred_language"] or "")[:2] == r["language"][:2] for r in results) / n, 3),
        "by_language_department": group_acc(results, "language", "department"),
        "by_language_urgency": group_acc(results, "language", "urgency"),
        "by_language_system_department": group_acc(
            [{**r, "pred_system_department": r["system_department"], "true_system_department": r["true_department"]} for r in results],
            "language", "system_department",
        ),
        "by_formality_urgency": group_acc(results, "formality", "urgency"),
        "mean_seconds": round(sum(r["seconds"] for r in results) / n, 2),
        "mean_gen_tokens": round(sum(r["gen_tokens"] for r in results) / n, 1),
    }
    with open(out_rows, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_sum, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nsaved {out_rows}\nsaved {out_sum}")


if __name__ == "__main__":
    main()
