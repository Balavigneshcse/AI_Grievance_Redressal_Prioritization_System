# Gold evaluation set

Hand-labelled complaints used to measure the system per language and to train the second-opinion classifier. Target: 60 rows, 12 per language code, every department and urgency represented, formal and informal versions of the same situation.

One JSON object per line in `complaints.jsonl`:

| Field | Values |
|---|---|
| `id` | `gold-001`, `gold-002`, ... |
| `text` | the complaint exactly as a citizen would type it |
| `language` | `en`, `ta`, `hi`, `ta-en` (Tanglish), `hi-en` (Hinglish) |
| `department` | `water`, `electricity`, `roads`, `sanitation`, `health`, `safety`, `revenue`, `general` (see `config/taxonomy.yaml`) |
| `urgency` | `critical`, `high`, `medium`, `low` (see `config/urgency.yaml`) |
| `formality` | `formal` or `informal` |
| `evidence_phrase` | the exact words in the text that justify the urgency |
| `location_hint` | the place mentioned, or `""` |
| `duplicate_of` | id of an earlier row this one duplicates, or omit |
| `contact_incomplete` | `true` when the row is a planted incomplete-contact case, or omit |
| `source` | `gold` |

Labelling rules:
- Urgency comes from content only. Never raise or lower it because of spelling, grammar, length or language.
- Write at least 6 pairs where the same situation appears once formal and once informal with the same labels. That pair is how the fairness gap is measured.
- Plant 6 near-duplicate pairs (same issue, same place, different wording).
- Plant 4 rows where a photo would contradict the text (note it in `location_hint` for now).
- Keep the text realistic: typos, mixed scripts, WhatsApp style are good.
