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
| `taxonomy_version` | `call-taxonomy/1`. A new type bumps it; old rows keep the version they were made under |
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

## 2. Taxonomy `call-taxonomy/1` (`call_data/taxonomy.py`)

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
| conversation (deep) | `conversation.language`, `conversation.talk_ratio` (measured, never from a model) |

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

## 4. Deep pipeline (v0.64)

- A visible "Deep analysis running" marker. `pipelines.deep` is already in
  every read.
- **Transcript.** It reuses the batch transcript when it is the best one, which
  it is today (Scribe v2). When the fast pipeline ran on a live draft, deep
  waits for the batch transcript.
- **Classifier.** It labels every segment:
  - semantic: topic and intent;
  - syntactic: question, statement, commitment, request;
  - sentiment and tone.
  It then extracts every taxonomy type.
- **Audio features** are computed on the server: waveform peaks, loudness, pitch,
  pace, pauses and overlap.
- **Supersede.** It supersedes the fast objects it improves and retracts wrong
  ones. It never touches an object a person decided; if it disagrees, it asks
  again.
- **Backfill** runs over stored transcripts on dev first, with a cost estimate
  before staging or production. The classified backfill is the gold set for
  the sales analysis.

## 5. Pipeline sets

A pipeline set is a named group of passes over the call and its objects.
- `sales-analysis` is the first: today's C3–C6, Coaching, the pointer review
  and Prospect.
- Later sets (per business type) register the same way and read the same
  objects.

## 6. APIs

| Route | Purpose |
|---|---|
| `GET /v1/sales-xray/call-data/leads/{id}` | A lead's facts across its calls, open questions, fills and pipeline states (Lead Desk visibility) |
| `POST /v1/sales-xray/call-data/objects/{id}/decision` | Accept, edit or reject (`command_id` idempotent) |
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
- **Streaming transcription** comes in v0.64 behind the same provider rule. The
  comparison is `docs/research/2026-10-19-streaming-transcription.md`:
  - recommended primary: Sarvam realtime;
  - fallback: AWS Transcribe in Mumbai;
  - batch stays on Scribe v2;
  - the live relay stays off-box per ADR 0056 §14;
  - drafts are never canonical.

## 9. Gates and limits

- **Auto-transcribing every Lead Desk call** is ADR 0056 §9's "auto-analyse"
  (D10). It needs its own consent and approval. Until then the fast pipeline
  runs on calls whose analysis a person (or an approved auto-upload) already
  admitted.
- **The engine's spend is not in the budget ledger yet.** Like the pointer
  review, it is capped by its own Admin daily cap with list-price estimates.
  Ledger integration needs the C2/C4/C5 stage enum widened (v0.64 follow-up).

## 10. Releases

- **v0.63:** objects store and taxonomy, fast pipeline and runner, lead
  auto-fill, confirmations on the lead screen, read-only Admin call map and
  settings, prospect-facts API.
- **v0.64:** deep pipeline and classifier, audio features, backfill (after the
  cost estimate), streaming transcription behind a provider switch, ledger
  integration.
