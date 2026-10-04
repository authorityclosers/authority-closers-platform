# AUT-347: dormant coaching-v7 candidate

Source pin: main `f8824ad9`. The owning card is AUT-347, including its
HEU-03, P3, speaker-map and ETH-03 amendments. The first CTO brief revision is
`668194a2-482a-4b4c-a73f-13314bc6c159`; later candidate activation is outside
this card. No provider was called, and all fixtures are fictional.

## Implemented

- An explicit v7 prompt asks for the amended B1 `call-map/1`, prospect-owned
  facts, literal next-step wording, answer fit, seller tasks and objections.
  It includes the signal profile's raw-file SHA-256 and closed kind lists.
- HEU-03 remains a prompt rule: absent stages are `not_applicable` with one
  next-time question. The independent D8 evidence ceiling is unchanged.
- Atomic claims cite their own 1–2 segments. Golden moments use direct segment
  references. Overview finding indices remain navigation only.
- Only v7 declares the frozen names-free speaker-role input. Display-only
  speaker names must be stated in cited C2 text; the sole confidence addition
  is the closed low/medium/high speaker label. No account profile name is sent.
- ETH-03 requests only segment IDs and the two legal-exposure categories,
  with no quoted text. Ordinary business figures remain BIZ-03.
- Gemini/OpenAI offline adapters round-trip the v7 marker and schema. The
  existing v6 pack is bound unchanged. Initial C5 requests, HTTP settings
  selection, admin save, stored-plan reuse and worker dispatch refuse v7.

## Verification

The focused suite covers the new candidate, existing v4–v6 prompt/schema pins,
the pack, C5 adapters, plans, runtime gates, frozen attribution, the B1 call
map and the report parser/source pin. **507 tests passed at `b8e0f51`**; its
four CI Python shards were green. The narrow price/budget rebalance passes
**43 prompt/schema/budget tests**, including a price of 180 and prospect budget
of 120 with a budget gap and `affordability_gap`. That fixture also passes
canonical B1 source validation. Ruff format/check
and mypy passed (397 source files). New negative cases reject oversized prose,
names, segment IDs, sensitive lists, offset selectors and excess dimension
evidence. Positive cases cover observed two refs, partial one and conflicted
one or two. Every string/array is bounded; wire call-map maxima are checked
against canonical B1, and generation schemas still strip local bounds.

The 60-minute fictional C2 fixture retains every source turn and fits the
existing structured input envelope, including the larger v7 schema. The output
cap remains 8,000, and the existing cost-admission checks still pass. The
separate output proof below also passes.

Dev `https://salesxray-dev.authorityclosers.com` returned a Cloudflare sign-in
redirect. No credential workaround or real-call check was attempted. The
candidate is intentionally unavailable at runtime.

## Bounded completion proof

The initial candidate at `22bd2e49` recorded a 137,948-byte counterexample
with retained unbounded prose. The CTO's changes-requested decision on
4 October selected Option A: bound v7 alone and keep acceptance check 4 and
the fixed 8,000 cap. This section supersedes that unresolved acceptance.

`test_v7_largest_valid_output_fits_unchanged_completion_cap` recursively walks
the entire local schema. It includes optional properties, every array at
`maxItems`, every free string at `maxLength` using JSON-escape-free ASCII,
the longest enum and the largest serialized `anyOf` branch. Numeric bounds
are also included; monetary `value_min` and `value_max` are now capped at
1e12 in v7 only. The resulting fictional fixture validates against
the local schema. It is a conservative wire-shape maximum; transcript-bound
and cross-field B1 rules can only narrow that envelope.

The CTO's ASCII `/3` planning convention gives **22,670 canonical bytes /
7,557 units**, below **24,000 bytes / 8,000 units**, with 1,330 bytes of room.
These are planning units, not measured provider tokens. Provider generation
schemas still omit local bounds, as requested; this proof covers the bounded
local acceptance schema rather than arbitrary provider output.

| Section/member        | Maximum bytes |
| --------------------- | ------------: |
| summary               |           312 |
| strengths             |           424 |
| improvements          |           427 |
| missed_opportunities  |           435 |
| objection_analysis    |           433 |
| closing_analysis      |           431 |
| verdict               |           312 |
| review_status         |            45 |
| dimensions            |         3,398 |
| overview              |         5,565 |
| call_map              |         8,612 |
| speakers              |         1,436 |
| sensitive_segments    |           826 |
| Outer braces + commas |            14 |
| **Total**             |    **22,670** |

Member sizes include the quoted property key, colon and complete value;
separators and the root braces are counted once in the final row.

The explicit v7 choices reduce counts before shortening prose: one item per
finding category and corresponding detail, golden moment, interpretation and
rewatch; two atomic claims, signals, prospect facts and ethics notes; one
pitch item, pain, prospect task and seller task; three money items and two
objections. The money list can retain both the price and lower prospect budget.
The envelope retains eight dimensions, up to eight phases, all five
qualification items, sixteen call-map speakers, eight display speakers and twelve sensitive
segments. Each display speaker cites one segment. All required fields remain.

Summary/verdict allow 300 characters; finding explanations and dimension
observations 240; one-sentence detail strings 120; call-map item text 120,
claims 160 and facts/signals 80; names 40; literal quotes 64; dates 60; IDs 16. Existing word limits still apply. Report evidence is direct `{segment_id}`
only; findings/dimensions allow at most two refs, observed exactly two, partial
one and golden moments one or two. B1 is untouched. Every local string/list
limit is stated in the v7 prompt from the fresh schema.

The `b8e0f51` envelope fit at 23,535 bytes but allowed only one money row.
The CTO's second review requested exactly this rebalance: three money rows,
1e12 monetary maxima, eight display speakers and two objections. Finding
counts remain one. The accepted proof method and every other limit are unchanged.

## Scope choice

The accumulated amendments exceed the original approximate 300-line target;
they still implement one dormant C5 candidate. Existing assertions in
`test_coaching_v5_depth.py`, `test_coaching_v6_integration.py` and
`test_speaker_roles_report_input.py` were updated only for the new declared
revision and retained gate/pin checks. This evidence file is the additional
implementation record. Validation/storage, runtime activation, rubrics,
providers, routes, stages and screens remain outside this change.

The CTO accepted the accumulated scope overrun. The second commit also
refreshes the whole-file `reports.py` hash assertion in `test_reports.py`,
which was the sole failed first-head CI test. Report validator semantics
remain revision `/8`; only dormant v7 generation changed in that module.

## Offline dev check

On `task/sales-xray/347-coaching-v7`, run the focused pytest command in the PR.
Inspect the new prompt/schema tests, then the two v7 budget tests: full-hour
input admission and the maximum-size completion both pass. Confirm
`coaching_revision_runtime_block("coaching-v7")` returns the
Gate 2 refusal. No real report rerun is part of this check.
