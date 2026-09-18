# Sales Xray report recovery and editable budget

## Scope

Combines the audited Admin/CLI shared-budget control with strict compatibility for
the observed C5 provider response shape. The report parser preserves behavior,
why-it-matters, uncertainty and source evidence. Unknown or ambiguous shapes still
fail validation; this change does not invent findings or suppress source checks.

Budget changes are revisioned and idempotent, require an existing authorized
operator, stay within the pinned release ceiling, and preserve held/spent amounts.
Operational recovery uses the canonical retained-response service, not SQL edits.

## Validation

- Combined checkout: 49 targeted report, retained-recovery, budget and provider
  activation tests passed.
- Ruff check and format on the CI scope (`packages/python tests`) passed; 674
  files already formatted.
- Mypy passed for all 300 source files.
- C5 slice author reports 169 focused tests passed before integration.
- Live guest screen was checked before release: transcript and conversation
  complete, report paused. This file is not evidence of production recovery.

## Operational configuration direction

The owner requires operational values such as shared spend limits, provider
selection, retry counts/backoff, supported processing ceilings and output limits
to be configurable through Admin and/or an audited CLI. New work should use
typed, bounded, persisted settings with revision history and clear effective
values rather than introduce hardcoded operational tuning. Existing accepted
plans retain their approved settings. Invariants and authorization checks remain
code-enforced. This release exposes the shared budget; it does not claim every
existing operational setting is already editable.

## Integrated recovery follow-up

The exact retained response required the additionally verified nested legacy
finding variant. Offline validation with the complete saved response and the
verified playback-bounded transcript passed: eight dimensions, nine sections,
overview present, source checks preserved, zero provider calls or DB writes.

One automatic C5 format repair is now included for newly accepted plans whose
provider approval permits it. The quote reserves its maximum cost. Only a known
validation failure after a persisted provider return qualifies; unknown network
dispatch is excluded. Original raw output and uncertain reservations remain.
Older accepted manifests retain their original budget. A PostgreSQL regression
exercises scheduler, failed response, repair, and final report persistence.

Combined Ruff/format and mypy checks passed. The broad local Windows unit run
reported 955 passed, 19 skipped, and 31 failures in filesystem/runtime fixtures;
it is not a passing full-suite claim. The exact Linux/PostgreSQL CI run remains
the release gate. Earlier focused report/recovery/budget checks passed.

## Remaining release proof

Validate the exact retained production response against the candidate; finish
CI and canonical staging/production installation; apply the approved budget
through the canonical Admin service; revalidate the retained C5 response; open
the real guest report in the browser. Preserve the original response and cost
history throughout. Production readiness is not claimed until those steps pass.
