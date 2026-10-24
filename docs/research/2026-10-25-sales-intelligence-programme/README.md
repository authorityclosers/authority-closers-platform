# Sales intelligence research programme (25 Oct 2026)

Owner order, 25 Oct 2026: an academic-level, benchmarked research programme for Sales X-Ray
(psychology, UX research, testing and feedback at the core, with large-scale data from
testers), a UX telemetry lab that finds where users get stuck, and a plan for moving to AWS
when load and revenue grow.

**Start with `00-owner-summary.md`: the 10 changes the research implies, on one page.**

| File | What it is |
|---|---|
| `00-owner-summary.md` | The top 10 changes for Sales X-Ray, ranked by impact and effort, with owners and how telemetry proves each |
| `01-field-map.md` | The field: 24 sales-intelligence, conversation-intelligence and inside-sales CRM vendors (global and Indian), features, UX patterns, pricing models, what wins, the white space, 15 recommendations |
| `02-seller-psychology.md` | Sellers' psychology: habits, motivation, targets and quotas, nudges and notification fatigue, gamification, cognitive load on phones, Indian multilingual use; a behaviour model, principles, anti-patterns, specific guidance (targets, drift nudges, leaderboards, streaks, coaching, notification tiers), 15 recommendations |
| `03-ux-research-methods.md` | How we research: moderated tests with real sellers, think-aloud in Hindi and Marathi (prompts in Devanagari, drafts for a native check), task scripts for 7 journeys, SUS, UMUX-Lite, SEQ, HEART, funnels, Keystroke-Level Model, benchmark targets per journey, feedback loops at scale, a research calendar |
| `04-telemetry-lab.md` | The measurement loop: how the new friction telemetry answers the research questions, and what is still to wire |
| `05-scale-and-aws-plan.md` | Plan only: a cost model per seller and per organisation, triggers to move, a phased AWS (Mumbai) plan with spend held to a share of revenue |
| `05a-aws-unit-prices.md` | Verified AWS, R2 and alternative unit prices (Mumbai, 25 Oct 2026) behind chapter 5 |

The lab itself: `docs/product/telemetry-friction-lab.md` (design and the flow contract for
builders); Admin → Product telemetry → Friction; the Monday markdown in
`/home/acdev/reports/telemetry-friction/<env>/latest.md` once the job is installed.

## Evidence standard

- Every factual claim carries a numbered citation; each chapter ends with its references
  (DOIs or URLs, accessed 25 Oct 2026). Nothing was cited that could not be found; anything
  that could not be fully checked is listed at the end of its chapter.
- Inputs are labelled **measured** (our own data), **external** (a source) or **assumed** (our
  proposal, to be replaced by measurement). Chapter 2 also tags evidence strength
  (meta-analysis, randomised, field, observational, lab, practitioner, book).
- Thresholds such as drift-nudge caps, novice time targets and quick-back windows are our
  proposals for testing, not research findings, and are marked so.

## Known gaps

- **Reddit and other community forums are blocked for the research tools**, so there is no
  first-hand seller or practitioner community evidence. The owner can supply threads, or the
  monthly seller interviews can fill it.
- Review sites (G2, Capterra) refused direct access; their themes come from search summaries
  and are marked as such.
- The shared web-search budget ran out partway through each chapter; the unchecked items are
  listed per chapter (for example current IAMAI–Kantar figures, the full DPDP rule text, some
  vendors' Indian-language support and funding).
- No **measured** UX numbers exist yet: the friction telemetry starts recording with the
  release that carries it. The first quarterly benchmark should replace the assumed targets.

## Where the chapters disagree

- **Leaderboards.** Chapter 1 (market practice) suggests team leaderboards blending activity
  with the skill-score trend. Chapter 2 (field evidence) finds rank feedback can lower
  performance, especially for low performers, and that AI scores on leaderboards crowd out
  quality; AGENTS.md also forbids official autonomous AI scoring before the AC-SVAL gates.
  **Decision in the summary:** leaderboards off by default, opt-in, top-3 recognition on
  behaviours sellers control, never AI scores or dials.
- **Pricing.** Chapter 1 records competitors' prices and models for internal comparison only.
  No price appears in the product (owner rule); packaging is the owner's decision.

## Rules kept

No customer or tester names in these files (fictional examples only, such as "Sunrise
Rooftops"); prices and revenue are internal; production data was not queried for this work
(the scale plan uses the 22 Oct capacity audit and 23 Oct economics, both read-only and
logged at the time).
