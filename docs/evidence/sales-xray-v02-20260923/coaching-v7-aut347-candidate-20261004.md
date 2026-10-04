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
the pack, C5 adapters, plans, runtime gates, frozen attribution and the B1 call
map. The first complete run passed 407 tests. Ruff format/check and mypy passed
(397 source files). The final PR records the final test count.

The 60-minute fictional C2 fixture retains every source turn and fits the
existing structured input envelope, including the larger v7 schema. The output
cap remains 8,000, and the existing cost-admission checks still pass. This
proves input admission, not the largest-output acceptance check.

Dev `https://salesxray-dev.authorityclosers.com` returned a Cloudflare sign-in
redirect. No credential workaround or real-call check was attempted. The
candidate is intentionally unavailable at runtime.

## Unmet acceptance: largest valid completion

`test_v7_largest_output_acceptance_is_blocked_by_retained_prose_bounds` preserves
a schema-valid lower-bound counterexample: 3 strengths, 3 improvements,
10 missed opportunities, 8 objection findings and 8 closing findings, each
within the retained 4,000-character explanation limit and with two direct
segment references. This is not even a maximum call-map/speaker/sensitive
output. It serializes to **137,948 bytes**, or **45,983 conservative /3 byte
units**, against the fixed **8,000 total-output cap**. These are conservative
planning units, not measured provider token usage. The provider schema also
retains unbounded prose strings, so it does not define a finite largest output.

Passing a small or maximum-cardinality short fixture would not establish the
card's largest-valid-output claim. No generation cap, quote requirement,
contract cardinality, provider allowance or acceptance criterion was silently
changed to make that assertion pass. Runtime refusal remains in place.

CTO review must settle the bounded v7 generation envelope shared with B3:
prefer compact evidence selectors plus explicit prose/aggregate bounds while
preserving the canonical B1 storage contract and fixed provider cap. An
alternative is to amend the largest-output criterion to test bounded accepted
responses and explicit exhaustion refusal; that would change the card's
acceptance rather than prove the current one. The draft PR must not merge
as a completed AUT-347 until this acceptance is resolved.

## Scope choice

The accumulated amendments exceed the original approximate 300-line target;
they still implement one dormant C5 candidate. Existing assertions in
`test_coaching_v5_depth.py`, `test_coaching_v6_integration.py` and
`test_speaker_roles_report_input.py` were updated only for the new declared
revision and retained gate/pin checks. This evidence file is the additional
implementation record. Validation/storage, runtime activation, rubrics,
providers, routes, stages and screens remain outside this change.

## Offline dev check

On `task/sales-xray/347-coaching-v7`, run the focused pytest command in the PR.
Inspect the new prompt/schema tests, then the two v7 budget tests: full-hour
input admission passes, and the counterexample records the unresolved output
bound. Confirm `coaching_revision_runtime_block("coaching-v7")` returns the
Gate 2 refusal. No real report rerun is part of this check.
