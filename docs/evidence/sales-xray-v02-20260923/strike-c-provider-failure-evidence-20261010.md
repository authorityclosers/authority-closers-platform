# Strike C: preserve original provider failure evidence

Task: [AUT-1676](/AUT/issues/AUT-1676). Strike baseline: `b6033ad3d3d55f928547e2901785e6e239357bdc`.

When a broker returns an HTTP failure observation, the inference worker currently discards it and
dead-letters the job. A historical `last_error` string cannot reconstruct the original response's
completeness, attempt binding or Retry-After. In addition, the observation validator rejected
digit-leading run UUIDs.

This bounded worker slice accepts digit-leading reservation/attempt identifiers, retains the
stricter named provider/route identifier rules, and commits original sanitized transport evidence
before failure cleanup. The event uses the existing append-only audit chain. The live lease,
recovery generation, tenant, run, dispatch key, quote, provider/model/operation and input digest
bind the append. An identical append is idempotent; conflicting observations cannot replace it.
Incomplete observations remain incomplete. No body or raw provider request ID is retained.

This slice does not schedule retries or change customer/provider accounting. The dispatch marker and
generic Admin retry guard remain in force. It does not repair the historical incident, manufacture
missing observations or assert a delivered report. Bounded retry coordination, stale-work recovery,
terminal customer settlement, UI states and historical recovery remain on this strike; ledger
changes must use the separate small sensitive PR route.

## Controlled intake

Exact IDs were fetched from
`docs/workflows/instructor-admin-workflow/01-research-journeys/source-manifest.csv` in the
prescribed order: Master Index, approved BRD, AC-IMP-00/01/03/04/05, then PRD, IA, UX Research, UX
States, UI System, SRS, Data/Tenancy, API/MCP, Security, QA, DevOps, Admin, Telemetry and ADR/Risk.
AC-UXA-01 and AC-GOV-AUD-001 were also fetched through the exact IDs in AC-IMP-01. No scoring,
provider route activation or real-call replay is part of this change.

Applied controls: BRD Q073; AC-IMP-03 ENG-G02/ENG-G10 and UX-G05; QA failure/retry and integrity
requirements. The [CTO refusal decision](/AUT/issues/AUT-1617#document-decision), revision
`23814a68-b4e1-429c-87d9-94bd1dc2dfa9`, requires original bound observations before retry and
separates retry eligibility from charge certainty.

Preserved the [inventory](/AUT/issues/AUT-1683#document-inventory), revision
`c6273b5b-4087-42d1-8b0f-83760ac2e027`: cutoff 9 October 20:52:06 UTC; 35 staging and 21 production
dead letters at 1/3 attempts. This is the existing all-record snapshot, not a fresh 14-day staging
reproduction or recovery dry-run.

## Evidence contract and UI wiring

The new system audit action is `conversation.provider_failure_observed` with resource type `job`.
Its payload has schema `ac.sales_xray.provider_failure_evidence/1`, `job_id`, `attempt_count`,
`recovery_generation`, `dispatch_started_at`, and `failure_observation`. The nested observation
keeps schema `ac.sales_xray.provider_failure_observation/1` and its existing exact transport shape,
including `response_body_complete`, `response_body_observed_bytes`, nullable `response_body_sha256`,
nullable `provider_request_id_sha256` and nullable `retry_after_seconds`. A future coordinator must
use original evidence and the separately reviewed attempt/budget authority. The event is not a
provider success, no-charge receipt or customer settlement.

Public progress response shape is unchanged. Fictional example of a failed provider stage under the
current API:

```json
{
  "submission_id": "01234567-89ab-4cde-8f01-23456789abcd",
  "recording_id": "12345678-9abc-4def-8012-3456789abcde",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "local_state": "completed",
  "state": "held",
  "has_report": false,
  "automatic_progression": false,
  "execution_hold": null,
  "failure_code": "conversation_provider_http_503",
  "stages": [{"stage": "C5", "state": "uncertain"}]
}
```

UI consumers cannot infer automatic retry, returned minutes, no provider charge or report delivery
from that shape. New terminal/retry fields remain to be implemented with their canonical state
transitions. Ownership-scoped reads are unchanged; no audit internals are added to learner
responses.

## Verification and limits

- Changed Python files pass Ruff lint and formatting; package mypy passed for
  all 437 source files after fixing the nullable tenant guard.
- The focused observation, provider transport and inference-worker stage suite
  passed: **79 tests**. Two broader unit runs reached 87 passing cases but failed in existing real
  broker subprocess timeout tests (`broker_process_unavailable` instead of
  `broker_timeout`); both runs were stopped. The wrapper-descendant timeout test
  passed independently (1 passed). These are not complete passing suite receipts.
- Initial PostgreSQL runs failed in native fixture preparation before entering
  the changed inference worker. The missing AudioAtlas binary was built and
  hash-verified using the same build function as CI. Native inspection then timed
  out waiting for the installed shared heavy-work launcher. Its live guardian
  was verified to belong to another run and was left alone.
- The new database tests now seed the known fictional one-second recording's
  source-bound checkpoint fixture directly, isolating provider evidence from
  native decoding. They cover complete/incomplete observations, a binding
  mismatch, evidence surviving cleanup failure, identical/conflicting appends,
  stale lease/generation fencing and the generic retry guard. All **4 PostgreSQL
  cases passed** locally in 73.30 seconds. CI and staging verification remain
  separate requirements.
- Database invocations explicitly selected the existing disposable loopback
  `ac_test_lane_sx-billing`. The launcher-provided URLs still named sx-prospects;
  neither that database nor host settings were changed.
- Dev and staging public URLs returned HTTP 403. No authenticated preview,
  fresh staging read-back, provider replay, settlement, host activation,
  deployment or production journey is claimed.

Dev: <https://salesxray-dev.authorityclosers.com>. Rollback is a code revert through the normal
release path; previously appended audit observations remain preserved.
