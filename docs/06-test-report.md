# SYNAPSE: Test Report, Day 1

Everything built up to Checkpoint 4, tested on the build laptop (RTX 3050 4 GB) on 15 October 2026 between 15:00 and 15:30, against the live stack: PostgreSQL 17 + pgvector, Ollama with gemma3:4b and bge-m3, Mailpit, FastAPI on :8000, Vite dev server on :5173.

Scripts: `scripts/test_api_e2e.py` (API and AI, 61 checks), `scripts/run_eval.py` (gold-set replay), `scripts/train_second_opinion.py` (classifier), browser walk-through by hand.

---

## 1. Training data and classifier

| Item | Result |
|---|---|
| Synthetic set | 460 complaints, all 160 department x urgency x language combinations, generated locally by Gemma 3 4B |
| Language balance | en 96, ta 93, hi 79, ta-en 96, hi-en 96 (Hindi lower because early runs produced wrong-script rows that were dropped; the generator now forces Devanagari and the final run dropped none) |
| Department classifier (NumPy softmax on bge-m3) | 0.869 held-out on 137 rows; per language en 0.93, ta 0.95, hi 0.83, hi-en 0.80, ta-en 0.74; every department recall >= 0.81 except General 0.50 (the catch-all) |
| Urgency classifier | 0.479 held-out on 94 rows (chance 0.25). Weak, as expected from embeddings alone; the LLM owns urgency, the classifier only votes on department |

---

## 2. End-to-end API and AI suite (`scripts/test_api_e2e.py`)

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

Suite grown to 77 checks (`scripts/test_api_e2e.py`), run against a Mailpit-backed API instance while `.env` points at Gmail (`SMTP_HOST=localhost` exported for both processes).

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

Round 4 (16 Oct, 01:30-02:50) completed all 160 combinations (475 rows, none dropped) and the synthetic set reached 1,644 rows. The retrain on 1,867 rows gives department 0.845 and urgency 0.563: urgency keeps creeping up, department has settled in the 0.85 to 0.88 band across four rounds and the general catch-all got harder (0.34) as the data grew more varied. The reading is that more synthetic data from the same generator has stopped helping; the next gain has to come from real labelled complaints and the officer corrections the system already records.

---

## 10. Night run (16 Oct 2026, 00:40): rating and reopen, proof, me-too, map, translation, search, limits

Suite grown to 114 checks, run against a Mailpit-backed API instance.

**Result: 114 of 114 checks passed.** New checks: queue search by tracking ID and by complainant name; the office attaches a resolution photo, the citizen sees it marked as proof, and an upload outside the admin's scope is refused; the citizen rates a resolved complaint (stored with its feedback window), reopens it with a note (back to in progress, reopen count 1, citizen event in the timeline, roads admin emailed), and cannot rate while it is open again; the English resolve note reaches the Tamil-speaking citizen translated into Tamil script in the status mail; another citizen supports the water complaint (counted once, the owner cannot support their own), the nearby list shows it as supported without any personal data, the supported list and the queue carry the count; the map lists located complaints and is scoped for a department admin; metrics carry the average rating, reopen rate and supporters; twelve failed logins for one address end in 429.

Three runs were needed. The first two stalled because the round-3 generator was still running (its process survived a Ctrl+C) and Ollama, serving one request at a time, replayed a queue of timed-out requests; the fix was to stop the generator, restart the Ollama server, and give the embedding call a timeout so a wedged model can never block the worker again. The remaining defects were ours: the static routes `/complaints/nearby` and `/complaints/supported` were registered after `/complaints/{id}` and were swallowed by it; the outbox translated a mail before sending the staff mails behind it (plain mails now go first and the suite waits for mail instead of sleeping); and the nearby list cut a supported complaint off at five results when older test complaints sat at the same coordinates (ties now break by supporters and recency).

## 11. Morning run (16 Oct 2026, 02:00): identity taken at registration

The name and the last four digits of the Aadhaar number moved from the complaint form to registration: `POST /auth/register` now requires `full_name` and `aadhaar_last4`, `PATCH /auth/me` lets an account from before this change add them once, and every complaint copies them from the account at intake (`db.py` also backfills older accounts from their latest complaint at start-up). Suite grown to 118 checks, run against a Mailpit-backed API instance on the new code.

**Result: 118 of 118 checks passed, first run.** New checks: registration without the two fields is rejected (422) and with `12a4` as the digits (400); the seeded citizen completes its details through `PATCH /auth/me` and a five-digit value is refused; a newly registered account carries the name and digits given at registration in the login response; every analysed complaint carries the account's name and digits although the form no longer sends them. The old check "complaint without name and Aadhaar digits rejected" went with the form fields. Browser check: the registration form shows the two new fields with the Aadhaar hint in all three languages, and the complaint form shows a "Filing as Demo Citizen, XXXX XXXX 4321" line from the account instead of the inputs.

## 12. Pre-jury run (16 Oct 2026, 02:15-02:50): district admins, clean reset, two full passes

Preparation for the final review: `scripts/demo_data.py --districts` now creates one district admin for each of the 38 Tamil Nadu districts (`district.<district>@synapse.local`, idempotent), and `--seed` sets one showcase complaint past its due time so the Overdue badge, the escalation note and the district admin's mail are always on screen. Every old complaint was wiped and the suite was run on the new code twice.

**Defects found and fixed.** `--reset` failed with a foreign-key error: the me-too `supports` table (added on the night run) still referenced complaints; the reset now clears it first. The second pass ended 117 of 118: the one failure, "district admin emailed about the overdue complaint", was a test-harness bug, not a product one. The suite counted an address's mails inside Mailpit's newest-200 window; once the inbox held more than 200 messages (365 after a night of runs) a new mail pushed an old one out of the window and the count never moved, although the API log shows the overdue mail sent 10 seconds after the escalation. The helpers now use Mailpit's search endpoint, which counts across the whole inbox.

**Result: 118 of 118 checks passed** on the third pass, straight after a reset, with the 38 district admins in place (the suite's own Madurai district admin and department admin are created and removed as before). The demo inbox is emptied before the showcase data is seeded, so the jury sees only the demo's mails.

**Demo recording.** `scripts/record_demo.py` drives Chrome through every feature with Playwright (registration with the OTP mail, a Tanglish complaint with in-app video, a photo and GPS, the AI result and timeline, district review, department work with request-info and the citizen's reply, resolution proof, rating, me-too support, search, the overdue badge, the map, staff creation, metrics, rule testing, classifier reload, the Tamil interface and the mail trail) and renders `docs/demo/vindex_demo_subtitled.mp4`, `docs/demo/vindex_demo.mp4` and `docs/demo/vindex_demo.srt`.

**Found by the user on the Karur district admin (03:20).** Every button answered 403 and "Not allowed for this role" although a fresh login for the same account passed every staff endpoint. The cause was in the browser, not the API: the token lived in `localStorage`, shared by all tabs, so logging in as a citizen in a second tab replaced the admin tab's token while that tab still showed the admin screens. Sessions are now per tab (`sessionStorage`, with the last login kept in `localStorage` for new tabs). Checked with Playwright: two tabs of one browser logged in as the Karur admin and the citizen, the admin tab keeps its token, no 401 or 403 during the queue's auto-refresh, the staff page still renders, and a third tab starts as the last login.
