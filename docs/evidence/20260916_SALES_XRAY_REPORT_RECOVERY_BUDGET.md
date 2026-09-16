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

## Remaining release proof

Validate the exact retained production response against the candidate; finish
CI and canonical staging/production installation; apply the approved budget
through the canonical Admin service; revalidate the retained C5 response; open
the real guest report in the browser. Preserve the original response and cost
history throughout. Automatic paid format-repair retry is a separate bounded
change and is not claimed by this slice.
