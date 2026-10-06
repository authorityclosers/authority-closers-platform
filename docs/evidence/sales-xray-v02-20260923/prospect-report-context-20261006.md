# AUT-1070 previous-call report context

Source pin: `555f52bf8f9562647a2f48e9945a109c46bbe7b5`; branch `task/sx-prospects/1070-prior-call-context`. Card 2 is merged in PR #364 (`afc8a70`). AUT-1375's live receipt remains separate; AUT-1373's post-verification queue order is unchanged.

Scope: `conversation_intelligence/prospect_report_context.py`, `prospect_library.py`, `acquisition_reports.py`, `tests/database/test_prospect_report_context_postgresql.py`, `tests/unit/conversation_intelligence/test_prospect_report_context.py`, and this evidence. Open PR file reservations were checked before editing; no overlapping files. The fictional HTTP/privacy fixtures exceed the approximate 300-line target within this single feature. No screen files or migrations changed.

## Composition and generation boundary

The generated report response now composes a local `previous_call_context` section. It uses only persisted, active confirmed memberships and the personal Calls authorization query, including explicit guest-to-account claims. Organisation-wide reading does not widen this context. Suggested matches do not establish context.

Cross-call text is resolved locally after current report/session admission. No prior text is copied into a provider prompt, task input, C5/C6 checkpoint, persisted report, or audit event. Consequently the existing provider, consent and external-processing contracts remain authoritative and unchanged. This is a source-citation section, not model-generated cross-call advice or a new canonical promise/profile state.

The six additional SQL reads are independent of history size, including empty history: current membership; lock at most three prior recording rows; recheck the same locked memberships; three batch snapshot/privacy reads. Selection uses acquisition receipt `(created_at, submission_id)`, descending to choose the nearest three earlier candidates; the response presents them ascending. These are receipt timestamps, not inferred conversation dates. There is no scan/retry to replace missing source details.

Prior report revisions must exist by the current report's creation time. Their source/checkpoint hashes and transcript lineage are verified with the existing snapshot reader. A newer revision cannot silently change an older report's citation. Current membership/source availability and privacy marks are checked on every read, so unlinking, source erasure, revocation, expiration, corruption and sensitive-segment withholding remove context immediately. Recording read fences serialize source erasure; the post-lock query cannot substitute an unlocked source.

`source_quotes` contains only exact transcript wording cited by the prior report's prospect notes, tasks or literal prospect details, with source-clock segment bounds. There are at most 12 quotes per source. Generated observations and hypotheses remain in the separate `report_interpretations` array with `interpretation_kind: "inference"`. No promise classification, fulfilment, score or hidden person attribute is inferred.

## Changed response contract

`GET /v1/conversation/submissions/{submission_id}/report` retains report-envelope/2 and adds the following top-level member for signed-in account reads. Guest previews omit it. A missing/unconfirmed membership returns null IDs and `sources: []`; a confirmed membership with no usable previous details returns its IDs and an empty sources array. Existing canonical report content stays source-bound to the current call.

Fictional example (placeholder IDs/digests illustrate the contract):

```json
{
  "previous_call_context": {
    "schema": "ac.sales-xray.previous-call-context/1",
    "composition": "local_source_citations",
    "membership_id": "22222222-2222-4222-8222-222222222222",
    "prospect_id": "33333333-3333-4333-8333-333333333333",
    "sources": [
      {
        "membership_id": "44444444-4444-4444-8444-444444444444",
        "submission_id": "11111111-1111-4111-8111-111111111111",
        "recording_id": "55555555-5555-4555-8555-555555555555",
        "call_created_at": "2026-10-06T09:00:00+00:00",
        "report_url": "/analysis/calls/11111111-1111-4111-8111-111111111111",
        "reference": {
          "snapshot_id": "66666666-6666-4666-8666-666666666666",
          "snapshot_kind": "c5_checkpoint",
          "source_revision": 1,
          "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "transcript_revision": "fictional-transcript-r1",
          "report_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "report_created_at": "2026-10-06T09:05:00+00:00",
          "transcript_checkpoint_id": "77777777-7777-4777-8777-777777777777",
          "transcript_manifest_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        },
        "source_quotes": [
          {
            "segment_id": "s1",
            "quote": "I will send the proposal on Friday.",
            "start_ms": 0,
            "end_ms": 900
          }
        ],
        "report_interpretations": [
          {
            "source": {
              "text": "A next action was stated.",
              "evidence": [
                {
                  "segment_id": "s1",
                  "quote": "I will send the proposal on Friday.",
                  "start_ms": 0,
                  "end_ms": 900
                }
              ]
            },
            "possible_concern": "The prospect may want time to review.",
            "interpretation_kind": "inference"
          }
        ]
      }
    ]
  }
}
```

UI Maker handoff: display the source quotations and link each to `report_url`; keep the source reference attached to its quote. Treat report interpretations as hypotheses. Use an empty section when `sources` is empty. This response does not authorize a prior call's audio.

## Verification and dev check

- Focused fictional PostgreSQL/HTTP proof: 10 tests passed, including the exact promise/provenance, unconfirmed match, immutable prior report bytes, seven withdrawal states, person/workspace isolation, six-query empty/nonempty reads, deterministic timestamp ties, three-source cap and creation-time revision cutoff.
- Adjacent prospect library/confirmation and report access/read tests: 48 passed. The earlier combined run's erasure-fixture failure was corrected to erase both manifest and payload; the focused final rerun passed.
- Two focused unit tests passed: seller-task promises retain the original quotation and omit unsupported or generated task wording.
- `uv run ruff format --check packages/python tests` and `uv run ruff check packages/python tests` passed. `uv run mypy packages/python` passed for 432 source files. Markdown passed Prettier; `git diff --check` and the current `ac-gate check` passed.
- Dev baseline: `https://salesxray-dev.authorityclosers.com/prospects` returned 302 to sign-in; loopback API report admission returned 404. Authenticated live dev/staging acceptance is not claimed. Tests used disposable local PostgreSQL schemas and fictional recordings; no external provider ran.
- The requested Windows `ac-orchestra` skill and prior Pro-chat artifacts were unavailable in this Linux environment. No cloud claim is used as evidence.

After governed delivery, use a fictional signed-in account on dev, then staging: create a prospect from call A; explicitly confirm call B against that prospect; request B's report and check `previous_call_context` cites A's report, transcript revision and original quote. Without B's confirmation the array is empty. Revoke/unlink/erase A through an authorized app path and check its context disappears. Use another fictional account/workspace to verify A's source details are absent. UI presentation wiring belongs to the UI Maker; this card supplies the cited response contract.
