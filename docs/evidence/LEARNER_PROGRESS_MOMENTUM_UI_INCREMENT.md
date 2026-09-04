# Learner progress hierarchy and motivation foundations

Status: bounded, uncommitted implementation candidate on
`codex/gamification-progress-ui`. No staging, production, provider, or
scoring approval is claimed.

## Scope

This increment extends the authenticated learner `/progress` surface with a
small, projection-first progress slice:

- a local, keyboard-accessible scope switch between the current course and
  the returned all-learning collection;
- a display-only all-learning roll-up that sums only server-returned course
  projections and calls out partial or unavailable data;
- restrained streak and achievement foundations that remain explicitly
  unavailable until their opt-in, server-owned criteria and visibility rules
  are published; and
- responsive light/dark/accent presentation with reduced-motion handling,
  44px interaction targets, non-color status cues, and no leaderboard, XP,
  mastery, or composite score.

The current course summary continues to use the canonical `/v1/learning`
projection already loaded by the progress route. The wider view reads the
existing `/v1/learning` collection read model; explicitly unsupported route
responses leave the current course view usable and show an honest unavailable
state when the learner switches scope. Auth, service, and network failures
remain route failures for controlled recovery.

## Controlled references

- Master Index: Drive ID
  `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`
- BRD: Drive ID
  `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk`
- AC-IMP-01: Drive ID
  `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU`
- AC-IMP-03: Drive ID
  `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo`
- AC-IMP-04: Drive ID
  `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc`
- AC-IMP-05: Drive ID
  `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw`
- PRD: Drive ID
  `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k`
- IA: Drive ID
  `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs`
- UX Research: Drive ID
  `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM`
- UX States: Drive ID
  `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E`
- UI System: Drive ID
  `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI`
- SRS: Drive ID
  `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g`
- Data/Tenancy: Drive ID
  `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`
- API/MCP: Drive ID
  `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`
- Security: Drive ID
  `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`
- Telemetry: Drive ID
  `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I`
- Mobile/PWA: Drive ID
  `1wxYkUGdHchtSYFpiXxGWQoaT95D4y4LO_qZG7MlEsoI`
- DevOps/SRE: Drive ID
  `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`
- QA/Release: Drive ID
  `1DU9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`
- ADR/Risk: Drive ID
  `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`
- AC-UXA-01: Drive ID
  `1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`

The selected Direction A / momentum visual references remain reference
evidence for shell, hierarchy, and mobile treatment. They do not authorize
new gamification semantics.

## Implementation evidence

- `apps/learner-web/app/components/progress-momentum.tsx` provides the
  reusable scope panel, display-only roll-up helper, and opt-in motivation
  foundation cards. Missing projections stay unavailable and are never
  converted into zero.
- `apps/learner-web/app/components/progress-runtime.tsx` loads the existing
  collection projection additively, keeps canonical current-course loading
  independent from the wider roll-up, includes collection provenance in the
  offline notice, and only treats explicit unsupported-route statuses as an
  unavailable optional projection. Auth, service, network, and abort failures
  retain their controlled route semantics.
- `apps/learner-web/app/progress-momentum.css` uses the existing learner theme
  variables and includes desktop, tablet/mobile, narrow-phone, dark/accent,
  and reduced-motion rules. The only interactive motion is a short scope
  transition/hover lift and it is disabled for reduced motion.
- `apps/learner-web/app/layout.tsx` loads the new stylesheet after the learner
  surface styles so the slice can compose with the existing shell.
- `apps/learner-web/app/lib/progress-momentum.test.tsx` verifies projection
  roll-up boundaries, missing-data behavior, source disclosure, accessible
  `dl` metric semantics, collection auth/service/network propagation,
  collection offline provenance, AbortError propagation/ignore behavior, the
  visible Not available fallback, and the absence of invented XP/ranking
  values.

## Data and product boundary

The slice consumes only `program_title`, `version_number`, `state`, and
`projection.{completed_count,denominator,percentage}` from the existing
learning read models. It does not write progress, derive mastery, interpret
analytics as progress, or couple progress to payment/access state.

Streak, badge, XP, rank, reward, and achievement values are not present in the
promoted learner API contract. The UI therefore exposes an opt-in foundation
with an explicit unavailable value and explains the missing server-owned
criteria instead of fabricating a motivational number.

## Verification boundary

The following local checks passed on Node 22.17.0 (the repository requests
Node 24, so this is local evidence only):

- `pnpm exec vitest run app/lib/progress-momentum.test.tsx`: 1 file, 14
  focused tests passed.
- `pnpm --filter @ac/learner-web test`: 29 files, 402 tests passed.
- `pnpm --filter @ac/learner-web typecheck`: passed.
- `pnpm --filter @ac/learner-web lint`: passed.
- `pnpm --filter @ac/learner-web build`: passed; the existing route table
  still includes `/progress`.
- `pnpm exec prettier --check` on the changed implementation, test, and
  evidence files: passed.
- `git diff --check`: passed.

Browser or Playwright capture is intentionally not run for this increment per
task scope; exact-current-SHA visual and staging evidence remain open for
independent review.
