# Implementation handoff

## Required inputs

Start with:

- `01-research-journeys/source-manifest.csv` for exact controlled source IDs;
- `01-research-journeys/flow-catalog.md` for stable IDs/routes;
- `02-ux-state-spec/state-transition-matrix.csv` for row-level behavior;
- `02-ux-state-spec/behavioral-spec.md` for cross-cutting semantics;
- `05-handoff-qa/component-contract.md` for reusable UI contracts;
- `05-handoff-qa/qa-release-checklist.md` for evidence gates.

## Build sequencing

1. Reconcile route/authz/data owners against controlled IA/API/Security docs.
2. Implement or verify shared shell, focus, status, responsive, and theme
   primitives without changing canonical data semantics.
3. Implement Dashboard/My Learning/Discover/program/module read surfaces with
   route-shaped loading, empty, partial, stale, lock, and expiry states.
4. Implement activity shell and draft/recovery behavior; media/avatar/
   certificate mutations remain behind their capability gates.
5. Add Progress/Insights/Plans/Notifications with explicit canonical versus
   descriptive data labels.
6. Run structural and journey QA, then attach exact runtime evidence.

## Stop conditions

Stop and record a gap rather than inventing behavior when implementation needs
an undefined payment/access rule, score/mastery taxonomy, provider contract,
schedule/notification commitment, privacy/retention rule, tenant/permission
decision, or certificate issuance policy. A P0 blocks the affected capability,
not unrelated documentation or shell work.

## Evidence format

For each changed screen/state record: requirement/source IDs, route and actor,
canonical entity, state transition, positive and negative acceptance cases,
privacy/security note, accessibility check, failure/retry proof, and exact
commit/environment. Keep superseded evidence identifiable; do not overwrite
audit-critical history.
