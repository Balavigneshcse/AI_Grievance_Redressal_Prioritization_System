# Vindex: demo runbook for the final jury review (16 Oct 2026, 09:45)

Five minutes of clicks, in order. Everything runs on the laptop; nothing leaves it except the status emails.

## Before the slot (15 minutes earlier)

1. Start everything: `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` (add `-Https` if a phone will be used; then open `https://<laptop-ip>:8000/health` on the phone once and accept the warning).
2. Fresh demo data: `python scripts\demo_data.py --reset --staff --seed` (about four minutes: ten complaints go through the real pipeline). Skip `--reset` if you want to keep what is already there.
3. Check `http://localhost:8000/health`: `db ok`, `ollama ok`, all three models `true`, `outbox_pending 0`.
4. Open four browser tabs, logged in as: citizen (`citizen@synapse.local`), department admin (`officer.water@synapse.local`), district admin (`district.coimbatore@synapse.local`), super admin (`admin@synapse.local`). Password: `SEED_PASSWORD` from `.env`. Mail inbox: `http://localhost:8025` (or the real Gmail inbox if `.env` points at Gmail).

## The story (one complaint, end to end)

| Step | Tab | Do | Say |
|---|---|---|---|
| 1 | Citizen | New complaint. Type in Tanglish: `thanni 3 days ah varala, veetla 2 kids vomiting, Gandhipuram 5th street`. Fill name and Aadhaar last 4. Camera: switch to Video, record 5 seconds, stop. Use current location. Submit. | Any language, any script, photo or video evidence, GPS. Tracking ID in under a second. |
| 2 | Citizen | Open "Track it". Watch Analysing turn into Under review with department, urgency, evidence highlighted in the original text, the office and the due time. | One local model call (Gemma 3 on this laptop), no cloud. Rules overrode "health" to Water Supply and forced a human because children are ill. |
| 3 | District admin | Queue, "Needs review". Open the complaint. Accept with a reason. | A human decides every uncertain or critical case. The reason is mandatory and becomes part of the audit trail. |
| 4 | Department admin | Queue, "Active work". The complaint is there (only water, only Coimbatore). Accept (starts work), then Request info: "Please share the door number". | Each department sees only its own cases. The citizen is emailed in Tamil. |
| 5 | Citizen | Track page shows "The office needs more information" with the question. Reply with a line and a photo. | The reply goes straight to the department and the case continues. |
| 6 | Department admin | Add a resolution photo, then Resolve with a note. | The citizen gets the status mail with the note translated into Tamil, and sees the proof photo on the tracking page. |
| 6b | Citizen | Track page: rate it with stars, or press "Not fixed, reopen". | The loop closes with the citizen, not with the office. |
| 6c | Citizen (second account) | New complaint, set the same location: the nearby list shows the case; press Support. | Duplicates become support; five supporters raise the priority. |
| 7 | Super admin | Map: markers by urgency, red ring for overdue. Admin: staff per district. Metrics: accuracy per language, rating, reopen rate. Rules: paste `gas leak near school`, Test. | Config, not code: rules are hot-reloaded; the classifier reloads with one click. |
| 8 | Super admin | Queue, "All complaints": point at an `Overdue` badge (one seeded complaint is past its due time) and the escalation note in its timeline. | SLA due times from the Tamil Nadu office mapping; breaches escalate to the district admin by email. |

## Numbers to have ready

- Gold set with rules: department 100%, critical recall 100%, language ID 92% (raw 4B model: 75% / 75% / 92%).
- Second-opinion classifier, held-out after round 3 (1,169 synthetic + gold + NYC rows, 1,392 in all): department 88% (English 93%, Hinglish 93%, Hindi 84%, Tanglish 84%, Tamil 78%), urgency 56%.
- End-to-end suite: 77+ checks green; analysis 12 to 20 s per complaint on an RTX 3050 4 GB; tracking ID in under 1 s.
- Mail: outbox with one persistent connection; 70 mails in one test run, none failed.

## If something goes wrong

- Analysis stuck on "Analysing": `http://localhost:8000/health` shows `queue_depth`; Ollama may be loading, wait 20 s. A model error never loses a complaint: it lands in the review queue as "awaiting analysis".
- No email: the API console prints `email ... sent` or `FAILED ... reason`. Switch to Mailpit by setting `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_TLS=false`, empty user and password, then restart the API.
- Phone camera does not open: the page must be `https://` (use `-Https`) and the certificate warning must have been accepted for both ports.
- Model stuck or every call takes a minute: a cancelled generator run or timed-out requests leave Ollama replaying a queue. Run `taskkill /IM llama-server.exe /F` then `taskkill /IM ollama.exe /F`; the tray app starts it again (otherwise run `ollama serve`). Never run `make_synthetic.py` during the demo: Ollama serves one request at a time and the generator takes it for 25 s per call.
- Model slower than this afternoon: other apps are holding graphics memory (browsers, WhatsApp, widgets). Close them and reload the model; `curl localhost:11434/api/ps` shows how much of Gemma sits in VRAM (2.8 GB is the good case, 1.6 GB the slow one).
- Port 8000 busy: `netstat -ano | findstr :8000`, then `taskkill /PID <pid> /F`.

## Questions the jury may ask

- Why local models: privacy (complaints carry names, addresses, Aadhaar digits), zero per-request cost, works without internet; Gemma 3 4B is the largest model a 4 GB card serves with vision.
- Why rules on top of the model: deterministic safety floors (gas leak, oxygen, children), auditable, editable by the super admin without redeploy; model + rules + second opinion disagree → human.
- Fairness: formality and language never change urgency; accuracy is measured per language on the dashboard; informal writers get the same service.
- Scale: stateless API, state in Postgres, one worker per GPU; config (departments, rules, 760 offices) not code; HNSW index keeps duplicate search fast.
- Pending: WhatsApp intake, video key frames to the model, verified office mapping from the municipality, fine-tuning on officer corrections.
