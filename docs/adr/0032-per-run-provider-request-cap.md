# ADR 0032: Provider request caps apply per analysis run

Date: 2026-09-28. Status: implemented; owner review pending.

## Authority and problem

The owner's decision in [GitHub #81](https://github.com/authorityclosers/authority-closers-platform/issues/81)
and [AUT-4 decisions D1/D2](https://paperclip.authorityclosers.com/AUT/issues/AUT-4#document-plan)
allow another analysis of identical audio, subject to the person's allowance and
the shared spending cap. A new upload creates a new recording/run.

Acquisition stage approvals are derived from tenant, processing person, source
hash and stage. Because submissions share a processing person, counting every
reservation under that approval made `max_requests` a lifetime cap on the audio
across uploads and owners.

## Decision

Keep the approval-prefix match and count only reservations whose existing
`quote.source.tenant_id` and `quote.source.recording_id` identify the current
recording. These fields are already persisted in the budget snapshot; no schema
change or historical rewrite is required. The budget lock still makes admission
and reservation atomic.

Within that recording, `max_requests` and any matching supplement retain their
existing enforcement and denial text. The `provider_stage_request_count` tester
scope retains its existing exemption. Person allowance, shared spending limits,
uncertain holds, approval derivation, approval files and authorization-reference
format are unchanged.

Each new recording reserves and dispatches its own provider work. Cache lookups
remain recording-scoped. Identical audio from another owner does not supply a
cached result or change the response semantics.

## Alternatives rejected

- Add the recording ID to approval derivation: unnecessary; it changes approval
  identity and authorization references when the persisted reservation already
  identifies the recording.
- Remove the request cap or require a tester exemption for re-analysis: either
  weakens within-run limits or leaves ordinary owners unable to re-analyse.
- Reuse provider results across recordings: outside this decision and contrary
  to the requirement for independent runs without cross-owner reuse signals.

## Verification

PostgreSQL regressions cover same-owner and cross-owner identical uploads,
separate reservations/provider calls, equivalent run response fields, per-run
limits, tester scope, and shared spending caps/uncertain holds. Existing allowance
and supplement regressions also pass. All fixtures use fictional accounts,
synthetic audio and a synthetic provider broker.

Local evidence on 2026-09-28:

- 21 PostgreSQL cases passed: both changed suites, `test_stage_supplement_postgresql.py`,
  plus existing claimed-person allowance, concurrent guest allowance, and exhausted
  upload replay checks. The disposable database and opt-in native test toolchain
  supplied by AUT-14/AUT-37 were used; no hosted provider was contacted.
- Regression sensitivity: substituting the old approval-prefix-only filter inside
  an isolated test process made all three re-upload cases fail with the original
  provider-allowance denial. The working-tree implementation was not reverted.
- 77 entitlement, activation-contract and internal-tester unit tests passed.
- Ruff format/check, mypy, ADR Prettier and `git diff --check` passed.

The public dev URL returned HTTP 403; its local web root returned HTTP 200.
Authenticated dev analysis remains unverified (tracked in AUT-38). After owner
merge, repeat the fictional same-owner and cross-owner upload checks on staging.
No successful dev provider journey or staging verification is claimed here.
