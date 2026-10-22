# An adaptive analysis engine for Sales X-Ray: design and phased plan (22 Oct 2026)

From the cost-research session, for the orchestrator.

**The owner's ask (22 Oct, about 18:00 IST):** "design an algorithm that is most optimized, Instagram/YouTube-like
… optimize based on user telemetry … very cheap … report structure, report elements, analysis type, coaching and
details extraction will change, but that should make it simple for our algorithm to plug in."

Figures are measured unless marked as a design choice. The engine builds on what already exists:
- the sealed processing plan;
- `call_ai.policy` (per-seller levels, the short-call rule);
- Report settings;
- the AI spend guard;
- `brain4_shadow` and `brain4_eval`;
- the gold set and blind review;
- telemetry/1.

## 1. The idea in one paragraph

A feed ranker picks, for each person, the cheapest set of items they will value, learns from what they do, and keeps
exploring. The engine does the same for each call:
- From a catalogue of **modules** (transcribe, extract, review, score, report, coach), each with a declared input,
  output contract, cost and measured quality, it chooses the **cheapest plan** that delivers what the call's Report
  needs at the quality bar.
- It computes everything else only **when someone asks**.
- It learns from gold reviews (quality) and from what people read and tap (value).

Unlike a feed, engagement never decides what is true. Coaching quality is anchored in the coaching lead's gold
labels (AC-SVAL), and telemetry only decides what is worth computing and showing first.

## 2. Building blocks

### 2.1 Artifacts: the contracts between modules

These already exist, with decoders:

| Artifact | Contract | Decoder | Today |
|---|---|---|---|
| `transcript` | C2 segments | `reports._validated_transcript` | Flash-Lite route, sealed |
| `voice` | measured talk ratio, pauses, overlap | `deep_runner.measured` | free, from audio frames |
| `lead_facts.fast` | call objects (fast types) | `extraction.validate_response` | `ac-call-data@` fast runner |
| `facts.c4` | C4 fact packet | `reports.parse_fact_packet` | one-pass C4 |
| `call_objects` | deep call data | `extraction.validate_response` | one-pass C4 → `plan_publish` |
| `review.pointers` | 27 pointers, outcome, qualification | `pointer_review.parse_review` | one-pass C4 (or classic) |
| `report.c5` | coaching-v5 | `reports.parse_report_draft` | C5 stage |
| `brain4.review` | 18 skills, brain4-review/1 | `brain4.parse` | shadow read (beta orgs) |

New artifacts (for example coach `moments`, D18 decision-state fields) get a contract and a decoder first; nothing
else changes.

### 2.2 Modules: the plug-ins

A module is a versioned declaration in a registry (code, reviewed like any other code):

```text
id / version                 one-pass-facts-v2 / 2
produces                     facts.c4, call_objects, review.pointers, brain4.review
reads                        transcript (+ voice, when measured before the read)
route                        sealed profile id(s): gemini-one-pass-v2, -flex; luna-c4-one-pass-v2, -flex
processor                    google | openai | local  (approval registry: DPA, privacy-page list, per environment)
cost model                   input tokens a + b·min; output tokens c + d·min; price per route and tier
latency                      p50 / p90 by length band, per tier
quality                      gold and benchmark results by stratum, with intervals and n
status                       beta | official  (official only through AC-SVAL)
```

- **A composite module** produces several artifacts in one read and is priced as one. One-pass C4 is the example:
  it does what classic C4 plus the separate review did, and is cheaper per call above about 1 minute (measured
  break-even).
- **Swapping or adding a module** means declaring it, sealing its route, running it in shadow and passing the gate
  (§4). The router then considers it with no router change.

### 2.3 Report specs: what each Report needs

Report settings (versioned per org, already in Admin) list the Report's sections. Each section names the artifacts
it needs and whether it is **precomputed** or **on demand**. For example, today's two Report kinds:

| Section | Needs | Precomputed by default |
|---|---|---|
| classic: overview, coaching | `report.c5` | yes |
| classic: 27 pointers | `review.pointers` | yes |
| brain4_beta: Coach view (18 skills) | `brain4.review` | yes |
| brain4_beta: detailed review (collapsed) | `review.pointers` | yes (it comes free with one-pass C4) |
| coaching report (C5) under brain4_beta | `report.c5` | **on demand** (owner decision) |
| lead card, prospect | `call_objects`, `lead_facts.fast` | yes |

When product changes the Report, it edits the spec. The router reads the spec, so new elements reach users as soon
as some module produces their artifacts.

### 2.4 Call features (known before analysis, free)

- **Length.**
- **Conversation or not** (`call_ai.short_call_reason`).
- **Speaker count.**
- **Language and script mix**, from the transcript.
- **Org and seller.** The Report spec and the AI level (`call_ai.policy.resolve`).
- **Who is waiting.** An upload in the app (someone is watching) or a phone auto-sync (no one is).
- **Call type and stage,** from fast lead facts.

## 3. The router

For each call, after C2:

1. **Required artifacts** = the precomputed sections of its Report spec, filtered by the seller's AI level
   (Off, Data only, Full: the existing levels).
2. **Candidate plans** = sealed module combinations that produce them. There are few, under 10 today, for example:
   - one-pass v1 + C5;
   - one-pass v2 (with Brain 4.0);
   - Luna C4 + Gemini C5;
   - each of them on standard or Flex.
3. **Expected cost and latency** of each plan, from the cost model at this call's length, on the measured rates.
4. **Feasible** = every artifact's quality is at or above its bar for this call's stratum (§4), the latency fits
   the "who is waiting" budget, and every processor is approved for the org.
5. **Choose** the cheapest feasible plan. When several are within a cost tolerance, an explore step (§5) may pick
   another.
6. **Log the decision, content-free:** plan id, feature bands, expected cost, the alternatives' expected costs, the
   explore flag. This extends `call_ai_decisions`.
7. **On demand:** a tap on an on-demand section runs the missing module on the saved transcript. This is the
   existing "Get full report" path, generalised to any section.

**What it decides today, measured** (₹ per audio minute on production's 14-day mix; deliverable 1):

| Decision | Measured effect |
|---|---|
| Calls under 1 min / no conversation → transcript + lead facts only | live since v0.77; 27 of 62 calls were short and about 30% of analysis spend |
| Precompute C5 or on demand (brain4_beta Report) | C5 = ₹0.205/min of the mix; each 10% of taps adds ₹0.021 back |
| Flex when no one waits, standard when someone does | Flex halves the analysis; reports in 1.5–6 min against 45–85 s |
| Brain 4.0 inline (v2) or separate read | inline saves the transcript re-read: ₹0.08–0.71 a call |
| Model per artifact (Gemini or Luna) | Luna C4 on Flex ₹0.19 + 0.0042/min a call; Gemini C4 ₹1.54 + 0.087/min standard |

## 4. Quality: offline bars and gates

- **Quality table.** For every module × artifact × stratum (length band, language mix, call type): the metric, its
  interval and n. Sources:
  - gold (blind review, gold v1, `brain4_eval`: agreement, weighted kappa, bootstrap);
  - the fictional benchmark (fact recall, coaching truths);
  - repeat-read baselines.
- **Measured noise floors a bar has to respect:**
  - The same one-pass request read twice agrees 0.78–0.81 on pointer status.
  - The subscription judge moves 6–9 points on facts and 2–7 on coaching between runs.
  - Gold v1 intervals are about ±15 points on 6 calls.
- **Gate** (design choice): a module enters the feasible set for a stratum when it is **non-inferior** to the
  current module on every artifact it produces. That means the lower bound of the paired difference is above −δ,
  with δ set per artifact by the owner, for example 5 points. It must also pass its contract on ≥ 95% of shadow
  calls.
  - Until enough gold exists, a stratum with no data falls back to the current production module.
  - Today the only fully gated modules are the live ones.
- **Shadow runs.** Candidate modules run on sampled calls, gold-assigned calls first, without being shown, under
  their own AI-spend feature cap. `brain4_shadow` is the pattern to generalise.

## 5. Online learning: telemetry, bandits, A/B, within AGENTS.md

### 5.1 Signals

These come from telemetry/1, which is analytics only and never progress, payment, access or scoring state.

| Signal | Status |
|---|---|
| `sx.report_opened`, `sx.pillar_read` (read time), `sx.coaching_opened`, `sx.clip_played`, `sx.outcome_set` | already exist |
| `sx.section_read {section, read_band}` | to add |
| `sx.section_action {section, action: expand / copy / clip / helpful / not_helpful}` | to add |
| `sx.on_demand_requested {section, from_level}` | to add |

All are enums only; no ids, content or free text.

### 5.2 Value per section

value = w_read·read + w_act·action + w_req·on-demand request, per section and org. The owner sets the weights.

On-demand requests are the clearest under-serving signal: a lean plan whose sections people keep requesting should
precompute them.

### 5.3 Bandit over depth and presentation

- **Arms:** precompute or on demand for each section, and the order of sections (and a few presentation variants).
- **Method:** contextual Thompson sampling, per org × call stratum.
- **Reward:** value − λ·expected ₹.
- **Exploration:** 5–10%, inside the AI-spend caps.
- **Unit:** the call for depth; the user session for presentation.

### 5.4 A/B for module swaps

Swapping modules is a **pre-registered A/B in shadow**, never a live bandit:
1. The new module runs beside the current one on sampled calls.
2. It reaches the gate (§4).
3. Root seals it.
4. The router may then choose it.

### 5.5 Hard limits, from AGENTS.md

- **No official scoring before AC-SVAL.** Brain 4.0 and any new scorer stay `status: beta`; the bandit never sets
  or changes a score's officialness.
- **No customer data to a new processor without approval.** The router's feasible set excludes modules whose
  processor isn't approved for the environment (the DPA and the privacy-page list). Fictional data goes to bench
  keys only.
- **Analytics never become canonical state.** Telemetry chooses what to compute and show. It never feeds progress,
  payment, access or scores.
- **Sealed routes only.** Today one provider revision is active per environment, so per-call choice between models
  or tiers needs a **sealed plan set**: Root seals a set of profiles, and the router may pick among them. This is
  an activation-contract change (phase 2).
  - Until then, the router changes only what the current sealed revision already allows: skip, on-demand,
    short-call.

## 6. Phased plan

### Phase 1: this week, shippable

No new processor, no seal change, one small migration (number from Align).

1. **Registry v0** (`conversation_intelligence/engine/registry.py`, pure). It declares today's modules with the
   measured cost fits, latency, processor, seal profile and gold numbers:
   - C2 Flash-Lite, standard and Flex;
   - fast lead facts;
   - one-pass C4 v1, standard and Flex;
   - C5;
   - `brain4_shadow`;
   - measured voice;
   - the short-call rule.

   It comes with unit tests that recompute the measured ₹/min of today's mix (0.709).
2. **Expected cost per call.**
   - Logged with the existing decision (`call_ai_decisions`), as one JSON field: plan id, expected paise,
     alternatives.
   - The cost meter (`cost_meter.py`) shows expected against actual by plan.
3. **Report-section telemetry.** Add the three events to the server taxonomy and to `apps/sales-xray-web/app/telemetry.ts`.
   The Report and Coach view emit them, with the consent and retention rules unchanged.
4. **Depth policy v0**, with owner-approved knobs in Report settings:
   - C5 precomputed or on demand for brain4_beta orgs;
   - Flex for background calls once the owner switches (option A is already sealed).

   It changes only skip and on-demand decisions within the active revision.
5. **Admin "Engine" panel:** cost per plan and section, on-demand request rates and section reads per org.

### Phase 2: 1–2 weeks

1. One-pass v2 (Brain 4.0 inline), by the one-pass session: dev trial, refit, seal.
2. A generalised shadow runner (`engine.shadow`, the `brain4_shadow` pattern) for any registered module, under its
   own cap.
3. The quality table, filled from the blind checkpoint (25 then 50 calls), gold v1 and the bench.
4. The **sealed plan set** with Root, so the router may pick between sealed profiles per call: Gemini or Luna C4,
   standard or Flex.

### Phase 3: 2–4 weeks

- The contextual bandit on depth and presentation, with the owner's value weights and an Admin experiment page:
  pre-registered metric, stopping rule, results with intervals.

### Phase 4

- A learned router (call features → probability someone needs each section) to decide precompute vs on-demand per
  call.
- Drift alerts (`brain4_eval` drop alerts) feed back into the gates.

## 7. What it would have chosen on today's mix (measured inputs)

| Plan for analysed calls | ₹/min all-in | Status |
|---|---:|---|
| Today: one-pass v1 + C5, standard | 0.709 | live |
| Brain 4.0 Report orgs, C5 on demand, standard | 0.62–0.67 | needs v2 + an owner decision |
| Same, Flex for background calls (all background) | 0.31–0.33 | option A sealed; needs the owner's switch |
| Luna (facts + Brain 4.0), Flex, C5 on demand | 0.153–0.156 | needs the Luna seal (Root) and Luna's own Brain 4.0 calibration (gold v1: Luna 39–40%, low across the board) |
| + compact transcript | 0.112–0.115 | needs the owner to accept −2.3 points of speaker accuracy |

The engine does not invent savings. It makes these choices per call and per org, logs them, and turns the next
module swap into a declaration plus a gate instead of a rebuild.
