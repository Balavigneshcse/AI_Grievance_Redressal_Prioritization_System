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

| Job | Model | Size | Why | Fallback |
|---|---|---|---|---|
| Language pre-detection | `facebook/fasttext-language-identification` (lid.176) | 130 MB (bin) or 1 MB (ftz) | 176 languages, sub-millisecond, CPU | `lingua-language-detector` (pure Python) |
| Sentence embeddings (duplicates, second-opinion classifier) | `intfloat/multilingual-e5-small` | ~470 MB | 100 languages including Tamil and Hindi, fast on CPU | `BAAI/bge-m3` (~2.2 GB) on a GPU machine |
| Second-opinion classifier | scikit-learn `LogisticRegression` on e5 embeddings | KB | Trains in seconds on 300-500 synthetic examples; independent of the LLM | none needed |

Caveats:
- fastText misreads romanised Tamil and Hindi (Tanglish, Hinglish) as English or another Latin-script language. It is a hint; the LLM makes the final language call and returns primary and secondary language.
- Embedding models are weaker on romanised text. Embed the LLM's English summary plus the resolved location for duplicate search, not the raw text.
- `paraphrase-multilingual-MiniLM-L12-v2` does not cover Tamil. Do not use it.

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
| Reverse geocoding (lat/lng to place) | `reverse_geocoder` pip (GeoNames, offline, city level) | yes | Ward level: a local GeoJSON of ward polygons + `shapely` point-in-polygon if the team can get one. OpenStreetMap Nominatim is a free non-AI web service and can be switched on by a flag if street-level addresses are wanted for the demo |
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
| **NYC 311 Service Requests** | NYC Open Data, dataset `erm2-nwe9` | Civic complaints with complaint type, agency, location | 2,000-row sample for routing-rule ideas and category coverage; English | 1-2 MB |
| **COMI-LINGUA** | Hugging Face `LingoIITGN/COMI-LINGUA` | 125K+ expert-annotated Hindi-English code-mixed instances: language ID, NER, POS, translation | Test language detection and entity extraction on Hinglish | tens of MB |
| **L3Cube-HingLID** | GitHub l3cube-pune | Hindi-English code-mixed language identification corpus | Second Hinglish LID test set | small |
| **DravidianCodeMix (Tamil-English)** | FIRE 2020 shared task | Tamil-English code-mixed YouTube comments | Tanglish samples for language-detection and normalisation tests; labels unused | small; verify link |
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

Python packages:

```bash
pip install ollama sentence-transformers fasttext-wheel lingua-language-detector scikit-learn pillow reverse_geocoder argon2-cffi huggingface_hub datasets
```

Small models (cached by Hugging Face on first use):

```python
from huggingface_hub import hf_hub_download
hf_hub_download("facebook/fasttext-language-identification", "model.bin")

from sentence_transformers import SentenceTransformer
SentenceTransformer("intfloat/multilingual-e5-small")
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
| Language detection | fastText hint + LLM final call |
| Duplicates | multilingual-e5-small embeddings on the English summary + location match |
| Second opinion | Logistic regression on e5 embeddings, trained on synthetic data |
| PII | Regex + LLM entities |
| Location | Browser Geolocation, EXIF, offline reverse_geocoder, Leaflet map; Nominatim behind a flag |
| Email | Mailpit locally for the demo; real SMTP by env var |
| Auth | argon2 hashing, 6-digit email OTP, 10-minute expiry |
| Evaluation data | 60-complaint gold set by the team; 300-500 synthetic; public sets for realism and LID tests |
| Cloud AI APIs | None |
