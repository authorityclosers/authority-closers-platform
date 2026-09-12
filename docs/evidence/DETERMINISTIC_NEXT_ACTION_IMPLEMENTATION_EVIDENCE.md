# Deterministic learner next-action implementation evidence

Status: bounded, additive learner-projection slice; no deployment, production
state change, external provider activation, or analytics write.

## Worktree and source baseline

- Worktree: `D:\Projects\authority-closers-platform-next-action`
- Branch: `codex/deterministic-next-action`
- Base: `65b1f36` (`origin/main` at inspection time)
- Scope: expose the existing canonical progress projection's
  `next_activity_id` to the learner API and consume it only when the returned
  activity is still action-enabled.

## Controlled-source mapping

The exact registered Drive IDs were fetched before editing, in the required
source order:

- Master Index `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`;
- BRD `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk`;
- AC-IMP-00 `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A`;
- AC-IMP-01 `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU`;
- AC-IMP-03 `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo`;
- AC-IMP-04 `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc`;
- AC-IMP-05 `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw`.

The learner and telemetry contracts were also fetched by their registered
IDs:

- PRD `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k`;
- IA `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs`;
- UX Research `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM`;
- UX States `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E`;
- SRS `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g`;
- Data/Tenancy `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`;
- API/MCP `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`;
- Security `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`;
- Telemetry `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I`;
- QA `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`;
- ADR/Risk `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`.

The relevant controlled decisions are:

- BRD progress must show skill/progress and strong next-action guidance;
  required activities and prerequisites are explicit; completion evidence is
  not mastery; the First Win may use deterministic/human-authored guidance.
- AC-IMP-04 defines ordered activities, explicit prerequisites, locked versus
  available state, server-owned progress, and the First Win exact next action.
- PRD, IA, UX Research, and UX States require an understandable next action
  and reason while keeping completion, evidence, and mastery distinct.
- Telemetry and Data/Tenancy make PostgreSQL/domain projections canonical;
  analytics is delayed/lossy and cannot grant access or rewrite progress.
- AC-IMP-03, AC-SVAL, and the ADR/Risk register prohibit autonomous official
  scoring before validation gates.

This slice uses only the already-defined activity order, required flag,
explicit prerequisite evaluation, and canonical activity state. It exposes the
already-existing `CourseProgressProjection.next_activity_id` field and its
existing `projection_version`; it does not introduce an event name, payload,
score, mastery formula, plan item, or new completion predicate.

## Delivered behavior

- `ProgressProjector` now returns a next activity only for a required activity
  in `available` or `in_progress` state. `locked` and `awaiting_review` remain
  visible through the existing activity-reason projection but are not emitted
  as an action. If no required activity is eligible, the pointer is null.
- `GET /v1/learning` and `GET /v1/learning/{program_id}` expose the nullable
  pointer alongside the same versioned canonical progress projection.
- The learner client follows the pointer only when the matching activity is
  still `available`/`in_progress` and has a server-returned allowed action. It
  falls back to the existing safe activity scan for older deployments or a
  stale/non-actionable pointer.

## Verification

Focused checks:

```text
uv run pytest tests/unit/learning/test_progress.py tests/unit/http/test_learning_routes.py -q
```

The final focused result and repository-wide checks are recorded in the pull
request after execution. PostgreSQL integration remains environment-gated and
is not treated as evidence unless a local test database is explicitly
configured.

## Explicit boundaries and remaining gates

- No analytics event is read or written; the planning/up-next projection stays
  explicit-plan-only.
- No migration, outbox/export change, provider, payment, entitlement, access,
  certificate, score, mastery, leaderboard, or AI behavior is activated.
- The API pointer is guidance, not canonical completion or access. Activity
  authorization, prompt availability, allowed actions, evidence, and
  completion continue to be independently server-resolved.
- The broader adaptive-learning rule system (context weighting, priorities,
  revisit/weakness policy, and learner-language copy) is not frozen by this
  slice. Any future rule beyond the existing canonical ordered required path
  needs promotion through the controlled PRD/IA/UX/SRS/data/API/security/QA
  chain before implementation.

## Superseding recovery validation — 2026-09-11

The candidate above was reconciled into the sole active UI tree,
`C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform`, on existing
branch `codex/v02-alpha-latest-ui-20260911` from `cb8df7b44fc79144a6697a77966f4a4c6088932f`.
The source candidate and all original dirty files remain preserved. Seven
candidate paths were copied only after verifying their destination was clean;
duplicate telemetry candidate backend files were byte-identical.

Independent review found the course surface still used its own selector and
that a stale modern pointer could fall back to optional work. The corrected
`next-learning-action.ts` selector is shared by dashboard and course/runtime
surfaces. It honors explicit null, server state and allowed actions; modern
responses also require canonical module/activity requiredness. Older responses
use returned-order, action-checked fallback. This intentionally unifies the
previous dashboard and course fallback ordering without adding priorities.
Independent rereview found no remaining P0/P1/P2 defects in this scope.

Executed against the integrated source:

- 157 focused frontend tests across selector, learner UI, dashboard shell and
  the existing revenue continuation regression: passed.
- 29 domain/API unit tests and two actual PostgreSQL integration tests: passed
  (31 total). Both learning endpoints agree on the pointer; pending human review
  with a locked successor yields null, and approval unlocks the next activity.
- Learner TypeScript, scoped ESLint, scoped Ruff and `git diff --check`: passed.
- Normal synthetic learner login, collection/detail pointer agreement, home
  and course keyboard navigation to the canonical activity: passed.
- Sixteen genuine screenshots across home/course, 320/390/768/1440 CSS pixels,
  and light/dark selected through Settings > Appearance: passed with no
  horizontal overflow or page errors. Effective theme is asserted, not inferred
  from the browser's preferred color scheme.

The reproducible browser harness and final proof are in the recovery packet
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`, specifically
`probe-next-action-browser.py` and `next-action-browser-20260911T071420Z/proof.json`.
Earlier failed harness runs and the light-only OS-preference run remain retained;
this successful run supersedes their acceptance status. The first mobile
failure selected a hidden desktop link and was fixed in the harness by choosing
the visible matching link. No product behavior was changed for the screenshot.

This is local development acceptance using synthetic data, not immutable release
or production evidence. It does not prove full course completion, real video
delivery, certificates or provider activation. The coordinated checkpoint's
broader validation and release boundaries are recorded in
`20260911_UI_RECOVERY_CHECKPOINT.md`; release identity is frozen separately.
