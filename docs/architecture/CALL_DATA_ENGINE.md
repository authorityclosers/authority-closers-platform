# Sales X-Ray call data engine

Design v1, 19 Oct 2026. Owner direction: "Data is the key: classified,
organised, cleaned and perfectly presented."

Every call becomes typed, evidence-backed data. Two pipelines fill it:
- the **fast pipeline**, which fills the lead within seconds;
- the **deep pipeline**, which reads the whole call later.

The existing Report, Prospect and Coaching keep working as the first plug-in
pipeline set. Code lives in `packages/python/ac_platform/call_data/`.

## 1. What a call becomes

```
organisation (tenant)
 └─ lead (Lead Desk) / prospect (Sales X-Ray)
     └─ call (recording + submission, C2 transcript revision)
         └─ call objects (typed facts, append-only, supersede links)
             └─ decisions (engine: auto_filled, asked; person: accepted, edited, rejected)
```

Each **call object** (`call_objects`) carries:

| Field | Meaning |
|---|---|
| `type_key`, `category` | From the taxonomy, e.g. `company.team_size` in `company` |
| `taxonomy_version` | `call-taxonomy/2` (v2 adds segment labels and audio). A new type bumps it; old rows keep the version they were made under |
| `value` | One checked JSON shape per kind: text, numeric (the prospect fact contract's `NumericFactValue`), when, enum, person, commitment, objection, question, ratio |
| `display` | One short line a person reads |
| `confidence` | 0–1, the model's own read. With no quote it is capped at 0.6 |
| `basis` | `observed` (said in the call and quoted), `inferred` (AI reads only) or `person` |
| `evidence` | Up to 3 `{segment_id, quote, start_ms, end_ms, speaker}`. Quotes are copied from the saved transcript, never taken from the model |
| `mentions` | How many separate segments support it |
| `pipeline`, `pipeline_version`, `run_id` | The maker: `fast/1` or `deep/1`, and the run with its model, prompt digest, tokens and cost |
| anchors | `tenant_id`, `recording_id`, `submission_id`, `person_id` (the salesperson), `lead_id`, `transcript_revision` |
| `supersedes_id`, `retracted` | The object this one replaces (unique: at most one successor), or a retraction |

**Rules**
- **Append-only.** Nothing is updated or deleted. A better value is a new row
  that supersedes the old one, and a run's outcome is a new row after its
  "running" row. Privacy erasure is the only exception: it empties `value`,
  `display` and `evidence` and stamps `erased_at`, the same way the pointer
  reviews do. It is hooked into `finish_erasure`.
- **A person's word wins.** Accept and edit are person decisions.
  - The engine never overwrites a lead value a person typed. It asks instead
    ("replace").
  - A later call may correct only the engine's own earlier fill.
  - A rejected value is never asked again on that lead.
- **No contact details.** Phone numbers and email addresses are never extracted
  (ADR 0056 §5).
- **Sensitive segments.** Segments marked sensitive (ADR 0051) never reach the
  model. An object quoting a segment marked later is hidden on read.
- **Our own test calls are skipped.** These are the canary and QA fixtures.

## 2. Taxonomy `call-taxonomy/2` (`call_data/taxonomy.py`)

There is one code registry. Each type has:
- key, category, label and value kind;
- one or many;
- a confirmation priority;
- whether the fast pipeline extracts it;
- the lead column and prospect field it maps to;
- its auto-fill rule.

Industry packs (later) add types under `pack.<industry>.`.

| Category | Types |
|---|---|
| people | `person.name`, `person.role`, `person.other_party`, `person.personal_context` |
| company | `company.name`, `company.industry`, `company.team_size`, `company.revenue`, `company.location` |
| need | `need.primary_pain`, `need.pain`, `need.goal` |
| friction | `friction.blocker`, `friction.objection` (kind, resolved), `friction.question` (answered) |
| decision | `decision.maker`, `decision.approver`, `decision.status`, `decision.timeline` |
| money | `money.budget`, `money.price_quoted`, `money.investment_discussed` |
| market | `market.alternative`, `market.competitor`, `market.past_attempt` |
| offer | `offer.product_mentioned` |
| commitment | `commitment.follow_up` (when, purpose), `commitment.seller_promise`, `commitment.prospect_promise`, `commitment.next_step` |
| signal (AI read) | `signal.urgency`, `signal.interest`: never asked, never filled, labelled as the AI's read |
| outcome | `outcome.call_outcome` |
| conversation (deep) | `conversation.language`, `conversation.talk_ratio` (measured, never from a model), `conversation.segment` (labels per segment) |
| audio (deep, measured) | `audio.features` (waveform, loudness, pitch, pace, pauses, overlap) |

Lead columns the engine may write: `name`, `company`, `city` and `interest`.
The prospect field mapping follows `prospect_fields.FIELD_REGISTRY`.

## 3. Fast pipeline (every new call, seconds)

```
C2 transcript saved ─► admit ─► "running" row (committed: counts as paid)
   ─► one model call (fast types) ─► validate, copy quotes
   ─► admit again + outcome row + objects + decisions + lead fills (one transaction)
```

- **Runner.** `python -m ac_platform.call_data.runner --loop --apply` runs as a
  long-lived process per environment (`infra/application/scripts/ac-call-data`).
  - It polls every 4 s.
  - One runner holds an advisory lock per database.
  - Like the pointer review, it re-executes inside `infisical run`, so the key
    exists only in that child.
  - It never backfills: only transcripts saved after the first start's marker
    are processed.
- **Admission** uses the pointer review's checks: the call is ready and not
  being erased, its permission is current, its workspace and account are
  active, and this transcript is the newest. These are checked before the
  call to the model and again in the saving transaction.
- **Attempts.** At most two per transcript. A start with no outcome counts as
  spent.
- **Auto-fill.** The type needs an auto-fill rule, `observed` basis with a quote,
  and confidence ≥ 0.85. It also needs repetition (≥ 2 segments), or a plainly
  stated simple fact (name, company, role, city). A lead column is written only
  when it is empty or holds the engine's own earlier fill. The write uses the
  Lead Desk's revision rule and adds an `edited` history row with
  `via: call_data`.
- **Confirmations.** At most 7 per call, highest priority first. Each is Accept,
  Edit or Reject, with the quote and its time. An accept or edit of a
  lead-column fact writes the lead through `LeadDesk.edit`, so the owner and
  revision rules are the Lead Desk's own.
- **Cost.** About 700 input and 150 output tokens per audio minute on Gemini
  3.8 Flash, so roughly ₹0.08 per audio minute (about ₹1 for a 13-minute
  call). The estimate uses the list price in `admin_pricing`. The daily cap is
  set in Admin (dev default ₹150).

## 4. Deep pipeline (`deep/1`, v0.64)

The deep pipeline runs after the fast pipeline has finished the same
transcript. It uses the same runner, admission rules and paid-attempt rules.
It is switched on, given a model (Gemini 3.8 Flash or 3.1 Pro) and capped in
Admin → Call data. Code: `deep_runner.py`, `deep.py`, `classifier.py`,
`audio.py`.

1. **Whole-call read.** One model call over the whole transcript extracts every
   taxonomy type the model can know (`DEEP_EXTRACT_TYPES`). The transcript is
   the batch transcript, already the best one, so nothing is re-transcribed.
2. **Segment classifier.** Every segment gets a `conversation.segment` object:
   - intent: greeting, rapport, discovery, pain, goal, qualification, pitch,
     pricing, objection, objection handling, decision process, next steps,
     closing, logistics, small talk, other;
   - act: question, answer, statement, request, commitment, agreement,
     disagreement, filler;
   - sentiment and tone, labelled as the AI's read;
   - up to 3 topics.

   Segments go in chunks of 120, with 4 segments of context on each side.
3. **Voice features.** These are computed on the server; no model is used. The
   audio check (C1, AudioAtlas) already stores 10 ms frames (loudness and pitch)
   and a decimated waveform. `audio.py` joins them with the transcript to give:
   - waveform peaks;
   - loudness and pitch per speaker and per segment;
   - pace (words per minute);
   - pauses (≥ 1.5 s; long ≥ 3 s) and overlap;
   - talk ratio.

   These are saved as `audio.features` and `conversation.talk_ratio`. When the
   frames can't be read, timings alone are used, and the run says so.
4. **Merge rules** (`deep.plan_merge`):
   - A fact a person accepted, edited or rejected is never touched. The person's
     word wins.
   - Any other current fact of the same identity (fast, or an older deep read)
     is superseded. Its question moves to the new value, or ends, under the same
     fill-or-ask rule.
   - A machine fact the deep read did not find, with confidence under 0.7, is
     retracted: a retraction row supersedes it.
   - Segment labels and measured objects supersede only their own earlier
     versions.

Segment and audio objects are analysis data. They stay out of the lead card
and prospect facts and feed Admin, the gold set and later analysis.

**Backfill.** `python -m ac_platform.call_data.runner --backfill --recent-hours 8760
--limit 200 --not-before <date> --apply` reads stored older calls once, with
trigger `backfill`. Run it on dev first, and get a cost estimate and the
owner's yes before staging or production.

## 5. Pipeline sets

A pipeline set is a named group of passes over the call and its objects.
- `sales-analysis` is the first: today's C3–C6, Coaching, the pointer review
  and Prospect.
- Later sets (per business type) register the same way and read the same
  objects.

## 6. APIs

| Route | Purpose |
|---|---|
| `GET /v1/sales-xray/call-data/leads/{id}` | A lead's facts across its calls, open questions, fills (`can_undo`), pipeline states, and `reply`: a WhatsApp or SMS after the newest call in its language (English, Hinglish, Hindi or Marathi; fixed wording, no model; the page fills `{my_name}` and `{org}`; sending only opens WhatsApp or SMS) (Lead Desk visibility) |
| `POST /v1/sales-xray/call-data/objects/{id}/decision` | Accept, edit or reject (`command_id` idempotent) |
| `POST /v1/sales-xray/call-data/objects/{id}/undo-fill` | One tap puts back a lead field the engine filled, while it still holds the filled value (a person's later change always wins); the fact becomes the person's `rejected`, so the same words don't fill it again (`command_id` idempotent). The lead read's `filled[].can_undo` says when |
| `GET /v1/sales-xray/call-data/prospect-facts?lead_id=` or `?call_id=` | `prospect-facts/1` for Prospect's Information |
| `GET /v1/sales-xray/call-data/taxonomy` | The registry |
| `GET /v1/admin/conversation/calls/{recording_id}/data-map` | Admin call map |
| `GET /v1/admin/call-data`, `PUT /v1/admin/call-data/settings` | Admin settings, spend and recent runs |

`prospect-facts/1` reader rule (agreed with the Prospect chat), per fact:
1. a person's decision;
2. then the newest deep fact;
3. then the newest fast fact;
4. then the Report's `structure.prospect_profile`.

## 7. Admin call map

One line per stage, each with status, start, end, duration, cost, provider,
model and version:

received → audio check → transcription → fast pipeline → call objects →
better transcript → deep pipeline → objects updated → Report · Coaching →
AI pointer review → Prospect.

It is built from today's checkpoints, inference tasks and jobs, plus the
engine's runs and objects. It holds no content: ids, times, states, models,
tokens and estimates only.

## 8. Providers stay swappable

- **Text models.** The model per pipeline is chosen in Admin
  (`call_data_settings`, append-only revisions). Only models with a reviewed
  list price are offered. Keys stay in Infisical.
- **Live transcription** (`streaming.py`). Admin → Call data → Live transcription
  chooses the provider:
  - Off: the default.
  - Sarvam realtime: built and recommended. It uses `saaras:v3-realtime` or
    `saaras:v4`, language auto/hi/mr/en, and code-mix mode.
  - AWS Transcribe in Mumbai: listed as the fallback, not built yet.

  A provider streams only when it is switched on AND Root has recorded its
  provider gate (AC-GOV-AUD-001) as cleared in
  `/etc/authority-closers/call-data-streaming-gate.json`. That file is never
  in git.

  Per ADR 0056 §14, the live relay runs off-box and the server receives draft
  text only. Drafts are never canonical; the batch transcript is the one that
  counts. The research is in
  `docs/research/2026-10-19-streaming-transcription.md`.

## 9. Gates and limits

- **Auto-transcribing every Lead Desk call** is ADR 0056 §9's "auto-analyse"
  (D10). It needs its own consent and approval. Until then the fast pipeline
  runs on calls whose analysis a person (or an approved auto-upload) already
  admitted.
- **The engine's spend is not in the budget ledger yet.** Like the pointer
  review, it is capped by its own Admin daily cap with list-price estimates.
  Ledger integration needs the C2/C4/C5 stage enum widened (v0.64 follow-up).

## 10. Releases

- **v0.63** shipped without the engine (Prospect only).
- **v0.64** carries everything:
  - store and taxonomy;
  - fast pipeline, lead auto-fill and confirmations;
  - deep pipeline, segment classifier and voice features;
  - supersede and retract rules;
  - Admin pipeline map and settings;
  - prospect-facts API;
  - the live transcription switch, off and gated.
- **After v0.64:**
  - budget-ledger integration (needs the C2/C4/C5 stage enum widened);
  - the off-box live relay (ADR 0056 L5);
  - the AWS adapter;
  - re-asking a person when the deep read disagrees with them.
