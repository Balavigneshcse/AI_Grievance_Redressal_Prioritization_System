"""Download the public datasets that can be fetched without a login, and list
the ones that need a manual download. Pure Python (requests + huggingface_hub).

Run:  python scripts/download_datasets.py
"""
from __future__ import annotations

import requests

from common import DATA

RAW = DATA / "raw"
RAW.mkdir(parents=True, exist_ok=True)


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


# 1. NYC 311 service requests (civic complaints with categories) -----------
step("1/3 NYC 311 sample (civic complaint types, English)")
nyc = RAW / "nyc311_sample.csv"
if nyc.exists():
    print("already present:", nyc)
else:
    url = (
        "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
        "?$limit=3000"
        "&$select=created_date,complaint_type,descriptor,agency,borough,incident_address,latitude,longitude"
        "&$where=descriptor IS NOT NULL"
    )
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        nyc.write_bytes(r.content)
        print("saved", nyc, f"({len(r.content)/1e6:.1f} MB)")
    except Exception as exc:
        print("NYC 311 download failed:", exc)

# 2. COMI-LINGUA (Hindi-English code-mixed) raw files from Hugging Face ------
step("2/3 COMI-LINGUA (Hinglish language ID / NER) from Hugging Face")
try:
    from huggingface_hub import HfApi, hf_hub_download

    repo = "LingoIITGN/COMI-LINGUA"
    api = HfApi()
    files = api.list_repo_files(repo, repo_type="dataset")
    small = [f for f in files if f.lower().endswith((".csv", ".json", ".jsonl", ".txt", ".tsv"))]
    print(f"{len(files)} files in repo, {len(small)} text/csv files")
    got = 0
    for f in small[:6]:
        try:
            p = hf_hub_download(repo, f, repo_type="dataset", local_dir=RAW / "comi_lingua")
            print("  saved", p)
            got += 1
        except Exception as exc:
            print("  skip", f, exc)
    if not got:
        print("No plain-text files; the dataset is parquet. Load it later with pandas.read_parquet if pyarrow is allowed.")
except Exception as exc:
    print("COMI-LINGUA listing failed (not fatal):", exc)

# 3. Tamil-English code-mixed candidates on Hugging Face ---------------------
step("3/3 Tamil-English code-mixed datasets on Hugging Face (listing only)")
try:
    from huggingface_hub import HfApi

    api = HfApi()
    seen = set()
    for q in ["tamil english code-mixed", "tanglish", "dravidian codemix"]:
        for d in api.list_datasets(search=q, limit=8):
            if d.id not in seen:
                seen.add(d.id)
                print("  candidate:", d.id)
    print("Pick one, check its licence, then download its files with hf_hub_download.")
except Exception as exc:
    print("listing failed (not fatal):", exc)

print(
    """
Manual downloads (need a login or a form), save under data/raw/:
  - AIKOSH Champions Dataset 2024-25 (MSME grievances, CSV)
      https://aikosh.indiaai.gov.in/home/datasets/details/champions_dataset_2024_25.html
  - CivicNLP-608 (English + Marathi civic complaints, 8 categories)
      https://ieee-dataport.org/documents/bilingual-civic-complaint-classification-dataset-english-and-marathi-public-service
  - Citizen complaints on Twitter, India (Mendeley)
      https://data.mendeley.com/datasets/w2cp7h53s5

The training set we rely on is generated locally: python scripts/make_synthetic.py
"""
)
