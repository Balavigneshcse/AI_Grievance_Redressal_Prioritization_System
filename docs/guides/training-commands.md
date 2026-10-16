# Training and evaluation commands

Run everything from the project root in a normal Command Prompt or PowerShell. The system Python 3.12 is used directly (no venv: Windows Application Control blocks torch and scipy, so the scripts only need NumPy, pandas, Pillow and the Ollama client).

## 0. One-time setup

```bash
pip install -r requirements.txt
```

Database and mail inbox (PostgreSQL 17 + pgvector on port 5434, Mailpit on 8025). Copy `.env.example` to `.env` first.

```bash
docker compose up -d
```

```bash
powershell -ExecutionPolicy Bypass -File scripts\setup\set_ollama_gpu.ps1
```

```bash
python scripts\setup\download_models.py
```

Pulls `gemma3:4b` and `bge-m3` if missing, then prints an embedding check, language hints and a geocoder check.

## 1. Datasets

```bash
python scripts\setup\download_datasets.py
```

Fetches the NYC 311 sample and COMI-LINGUA files, lists Tamil-English candidates, and prints the manual-download list.

## 2. Generate the synthetic training set (uses Gemma on the GPU)

```bash
python scripts\training\make_synthetic.py --per-combo 3
```

8 departments x 4 urgency levels x 5 language codes = 160 calls, 3 complaints each, about 480 rows. Measured: about 27 s per call on Gemma, so 75-95 minutes on the RTX 3050. Run it while the team works on other things; it is resumable, stop it any time and rerun. For a quick first pass:

```bash
python scripts\training\make_synthetic.py --per-combo 1 --langs en,ta-en
```

Twice as fast, using the text-only Qwen already on the laptop (fine for generating training text):

```bash
python scripts\training\make_synthetic.py --per-combo 3 --model qwen3:4b-instruct-2507-q4_K_M
```

## 2b. Clean the synthetic set (after generation finishes)

```bash
python scripts\training\clean_synthetic.py
```

Drops rows whose text is not in the script their language label promises (the LLM ignores the language instruction in roughly 7% of calls) and exact duplicates. Keeps a `.bak` copy. Rerun `make_synthetic.py` afterwards to regenerate the dropped combinations; new runs apply the same check automatically.

## 2c. Round 2 and later: more training data

The generator skips every department x urgency x language combination already present in its output file, so a second round goes to a new file and is merged afterwards:

```bash
python scripts\training\make_synthetic.py --per-combo 3 --out data\synthetic\complaints_round2.jsonl
```

```bash
python scripts\training\clean_synthetic.py --file data\synthetic\complaints_round2.jsonl
```

```bash
python -c "import shutil; shutil.copyfileobj(open('data/synthetic/complaints_round2.jsonl','rb'), open('data/synthetic/complaints.jsonl','ab'))"
```

Then step 3 (train) and step 4 (evaluate). Restart the API afterwards, or call `POST /admin/models/reload` as the super admin, so the new classifier is used. While generation runs, complaint analysis in the app is about twice as slow because both share the GPU.

## 3. Train the second-opinion classifier

```bash
python scripts\training\train_second_opinion.py
```

Embeds every row with bge-m3 (GPU), trains the department and urgency softmax models, prints held-out accuracy overall and per language, and saves `models/second_opinion_*.npz` plus `models/second_opinion_report.json`.

Run it only after generation has finished: with a partial file the models see one or two departments and the urgency numbers are meaningless (a run at 51 water-only rows gave 0.31 on urgency). The script prints a warning in that case. Do not run it while `make_synthetic.py` is still going; both need the GPU and Ollama serves one request at a time.

## 4. Evaluate the LLM on the gold set

```bash
python scripts\evaluation\run_eval.py
```

Replays `data/eval/complaints.jsonl` through Gemma and writes `data/eval/summary_gemma3_4b.json` with department accuracy, urgency accuracy, critical recall, accuracy per language and per formality, and mean latency. Compare with the text-only Qwen already on the laptop:

```bash
python scripts\evaluation\run_eval.py --model qwen3:4b-instruct-2507-q4_K_M
```

## 5. One complaint by hand

```bash
python scripts\evaluation\smoke_test_llm.py --text "road la periya kuzhi, bike skid aagudhu, Gandhipuram"
```

```bash
python scripts\evaluation\smoke_test_llm.py --image photo.jpg --text "see this"
```

## What is trained and what is not

| Model | Trained by us? | Role |
|---|---|---|
| Gemma 3 4B (Ollama) | No, prompted with our taxonomy and urgency scale, JSON-schema output | text + image understanding |
| bge-m3 (Ollama) | No | sentence embeddings |
| Softmax regression (NumPy) | **Yes**, step 3 | second opinion on department and urgency; disagreement with Gemma sends the case to review |
| Script-based language hint | No, rule | Tamil / Devanagari / Latin |
