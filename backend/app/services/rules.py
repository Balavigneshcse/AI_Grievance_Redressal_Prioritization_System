"""Configurable routing rules from config/rules.yaml, hot-reloaded on file change."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import settings

RULES_PATH: Path = settings.ROOT / "config" / "rules.yaml"
URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_cache: dict = {"mtime": None, "rules": []}


def load_rules() -> list[dict]:
    try:
        mtime = RULES_PATH.stat().st_mtime
    except FileNotFoundError:
        return []
    if _cache["mtime"] != mtime:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _cache["rules"] = [r for r in data.get("rules", []) if r.get("enabled", True)]
        _cache["mtime"] = mtime
    return _cache["rules"]


def rules_yaml_text() -> str:
    return RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.exists() else "rules: []\n"


def validate_rules_yaml(text: str) -> list[dict]:
    data = yaml.safe_load(text) or {}
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise ValueError("top-level 'rules' must be a list")
    for r in rules:
        if "id" not in r or "match" not in r or "action" not in r:
            raise ValueError(f"rule {r.get('id', '?')} needs id, match and action")
    return rules


@dataclass
class RuleResult:
    matched_ids: list[str] = field(default_factory=list)
    department: str | None = None
    urgency_floor: str | None = None
    force_review: bool = False
    notes: list[str] = field(default_factory=list)


def evaluate(text: str, language: str | None = None, ward: str | None = None) -> RuleResult:
    low = (text or "").lower()
    out = RuleResult()
    for r in load_rules():
        m = r.get("match", {})
        hit = False
        if any(k.lower() in low for k in m.get("keywords", [])):
            hit = True
        if not hit and m.get("regex"):
            try:
                hit = re.search(m["regex"], text, flags=re.IGNORECASE) is not None
            except re.error:
                hit = False
        if hit and m.get("language") and language not in m["language"]:
            hit = False
        if hit and m.get("ward") and ward not in m["ward"]:
            hit = False
        if not hit:
            continue
        a = r.get("action", {})
        out.matched_ids.append(str(r["id"]))
        if a.get("department") and not out.department:
            out.department = a["department"]
            out.notes.append(f"{r['id']} {r.get('name', '')}: department -> {a['department']}")
        if a.get("urgency_floor"):
            if out.urgency_floor is None or URGENCY_RANK[a["urgency_floor"]] > URGENCY_RANK[out.urgency_floor]:
                out.urgency_floor = a["urgency_floor"]
            out.notes.append(f"{r['id']} {r.get('name', '')}: urgency at least {a['urgency_floor']}")
        if a.get("force_review"):
            out.force_review = True
            out.notes.append(f"{r['id']} {r.get('name', '')}: human review required")
    return out
