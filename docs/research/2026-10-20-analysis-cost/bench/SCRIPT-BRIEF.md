# Brief: write fictional Indian sales-call scripts with ground truth (analysis-cost benchmark, 20 Oct 2026)

You are writing part of a **fictional** benchmark set used to choose cheaper AI models for a sales-call analysis
product. Everything must be invented: people, companies, products, places of business, numbers. **No real company
or person names, no real phone numbers / emails / URLs / addresses / PAN / Aadhaar / GST numbers.** Indian first
names and surnames are fine as long as the full name is invented and not a public figure. Company names must be
clearly made up (e.g. "Sahyadri Modular Kitchens Pvt Ltd", "Trivikram Solar Rooftops"), not brands.

## Your calls
Write exactly the calls listed in `assignments.json` under your generator name. For each call write three files
into `calls/<call_id>/`:

### 1. `plan.json` (write this FIRST)
```json
{
  "call_id": "fx-07",
  "call_type": "cold_call | inbound_followup | demo | objection_heavy | negotiation_close | lost_deal | callback | multi_party",
  "language_mix": "en-IN | hi-en | mr-en | hi | gu-en",
  "target_minutes": 22,
  "seller": {"company": "...", "product": "...", "price_list": ["..."]},
  "speakers": [
    {"id": "S1", "role": "salesperson", "name": "...", "gender": "f|m", "age_band": "20s|30s|40s|50s+", "style": "..."},
    {"id": "S2", "role": "prospect", "name": "...", "gender": "...", "age_band": "...", "style": "..."}
  ],
  "sections": [{"name": "opening", "minutes": 2, "facts": ["f01"]}],
  "coaching_truths": [
    {"id": "k01", "kind": "missed_discovery | talked_over | no_next_step | good_objection_handling | price_too_early | good_rapport | ignored_buying_signal | wrong_info_given | other",
     "turn_ids": ["t034"], "statement": "The salesperson quoted the price before asking about budget."}
  ]
}
```

### 2. `script.json`
```json
{"call_id": "fx-07", "turns": [
  {"id": "t001", "speaker": "S1", "lang": "hi-en", "text": "...", "tts": "...", "pause_before_ms": 300, "overlap_prev_ms": 0}
]}
```
- `text` is how a good human transcriber writes it: Hindi and Marathi in Devanagari, English words in Latin script
  where speakers naturally say them in English (e.g. "मैं आपको quotation भेजता हूँ"), English turns in Latin.
- `tts` is the same words for a text-to-speech engine: Hindi/Marathi turns fully in Devanagari (English words
  transliterated, e.g. "कोटेशन"), English-only turns in Latin, numbers written as spoken words in the turn's language
  ("बारह लाख पचास हज़ार", "twenty-second October").
- Realistic Indian phone speech: fillers ("haan", "achha", "बरोबर", "ok ok"), interruptions, self-corrections, small
  talk, a bad-line moment ("hello? आवाज़ कट रही है"), repetition of numbers. Average 130–150 spoken words per minute
  of `target_minutes` (count words of `tts`). Turns 3–60 words; vary them.
- 2–4 speakers per `call_type` (multi_party: 3–4).

### 3. `facts.json` — the ground truth
```json
[{"id": "f01", "type": "person_name | company | product | price | budget | quantity | date | time | duration | location | decision_maker | competitor | competitor_price | objection | commitment | next_step | timeline | payment_terms | discount | personal_detail | pain_point | requirement | contact_preference",
  "slot": "prospect.budget", "value": "₹12.5 lakh", "normalized": "1250000 INR",
  "turn_ids": ["t045"], "evidence": "साढ़े बारह लाख तक", "said_by": "S2", "critical": true,
  "needle": false, "depth": 0.48, "trap": null}]
```
- `evidence` is copied **verbatim** from the `text` of the cited turn(s) (the checker looks for it there).
- 25–60 facts per call (scale with length; ≥ 1 per minute of audio for long calls).
- `critical: true` for names, money, dates, quantities, commitments, next steps.
- **Needles** (calls ≥ 15 min): 2–4 facts mentioned **once only**, at ~10%, ~50% and ~90% of the call (`depth` =
  turn position / number of turns), half of them **non-literal**: the fact is stated in words that do not match the
  slot name (e.g. slot `prospect.decision_date` but the turn says "दिवाली के बाद मेरा भाई US से आएगा, तब final करेंगे").
- **Traps** (`trap` field), at least 2 per call ≥ 6 min: `self_correction` ("Tuesday — no, Wednesday"; the
  ground truth is the corrected value), `alt_number_form` ("साढ़े बारह लाख" vs "12.5 L"), `third_party_name`,
  `competitor_price` (must not be taken as our price), `retracted` (a claim the speaker withdraws; ground truth
  records it as withdrawn), `ambiguous_speaker`.
- Every fact's value must be literally recoverable from the cited turns (allowing number/word forms). Do not put a
  fact in `facts.json` that is not said in the script.

## Realism rules (read twice)
- **Never say "fictional", "काल्पनिक", "नकली", "example" or similar inside the dialogue.** The data is fictional; the
  people in the call do not know that. Write it exactly like a real call.
- **Colloquial phone register, not written/literary language.** People speak in short, broken, overlapping
  sentences.
- **`hi-en` and `mr-en` mean heavy code-mixing**, the way Indian salespeople really talk: many English words, in Latin
  script in `text` — "sir", "madam", "okay", "budget", "quotation", "discount", "EMI", "booking amount", "site visit",
  "follow-up", "WhatsApp", "PDF", "installation", "warranty", "per month", "final", "confirm", "actually", "basically".
  Example `mr-en`: "हो sir, मी तुम्हाला quotation WhatsApp वर पाठवते, basically installation पण त्यातच included आहे."
  Example `hi-en`: "Sir actually हमारा जो basic plan है ना, वो per month पंद्रह सौ का पड़ता है, EMI भी हो जाएगा."
  `hi` and `mr` (no "-en") are Hindi-/Marathi-dominant but still use common English words; `en-IN` is Indian English
  with occasional Hindi words ("haan", "achha", "theek hai", "ji").
- Mix number forms the way people speak: "साढ़े बारह लाख", "twelve point five lakh", "12.5", "पंधरा हजार", "fifteen
  thousand" — and record the normalised value in facts.
- You may write a helper program to assemble the JSON, but every line of dialogue must be written by you as natural
  speech, not generated from templates.

## Quality bar
Calls must feel like real Indian SMB sales calls (real-estate, solar rooftops, modular kitchens, coaching
institutes, insurance, CA/tax services, CRM software, packaging, dairy equipment, travel packages, gym memberships,
school admissions, used cars, interior design…). Salespeople make realistic mistakes (each call 2–6
`coaching_truths`). Prospects are not cooperative robots: they hedge, change topic, mention family, ask for a
discount, compare with a competitor.

## Process
1. For each call: plan.json → script.json section by section → facts.json → run
   `python3 check_call.py calls/<call_id>` and fix every error it reports until it prints OK.
2. Write nothing outside `calls/`. Do not read or copy any real call, transcript or customer data from anywhere.
3. When all your calls pass, write `calls/<generator>-DONE.txt` with one line per call: id, minutes (estimated
   from words), turns, facts, needles.
