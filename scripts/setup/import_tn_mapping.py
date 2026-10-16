"""Convert the Tamil Nadu district / department mapping spreadsheet into
config/tn_mapping.json, which the pipeline uses to route a complaint to a
specific district office and to set its due time.

The spreadsheet's 20 departments are mapped onto SYNAPSE's 8 model categories,
so the LLM, prompt, rules and training data stay unchanged. The spreadsheet
itself says its routing categories are demo values to be verified.

Run:  python scripts/setup/import_tn_mapping.py
"""
from __future__ import annotations

import json
import sys

import pandas as pd

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))  # scripts/, home of the shared common.py
from common import CONFIG, DATA

SRC = DATA / "reference" / "tn_district_department_mapping.xlsx"
OUT = CONFIG / "tn_mapping.json"

# Spreadsheet department -> SYNAPSE category (the 8 ids in config/taxonomy.yaml)
CATEGORY_OF = {
    "DEP01": "revenue",     # Revenue & District Administration
    "DEP02": "safety",      # Police
    "DEP03": "safety",      # Fire & Rescue
    "DEP04": "health",      # Health & Medical
    "DEP05": "water",       # Water Supply
    "DEP06": "electricity", # Electricity
    "DEP07": "roads",       # Roads & Highways
    "DEP08": "roads",       # Street Lighting
    "DEP09": "sanitation",  # Sanitation & Garbage
    "DEP10": "sanitation",  # Drainage & Sewage
    "DEP11": "general",     # Rural Development & Panchayat
    "DEP12": "revenue",     # Municipal Administration (certificates, licences)
    "DEP13": "general",     # School Education
    "DEP14": "general",     # Social Welfare
    "DEP15": "general",     # Food & Civil Supplies
    "DEP16": "general",     # Agriculture
    "DEP17": "health",      # Animal Husbandry
    "DEP18": "health",      # Environment & Pollution
    "DEP19": "general",     # Transport
    "DEP20": "safety",      # Women & Child Welfare
}

# Office used when no keyword hint picks a more specific one
DEFAULT_DEPARTMENT_OF_CATEGORY = {
    "water": "DEP05", "electricity": "DEP06", "roads": "DEP07", "sanitation": "DEP09",
    "health": "DEP04", "safety": "DEP03", "revenue": "DEP01", "general": "DEP12",
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not SRC.exists():
        raise SystemExit(f"{SRC} not found")
    districts = pd.read_excel(SRC, "Districts")
    departments = pd.read_excel(SRC, "Departments")
    offices = pd.read_excel(SRC, "District_Departments_Original")
    rules = pd.read_excel(SRC, "Routing_Rules")
    scope = pd.read_excel(SRC, "District_Department_Mapping").drop_duplicates("Department ID").set_index("Department ID")["Typical grievance scope"]

    out = {
        "source": SRC.name,
        "note": "Spreadsheet marks these as demo routing categories; verify the actual office before production.",
        "districts": [{"id": r.district_id, "name": r.district_name, "headquarters": r.headquarters} for r in districts.itertuples()],
        "departments": [
            {"id": r.department_id, "name": r.department_name, "scope": str(scope.get(r.department_id, "")), "category": CATEGORY_OF.get(r.department_id, "general")}
            for r in departments.itertuples()
        ],
        "category_default_department": DEFAULT_DEPARTMENT_OF_CATEGORY,
        "offices": {},
        "keyword_rules": [
            {"id": r.rule_id, "keyword": str(r.keyword).strip().lower(), "department_id": r.department_id, "priority": str(r.default_priority)}
            for r in rules.itertuples()
        ],
    }
    for r in offices.itertuples():
        out["offices"].setdefault(r.district, {})[r.department_id] = {"office_name": r.office_name, "sla_hours": int(r.default_sla_hours)}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT}: {len(out['districts'])} districts, {len(out['departments'])} departments, "
          f"{sum(len(v) for v in out['offices'].values())} offices, {len(out['keyword_rules'])} keyword rules")
    unmapped = [d["id"] for d in out["departments"] if d["id"] not in CATEGORY_OF]
    if unmapped:
        print("WARNING unmapped departments (defaulted to general):", unmapped)


if __name__ == "__main__":
    main()
