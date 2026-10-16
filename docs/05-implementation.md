# SYNAPSE: Technical Implementation

## Phase 4 - Checkpoint 4

Covers: what is built, how it runs, the API, and the evidence from the first end-to-end run.

Date: 15 October 2026 | Status: backend and frontend complete and tested end to end

---

## 1. What is built

| Layer | Location | State |
|---|---|---|
| API server | `backend/app/main.py` (FastAPI, 30 routes, OpenAPI at `/docs`) | complete |
| Database | `backend/app/models.py` (SQLAlchemy 2, 11 tables, pgvector column + HNSW index), `backend/app/db.py` (create, seed departments in en/ta/hi) | complete |
| Auth | `backend/app/api/auth.py`, `backend/app/security.py`: register with mobile + email + strong password, email OTP (hashed, 10 min, 5 attempts), login, forgot/reset by OTP, JWT with password-version invalidation | complete |
| Complaint intake | `backend/app/api/complaints.py`: multipart text + photos/videos + GPS or manual address, EXIF GPS fallback, tracking ID, acknowledgement email, media served through an authenticated route | complete |
| Analysis worker | `backend/app/services/worker.py` + `pipeline.py`: one background thread; language hint, PII mask, offline geocode, Gemma 3 (text + first photo) with JSON schema, bge-m3 embedding, pgvector duplicate search, NumPy second opinion, YAML rules, decision, status event, email | complete |
| Rules engine | `backend/app/services/rules.py`, `config/rules.yaml`: 12 rules in English, Tamil, Hindi and romanised forms (gas leak, medical dependency on power, exposed wires, fire or collapse, water supply, street lights, sewage into homes, disease clusters, repeat complaints, revenue papers, children or elderly at risk, rescue of a person or animal from a well, borewell, pit or lift, and snakes, bee hives or wild animals inside a home, the last two added 16 Oct for Fire & Rescue); hot reload; admin test endpoint | complete |
| District office routing | `config/tn_mapping.json` from the team's Tamil Nadu spreadsheet (38 districts, 20 departments mapped onto our 8 categories, 760 offices with SLA, 41 keyword hints): each complaint gets a district, a named office and a due time | complete |
| Officer review | `backend/app/api/review.py`: review queue sorted by urgency then age with flags, department queues, accept / reassign / merge / request info / resolve / close / reopen with mandatory reason, override log, status emails | complete |
| Admin | `backend/app/api/admin.py`: read/write rules with change log, rule tester, metrics (totals, by status, by department, live accuracy per language from officer corrections, eval runs, second-opinion report) | complete |
| Notifications | `backend/app/services/notifier.py`: OTP, acknowledgement, routed, under review, status templates in en/ta/hi; every send logged | complete |
| Local services | `docker-compose.yml`: PostgreSQL 17 + pgvector (port 5434), Mailpit (8025/1025) | running |
| Seed | `backend/seed.py`: super admin, Coimbatore district admin, two Coimbatore department admins (water, roads), one citizen | done |
| Frontend | `frontend/` (React 18 + Vite, Tailwind v4, shadcn/ui on Base UI, lucide-react, react-router, react-hook-form + zod, i18next en/ta/hi, react-leaflet): register, OTP verify, login, forgot/reset, my complaints, new complaint with in-app camera, GPS, map pin, reverse geocode and bottom sheet, track page with 3 s polling, evidence highlighting and timeline, officer queue with filters and flags, officer workspace with accept / reassign / merge / request-info dialogs; `npm run build` passes | complete, verified in the browser against the live API (15 Oct 15:25) |

---

## 2. Running it

```bash
docker compose up -d
```

```bash
cd backend && python seed.py && python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

Open `http://localhost:8000/docs` for the API, `http://localhost:8025` for the mail inbox, `http://localhost:5173` for the app. Seed accounts (password from `SEED_PASSWORD` in `.env`): `admin@synapse.local` (super admin), `district.coimbatore@synapse.local` (district admin, Coimbatore), `officer.water@synapse.local` and `officer.roads@synapse.local` (department admins, Coimbatore), `citizen@synapse.local`.

---

## 3. API

| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | `/auth/register` | public | name, Aadhaar last 4, mobile, email, password, language; sends OTP |
| POST | `/auth/verify-otp` | public | activates the account, returns JWT |
| POST | `/auth/resend-otp` | public | new registration code |
| POST | `/auth/login` | public | JWT; 403 if unverified |
| POST | `/auth/forgot`, `/auth/reset` | public | password reset by OTP; invalidates old sessions |
| GET | `/auth/me` | any | current user |
| PATCH | `/auth/me` | any | change name, Aadhaar last 4 or mail language; accounts from before 16 Oct complete their details here |
| GET | `/departments` | public | ids and names in three languages |
| POST | `/complaints` | complainant | multipart intake, returns 202 + tracking ID, queues analysis |
| GET | `/complaints/mine` | complainant | own complaints |
| GET | `/complaints/{id}`, `/complaints/track/{tracking_id}`, `/complaints/{id}/timeline` | owner or staff | detail with analysis, decision, timeline; PII and second opinion only for staff |
| GET | `/media/{id}` | owner or staff | photo or video file |
| POST | `/geo/reverse` | public | lat/lng to nearest locality |
| GET | `/review/queue` | staff | complaints in the caller's scope; `view=review|active|resolved|all`, filters by department, urgency, language, district, `q` text search; sorted by urgency then supporters |
| GET | `/departments/{dept}/queue` | staff (own department for department admins) | routed, in-progress and awaiting-info complaints |
| GET | `/review/{id}` | staff, inside scope | full detail including masked text, PII map, complainant name and Aadhaar last 4 |
| POST | `/review/{id}/decision` | staff, inside scope | accept, reassign, merge, request_info, resolve, close, reopen; reason required |
| GET, POST | `/admin/users` | super admin, district admin | list and create staff accounts (district admin: department admins of own district only); the generated password is returned once |
| PATCH | `/admin/users/{id}` | super admin, district admin | enable or disable, rename, move department, reset password |
| GET | `/admin/districts` | staff | the 38 Tamil Nadu districts with staff counts |
| GET | `/admin/overview` | super admin, district admin | complaint counts per district and department |
| POST | `/complaints/{id}/reply` | complainant (owner) | answer a request for information or add details, with photos or videos; an awaiting-info case resumes; the office is emailed |
| POST | `/admin/sla/check` | super admin | escalate overdue complaints now (the worker does it every minute) |
| POST | `/complaints/{id}/feedback` | complainant | after resolution: rating 1-5 with a note, or reopen (back to in progress, department emailed); allowed for `REOPEN_WINDOW_DAYS` |
| POST | `/complaints/{id}/support` | any citizen but the owner | "me too" on an open complaint; `SUPPORT_BOOST_AT` supporters raise urgency one level |
| GET | `/complaints/nearby?lat&lng` | citizen | open complaints within `NEARBY_KM`, nearest first, no personal data |
| GET | `/complaints/supported` | citizen | complaints the caller supports |
| POST | `/review/{id}/attachments` | staff, inside scope | resolution proof photos or videos (media role `resolution`) |
| GET | `/admin/map?view=open|all` | staff | located complaints in scope for the map |
| GET, PUT | `/admin/rules` | super admin (read: all staff) | YAML rules with change log |
| POST | `/admin/rules/test` | staff | run the rules against a text |
| POST | `/admin/models/reload` | super admin | pick up a newly trained second-opinion model |
| GET | `/admin/metrics` | staff | dashboard data |
| GET | `/health` | public | db, Ollama, models, queue depth |

---

## 4. Evidence: first end-to-end run (15 Oct 2026, 14:20)

Driven by a script against the live API with Gemma sharing the GPU with the synthetic-data generator.

| Step | Result |
|---|---|
| `/health` | db ok, Ollama ok, gemma3:4b, bge-m3 and second-opinion model present |
| Register (Tamil preferred) | 201; OTP email arrived in Mailpit with a Tamil subject |
| Verify OTP | 200, JWT issued |
| File complaint: "thanni 3 days ah varala sir. veetla 2 kids irukanga, rendu perum vomiting and fever. Anna Nagar 4th street ... my number 98xxxxxxxx", with browser GPS | 202, tracking ID SYN-2026-000001, acknowledgement email sent |
| Worker | 50 s wall clock (Gemma 38 s while the generator held the GPU); language ta+en; model said health, critical, 0.95; evidence spans copied verbatim from the Tanglish text; place resolved to Gandhipuram, Coimbatore |
| Rules | R5 water keyword forced department Water Supply; R8 repeat complaint raised the floor |
| Decision | review queue, reasons: rule overrides model department, critical always checked |
| PII | citizen response has no PII map; officer response shows `[PHONE_1]` mapped to the number and the masked text |
| Officer | queue shows the complaint with flags critical and disagreement; reassign to Water / Critical with reason; status routed; routed email sent in Tamil |
| Admin metrics | 1 complaint, 1 critical open, review rate 1.0, auto-closed 0, live accuracy for ta recorded the correction as a model miss |
| Mail | 4 emails to the citizen: OTP, acknowledgement, under review, routed |

**Second run (14:48), after the Tamil Nadu office mapping was added.** A Hinglish street-light complaint with Ukkadam GPS, filed twice:

| Step | Result |
|---|---|
| Model | said Safety (women feel unsafe in the dark), Medium, confidence 0.95 |
| Rule R5b (street light, three languages) | overrode department to Roads; the override is a disagreement, so the complaint went to review instead of auto-routing |
| District office | district Coimbatore from the locality; keyword RR008 picked the Street Lighting office rather than the Roads default; due time set 24 h out for Medium |
| Duplicate detection | the second filing matched the first at similarity 1.00 and was flagged as a possible duplicate |
| Officer queue | shows the complaint with flags disagreement and duplicate, office name and due time |

Together the two runs cover every Phase 1 problem except photo evidence, which is implemented (first photo goes to the model, EXIF GPS read) and will be shown live.

---

## 5. Known limits at this checkpoint

- Latency per complaint is 17-20 s with the GPU free, more while training or generation runs; the UI shows an "analysing" state.
- Notifications are email only (OTP, acknowledgement, under review, routed, resolved). No SMS. WhatsApp intake and notifications are in the roadmap and deliberately not built.
- Video: the file is stored and served; only photos go to the model. Key-frame extraction is a stretch.
- Rules editor UI, dashboard charts and department queue screens are after the core complainant and officer flows.
- No automated tests beyond the end-to-end script and `scripts/run_eval.py` yet.

---

## 6. Day 1 evening: roles, identity, video evidence, async mail (15 Oct 2026, 18:00-19:30)

### Role hierarchy

| Role | Scope | Can do |
|---|---|---|
| `super_admin` | all districts | create district admins and any staff account, rules editor, metrics, model reload, every complaint |
| `district_admin` | one Tamil Nadu district | review queue of the district (cases that need a human), add departments by creating their department admins, disable them |
| `dept_admin` | one department in one district | sees only that department's complaints in that district: accept (starts work), request info, resolve, close, reassign, merge |
| `complainant` | own complaints | file, track, reply |

Scoping lives in `backend/app/api/deps.py` (`scope_complaints`, `can_access`) and is applied by every review route, the detail route and the media route. A department admin opening another department's complaint gets 403. Disabling an account bumps its password version, which ends every open session. The migration in `db.py` renames the day-1 roles (`admin` → `super_admin`, `officer` → `dept_admin`) and adds `users.district`, `users.full_name`, `users.is_active`.

Frontend: `/admin` (super and district admins) lists staff with an active switch, shows complaint counts per district, and creates accounts in a dialog; the generated password is shown once with a copy button. The queue page has four views (needs review, active work, resolved, all), is scoped by role, and refreshes itself every 5 s, so a department admin sees a new routed complaint without reloading.

### Complaint identity

The citizen's full name and the last four digits of their Aadhaar number are taken once, at registration (`users.full_name`, `users.aadhaar_last4`; the API rejects a registration without them or with anything but four digits). Every complaint copies them at intake into `complaints.complainant_name` and `complaints.aadhaar_last4`, so the office sees them on the queue and the detail page, the citizen sees them on the tracking page, and the model never does: it only sees the masked complaint text. The complaint form shows a "Filing as" line from the account instead of asking again. Accounts created before 16 Oct are backfilled at start-up from their latest complaint; one that never filed sees a one-time "Complete your account" card on the form, which saves through `PATCH /auth/me`. An account without the details gets 400 on submit.

### Video evidence

The camera dialog has a video mode: MediaRecorder at 1.5 Mbit/s with sound when a microphone is available, a running clock, and an automatic stop at 5 minutes. Limits, enforced on both sides: photos up to 25 MB, videos up to 100 MB and 300 s (`MAX_PHOTO_MB`, `MAX_VIDEO_MB`, `MAX_VIDEO_SECONDS`). Uploads are streamed to disk in 1 MB pieces so a 100 MB video never sits in memory. Videos are evidence for the office; the model still reads only the first photo.

### Performance

- Mail is asynchronous: `notify()` writes a `queued` row and an outbox thread (`services/notifier.py`) delivers it through one persistent SMTP connection, with three attempts and the reason stored on failure. Registration, intake and the analysis worker no longer wait 7-10 s per email on a slow network.
- Gemma and bge-m3 are warmed at startup and kept loaded (`LLM_KEEP_ALIVE=2h`), so the first complaint after a restart does not pay the model load.
- The worker logs the time per complaint and the model share of it; the API logs which mail server it uses at startup and every send.

### Console fixes

Google Fonts were removed (the hackathon network closes those connections); the UI uses the system fonts that ship with Windows and Android and cover Tamil and Devanagari. The two `Button`s that render a router `Link` now pass `nativeButton={false}`, which clears the Base UI warning.

---

## 7. Closing the loops (15 Oct 2026, 20:00-21:30)

| Loop | What was missing | What exists now |
|---|---|---|
| Citizen reply | A request for information was a dead end | `POST /complaints/{id}/reply` with text and up to four photos or videos; the Track page shows the office's question and a reply box; an awaiting-info case goes back to the status it came from; the department (or the district admin for a reviewed case) is emailed; the citizen gets a status mail |
| Staff emails | Only citizens were emailed | `notify_staff()` in `services/notifier.py`: `staff_routed` to the department admins of the complaint's department and district (routing, reassignment, reviewer acceptance), `staff_review` to the district admin (or super admins when the district has none), `staff_reply`, `overdue`; all three languages |
| SLA | Due times existed but nothing watched them | `services/sla.py`: every minute the worker escalates open complaints past `due_at` once (timeline event, `escalated_at`, emails to district and department admins); the queue shows an `overdue` flag and the time left or exceeded; the Track page shows an escalation notice; `POST /admin/sla/check` runs it on demand |
| Admin pages | Rules and metrics only through the API | `/admin/rules` (rule list, YAML editor with change note, rule tester, classifier reload; read-only for district admins) and `/admin/metrics` (totals, live health, bars by status and department, live accuracy per language, second-opinion report, gold-set evaluation runs; refreshes every 10 s) |
| Vision input | Only the first photo reached the model | Up to three photos per complaint are sent to Gemma 3 |
| Health | `db`, `ollama`, models, queue depth | plus `model_latency_ms` (last and mean of the last 10), `outbox_pending`, `overdue_open` |

### Demo tooling

- `scripts/demo_data.py --reset --districts --staff --seed`: wipes complaints, their media and the test accounts (the me-too `supports` rows included), creates one district admin for each of the 38 Tamil Nadu districts (`district.<district>@synapse.local`, password `SEED_PASSWORD`, skipped when present) plus the Chennai and Madurai demo staff, files ten showcase complaints in five languages across Coimbatore, Chennai, Madurai, Salem and Tiruchirappalli through the real pipeline, then accepts, questions and resolves a few so every queue view has content, and sets one past its due time and runs the SLA check so the overdue path is on screen.
- `scripts/record_demo.py`: records the demo video. Playwright drives Google Chrome (headless, Chrome's test camera for the in-app video, device location set to Gandhipuram) through registration, filing, tracking, review, department work, the citizen's reply, proof and rating, me-too support, search, map, staff, metrics, rules and the Tamil interface, logging a caption per step; ffmpeg (from `imageio-ffmpeg`) renders `docs/demo/vindex_demo.mp4`, the same with burned-in captions as `vindex_demo_subtitled.mp4`, and the `vindex_demo.srt` track. `--headed` shows the browser, `--render` only rebuilds the MP4s.
- `scripts/start.ps1`: one command for Postgres + Mailpit, the API and the app, each in its own window; `-Https` serves both over HTTPS on the laptop's LAN address with a self-signed certificate from `scripts/make_cert.py`, which phones need before the camera and GPS APIs work. The API allows any private-network origin.
- `docs/07-demo-runbook.md`: the five-minute click path, the numbers to quote, and the recovery steps.

### Demo addresses and real mail servers (22:50)

The seeded staff accounts live on `synapse.local`, a domain that does not exist, so Gmail accepted their mails and bounced them back into the sender's inbox. The outbox now checks the recipient before every send: when the SMTP host is a real server (anything but the local Mailpit), addresses on `.local`, `.test`, `.invalid`, `.localhost`, `.example` and the `example.*` domains are marked `skipped` with a note instead of being sent. With Mailpit nothing is skipped, so the test suite still sees every mail. For a demo with real inboxes, `PATCH /admin/users/{id}` accepts a new `email`, and the Admin page has a "Change email" action next to each staff address.

---

## 8. Night additions (15-16 Oct 2026, 23:30-01:00)

| Feature | What exists now |
|---|---|
| Rating and reopen | After resolve or close the Track page asks "Was it fixed?": a 1-5 star rating with a note, or "Not fixed, reopen" which puts the case back in progress, writes a citizen timeline event and emails the department (`staff_reopen`). Both allowed for seven days (`REOPEN_WINDOW_DAYS`). Metrics show the average rating and the reopen rate |
| Resolution proof | Staff attach photos or videos of the completed work (`/review/{id}/attachments`, media role `resolution`); the Track page shows them under "Resolution proof from the office" and the resolve mail says a photo is on the tracking page |
| Me too | When a citizen sets a location on the new-complaint form, open complaints within 2 km are listed with a Support button; supporting adds a `supports` row and raises the counter, five supporters raise urgency one level (once), the queue sorts by supporters after urgency and shows `+N`, a `popular` flag appears at three; "Complaints you support" is listed on the home page |
| District map | `/admin/map` for every staff role, scoped like the queue: circle markers coloured by urgency, size growing with supporters, a red ring for overdue, popups with a link to the case, open/all toggle, refresh every 15 s |
| Translated officer notes | A `status` mail to a Tamil or Hindi citizen that carries an English officer note stores the note (`notifications.note_en`); the outbox translates it with Gemma 3 (`services/translate.py`, script-checked, cached) before sending and falls back to English on any failure (`TRANSLATE_NOTES` to disable) |
| Queue search | `q` matches tracking ID, complainant name, complaint text, address or resolved place; the queue page has a debounced search box |
| Rate limiting | In-memory limiter (`services/ratelimit.py`): login 30 per minute per IP and 10 per minute per email, register 20 per 10 minutes per IP, OTP resend and forgot-password 3 per 10 minutes per email and 10 per IP, OTP verify 10 per 10 minutes per email; 429 with Retry-After |

### Sessions are per browser tab (16 Oct 2026, 03:30)

The front end kept the JWT in `localStorage`, which every tab of a browser shares: logging in as a second role in another tab replaced the first tab's token while that tab still showed the first role's screens, and every request from it answered 403 ("Not allowed for this role"). The token and user now live in `sessionStorage`, so each tab keeps the login it made; `localStorage` only remembers the last login so that a new tab or a restarted browser starts as that user (the first read pins it to the tab). Logging out clears both; other tabs keep their own sessions.

### The decision bar follows the status (16 Oct 2026, 08:45)

The bar offered every action in every status, so pressing Accept on a case already in progress produced a 409 ("Cannot accept from status in_progress"). `DecisionBar.tsx` now mirrors the transitions in `review.py`: Accept only while the case is under review or routed (labelled "Start work" for a department admin, whose accept now moves the case to in progress from either status), Reassign, Merge and Resolve while the case is open, Request info unless it is already awaiting a reply, Close only when resolved, and a staff Reopen on resolved or closed cases; a merged case shows a note instead of buttons. The main button is the next natural step (accept, then resolve, then close), the rest sit behind More.

### Fixes after the A-to-Z test pass (16 Oct 2026, 09:50-10:20)

The five high-severity bugs from section 13 of the test report:

| Bug | Fix |
|---|---|
| Stored script attack through an SVG attachment | Uploads are recognised by their first bytes, never by the declared type or file name: only JPEG, PNG and WebP photos and WebM, MP4 and MOV videos are stored, under the detected type and extension (`MEDIA_TYPES`, `_sniff` in `api/complaints.py`); anything else answers 400 and the files already written for that request are removed. `/media/{id}` sends `nosniff` and a sandbox policy, and serves anything stored before this check as an opaque download. The app renders only those six types (`SAFE_MEDIA_TYPES` in `lib/api.ts`); anything else shows the "could not load" tile and cannot be opened |
| Tamil and Hindi keywords matched inside other words | `keyword_in` (`scripts/common.py`, shared by the rules and the spreadsheet keyword hints): Tamil and Hindi keywords must start a word, and short ones (three letters or fewer: தீ, आग, नाग, பட்டா) must be the whole word or take a listed case ending (தீயில், சாலையில், सांपों). On the 1,641 labelled synthetic complaints, non-safety Tamil complaints sent to Fire and Safety fell from 39 to 3 and Hindi from 23 to 10; the remaining ones mention a real fire or hanging wire, and no genuine safety match was lost |
| GPS covered 13 of 38 districts | `config/places_tn.csv` grew from 47 to 137 places: all 38 district headquarters and the major towns. A point more than `MAX_PLACE_KM` (30 km) from every place, such as Bengaluru, Palakkad or a bad coordinate, gets no district instead of the nearest wrong one |
| Addresses in Tamil script resolved to no district | `district_for` reads district names as whole words in English, Tamil (with case endings: கோயம்புத்தூரில், சேலத்தில்) and Hindi, plus common names (Trichy, Kovai, Ooty, Tuticorin, Madras), from the new `config/district_names.json`; "eroded" is no longer Erode. A complaint whose district is still unknown goes to review (the super admins' queue) with a default 24-hour SLA scaled by urgency, instead of being routed into nobody's queue |
| Complaints lost on restart | The worker tracks what it has queued; at start-up it re-queues every complaint left in Received or Analysing, and the minute check re-queues any stuck for more than 10 minutes and restarts the worker thread if it died |

### Operating note: one model server, one request at a time

Ollama on the 4 GB card runs with `OLLAMA_NUM_PARALLEL=1`, so the analysis worker, the outbox translation, the generator and the training scripts share one queue. A generator run in parallel with the app makes every complaint wait behind 25-second calls, and requests that time out on the client keep running on the server, which can wedge it for minutes. Every model call in the API now carries a timeout (chat 180 s, embedding 120 s, translation 45 s); a stuck server is cleared by restarting `ollama.exe`. Do not run `make_synthetic.py` or `train_second_opinion.py` while the app is being used.
