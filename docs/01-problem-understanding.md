# SYNAPSE: AI Grievance Redressal Prioritization System

## Phase 1 - Problem Understanding

Hackathon: 24-hour build | Date: 15 October 2026 | Status: Draft v1

---

## 1. Problem Analysis

### 1.1 Context

Government and corporate grievance portals (CPGRAMS, state and municipal portals, customer-support desks) receive thousands of complaints a day as free text. Today a human reads each one, guesses the department, and forwards it. The subject, urgency and routing are decided by whoever happens to read it first, which makes outcomes slow and inconsistent.

### 1.2 Root causes

| Symptom | Underlying cause |
|---|---|
| Serious cases wait behind routine ones | Urgency is judged first-in-first-out, not by content |
| Complaints bounce between departments | Routing depends on the individual reader; no shared rules |
| Same issue filed 3-4 times | No duplicate check at intake; no acknowledgement, so the complainant resubmits |
| Complainants cannot be contacted | Contact details missing or malformed; nobody flags it at intake |
| Non-English and informal writers get worse service | Staff fluency varies; informal text is read as "less serious" |
| Complainant has no idea what happened | Status lives in internal tools; no outbound updates |

### 1.3 Why it matters

- A buried Critical case (gas leak, exposed wire, medical dependency on power) costs lives, not just time.
- Misrouting adds days per hop and erodes trust in the portal.
- Staff time goes to reading and forwarding instead of resolving.

### 1.4 Constraints set by the problem statement

These are non-negotiable design rules, not nice-to-haves:

1. Original text is always preserved; normalisation is additive.
2. Every recommendation is explainable (evidence spans, matched rules, confidence).
3. Uncertain and potentially urgent cases go to a human.
4. Staff can reassign and correct; corrections are recorded.
5. The model never rejects or closes a complaint on its own.
6. Personal data is protected.
7. Performance is measured per language and per complaint type.
8. Accounts are verified (email OTP), passwords are hashed, OTPs expire, and media and location are visible only to the complainant and authorised staff.
9. All models run on the organisation's own hardware. Complaint text, photos and location never leave its servers. No cloud AI APIs.

### 1.5 Scope assumption for the hackathon

- **Domain:** civic / municipal grievances. The architecture is domain-agnostic; only the taxonomy and routing config change for a corporate deployment.
- **Languages:** English, Tamil, Hindi, and code-mixed (Tanglish / Hinglish).
- **Access:** complainants register with mobile number, email and a strong password; the account is verified by email OTP, and forgotten passwords are reset by email OTP.
- **Evidence:** a complaint can carry photos or a video taken in-app (with GPS) or uploaded from the gallery; location comes from the camera, the photo's EXIF data, a "use current location" button, or manual entry.

---

## 2. Target Users

| User | Who they are | What they need | Pain today |
|---|---|---|---|
| **Complainant** (primary) | Citizen or customer; any language, any literacy level, often on a phone | Register once (mobile, email, password, email OTP), submit in own words with photo or video and location, get an ID, know what is happening | Form is English-only, no way to attach evidence or pin a location, no acknowledgement, no status |
| **Grievance officer** (primary) | Front-line triage staff at a helpdesk or call centre | A prioritised queue, the reason behind each suggestion, one-click reassign | Reads everything manually, no urgency signal, no routing guide |
| **Department resolver** | Engineer, inspector or support agent in the target department | Only relevant, de-duplicated, complete complaints | Receives misrouted and duplicate cases |
| **Administrator** | Portal owner or nodal officer | Edit routing rules, watch backlog and accuracy, audit decisions | Rules live in people's heads; no metrics |
| **Auditor / oversight** | RTI, ombudsman, internal audit | Full trail of who decided what and why | No trail |

---

## 3. Problems Faced

Concrete failure modes the system must handle. Each is tied to a sample so it can be tested.

| # | Problem | Example input | Expected behaviour |
|---|---|---|---|
| P1 | Multilingual and code-mixed text | "Water supply 3 days ah illa, kids are sick" | Detect ta+en, classify Water, urgency High |
| P2 | Urgency buried in long text | 300-word complaint; paragraph 3 says father is on home oxygen and power is cut | Critical, evidence span highlighted |
| P3 | Misclassification | Streetlight complaint sent to Electricity instead of Roads and Infrastructure | Rules and model compared; disagreement goes to review |
| P4 | Duplicate submissions | Same pothole, same street, filed 4 times in 2 days | Link to the original, do not open a new ticket |
| P5 | Incomplete contact info | Only a first name, phone missing a digit | Flag "contact incomplete", still accept the complaint |
| P6 | Informal or low-resource writing penalised | All lowercase, no punctuation, spelling variants | Urgency unaffected by formality; tested per language |
| P7 | Spelling and transliteration variants | "thanni", "thanneer", "தண்ணீர்" all mean water | Normalised for matching; original kept |
| P8 | No status visibility | Complainant resubmits because nothing came back | Acknowledgement within seconds, update on every status change |
| P9 | PII in free text | Aadhaar, phone, address pasted in body | Masked before model call and in logs; visible only to authorised staff |
| P10 | Over-automation | Model is 99% sure it is spam | Never auto-close; low-value goes to a human queue |
| P11 | Unverified or fake submissions | Anonymous bot floods the portal, or one person files under five names | Registration with mobile, email and strong password; email OTP verification; one verified identity per account |
| P12 | Location missing or vague | "Near the temple, road is broken" with no landmark or ward | GPS captured from in-app camera or photo EXIF; "use current location" button; manual address fallback; reverse-geocoded to ward |
| P13 | Text alone does not show severity | "Road is bad" could be a crack or a two-metre sinkhole | Photo or video attached; vision model describes the image and corroborates category and urgency |

---

## 4. Objectives

Measurable targets for the 24-hour build. Numbers are against a hand-labelled evaluation set (target: 60 complaints, 15 per language, all categories represented).

| ID | Objective | Target |
|---|---|---|
| O1 | Accept and correctly detect language, including code-mixed | >= 95% language detection accuracy |
| O2 | Classify category with an explanation | >= 85% top-1 category accuracy; every prediction carries evidence spans |
| O3 | Score urgency on a fixed 4-level scale | >= 85% exact match; 100% of ground-truth Critical reach the review queue |
| O4 | Route via configurable rules plus model | Rules editable in a config file without redeploy; rule wins on conflict |
| O5 | Flag uncertain cases for human review | Confidence below threshold or rule/model disagreement goes to review; threshold tunable |
| O6 | Detect duplicates | >= 80% of planted duplicates linked |
| O7 | Keep the complainant informed | Acknowledgement in their language on submit; update on every status change |
| O8 | Measure fairness | Dashboard shows accuracy per language and per category; informal vs formal gap reported |
| O9 | Protect personal data | PII masked before any model call; audit log of access |
| O10 | Human authority | Zero auto-closures; every override recorded with who, when, why |
| O11 | Verified identity | Registration needs mobile, email and a strong password; account activates only after email OTP; password reset only by email OTP; OTP expires in 10 minutes |
| O12 | Evidence and location capture | Photo or video from in-app camera or upload; GPS auto-filled from camera, EXIF or current-location button; manual entry fallback; >= 90% of complaints end with a resolvable location |

---

## 5. Proposed Solution

### 5.1 One line

A triage pipeline built on locally hosted open-weight models, with a rules layer on top, a human review queue in the middle, and a status loop back to the complainant. No cloud AI APIs: the data stays on the organisation's servers.

### 5.2 Pipeline

```
[0] Account: register (mobile, email, strong password) -> email OTP -> verified
    forgot password -> email OTP -> new password
        |
        v
Complaint (text in any language, optional photo/video, location)
        |
        v
[1] Intake: store raw text, media files and location (never modified)
    location source: in-app camera GPS | photo EXIF | current-location button | manual entry
        |
        v
[2] Language detection (primary + secondary for code-mix)
        |
        v
[3] PII detection and masking (phone, ID numbers, addresses)
        |
        v
[4] Normalisation (transliteration, spelling variants) stored alongside raw
        |
        v
[5] Local LLM analysis (open-weight model served by Ollama) -> structured JSON
      { category, urgency, confidence, entities, evidence_spans, summary }
        |
        v
[5b] Media analysis (local vision model on photo / video key frame)
      -> what is visible, does it match the text, severity cue
        |
        v
[5c] Location resolution: lat/lng -> address + ward/zone (reverse geocoding);
      manual address -> lat/lng; ward feeds the routing rules
        |
        v
[6] Rules engine (configurable YAML/JSON)
      e.g. keyword "gas leak" -> Fire & Safety, Critical, force review
      rules override model; disagreements raise a flag
        |
        v
[7] Duplicate check (embedding similarity + location/contact match)
        |
        v
[8] Decision
      confident and not critical                          -> Department queue
      low confidence / critical / disagreement / duplicate -> Human review queue
        |
        v
[9] Acknowledgement to complainant (their language) + tracking ID
        |
        v
[10] Officer actions: accept / reassign / merge / correct
        -> correction stored -> feeds eval metrics
        -> status update sent to complainant
```

### 5.3 Why local open-weight models

- Grievance text carries names, phone numbers, addresses and photos of people's homes. A government or corporate portal cannot ship that to a third-party cloud. Local inference keeps the data inside the organisation.
- No per-request cost, no rate limits, works on an intranet or during an outage.
- No labelled multilingual dataset exists for this task; an open-weight multilingual LLM handles Tamil, Hindi and code-mix without training.
- Structured JSON output (schema-constrained decoding) gives category, urgency, entities and evidence in one call, the same as a hosted model would.
- Evidence spans make the recommendation explainable by construction.
- A rules layer gives administrators control the model cannot override.
- Two independent predictors: the LLM and a small embedding classifier trained on our own data. When they disagree, the case goes to a human. This is the fairness safeguard against one model's blind spots.

### 5.4 Urgency scale (shared by prompt, rules and UI)

| Level | Criteria |
|---|---|
| Critical | Immediate risk to life or safety; medical dependency; vulnerable person (child, elderly, disabled) affected now |
| High | Essential service fully down (no water, no power, sewage overflow); time-bound deadline; repeat complaint |
| Medium | Service degraded or partial; property damage; billing dispute with financial impact |
| Low | Information request, suggestion, cosmetic issue, general feedback |

Formality, length, grammar and language are explicitly not urgency signals.

### 5.5 Department taxonomy (initial)

Water Supply, Electricity, Roads and Infrastructure, Sanitation and Waste, Public Health, Fire and Safety, Revenue and Property, General / Unclassified.

---

## 6. Core Features

| # | Feature | Description | Priority |
|---|---|---|---|
| F1 | Multilingual intake | Free-text form; language auto-detected; raw text preserved | MVP |
| F2 | Structured analysis | Category, urgency, confidence, entities, summary from a local open-weight LLM | MVP |
| F3 | Evidence highlighting | The exact phrases that drove category and urgency, shown inline | MVP |
| F4 | Configurable routing rules | Admin-editable rules file; rules override model; disagreements flagged | MVP |
| F5 | Human review queue | Low-confidence, Critical, disagreement and duplicate cases land here first | MVP |
| F6 | Override and correction log | Officer can reassign category, department, urgency; correction stored with reason | MVP |
| F7 | Duplicate detection | Similar complaints linked; officer confirms merge | MVP |
| F8 | Complainant tracking | Tracking ID, status page, acknowledgement and status updates by email in their language | MVP |
| F9 | Fairness and performance dashboard | Accuracy per language and category on the eval set; review-queue load; backlog by department | MVP |
| F10 | PII masking | Phone, ID numbers, addresses masked before model call and in logs | MVP |
| F11 | Audit trail | Every automated and manual decision timestamped with actor and reason | MVP |
| F12 | Incomplete-contact flag | Missing or malformed contact detected at intake; complaint still accepted | MVP |
| F13 | Account registration | Mobile number, email, strong-password policy; account activates after email OTP | MVP |
| F14 | Password reset | Forgot-password flow sends an email OTP; new password set after OTP check | MVP |
| F15 | Photo and video evidence | Upload from gallery, or open the in-app camera to take a photo or short video | MVP |
| F16 | Location capture | GPS from in-app camera or photo EXIF; "use current location" button; manual address entry; reverse geocoding to ward | MVP |
| F17 | Image evidence analysis | Local vision model describes the photo, checks it matches the text, adds a severity cue to the explanation | MVP |
| F18 | Embedding classifier second opinion | Logistic regression on multilingual sentence embeddings, trained on our synthetic and corrected data; disagreement with the LLM sends the case to review | Stretch |
| F19 | Voice / WhatsApp intake | Speech-to-text or chat channel | Stretch |
| F20 | WhatsApp channel | Receive complaints and send status updates on a WhatsApp Business number (roadmap only, not built in the hackathon). No SMS. | Roadmap |

---

## 7. Out of Scope (24 hours)

- SMS of any kind. Email is the channel: OTP, acknowledgement, under review, routed, and resolved mails.
- WhatsApp intake and notifications (in the roadmap, not implemented)
- Mobile-number OTP (the number is collected and validated; verification is by email OTP only)
- More than 4 languages
- Native mobile app (the web app is responsive and uses the phone browser's camera and GPS)
- Full video analysis (one key frame is analysed; the video itself is stored for staff)
- Cloud AI APIs of any kind (all inference runs on local hardware)
- Integration with an existing portal's database

---

## 8. Demo Script (what judges will see)

1. Register with mobile, email and password; enter the email OTP; log in. Show forgot-password with a second OTP.
2. Submit a Tanglish complaint with a photo taken in-app and "use current location": language, category, urgency, entities, evidence spans, image description and map pin shown.
3. Submit a long complaint with buried medical urgency: marked Critical, lands in review queue.
4. Officer reassigns: correction logged, complainant receives a status email.
5. Submit a near-duplicate from the same location: linked to the original.
6. Open dashboard: per-language accuracy and review-queue load.
7. Show masked PII in the stored record.

---

## 9. Open Questions for Phase 2

- Which machine serves the models (GPU or CPU, how much memory) decides the model size; see `docs/02-models-and-datasets.md`.
- Who builds the evaluation set and when (should start in hour 1).
- Confidence threshold for review: start at 0.7 and tune on the eval set.
- Email provider for OTP and status updates: SMTP with an app password, or a transactional email API with a free tier.
- Map and geocoding provider: OpenStreetMap Nominatim (free, no key) or Google Maps (key needed).
- Media storage: local disk for the demo, object storage later.
