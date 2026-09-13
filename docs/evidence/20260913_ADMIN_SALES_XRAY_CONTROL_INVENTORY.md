# Admin Sales Xray control inventory

Status: implemented control-center UX on `codex/admin-controls-20260913` from `77b918c`.

Scope: the Admin Sales Xray routes outside the reviewer implementation. The control center presents the existing server-authorized capabilities and keeps missing benchmark/provider-test actions explicit.

## Route inventory

| Route                   | Purpose                     | Real capability                                                                                                                                                                         |
| ----------------------- | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/sales-xray`           | Control center              | Shows provider setup, routing revisions, and the configured spend ceiling. Links to supported settings and reviewer entrypoints.                                                        |
| `/sales-xray/settings`  | Provider and route settings | Reads and saves immutable provider configuration revisions through the existing admin endpoint. Stores provider/model bindings, opaque references, and task route revision identifiers. |
| `/sales-xray/benchmark` | Benchmark readiness         | Shows the current setup, links to provider settings and reviewer invitations, and keeps advanced API gaps collapsed.                                                                    |
| `/sales-xray/review`    | Reviewer entrypoint         | Existing reviewer assignment queue; this slice links to it without changing the review subtree.                                                                                         |

## Existing backend surface

The current HTTP composition exposes:

- `GET /v1/admin/conversation/providers`: safe provider catalog plus the current tenant-scoped configuration revision.
- `POST /v1/admin/conversation/providers`: appends an immutable configuration revision after verified AC admin authorization, current-revision checking, idempotency, and zero-paid-spend validation. The payload accepts opaque references; it does not accept secret values or activate execution.
- `GET/POST /v1/admin/conversation/review-assignments` and the existing revoke routes: server-authorized human reviewer handoffs.
- `POST /v1/conversation/recordings/{recording_id}/analysis/quote`, `POST /v1/conversation/recordings/{recording_id}/analysis`, and progress reads: recording-owner and stage-consent scoped analysis, not admin benchmark execution.

The source of truth for these findings is `packages/python/ac_platform/http/conversation_admin.py`, `conversation_analysis.py`, `conversation_reviews.py`, and `conversation_intelligence/provider_admin.py` at this commit.

## Exact gaps kept visible

The current composition has no routes for:

- `GET/POST /v1/admin/conversation/benchmarks`;
- `POST /v1/admin/conversation/test-runs`;
- `POST /v1/admin/conversation/providers/{provider_id}/probe`;
- prompt/profile parameter-object CRUD or model-training controls; or
- hosted run history/results for the benchmark plan.

`packages/python/ac_platform/conversation_intelligence/approved_call_test.py` is a supervised private proof runner. Its module docstring explicitly states that it is not a hosted worker or HTTP surface. It therefore cannot be safely called by a browser control without a separately authorized server contract covering consent, retention, provenance, provider activation, professional review, and result storage.

The benchmark plan in `docs/implementation/SALES_XRAY_BENCHMARK_PLAN.md` remains a plan and does not provide execution evidence. No benchmark result, provider quality claim, model-training action, paid external test, or automatic official score is asserted by this UI.

## Parameter semantics

Settings expose `recipe_revision`, `profile_revision`, and `prompt_revision` because the provider registry already persists those route fields. They are references to approved configuration revisions. The UI labels them as analysis revisions and states that changing them does not train a model or start analysis.

## Verification

Focused checks for this slice:

```text
pnpm --filter @ac/admin-web exec vitest run app/sales-xray/provider-controls.test.tsx app/sales-xray/control-center.test.tsx app/sales-xray/benchmark-center.test.tsx
pnpm --filter @ac/admin-web typecheck
pnpm --filter @ac/admin-web build
```

Browser or hosted verification remains separate; this change does not deploy or mutate services.
