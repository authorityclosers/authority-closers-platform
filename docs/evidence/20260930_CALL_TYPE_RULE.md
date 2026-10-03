# Call type rule, proposed `call_types_v1` (AUT-629)

Source: AUT-341 decision brief, decision 1 (revision `668194a2`), and the owner's
call-type table on AUT-341 (30 Sep, §3). Base: `main` at `6f04a808`.

## What landed

- `apps/sales-xray-web/app/call-type.ts` (`deriveCallType`) and its Python twin
  `packages/python/ac_platform/conversation_intelligence/call_type.py`
  (`derive_call_type`). Both are pure functions with no model call and no
  transcript parsing. They return one closed key, never a number.
- `profiles/call_types_v1.json`: `status: proposed`. It maps the owner's eight
  labels to stable keys, records the rule order, the reading of each rule and
  the thresholds. Report Lab v8 reuses it.
- `apps/sales-xray-web/tests/fixtures/call-type-vectors.json`: 47 fictional
  vectors that both languages read.

Not wired anywhere yet: no UI chip, no call-map output, no runtime activation.
Real calls carry no `call_purpose` before v7 and Gate 2, so any caller gets
`unclear`. The rule never makes up a type.

## Rule (first match wins)

1. `not_sales`: `call_purpose` is support, onboarding, internal or personal.
   A missing, `unclear` or unknown purpose returns `unclear`. The rule never
   infers it from phases.
2. `objection_negotiation`: objection time is more than every other stage's
   time. A tie does not match.
3. `prospect_story`: prospect talk share > 0.6. Exactly 0.6 does not match.
4. `screening`: the call is ≤ `short_call_ms`, at least one qualification item
   is confirmed, there is no pitch, and the outcome is `follow_up`,
   `disqualified` or `lost`.
5. `first_meeting`: discovery, with no pitch and no close.
6. `pitch_demo`: pitch time > 0.5 × duration and discovery ≤
   `little_questions_ms`.
7. `follow_up_closing`: discovery ≤ `little_questions_ms`, and either a close
   or a measured price moment (`price_moments` > 0, from call-metrics). Missing
   price data counts as no price talk; the rule never guesses it.
8. `full_sales`: discovery, pitch and close are all present.
9. Otherwise `unclear`.

Stage time: phases are sorted by start. Each phase ends where the next one
starts, and the last one ends at the call's duration. Times are clipped to the
call. Repeated stages add up. Objection time is the union of the objection
phases and any `objection_spans`, so overlaps count once.

`unclear` is also returned for: a missing or non-finite duration, share or
timing; zero duration; a share outside 0–1; no phases; an unknown phase name or
outcome; a missing qualification list; an objection span that ends before it
starts.

## Proposed thresholds (not approved business semantics)

`CALL_TYPE_THRESHOLDS` in both twins, equal to the profile and the vectors (a
test pins all three):

| key | value | owner's words |
|---|---|---|
| `prospect_share_over` | 0.6 | prospect talks more than 60% |
| `pitch_share_over` | 0.5 | pitch is more than half |
| `short_call_ms` | 600000 (10 min) | short (screening) |
| `little_questions_ms` | 120000 (2 min) | little or short questioning |

The owner fixes these, the rule readings for `screening` (no pitch; which
outcomes count as advance or stop) and `follow_up_closing`, and the list itself
at Gate 2, together with the signal list.

## Hashes

- `call_types_v1.json` sha256 `122c9b2c9280350b5bd6bb86619e61b79ca67cb1ef9cf8dec682d6e0ef0a2188`
- `call-type-vectors.json` sha256 `4338020e15139fe359a5c829505c22edaff4072669d3a06580ac7c119311d33b`

## Vector coverage

All eight types and `unclear`; missing, unclear and unknown purpose; prospect
share exactly 0.60 and 0.61; pitch exactly half and half + 1 ms; short call at
10 min − 1 ms, at 10 min and at 10 min + 1 ms; little questioning at 2 min
− 1 ms, at 2 min and at 2 min + 1 ms; repeated discovery adding up past the
limit; a repeated opening; objection tied with other stages; an objection span
inside (counted once) and past the objection phase; phases out of order;
phases that share a start; a phase after the call end; and order proofs
(objection over prospect story, screening over first meeting, `not_sales` over
sales phases).

## Runs

```
$ pnpm --filter @ac/sales-xray-web test app/call-type.test.ts
 Test Files  1 passed (1)
      Tests  54 passed (54)

$ uv run pytest -q tests/unit/conversation_intelligence/test_call_type.py
56 passed

$ pnpm --filter @ac/sales-xray-web test app/call-type.test.ts app/call-metrics.test.ts app/call-map-contract.test.ts
 Test Files  3 passed (3)
      Tests  130 passed (130)

$ uv run pytest -q tests/unit/conversation_intelligence/test_call_type.py tests/unit/conversation_intelligence/test_call_metrics.py
92 passed
```

Also clean: `ruff format --check`, `ruff check`, `mypy packages/python`, and
the web lint, typecheck and prettier checks.
