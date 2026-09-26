# Sales Xray quote cap disclosure regression

Verified locally on 26 September 2026 against base commit
`12441bb7b75c0d88575e6913652acc0e42606a99`, with the focused patch described below.
This is local implementation evidence, not a deployment or provider-run receipt.

## Problem and change

When a previous Admin-approved budget ledger has a larger cap than the current
release approval, the hosted-provider quote response exposed the historical
ledger cap. Admission already enforced the smaller effective cap. The response
therefore disagreed with the ceiling enforced for new work.

`ConversationAuthority.issue` now returns the existing
`effective_budget_cap_paise(release_cap, persisted_cap)` result in
`budget_cap_paise`. That helper takes the smaller of the two approved caps. The
patch changes quote disclosure only: it does not edit the budget ledger, grant
new allowance, alter a quote fingerprint, accept a quote, or dispatch a provider.

The existing real-PostgreSQL carried-cap regression now asserts that both quotes
display the current 100,000-paise release cap while the historical Admin ledger
remains at 250,000 paise. Its concurrent admission assertions still prove that
only one of two 60,000-paise requests is admitted, leaving one job and a
60,000-paise reservation.

## Validation

Tests used the disposable local PostgreSQL server on loopback port 55610 and the
repository's isolated-schema harness. Temporary recording storage was placed
under `D:/AuthorityClosers-Private`; that directory and its drive root were checked
to have no `.git` ancestor. Earlier repository-ancestor storage failures did not
exercise the regression and are not counted as validation.

- `test_carried_budget_cap_does_not_expand_current_release_admission`:
  **1 passed in 24.83 seconds**.
- `test_paid_hosted_quote_uses_project_cap_and_preserves_uncertain_hold`,
  `test_named_provider_request_scope_keeps_budget_and_uncertain_stage_holds`, and
  `tests/unit/conversation_intelligence/test_entitlements.py`:
  **40 passed in 38.35 seconds**.
- Ruff check on the two changed Python files: **passed**.
- Ruff format check on the two changed Python files: **passed**.
- `git diff --check` on the two changed Python files: **passed**.

The neighboring tests cover ordinary project-cap disclosure, uncertain provider
holds, count-scope grants that cannot bypass money limits, the lower persisted
cap case, and cumulative reservations against a carried ledger.

No external provider calls, production or staging writes, operational SQL
recovery, or deployment were performed for this verification. Provider behavior
in these tests is synthetic; money and job persistence use real PostgreSQL.

## Review and release boundary

The changed response uses the same existing helper as reservation enforcement.
Historical Admin approval and reservation data remain intact. No migration is
needed. Release review should include this narrow source patch and regression
assertions without bundling unrelated worktree changes. An authenticated staging
quote must still be checked after deployment before claiming the live benchmark
blocker is resolved.
