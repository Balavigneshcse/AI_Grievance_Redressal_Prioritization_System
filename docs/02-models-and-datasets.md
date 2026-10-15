# SYNAPSE: Models and Datasets (local-only)

Companion to Phase 1. Answers one question: what runs on our own machine, what we download, and what we build ourselves.

Rule for the whole project: **every model runs locally. No cloud AI APIs.** Complaint text, photos and location never leave the server.

Date: 15 October 2026 | Status: Draft v2 (local-only)

---

## 1. Strategy

- **One open-weight multimodal LLM does the language-heavy work.** Category, urgency, entities, evidence spans, summary, English translation for staff, and photo description all come from a single model served by Ollama with a JSON schema so the output is always valid.
- **Two small local models do the fast, cheap jobs.** fastText for language pre-detection, a multilingual sentence-embedding model for duplicate detection and a second-opinion classifier.
- **Everything else is a library.** EXIF, offline reverse geocoding, password hashing, a local mail server for OTP in the demo.
- **No training in the first 24 hours** beyond a logistic-regression head on embeddings, which trains in seconds.

Download budget: 4 to 9 GB depending on GPU. Pull the LLM first thing; it is the slowest download.

---

## 2. Models

### 2.1 Main LLM (text + vision), served by Ollama

| Hardware we have | Model | Ollama tag | Size on disk | Expected speed |
|---|---|---|---|---|
| Laptop, no GPU, 16 GB RAM | Gemma 3 4B (instruction-tuned, vision) | `gemma3:4b` | ~3.3 GB | 5-10 tokens/s; one complaint in 20-40 s with a short JSON output |
| Laptop GPU 6-8 GB (RTX 3050/4060) | Gemma 3 4B | `gemma3:4b` | ~3.3 GB | 30-50 tokens/s; one complaint in 3-6 s |
| GPU 12 GB+ | Gemma 3 12B | `gemma3:12b` | ~8 GB | 15-25 tokens/s; better Tamil and Hindi |
| GPU 24 GB | Gemma 3 27B | `gemma3:27b` | ~17 GB | Best quality; only if the machine exists |

**Our machine: RTX 3050 laptop, 4 GB VRAM, 15 GB RAM. Chosen: `gemma3:4b`.** It is the largest model that sits entirely on this GPU. A 12B or 8B model does not fit in 4 GB; Ollama would spill most layers to the CPU and the result is 5-10x slower, not faster. "Bigger" and "faster" pull in opposite directions on 4 GB, and Gemma 3 4B is where they meet.

GPU settings so every Gemma layer stays on the card (set once as Windows user environment variables, then restart Ollama):

| Variable | Value | Effect |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | Less VRAM for attention, faster prompt processing |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves the KV cache so a 4096 context fits beside the weights |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keeps Gemma loaded between complaints; no reload cost |

In every request: `num_ctx` 2048 (the prompt is about 1,100 tokens and the JSON under 200), short JSON output. Check placement with `ollama ps`.

**Measured on the build laptop (15 Oct 2026, warm model, 2048 context, flash attention + q8 KV cache):**

| Model | GPU placement | Latency per complaint (180-token JSON) | Generation speed | Photos |
|---|---|---|---|---|
| `gemma3:4b` | 15 of 35 layers on GPU (48%) | 17-20 s | 10-11 tok/s | yes |
| `qwen3:4b-instruct-2507-q4_K_M` (already on the laptop) | 77% GPU | 9 s | 21 tok/s | no |

Cold model load adds 14-28 s once. bge-m3 embeddings on CPU: about 1.8 s per text while Gemma holds the GPU.

**Gold-set replay (12 hand-labelled rows, `scripts/run_eval.py`, 15 Oct 2026):**

| Model | Department accuracy | Urgency exact | Urgency within one level | Critical recall | Mean latency |
|---|---|---|---|---|---|
| `gemma3:4b` | 0.83 | 0.83 | 1.00 | **1.00** (4 of 4) | 17.6 s |
| `qwen3:4b-instruct-2507` | 0.92 | 0.83 | 1.00 | 0.75 (missed the leaning electric pole near school children) | 11.7 s |

Twelve rows is a smoke test, not a benchmark; the team's 60-row gold set replaces it. Two of Gemma's misses are judgement calls the rules layer is designed for: the Tanglish "no water, kids sick" row was routed to health instead of water by both models, and the dark street where women feel unsafe went to safety instead of roads. Critical recall is the number that matters for a grievance system, and Gemma caught every Critical case.

Why Gemma does not fit fully: the card reports 2.8 GiB available after the desktop's share, and the Gemma file is 3.4 GB including its vision tower. The 4 GB card cannot hold both Gemma and Qwen at once, so a text-to-Qwen / photo-to-Gemma split pays a 15-30 s reload every time the model changes.

RAM is the second limit: 15.3 GB total with under 2 GB free during tests (Ollama 4.3 GB, Windows memory compression 1.8 GB, Docker/WSL 1 GB, editors and browsers). For the demo: close Docker Desktop and run Mailpit as the native Windows exe instead, close PyCharm and spare browser tabs. Expect about 15 s per complaint, handled asynchronously; the complainant gets the tracking ID instantly.

Why Gemma 3:
- Open weights, 140+ languages, image input built in, 128K context, runs on CPU.
- On IndicVisionBench (English plus 10 Indian languages) Gemma 3 scored about 0.86 on Tamil and 0.88 on Hindi multiple-choice, the most consistent open model across Indic languages.
- One model for text and photos means one runtime, one prompt format, one thing to debug.

Alternative to benchmark against if time allows: **Qwen3-VL** (`qwen3-vl:4b` or `qwen3-vl:8b` if the tag is in the Ollama library). On a 2026 cross-lingual audit over seven Indian languages, Qwen3-VL-30B and Gemma 3-27B tied within a tenth of a point. Gemma 4 has been mentioned in community posts but has no Indic vision evidence yet; test it only if it appears in the Ollama library.

Expect an 8-point drop from English to Hindi and Tamil on any open model. That is why the eval set is per language and why uncertain cases go to a human.

Implementation notes:
- Use Ollama's `format` parameter with our JSON schema (category enum, urgency enum, confidence 0-1, entities, evidence_spans, image_findings, summary_en). Schema-constrained decoding, no parsing failures.
- Keep the JSON short (under 200 tokens). On CPU, output length is the latency.
- Keep the system prompt, taxonomy and urgency scale fixed so Ollama's prompt cache is reused.
- Set `num_ctx` to 4096 for the analysis call; complaints are short.
- Python: `pip install ollama`, call `ollama.chat(model, messages, format=schema, images=[...])`.
- If Ollama is down or times out, the complaint goes straight to the human review queue with status "awaiting analysis". Never drop it.

### 2.2 Small local models

| Job | Model | Size | Why | Note |
|---|---|---|---|---|
| Sentence embeddings (duplicates, second-opinion classifier) | **bge-m3** served by Ollama (`bge-m3`, 567M params, 1024-dim) | ~1.2 GB | Strongest open multilingual embedding model; covers Tamil and Hindi; same Ollama runtime as Gemma | At runtime the embed call passes `num_gpu: 0` so bge-m3 runs on CPU and Gemma keeps the 4 GB card; training uses the GPU |
| Language hint | Unicode script detection (pure Python) | 0 | Tamil script -> ta, Devanagari -> hi, Latin -> English or romanised; three languages need nothing heavier | The LLM makes the final call, including Tanglish vs English |
| Second-opinion classifier | Softmax regression written in NumPy, trained on bge-m3 embeddings | KB | Trains in seconds on 300-500 synthetic examples; independent of the LLM | Saved as `models/second_opinion_*.npz` |

Why not sentence-transformers, fastText or scikit-learn: Windows Application Control on the build laptop blocks unsigned native DLLs (torch and scipy fail to load). NumPy, pandas and Pillow load fine. So every model goes through Ollama and the Python side stays pure.

Caveats:
- Script detection cannot tell Tanglish from English (both Latin letters). It is a hint; the LLM makes the final language call and returns primary and secondary language.
- Embedding models are weaker on romanised text. Embed the LLM's English summary plus the resolved location for duplicate search, not the raw text.

### 2.3 Optional local models (only if time)

| Job | Model | Size | Notes |
|---|---|---|---|
| Better Indic-to-English translation for staff | `ai4bharat/indictrans2-indic-en-dist-200M` | ~0.9 GB | The LLM already translates; use this only if its Tamil output is weak |
| Named entities in Indic scripts | `ai4bharat/IndicNER` | ~1 GB | The LLM already extracts entities |
| Speech to text (stretch) | `openai/whisper-base` via `faster-whisper` | ~150 MB | Voice intake only |
| Fine-tuned classifier (after hackathon) | `ai4bharat/IndicBERTv2-MLM-only` or `xlm-roberta-base` | ~1.1 GB | Train on the corrections log |

### 2.4 Not models, but needed

| Job | Tool | Local? | Notes |
|---|---|---|---|
| PII masking | Regex: Aadhaar (12 digits), PAN, 10-digit mobile, email, PIN code, plus LLM entity list | yes | No Presidio; its spaCy model is 500 MB for English only |
| Photo GPS | `Pillow` (EXIF) | yes | In-app camera capture sends GPS from the browser instead |
| Current location button | Browser Geolocation API | yes (device) | Needs HTTPS or localhost |
| Reverse geocoding (lat/lng to place) | Nearest locality from `config/places_tn.csv` (haversine, offline, pure Python) | yes | 45 Coimbatore localities and major Tamil Nadu cities; add rows freely. `reverse_geocoder` needs scipy, which is blocked here. OpenStreetMap Nominatim is a free non-AI web service and can be switched on by a flag if street-level addresses are wanted for the demo |
| Map display | Leaflet.js | yes (library) | Tiles come from OpenStreetMap over the web; offline fallback is a plain coordinate display |
| Email for OTP and status | **Mailpit** (local SMTP server with a web inbox) | yes | Perfect for the demo: OTP emails appear in a local inbox at `localhost:8025`. Switch to a real SMTP server by env var for production |
| Password hashing | `argon2-cffi` | yes | 8+ chars, mixed case, digit, symbol |
| Video key frame | Browser canvas grab before upload | yes | No ffmpeg on the server; full video stored for staff |
| Transliteration (optional) | `indic-transliteration` pip | yes | Rule-based; the LLM handles most of it |

---

## 3. Datasets

No public dataset matches the exact task (multilingual civic complaint + urgency + evidence). The plan: build a small gold set ourselves, generate a synthetic training set with the local LLM, and use public data for realism and language-detection tests.

### 3.1 Build ourselves

**SYNAPSE eval set** (gold, 60 complaints): 15 each in English, Tamil, Hindi and code-mixed, covering all 8 departments and 4 urgency levels, with formal and informal versions of the same complaint. Hand-labelled by team members fluent in each language. Stored as `data/eval/complaints.jsonl`. Start in hour 1. Feeds the fairness dashboard.

**SYNAPSE synthetic set** (300-500 complaints): generated by the local LLM from a prompt that fixes department, urgency, language, formality and a buried-signal flag. Used only to train the embedding classifier and to smoke-test the pipeline. Stored as `data/synthetic/complaints.jsonl`. Generate overnight on CPU or in minutes on GPU.

Planted cases inside the eval set: 6 near-duplicate pairs, 5 incomplete-contact cases, 4 complaints where the photo contradicts the text.

### 3.2 Public datasets to download

| Dataset | Source | What it is | Use for us | Size |
|---|---|---|---|---|
| **AIKOSH Champions Dataset 2024-25** | aikosh.indiaai.gov.in (Open Government License India) | Masked MSME grievance records with category, description, final reply | Real Indian grievance phrasing for few-shot examples and prompt testing; English | 6 MB CSV |
| **CivicNLP-608** | IEEE DataPort, DOI 10.21227/13nz-rt85 | 608 civic complaints, English and Marathi, 8 categories (water, electricity, roads, garbage, street lights...) | Closest domain match; taxonomy sanity check and category accuracy test | small; check access |
| **Tamil Nadu district / department mapping** (team-provided) | `data/reference/tn_district_department_mapping.xlsx`, imported to `config/tn_mapping.json` by `scripts/import_tn_mapping.py` | 38 districts, 20 departments with grievance scope, 760 district-office rows with SLA hours, 41 keyword rules in English and Tamil | Routes each complaint to a named district office and sets a due time from the SLA scaled by urgency; keyword rules pick the specific office (for example Street Lighting under Roads). The 20 departments are mapped onto our 8 model categories so nothing trained changes. The sheet marks its categories as demo values to verify. | small |
| **NYC 311 Service Requests** (downloaded) | NYC Open Data, dataset `erm2-nwe9` | Civic complaints with complaint type, descriptor, agency, location | 3,000-row sample for routing-rule ideas and extra English department training rows; mapped to our taxonomy in `train_second_opinion.py` | 0.4 MB, `data/raw/nyc311_sample.csv` |
| **COMI-LINGUA** (downloaded) | Hugging Face `LingoIITGN/COMI-LINGUA` | Expert-annotated Hindi-English code-mixed sentences: `LID_train/test.csv` (token-level language ID, 30K rows), `MLI_train/test.csv` (matrix language, 26K rows), `MT_train/test.csv` (Hinglish to English translation, 25K rows) | Test language detection and translation on Hinglish; few-shot Hinglish examples | 185 MB in `data/raw/comi_lingua/` |
| **DravidianCodeMix Tamil-English** (downloaded) | Hugging Face mirror `IsaacRodgz/DravidianCodeMix-Dataset` (FIRE 2020) | 35K train, 4.4K dev, 4.4K test Tamil-English code-mixed YouTube comments with sentiment labels, Tamil script and romanised | Tanglish samples for language-detection and normalisation tests; sentiment labels unused | 3 parquet files in `data/raw/dravidian_codemix/`, read with `pandas.read_parquet` |
| **L3Cube-HingLID** | GitHub l3cube-pune | Hindi-English code-mixed language identification corpus | Second Hinglish LID test set, only if COMI-LINGUA is not enough | small |
| **Citizen complaints on Twitter (India)** | Mendeley Data `w2cp7h53s5` | Complaint vs non-complaint tweets at Indian government accounts | Short informal complaint phrasing; spam-vs-genuine examples | SQL dump |

Skip: CFPB Consumer Complaint Database (US financial; only relevant for a corporate deployment).

---

## 4. Download checklist (do this first, on the best machine)

Ollama and the LLM:

```bash
winget install Ollama.Ollama
```

```bash
ollama pull gemma3:4b
```

Pull `gemma3:12b` instead on a machine with a 12 GB+ GPU.

Embedding model (also through Ollama):

```bash
ollama pull bge-m3
```

Python packages (pure Python plus NumPy, pandas, Pillow):

```bash
pip install -r requirements.txt
```

Mailpit (local SMTP + web inbox): download the Windows binary from the Mailpit GitHub releases page, run `mailpit.exe`, inbox at `http://localhost:8025`, SMTP on port 1025.

NYC 311 sample:

```bash
curl -L "https://data.cityofnewyork.us/resource/erm2-nwe9.csv?\$limit=2000" -o data/raw/nyc311_sample.csv
```

COMI-LINGUA (check the dataset card for config names):

```python
from datasets import load_dataset
ds = load_dataset("LingoIITGN/COMI-LINGUA", "LID")
```

AIKOSH, CivicNLP-608, Mendeley and DravidianCodeMix are manual downloads; put them under `data/raw/`.

Smoke test once pulled:

```bash
ollama run gemma3:4b "Classify this complaint into one of: water, electricity, roads. Reply with JSON. Complaint: thanni 3 days ah varala, kids are sick"
```

---

## 5. Decision summary

| Need | Decision |
|---|---|
| Core NLP and vision | Gemma 3 (4B on laptop, 12B on GPU) via Ollama, JSON-schema output |
| Language detection | Script detection hint + LLM final call |
| Duplicates | bge-m3 (Ollama) embeddings on the English summary + location match |
| Second opinion | NumPy softmax regression on bge-m3 embeddings, trained on synthetic data |
| PII | Regex + LLM entities |
| Location | Browser Geolocation, EXIF, offline nearest locality from `places_tn.csv`, Leaflet map; Nominatim behind a flag |
| Email | Mailpit locally for the demo; real SMTP by env var |
| Auth | argon2 hashing, 6-digit email OTP, 10-minute expiry |
| Evaluation data | 60-complaint gold set by the team; 300-500 synthetic; public sets for realism and LID tests |
| Cloud AI APIs | None |
