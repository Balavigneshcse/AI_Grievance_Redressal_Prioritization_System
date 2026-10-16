# SYNAPSE: Test Report, Day 1

Everything built up to Checkpoint 4, tested on the build laptop (RTX 3050 4 GB) on 15 October 2026 between 15:00 and 15:30, against the live stack: PostgreSQL 17 + pgvector, Ollama with gemma3:4b and bge-m3, Mailpit, FastAPI on :8000, Vite dev server on :5173.

Scripts: `tests/test_api_e2e.py` (API and AI, 61 checks), `scripts/evaluation/run_eval.py` (gold-set replay), `scripts/training/train_second_opinion.py` (classifier), browser walk-through by hand.

---

## 1. Training data and classifier

| Item | Result |
|---|---|
| Synthetic set | 460 complaints, all 160 department x urgency x language combinations, generated locally by Gemma 3 4B |
| Language balance | en 96, ta 93, hi 79, ta-en 96, hi-en 96 (Hindi lower because early runs produced wrong-script rows that were dropped; the generator now forces Devanagari and the final run dropped none) |
| Department classifier (NumPy softmax on bge-m3) | 0.869 held-out on 137 rows; per language en 0.93, ta 0.95, hi 0.83, hi-en 0.80, ta-en 0.74; every department recall >= 0.81 except General 0.50 (the catch-all) |
| Urgency classifier | 0.479 held-out on 94 rows (chance 0.25). Weak, as expected from embeddings alone; the LLM owns urgency, the classifier only votes on department |

---

## 2. End-to-end API and AI suite (`tests/test_api_e2e.py`)

First run: 58 of 61 checks passed. Of the three failures, two were test bugs (negative tests sent a one-character reason, which fails validation with 422 before the business rule is reached) and one was a model weakness (a Hinglish complaint labelled Tamil). Second run after the fixes below: see section 5.

What passed on the first run, grouped:

| Area | Checks | Notes |
|---|---|---|
| Auth | wrong password 401; complainant blocked from officer routes 403; weak password 400; register 201; login before OTP 403; wrong OTP 400; correct OTP logs in; forgot + reset by OTP; old token invalid after reset; login with new password | all pass |
| AI, five languages | Tamil script water + sick children -> water, critical, review, rules R5 + R10; Devanagari power cut + oxygen -> electricity, critical, review, rule R2; English suggestion -> general, low, routed automatically; Hinglish gas smell -> safety, critical, review, rule R1; Tanglish pothole accident + repeat -> roads, high, rule R8 | department, urgency, rules, review decision correct in all five; evidence spans quoted verbatim from the original text including Tamil and Devanagari; English summary present; district office and due time set; second opinion populated |
| Photo | JPEG with GPS EXIF and no coordinates in the form -> location source exif, resolved to Gandhipuram; vision model described "a large pothole in the center of the road"; media served to the owner, 403 for another complainant | all pass |
| Duplicates | the same Tamil complaint filed twice -> second flagged as possible duplicate at similarity 1.00 and sent to review | pass |
| PII | phone and Aadhaar-like number masked in the text the model sees; map visible to the officer, absent for the complainant | pass |
| Officer | queue with flags; merge duplicate into original -> merged; request info -> awaiting_info; reassign urgency -> routed; resolve then close -> closed; decision without reason rejected; timeline shows received, analysing, routed, resolved, closed; department queue lists routed water complaints | pass |
| Admin | metrics with totals, by status, live accuracy per language; auto-closed is zero; rules tester matches R1 and R5b; invalid YAML rejected; officer cannot edit rules; model reload | pass |
| Email | 27 emails to the test citizen in Mailpit (OTP, acknowledgement, under review, routed, status) | pass |
| Latency | mean 19.7 s per complaint with the GPU shared with training | |

---

## 3. Browser walk-through (Vindex, shadcn/ui)

| Screen | Result |
|---|---|
| Register (phone width, Tamil UI) | renders with icons, strength bar, language select |
| Login as seeded citizen | redirects to My complaints with Tamil department names, status and urgency badges |
| New complaint | Tanglish text typed, "Enter address manually" with a Coimbatore address, submit -> success sheet with tracking ID in under a second |
| Track page | polled every 3 s: Analysing state, then Under review / High / Roads with summary, timeline, reasons, office and the manual address marked "Entered manually" |
| Officer queue (desktop width) | filters, urgency badge, confidence, flags disagreement and duplicate |
| Language menu | opened at the page corner at first: the shadcn Button did not forward its ref, so Base UI had no anchor; fixed, menu now anchors under the trigger |

---

## 4. Defects found and fixed during testing

| Defect | Fix |
|---|---|
| Romanised Hindi labelled as Tamil by the 4B model | A function-word detector classifies Latin-script text as Hinglish, Tanglish or English and the result is passed to the model as a script hint (shared by the pipeline, the eval runner and the smoke test) |
| Spreadsheet keyword "bus" matched "bus stand" and, mapping to General, forced a review of a clear Roads complaint | Keyword hints and rules match whole words for Latin-script keywords; a hint into the General catch-all no longer counts as a disagreement |
| `SMTP_TLS=true` with Mailpit would make every send fail | Mailer upgrades to TLS only when the server offers STARTTLS |
| Generator: Hindi prompts answered in the wrong script; occasional "token repeat limit" aborts | Explicit Devanagari instruction per language; one retry at lower temperature with a repeat penalty |
| Dropdown menus rendered at 0,0 | Button forwards its ref |
| Test suite: two negative tests used an invalid reason | Reasons fixed so the business rules are exercised |

---

## 5. Second run and gold-set replay (after the fixes, 15:11-15:16)

**End-to-end suite: 61 of 61 checks passed.** The Hinglish gas-smell complaint is now labelled `hi` with the script hint; every other case kept its department, urgency, rule matches and review decision. Mean latency 16-20 s per complaint with the GPU free of the generator.

**Gold-set replay (12 rows), raw model versus whole system (model + rules):**

| Metric | Raw Gemma 3 4B | System (model + rules) |
|---|---|---|
| Department accuracy | 0.75 | **1.00** |
| Urgency exact | 0.75 | **0.83** (all misses within one level) |
| Critical recall | 0.75 | **1.00** (4 of 4) |
| Language identification | 0.92 | 0.92 |
| Mean latency | 12.7 s | same |

The three raw-model misses are the ambiguous rows the rules exist for: Tanglish water outage with sick children (model says health, rule R5 says water), the leaning electric pole with hanging wires near school children (model says electricity/high, rule R3 forces safety/critical), and the dark street where women feel unsafe (model says safety, rule R5b says roads). Twelve rows remain a smoke test; the team's 60-row gold set is the real benchmark.

**Bus-stand pothole recheck:** the Tanglish complaint that previously triggered a false review through the "bus" keyword now routes directly to Roads / High at the Coimbatore Roads & Highways Office with no disagreement, and the script hint reads it as Tanglish.

**Browser:** register, login, my complaints, new complaint with manual address, track page polling through analysing to the final decision, officer queue, language menu: all verified by hand on the running app.

---

## 6. Verdict

Everything built up to Checkpoint 4 works end to end on the build laptop. The AI layer is accurate where it matters (no Critical case is missed by the system, every department decision on the gold set is right once rules apply, language identification is 92%), and every uncertain or disagreeing case is routed to a human by design. Remaining weaknesses are documented: the raw 4B model alone is 75% on department, urgency from embeddings is weak, and latency is 15-20 s per complaint.

---

## 7. Evening run (15 Oct 2026, 19:00-19:40): roles, identity fields, video limits, async mail

Suite grown to 77 checks (`tests/test_api_e2e.py`), run against a Mailpit-backed API instance while `.env` points at Gmail (`SMTP_HOST=localhost` exported for both processes).

**Result: 77 of 77 checks passed.** New checks: complaint without name and Aadhaar digits rejected; name and digits stored and visible to staff; roads department admin gets 403 on a water complaint; a department admin's queue holds only its department; super admin creates a district admin; that district admin cannot create another district admin (403) but creates a department admin in its own district; the new department admin sees no Coimbatore complaints; disabling the account locks it out; department admins cannot list staff; 38 districts listed.

Mail: every OTP, acknowledgement, routed, review and status email left through the outbox thread within two seconds of the request, over one connection kept open for the whole run; no failed sends. The suite now waits for a new message before reading an OTP.

Analysis time per complaint during the run: 15-32 s with the GPU shared with the frontend dev server and the warm-up (mean model latency reported by the metrics endpoint: 15.8 s).

Two false alarms found and fixed while testing: a run that crashed midway left an open English "benches" complaint, so the next run's identical text was correctly flagged as a duplicate; and the forbidden-role request used a one-letter name, so validation answered 422 before the role check. Both were test-data issues, not product defects.

---

## 8. Late evening run (15 Oct 2026, 21:20): reply loop, staff mail, overdue escalation, admin pages

Suite grown to 91 checks, run against a Mailpit-backed API instance on the new code.

**Result: 91 of 91 checks passed, first run.** New checks: a complaint with two photos stores both and the vision model reports findings; the citizen's reply on an awaiting-info case is accepted and returns the complaint to the status it came from, recorded in the timeline under the citizen; a reply with a photo on a routed case; replies rejected on closed complaints and from anyone but the complainant; the department admin of Coimbatore water is emailed when a water complaint is routed there; the district admin is emailed when a Coimbatore case needs review; an overdue complaint is escalated by `POST /admin/sla/check` exactly once, carries the `overdue` flag in the queue, the escalation timestamp and the timeline note, and the district admin receives the overdue mail; the health endpoint reports the outbox backlog, open overdue cases and the model latency.

Mail during the run left through the outbox over one connection: citizen OTP, acknowledgement, routed, review and status mails plus the new staff mails (`staff_routed`, `staff_review`, `staff_reply`, `overdue`), none failed.

The browser check of the new screens (rules, metrics, admin, reply card on an awaiting-info complaint) found no console errors.

---

## 9. Round-2 training (15 Oct 2026, 22:00-22:45)

A second generation run added 477 complaints (160 department x urgency x language combinations, 3 each, none dropped by the script check), bringing the synthetic set to 940 rows. The classifier was retrained on 1,163 rows (synthetic + gold + NYC 311 sample) and the gold set replayed.

| Metric | Round 1 (460 synthetic) | Round 2 (940 synthetic) | Round 3 (1,169 synthetic, partial run) | Round 4 (1,644 synthetic) |
|---|---|---|---|---|
| Department, held-out | 0.869 (137 rows) | 0.846 (234 rows): water 1.00, electricity 0.93, sanitation 0.94, health 0.94, revenue 0.92, roads 0.81, safety 0.75, general 0.53 | 0.875 (279 rows): health 1.00, roads 0.98, water 0.97, revenue 0.96, electricity 0.90, sanitation 0.83, safety 0.82, general 0.50 | 0.845 (373 rows): water 0.98, revenue 0.97, roads 0.95, electricity 0.92, health 0.91, sanitation 0.87, safety 0.78, general 0.34 |
| Department per language | en 0.93, ta 0.95, hi 0.83, hi-en 0.80, ta-en 0.74 | en 0.91, hi 0.89, ta-en 0.85, hi-en 0.78, ta 0.73 | en 0.93, hi-en 0.93, hi 0.84, ta-en 0.84, ta 0.78 | en 0.89, hi-en 0.88, ta-en 0.87, hi 0.80, ta 0.76 |
| Urgency, held-out | 0.479 | 0.550 (chance 0.25); low 0.81, critical 0.52 | 0.555; low 0.79, critical 0.61 | 0.563; low 0.73, critical 0.63, high 0.56 |
| Gold set, model alone | department 0.83, critical recall 0.75 | unchanged (the model is not trained) | unchanged | unchanged |
| Gold set, system with rules | department 1.00, urgency 0.92, critical recall 1.00, language ID 0.92 | unchanged | unchanged | unchanged |
| Mean model latency on the gold set | 12.7 s | 11.5 s | 13.2 s | 12.4 s |

Reading: the larger held-out split is a harder, more varied set, so the department number moved from 0.87 to 0.85 while urgency improved from 0.48 to 0.55; the general catch-all remains the weak class (0.53) and Tamil-script department accuracy dropped on a 37-row split. The classifier is a second opinion only: department decisions on the gold set are 100% once rules apply, and every disagreement goes to a human. The running API picked up the new files through `POST /admin/models/reload`.

Round 3 (16 Oct, 00:30-01:10) was cut short at 79 of 160 combinations when the generator had to be stopped for the test run; its 229 rows were cleaned and appended, and the retrain on 1,392 rows lifted department accuracy to 0.875 with Hinglish at 0.93; Tamil script remains the weakest language (0.78 on 49 rows) and the general catch-all the weakest class (0.50).

Round 4 (16 Oct, 01:30-02:50) completed all 160 combinations (475 rows, none dropped) and the synthetic set reached 1,644 rows. The retrain on 1,867 rows gives department 0.845 and urgency 0.563: urgency keeps creeping up, department has settled in the 0.85 to 0.88 band across four rounds and the general catch-all got harder (0.34) as the data grew more varied. The reading is that more synthetic data from the same generator has stopped helping; the next gain has to come from real labelled complaints and the officer corrections the system already records. Section 14 runs that loop on 100 test complaints.

---

## 10. Night run (16 Oct 2026, 00:40): rating and reopen, proof, me-too, map, translation, search, limits

Suite grown to 114 checks, run against a Mailpit-backed API instance.

**Result: 114 of 114 checks passed.** New checks: queue search by tracking ID and by complainant name; the office attaches a resolution photo, the citizen sees it marked as proof, and an upload outside the admin's scope is refused; the citizen rates a resolved complaint (stored with its feedback window), reopens it with a note (back to in progress, reopen count 1, citizen event in the timeline, roads admin emailed), and cannot rate while it is open again; the English resolve note reaches the Tamil-speaking citizen translated into Tamil script in the status mail; another citizen supports the water complaint (counted once, the owner cannot support their own), the nearby list shows it as supported without any personal data, the supported list and the queue carry the count; the map lists located complaints and is scoped for a department admin; metrics carry the average rating, reopen rate and supporters; twelve failed logins for one address end in 429.

Three runs were needed. The first two stalled because the round-3 generator was still running (its process survived a Ctrl+C) and Ollama, serving one request at a time, replayed a queue of timed-out requests; the fix was to stop the generator, restart the Ollama server, and give the embedding call a timeout so a wedged model can never block the worker again. The remaining defects were ours: the static routes `/complaints/nearby` and `/complaints/supported` were registered after `/complaints/{id}` and were swallowed by it; the outbox translated a mail before sending the staff mails behind it (plain mails now go first and the suite waits for mail instead of sleeping); and the nearby list cut a supported complaint off at five results when older test complaints sat at the same coordinates (ties now break by supporters and recency).

## 11. Morning run (16 Oct 2026, 02:00): identity taken at registration

The name and the last four digits of the Aadhaar number moved from the complaint form to registration: `POST /auth/register` now requires `full_name` and `aadhaar_last4`, `PATCH /auth/me` lets an account from before this change add them once, and every complaint copies them from the account at intake (`db.py` also backfills older accounts from their latest complaint at start-up). Suite grown to 118 checks, run against a Mailpit-backed API instance on the new code.

**Result: 118 of 118 checks passed, first run.** New checks: registration without the two fields is rejected (422) and with `12a4` as the digits (400); the seeded citizen completes its details through `PATCH /auth/me` and a five-digit value is refused; a newly registered account carries the name and digits given at registration in the login response; every analysed complaint carries the account's name and digits although the form no longer sends them. The old check "complaint without name and Aadhaar digits rejected" went with the form fields. Browser check: the registration form shows the two new fields with the Aadhaar hint in all three languages, and the complaint form shows a "Filing as Demo Citizen, XXXX XXXX 4321" line from the account instead of the inputs.

## 12. Pre-jury run (16 Oct 2026, 02:15-02:50): district admins, clean reset, two full passes

Preparation for the final review: `scripts/demo/demo_data.py --districts` now creates one district admin for each of the 38 Tamil Nadu districts (`district.<district>@synapse.local`, idempotent), and `--seed` sets one showcase complaint past its due time so the Overdue badge, the escalation note and the district admin's mail are always on screen. Every old complaint was wiped and the suite was run on the new code twice.

**Defects found and fixed.** `--reset` failed with a foreign-key error: the me-too `supports` table (added on the night run) still referenced complaints; the reset now clears it first. The second pass ended 117 of 118: the one failure, "district admin emailed about the overdue complaint", was a test-harness bug, not a product one. The suite counted an address's mails inside Mailpit's newest-200 window; once the inbox held more than 200 messages (365 after a night of runs) a new mail pushed an old one out of the window and the count never moved, although the API log shows the overdue mail sent 10 seconds after the escalation. The helpers now use Mailpit's search endpoint, which counts across the whole inbox.

**Result: 118 of 118 checks passed** on the third pass, straight after a reset, with the 38 district admins in place (the suite's own Madurai district admin and department admin are created and removed as before). The demo inbox is emptied before the showcase data is seeded, so the jury sees only the demo's mails.

**Demo recording.** `scripts/demo/record_demo.py` drives Chrome through every feature with Playwright (registration with the OTP mail, a Tanglish complaint with in-app video, a photo and GPS, the AI result and timeline, district review, department work with request-info and the citizen's reply, resolution proof, rating, me-too support, search, the overdue badge, the map, staff creation, metrics, rule testing, classifier reload, the Tamil interface and the mail trail) and renders `docs/demo/vindex_demo_subtitled.mp4`, `docs/demo/vindex_demo.mp4` and `docs/demo/vindex_demo.srt`.

**Found by the user on the Karur district admin (03:20).** Every button answered 403 and "Not allowed for this role" although a fresh login for the same account passed every staff endpoint. The cause was in the browser, not the API: the token lived in `localStorage`, shared by all tabs, so logging in as a citizen in a second tab replaced the admin tab's token while that tab still showed the admin screens. Sessions are now per tab (`sessionStorage`, with the last login kept in `localStorage` for new tabs). Checked with Playwright: two tabs of one browser logged in as the Karur admin and the citizen, the admin tab keeps its token, no 401 or 403 during the queue's auto-refresh, the staff page still renders, and a third tab starts as the last login.

**Found by the user on a department admin (08:40).** Accept on a case already in progress answered 409 "Cannot accept from status in_progress": the bar offered every action regardless of status. It now offers only the transitions the API allows, and a department admin's accept is labelled "Start work" and goes straight to in progress. Checked in the browser with the demo data: in progress shows Resolve, Reassign, Merge, Request info; under review shows Accept and More (Resolve); awaiting info drops Request info; resolved shows Close and More (Reopen).

**Found by the user on a closed case (08:50).** The timeline drew its newest entry as the hollow "current step" ring whatever the status, so a closed complaint ended with an open ring after the citizen's rating. The ring is now reserved for cases that are still open; once a case is resolved, closed or merged every entry is a green check. Checked on the demo data: closed and resolved cases end green, an in-progress case keeps the ring.

**Rescue rules (09:05).** Two rules added so that rescue situations always reach Fire & Rescue whatever the model says: R11, a person or animal fallen into a well, borewell, pit or drain or stuck in a lift (Fire and Safety, Critical, human review), and R12, a snake, bee hive or wild animal inside a home (Fire and Safety, High, human review), each with English, Tamil, Hindi and romanised keywords; the taxonomy examples carry the same cases for the model. Checked with the rules engine on ten complaints across the five language forms: all route to safety with the expected floor and review; a broken borewell stays a water complaint and a pothole matches nothing. The office dry run gives the district's Fire & Rescue office (24 h SLA, so 6 h for a Critical case). Three checks added to the suite.

## 13. Full A-to-Z pass (16 Oct 2026, 09:20-09:45): every feature, security probes, bug list

Run on an isolated copy so the demo data stayed untouched: a separate database `synapse_test`, a test API on port 8100 with its own media folder, a second app on 5174, mail to Mailpit under a test sender (removed afterwards). The demo database was checked before and after (13 complaints, 50 users, 118 notifications, unchanged).

| Area | Result |
|---|---|
| Production build (`npm run build`) | passes; one warning: a single 1 MB JavaScript bundle |
| Translations | English, Tamil and Hindi have identical key sets; no key used in code is missing |
| API suite (`test_api_e2e.py`) | **121 of 121** |
| Gold set (`run_eval.py`) | system with rules unchanged: department 1.00, urgency 0.92, critical recall 1.00, language ID 0.92, 15.4 s per complaint; the model alone 0.75 on department this run (0.83 last run: run-to-run variation) |
| Browser walkthrough (Playwright, Chrome, every role) | 45 of 53 steps pass; 5 failures were artefacts of the test script (a stale toast read, e-mail addresses read as translation keys), 3 are real (below) |
| Security and edge probes | 15 pass, 18 bugs, 5 notes (below) |

What works end to end: registration with OTP (mail in the chosen language), forgot and reset password, the complaint form (validation, script badge, photo, 26 MB refusal, in-app video, GPS, nearby list), tracking that updates itself, district review, department Start work and Request info, citizen reply with a photo, resolution proof, rating, reopen, close, the green timeline, queue search and filters, the map, staff accounts (super admin and district admin scopes), the rule tester, classifier reload, metrics, refusals outside a role's scope, role redirects, the Tamil interface, phone width without horizontal scrolling. Probes that passed: a Karur district admin is fully fenced off from Coimbatore, unsigned tokens are refused, CORS is closed to outside origins, SQL metacharacters in search are harmless, role fields are ignored at registration, media of another department is refused, three simultaneous complaints get distinct tracking IDs, a resolve sent during analysis is not overwritten.

### Bugs found

| # | Severity | Bug | Evidence | Where |
|---|---|---|---|---|
| 1 | High | Stored XSS through an SVG attachment: a citizen attaches an SVG with a script; when staff click the photo, it opens as a same-origin blob and the script reads the stored login token | new tab title "XSS-ONLOAD eyJhbGciOiJIUzI1..." | `api/complaints.py` `_save_uploads` (any `image/*` accepted by declared type); `components/MediaThumb.tsx` (opens the blob in a new tab) |
| 2 | High | Tamil and Hindi rule keywords match inside other words, so ordinary complaints go to Fire and Safety as Critical with forced review: "தீர்வு / தீர்க்க" (solution, solve) contain "தீ" (fire), "आग्रह" (request) and "आगे" (in front) contain "आग", "नागरिक" (citizen) contains "नाग" (cobra, rule R12 added 16 Oct), "பட்டாசு" (crackers) contains "பட்டா" (patta) | on 1,641 labelled synthetic complaints: 38 of 297 non-safety Tamil (12.8%) and 13 of 272 Hindi sent to Fire and Safety; the rule tester shows R4 for a Tamil garbage complaint | `services/rules.py` `keyword_in` (substring for non-ASCII); `config/rules.yaml` |
| 3 | High | The offline place table covers 13 of 38 districts, so GPS complaints from the other 25 go to a neighbouring district's office and admins | Ariyalur to Thanjavur, Ramanathapuram to Madurai, Dharmapuri to Salem, Tenkasi to Tirunelveli | `config/places_tn.csv`, `scripts/common.py` `nearest_place` |
| 4 | High | An address typed in Tamil script (and common names such as Trichy, Kovai, Ooty, Tuticorin, Madras) gives no district: no office, no due time, status Routed, visible only to the super admin, never escalated | "கோயம்புத்தூர், காந்திபுரம் 5வது தெரு" routed with district, office and due time all empty | `scripts/common.py` `district_for` |
| 5 | High | Complaints stay "Analysing" forever after an API restart: the work queue lives in memory and nothing re-queues received or analysing complaints at start-up, so they never reach any queue | SYN-2026-000019 still analysing with no analysis 95 s after a restart, queue depth 0 | `services/worker.py` |
| 6 | Medium (fixed 16 Oct) | The server does not enforce the status machine: request info on a closed complaint reopens it, reassign on a merged complaint routes it, staff reopen on an in-progress case sends it back to review (the app hides these, the API accepts them). **Fixed** with the medium-severity fixes: the API refuses with 409 every decision the decision bar does not offer, and checks it under a row lock | all three answered 200 | `api/review.py` `decide`, `services/pipeline.py` `_set_status` |
| 7 | Medium (fixed 16 Oct) | No coordinate check or distance limit: lat 999 is accepted and routed to Tirunelveli; a pin in Delhi becomes a Chennai water complaint with an SLA. **Routing fixed** with the high-severity fixes: a point more than 30 km from every known place gets no district and goes to review. **Coordinates fixed** with the medium-severity fixes: intake answers 400 for a latitude or longitude out of range, NaN, or half a pair | probes P05a, P05b | `api/complaints.py` intake, `common.nearest_place` |
| 8 | Medium (fixed 16 Oct) | District names are matched as substrings of the text: "eroded" makes a complaint Erode district's. **Fixed** with the high-severity fixes: district names match as whole words, and in complaint text only a capitalised "Erode" counts | routed to Erode Roads & Highways Office | `common.district_for` |
| 9 | Medium (fixed 16 Oct) | One image the model cannot decode makes the whole analysis fail ("Failed to load image"): no department or urgency suggestion, straight to review; phone formats such as HEIC are likely affected (not tested). **Fixed** with the medium-severity fixes: the analysis asks the model once more without the photos and says so in the reasons (HEIC is refused at upload since the high-severity fixes) | SYN-2026-000020 | `services/pipeline.py` (no retry without images) |
| 10 | Medium (fixed 16 Oct) | PII masking misses mobile numbers written with spaces or dashes ("98765 43210", "+91 98765 43210", "98765-43210"); PIN codes are not masked although the docs say so; "+919876543210" is masked but labelled Aadhaar. **Fixed** with the medium-severity fixes: all three formats are masked as phones, "+919876543210" is a phone, PIN codes are masked | direct calls to `mask_pii` | `services/pii.py` |
| 11 | Medium (mostly fixed 16 Oct) | Uploads trust the declared type (plain text accepted as image/png), there is no server-side file-count limit (10 accepted, the app allows 6), and the 5-minute video limit exists only in the browser. **Type check fixed** with the high-severity fixes: files are recognised by their signature. **File count fixed** with the medium-severity fixes: more than 6 files in one request answer 400. **Still open:** the server-side video length | probes P04b, P04c | `api/complaints.py` `_save_uploads` |
| 12 | Medium (fixed 16 Oct) | Four simultaneous "Support" clicks by one citizen: one answers 500 (unique-constraint race). **Fixed** with the medium-severity fixes: the complaint row is locked while a support is recorded, so simultaneous clicks all answer 200 and count once | [200, 500, 200, 200] | `api/complaints.py` `support` |
| 13 | Low (fixed 16 Oct) | Staff accounts can add "me too" support, and any citizen can support any complaint by ID, not only nearby ones. **Fixed** with the low-severity fixes: staff get 403, and a citizen sends where they are, which must be within 2 km (`NEARBY_KM`) of the complaint | department admin support answered 200 | `api/complaints.py` `support` |
| 14 | Low (fixed 16 Oct) | Reviewer Accept is offered on an already routed case: it adds a duplicate "Routed" entry and re-sends the routed mail. **Fixed** with the low-severity fixes: the bar offers Accept on a routed case only to the department admin (Start work), the API refuses a reviewer's with 409 | timeline entries 7 to 8, citizen mails 44 to 45 | `components/DecisionBar.tsx` `allowedActions`, `api/review.py` |
| 15 | Low (fixed 16 Oct) | The nearby list accepts any radius (km=100000) and returns open complaints statewide with summaries. **Fixed** with the low-severity fixes: the radius is capped at 2 km and the list at 20 | 12 items, 2 over 50 km away | `api/complaints.py` `nearby` |
| 16 | Low (fixed 16 Oct) | No maximum complaint length: 15,000 characters accepted while the model reads about 2,048 tokens. **Fixed** with the low-severity fixes: 5,000 characters at most, on the server and in the form | probe P06 | `api/complaints.py` intake |
| 17 | Low (fixed 16 Oct) | Account enumeration: verify-otp and reset answer "No account for this email" (forgot is generic); tracking-ID lookup answers 403 for someone else's complaint and 404 for a missing one. **Fixed** with the low-severity fixes: one answer for a wrong code and an unknown email, 404 for a tracking ID outside the caller's reach | probes P09, P15 | `api/auth.py`, `api/complaints.py` |
| 18 | Low (fixed 16 Oct) | `/health` is public and shows queue depth, outbox backlog and latency. **Fixed** with the low-severity fixes: the public answer is the status only; the details go to staff or to a caller on the API's own machine | probe P16 | `api/misc.py` |
| 19 | Low (fixed 16 Oct) | The registration Aadhaar field accepts letters while typing (refused only on submit); the complaint-form card strips them live. **Fixed** with the low-severity fixes: digits only while typing, as on the card | browser step B01b | `pages/Register.tsx` |
| 20 | Low (fixed 16 Oct) | One 1 MB JavaScript bundle (311 KB gzipped), no code splitting. **Fixed** with the low-severity fixes: admin, officer and complaint-form pages load on first visit; 249 KB gzipped at start, no build warning | build warning | `frontend` build |
| 21 | Note (fixed 16 Oct) | `demo_data.py` and `record_demo.py` read the database only from `.env`, so a reset always targets the demo database, even when testing elsewhere. **Fixed** with the low-severity fixes: the environment comes first, then `.env`, for the database and the API address alike | code reading | `scripts/demo/demo_data.py`, `scripts/demo/record_demo.py` |
| 22 | Note (fixed 16 Oct) | Rule R10 treats "old age" as at-risk, so a routine pension complaint gets High urgency and forced review. **Fixed** with the low-severity fixes: "old age" is no longer a keyword, and the elderly rule (now R10b) skips pension and allowance requests | rules engine | `config/rules.yaml` |

### Fixes for bugs 1-5 and retest (16 Oct 2026, 09:50-10:40)

What changed is described in `docs/05-implementation.md` ("Fixes after the A-to-Z test pass"). Retest on the isolated stack:

| Bug | Retest |
|---|---|
| 1 SVG script attack | an SVG upload and a text file declared as PNG both answer 400 (suite); the SVG planted before the fix now shows as an unreadable tile, cannot be opened, and no script ran (browser); real JPEG uploads, in-app camera photos and the WebM video from the in-app recorder still pass |
| 2 Tamil and Hindi keywords | the rule tester no longer matches the fire rule for "தீர்க்கவும்" or "आगे / आग्रह", nor the cobra rule for "नागरिक", while a real Tamil fire still matches (suite); on the 1,641 labelled complaints, non-safety Tamil complaints sent to Fire and Safety fell from 39 to 3 and Hindi from 23 to 10, all remaining ones mentioning a real fire or hanging wire; no genuine safety match was lost |
| 3 district coverage | all 38 district headquarters resolve to their own district; Ariyalur town now goes to the Ariyalur office; Bengaluru, Palakkad, Chittoor, Thiruvananthapuram, Tirupati and Delhi get no district and go to review. Two rows needed care: the headquarters of Ramanathapuram (Coimbatore also has a Ramanathapuram locality) and Tambaram, moved from Chennai to Chengalpattu district |
| 4 addresses in Tamil script | "கோயம்புத்தூர், காந்திபுரம் 5வது தெரு" resolves to Coimbatore with its office and due time; a complaint at lat 999 or with "eroded" and no location gets no district and goes to review with a due time instead of being routed into nobody's queue (suite and probes) |
| 5 complaints lost on restart | the complaint left in Analysing by the earlier restart was picked up as soon as the fixed API started ("re-queued 1 unfinished complaint") and moved to Under review |

**Suite: 129 of 129** on a fresh test database (121 earlier checks plus 8 for these fixes). A run on the reused database showed 127 of 129: a leftover open "benches" complaint from the first run made the new one a possible duplicate, the known effect of re-running without a reset. **Browser walkthrough: 45 of 52 steps pass**; the failures are bug 19 (not in this round) and the same test-script artefacts as before (stale toasts, e-mail addresses read as keys, a rule-tester check that also reads the rules table). Bug 8 is fixed by these changes and bugs 7 and 11 are half fixed (see the table); bugs 6, 9, 10 and 12 to 20 are still open.

### Fixes for bugs 6, 7 and 9-12 and retest (16 Oct 2026, 11:20-12:00)

What changed is described in `docs/05-implementation.md` ("Fixes for the medium-severity bugs"). Same isolated set-up as above: a fresh `synapse_test` database, a test API on port 8100 with its own media folder outside the repository, mail to Mailpit under a test sender (removed afterwards); the demo database was not touched. Bugs 6 and 12 were first reproduced with the unchanged code, so their checks are known to catch them.

| Bug | Before the fix | After the fix |
|---|---|---|
| 6 status machine | nine of ten probes answered 200: request info on a closed case (became awaiting info), reassign on a merged one (became routed), staff reopen of an in-progress one (became under review), resolve on a resolved, received or merged case, request info on a resolved or awaiting-info case and a merge of a closed case; only accept on a received case was refused | all ten answer 409 ("Cannot request info from status closed"); the allowed ones still pass (request info on routed, resolve on awaiting info, reopen on closed, merge from in progress); two simultaneous closes on a resolved case give one 200 and one 409 with a single "closed" entry, in three rounds of three |
| 7 coordinates | lat 999 accepted (bug table) | lat 999, lng 181, lat -91 with lng -181, NaN and a latitude without a longitude answer 400 and store nothing; a Delhi pin (valid but outside Tamil Nadu) still goes to review with no district |
| 9 unreadable photo | the analysis failed with no suggestion (bug table) | a complaint whose photo is a JPEG header with nothing readable behind it: the call with the photo got 400 "Failed to load image or audio file", the retry gave department and urgency (safety, critical; rule R5b then set the department to roads), the first reason is "photo could not be read by the model; analysed from the text alone", the photo stays on the case; 24 s for the whole analysis |
| 10 PII masking | "98765 43210", "+91 98765 43210", "98765-43210", "9876 543 210" and "0091 98765 43210" left unmasked, "+919876543210" became "+[AADHAAR_1]", "641012" left unmasked | all masked as `[PHONE_n]` (the "+" included), "641012" and "641 012" as `[PIN_n]`; unchanged: Aadhaar in every grouping (including one starting 91), e-mail addresses with digits, PAN; left alone: a landline (0422 2345678), "Rs 1500", tracking IDs such as SYN-2026-000012 |
| 11 file count | 10 files accepted (bug table) | 7 photos in one request answer 400 "Attach at most 6 photos or videos at a time" before anything is written; 6 are accepted |
| 12 support race | five rounds of four simultaneous supports by one account: four rounds had three 500s each (the count and the support row stayed at 1) | all 20 requests answer 200, with one support row, a count of 1 and one timeline entry per complaint |

**Suite: 137 of 137** on a fresh test database (129 earlier checks plus 8 for these fixes: the PII formats, coordinates, file count, three for the status machine, simultaneous supports, the unreadable photo). Two earlier inputs changed with the fixes: the "no district" complaint is pinned in Delhi instead of at lat 999, which intake now refuses, and the PII complaint carries the new phone formats and a PIN code. Still open: bugs 13 to 20, notes 21 and 22, and the server-side video length from bug 11.

### Fixes for bugs 13-20 and notes 21-22 and retest (16 Oct 2026, 11:30-12:20)

What changed is described in `docs/05-implementation.md` ("Fixes for the low-severity bugs and notes"). Same isolated set-up: a fresh `synapse_test` database, a test API on port 8100 with its own media folder outside the repository, mail to Mailpit under a test sender (the 57 test mails removed afterwards, the inbox held nothing else), and for the browser checks a second app on 5174 pointed at the test API. The demo database had the same counts before and after (15 complaints, 50 users, 127 notifications, 82 status events, 1 support) and the demo API on 8000 was not restarted.

| Bug | Retest |
|---|---|
| 13 me-too support | a department admin's support answers 403; a citizen's without a location 400, from Chennai 403, from 1 km away 200 (suite). Browser: the citizen's Support on a complaint 1.3 km away answered 200 (the form sends its GPS point), and a department admin sees the nearby list with no Support buttons |
| 14 reviewer accept on a routed case | the super admin's accept answers 409 and the timeline gains no Routed entry; the water department admin's accept on the same case starts the work (suite). Browser: on a routed case the super admin's bar shows Resolve, Reassign, Merge and Request info, the department admin's shows Start work |
| 15 nearby radius | `km=100000&limit=1000` returns 4 items, the farthest 1.81 km away, without the Delhi complaint; `km=0` and `lat=999` answer 422 (suite) |
| 16 complaint length | 5,179 characters answer 400 and nothing is stored (suite). Browser: a 5,180-character text stops at 5,000 in the box and the counter turns red ("5000 / 5000") |
| 17 account enumeration | with a live reset code on a real account, verify-otp and reset answer an unknown address exactly like a wrong code for the real one (400, same message); the tracking-ID lookup answers 404 for another citizen's and another department's complaint, like a missing ID, and 200 to the owner (suite) |
| 18 `/health` | without a login and with a citizen's, through a proxy header: `{"status": "ok"}` only; with a super admin's: the details (suite); on the API's own machine the details, as the suite's first check and the Metrics page's live health card show |
| 19 Aadhaar field | browser: "12x34" typed in one burst gives 1234, a pasted "XXXX XXXX 1234" gives 1234, typing 5, q, 6, 7, 8, 9 gives 5678. A first version kept `maxLength={4}` and lost a digit when a letter came in the same burst: the browser cut "12x34" to "12x3" before the letters were removed. The field now cuts to four digits itself |
| 20 bundle | `npm run build`: JavaScript at start 779 kB (249 kB gzipped) instead of 1,013 kB (311 kB), no chunk over 500 kB, no warning. Browser: the admin, metrics, rules and map pages, the officer queue and the complaint form load on first visit, no console errors |
| 21 demo scripts | `demo_data.py --reset` with the test stack's `DATABASE_URL` and `MEDIA_DIR` in the environment emptied `synapse_test` (11 complaints, 3 test accounts, the test media) and left the demo database unchanged |
| 22 rule R10 | the rule tester: an old-age pension complaint in English, Hindi ("बुजुर्ग पेंशन") and Tamil ("முதியவர் உதவித்தொகை") matches neither R10 nor R10b, elderly residents without water match R10b, sick children R10 (suite); on the 2,837 labelled synthetic and gold complaints, R10 and R10b together match the same 136 complaints as the old R10 |

**Suite: 148 of 148** on a fresh test database (137 earlier checks plus 11 for these fixes). The earlier support checks now send the supporter's location: the three support calls before the nearby check and the four simultaneous supports of the medium-severity checks. Still open from section 13: the server-side video length from bug 11.

---

## 14. Officer corrections as training labels (16 Oct 2026, 12:45-13:50)

Does training on what officers confirm move the second opinion where more synthetic data stopped helping (section 9)? The loop is described in `docs/05-implementation.md` ("Officer corrections as training labels"). Run on an isolated copy: database `synapse_labels`, a test API on port 8130 with its own media folder, mail to Mailpit under a test sender (removed afterwards). The demo database was only read and had the same counts before and after (15 complaints, 50 users, 127 notifications, 82 status events, 26 overrides). Training wrote to a scratch folder (`--out`, `--cache`): `models/` still holds the round-4 classifier.

**Set-up.** `demo_data.py --seed` filed the ten showcase complaints, and its staff actions confirmed two of them. Then 100 complaints written for this test, not by the generator: 20 in each language form, with two per department, four general cases (noise, an information request, thanks, a suggestion), a leaning electric pole (Fire and Safety, where rule R3 sends it) and a dengue cluster, all in Coimbatore localities. None of the texts is in the training data. They went through the real pipeline one at a time, 19.9 s each. A script played the officers: when the routed department and urgency matched the label it accepted (the district admin on a review case, the department admin's Start work on a routed one); otherwise the district admin reassigned the department, the urgency or both.

**What the officers found.**

| | en | ta | hi | ta-en | hi-en | All |
|---|---|---|---|---|---|---|
| Department routed right | 0.80 | 0.85 | 0.75 | 0.75 | 0.85 | 0.80 |
| Urgency right | 0.55 | 0.65 | 0.70 | 0.30 | 0.60 | 0.56 |
| Both right (accepted) | 0.50 | 0.60 | 0.55 | 0.30 | 0.50 | 0.49 |

49 accepts and 51 reassigns. 20 reassigns changed the department: general complaints sent to five other departments (6), health to water or roads (5), safety to electricity, roads, health or water (5), sanitation to roads or water (3), and one roads complaint to safety. The other 31 changed only the urgency.

**Export.** `export_corrections.py` on `synapse_labels`: 102 rows (the 100 plus the two the seed confirmed), 20 or 21 per language, every department. Gemma's department agreed with the officers on 0.824 of them and the deployed second opinion on 0.833. On the demo database (read-only) it found 6 confirmed complaints and wrote nothing (`--min-rows` 30). One finding: the analysis gave primary `ta` for 10 of the 22 Devanagari complaints on the test stack (9 of the 20 Hindi test complaints) despite the script hint. The export therefore takes Tamil and Devanagari from the script and the analysis language only for text in English letters; the pipeline itself is unchanged.

**Retrain** (`train_second_opinion.py --corrections --cpu`, officer weight 3, five folds by complaint). Without officer rows the run reproduces round 4: department 0.847 and urgency 0.563 on the synthetic held-out split, against 0.845 and 0.563 with GPU embeddings. Accuracy on the 102 officer rows, each predicted by a model that never saw its complaint:

| Model | Input | | en | ta | hi | ta-en | hi-en | All | General recall |
|---|---|---|---|---|---|---|---|---|---|
| Department | complaint text (what training embeds) | before | 0.95 | 0.71 | 0.90 | 0.80 | 0.50 | 0.775 | 0.80 |
| | | after | 0.95 | 0.81 | 0.95 | 0.70 | 0.50 | 0.784 | 0.80 |
| | English summary + place (what the API embeds) | before | 0.90 | 0.76 | 0.90 | 0.80 | 0.80 | 0.833 | 0.85 |
| | | after | 0.90 | 0.81 | 0.95 | 0.80 | 0.90 | **0.873** | 0.90 |
| Urgency | complaint text | before | 0.30 | 0.48 | 0.52 | 0.20 | 0.20 | 0.343 | |
| | | after | 0.55 | 0.62 | 0.71 | 0.65 | 0.45 | 0.598 | |
| | English summary + place | before | 0.45 | 0.52 | 0.57 | 0.55 | 0.60 | 0.539 | |
| | | after | 0.60 | 0.67 | 0.67 | 0.60 | 0.60 | **0.627** | |

On the synthetic held-out split, department stays at 0.847 and urgency goes from 0.563 to 0.536. Officer weight (accuracy on the 102 rows, text / API input, then the synthetic split):

| Weight | Department | Urgency |
|---|---|---|
| none (before) | 0.775 / 0.833, synthetic 0.847 | 0.343 / 0.539, synthetic 0.563 |
| 1 | 0.765 / 0.853, synthetic 0.845 | 0.500 / 0.588, synthetic 0.569 |
| **3 (default)** | **0.784 / 0.873, synthetic 0.847** | **0.598 / 0.627, synthetic 0.536** |
| 5 | 0.784 / 0.863, synthetic 0.839 | 0.647 / 0.637, synthetic 0.536 |
| 10 | 0.775 / 0.853, synthetic 0.836 | 0.706 / 0.706, synthetic 0.512 |

The first run embedded 1,822 texts on the CPU in 15 minutes, sharing the model server with another training run. With the cache, every later run took 5 to 20 s, including the first embedding of the 102 rows' runtime input.

Reading:
- Department: on the complaint text the officer rows change one complaint in 102. On the input the API really uses, they lift the second opinion from 0.833 to 0.873: Hinglish 0.80 to 0.90, Tamil 0.76 to 0.81, Hindi 0.90 to 0.95, no language lower, and no cost on the synthetic split. On these complaints the general catch-all is not the weak class (0.85 before); its 0.34 on the synthetic split does not carry over to them.
- Urgency gains most: 0.34 to 0.60 on the text and 0.54 to 0.63 on the API's input, with medium recall from 0.17 to 0.63 (text). The officer rows teach the officers' scale and the synthetic split pays a little (0.563 to 0.536); a higher weight follows the officers further and the generator less (weight 10: 0.71 and 0.51). Weight 3 gives the best department result on both inputs (tied with 5 on the text), so it stays the default. The routing decision only uses the department vote; the urgency vote is stored for staff.
- The classifier is trained on complaint text, but at runtime it reads the English summary and place. On these complaints that is the better input for the deployed model (0.833 against 0.765; Hinglish 0.80 against 0.50), which is why the report now scores both and the export keeps each row's runtime input.
- Limits: one author wrote the labels and a script that never errs applied them, so they are cleaner and more consistent than real officers' decisions will be. With 20 complaints per language, one complaint moves a language by 0.05. This shows the loop working end to end, not a production gain; the candidate model was not deployed.
