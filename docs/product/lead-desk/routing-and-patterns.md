# Smart routing and the pattern engine: who should get which leads, without AI

The owner, 25 Oct 2026, ~17:00 IST: "assign leads that are more than x value to [seller A] and under Y
value to [seller B]… I need this smartness inside our own salesxray inbuilt without even using AI, so
pattern recognition… native analysis engine built and suggestions… if a salesperson is really good at
converting specific type or category leads it can prompt or notify owner to assign these group of
leads… it auto groups, gives a simple reason and asks to assign".

This doc is the design. It builds on the lead rules that exist (`allocation.py`: availability,
caps, languages, areas, interests, fewest open), on distribution (`team-engine.md` section 1) and on
the universal intake (`universal-intake.md`).

## 1. What a lead carries for routing

| Facet | From | Example |
|---|---|---|
| Source and channel | the intake (connection, form id, file label) | "Meta form 1012520495288699", "Zoho CRM export" |
| Answers | a lead form's questions, made readable at intake | "What do you currently do?" = "Business owner / startup" |
| Value | an answer or column the owner marks as value, read as a number band | "₹60,000 – ₹1,00,000" → 60,000–1,00,000 (low, high, mid) |
| Place, language, interest | the existing fields | Pune, Marathi, "3 kW rooftop" |
| Received at | the source's own time | 19 May 2026, 20:16 IST |

- **Answers** become facets: (question, answer) pairs kept per lead in an indexed table, so lists
  filter by them and rules read them. Free text stays in the payload.
- **Value** is set per organisation: "the value of a lead is its answer to …", with the bands read
  as numbers.
  - A band like "₹1,00,000+" has a low and no high.
  - A lead without the answer has no value, and value rules skip it.

## 2. Rules: the owner's "more than X to one seller, under Y to another"

A routing rule is: **when** a condition on facets, **give to** one person or a group (round-robin
inside it), **within** caps.

- **Conditions:** value ≥ / < / between; answer is one of; source or channel is; city, language or
  interest is. Several conditions in one rule all apply.
- **Order:** rules are tried top to bottom, and the first that matches gives the lead out. A lead no
  rule matches goes by the existing lead rules (fewest open among the available).
- **Caps:** a person at their open-lead cap is skipped. If a group is full, the lead falls to the
  next rule, and the history line says so ("Rule 1: Asha away or at their limit, given by the lead rules").
- **Every assignment says why:** "Value ₹1,00,000+ ≥ ₹1,00,000: Asha (rule 1)".
- **Edits:** rules are versioned and edits supersede. A new version applies to leads arriving after
  it.
  - "Apply to waiting leads" runs the distribution (`POST /leads/distribute`) with the rule as a
    preview first.
- **Pure core:** `routing.decide(lead_facets, rules, team_state) -> Decision(person, rule, why)`.
  No database and no clock, with property tests: deterministic, caps never exceeded, the first
  matching rule wins.

## 3. The pattern engine: who converts which leads best

It is plain counting with guards, no model.

- **Segments:** each facet value is a segment ("Business owner / startup", "₹60,000 – ₹1,00,000",
  "Pune", "Meta form …"). So is each pair of facets, once the single ones have enough data.
- **Per seller × segment**, over the last 90 days of leads that were given out:
  - conversion = Won ÷ (Won + Lost), with Junk left out as the Lead OS reports do;
  - speed = the median minutes to the first call;
  - connect rate = connected ÷ calls.
- **Guards** (it never suggests on thin data):
  - at least 10 closed leads for the seller in the segment;
  - at least 30 closed in the segment across the team;
  - the seller's rate, smoothed toward the team's (a Beta prior worth 10 leads), beats the team's
    rate by at least 1.5× and 10 points;
  - the 80% intervals of the seller's and the team's rates don't overlap.
- **Output:** `Pattern(seller, segment, rate, team_rate, closed, won, speed)`, recomputed nightly and
  on demand. Stored as a dated snapshot: superseded, never edited.

## 4. Suggestions: grouped, one plain reason, Assign or Dismiss

When a pattern holds and leads in its segment wait (unassigned, or with a seller who converts the
segment worse and hasn't called them yet), the engine makes one **suggestion** per (segment, seller):

> **Asha closes "Business owner / startup" leads best**: 9 of 22 won (41%), the team 14%.
> 6 such leads are waiting. **Assign to Asha** · Dismiss

- Owners and managers see it as a card on Home and in Leads → Team, with a notification once (normal
  urgency, quiet hours respected).
- **Assign** runs the distribution with these leads and that seller: preview, then apply, one history
  line each, "Suggested: closes this kind best".
- **Dismiss** hides it for 14 days or until the numbers change by more than 5 points.
- Every suggestion is stored with its numbers, shown, acted or dismissed: append-only, for audit and
  to measure whether suggestions help (conversion of suggested leads against the rest).
- A suggestion never assigns by itself. An owner may turn a suggestion into a rule ("Always give
  these to Asha"), which goes through section 2.

## 5. API, MCP and AI-writes

Rules, patterns and suggestions are read through the API and the MCP server:
- `GET /routing/rules`, `GET /patterns`, `GET /suggestions`.
- Writes go through the same command endpoints: `PUT /routing/rules`, `POST /suggestions/{id}/assign`
  and `/dismiss`.
- An AI assistant (ChatGPT, Claude) can propose a rule or act on a suggestion only through the
  AI-writes policy engine (design 97207c943): scoped keys, owner-only for rules, a preview the person
  confirms, and the audit trail. The engine itself stays deterministic and explains every number.

## 6. Data (migrations, numbers from the orchestrator)

- `lead_desk_lead_facets`: tenant, lead, key, value text, value low/high numeric. Unique per (lead,
  key), indexed (tenant, key, value). Written at intake and on edit.
- `lead_desk_routing_rules`: versioned rows (tenant, version, position, conditions JSON, target,
  created_by, created_at). The current version is the newest.
- `lead_desk_patterns`: dated snapshots (tenant, as_of, seller, segment key and value, counts, rates).
- `lead_desk_suggestions`: append-only (tenant, segment, seller, numbers, leads at the time, state,
  acted_by, acted_at).

## 7. Slices

1. Facets and value: answers kept as facets at intake; a value answer per organisation; Leads filter
   by answer and by value; the lead page shows answers.
2. Routing rules with value bands, their editor, a preview on waiting leads, and why on every
   assignment.
3. The pattern engine with guards (pure, with property tests), and the nightly snapshot.
4. Suggestions: the card, the notification, Assign through distribution, Dismiss, and their
   measurement.
5. API and MCP reads, and writes through the AI-writes policy.

**As built (R0, pure):** `lead_desk/facets.py` reads a lead's answers as facets and an answer as a
value band (₹, k, lakh, crore, "+", "under", ranges with a shared unit); `lead_desk/routing.py`
decides with rules of value, answer and field conditions, round-robin inside a group, caps and a
one-line reason, with property tests. Value conditions read a band with care: "at least X" needs
its low to be X or more, "below X" its high under X, so a band across the line meets neither and
goes by the lead rules. Tables and the editor come with slices 1 and 2.

## 8. Acceptance

1. With "value ≥ ₹1,00,000 → Asha; value < ₹60,000 → Ravi", a new lead answering
   "₹1,00,000+" goes to Asha and one answering "₹15,000 – ₹30,000" goes to Ravi. Each history
   line names the rule.
2. Asha at their cap: the next high-value lead falls to the lead rules, and the line says so.
3. With 9 of 22 won for Asha in a segment and 14% for the team (30+ closed), a suggestion appears.
   With 4 of 6 won it does not (too few).
4. Assign from a suggestion moves exactly the waiting leads it named, with "Suggested" history lines.
   Dismiss hides it for 14 days.
5. No suggestion or rule ever uses a lead's name, number or free text, and none runs a model.
