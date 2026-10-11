# AUT-1355: expiry during artifact inventory

Source pin: `2e662a8538a31d3086076ba98dd6026bd3a2b20e`.
This is the separate urgent inbox follow-up to merged PR #446, started with
the lane gate and `--fixes-red-main`. Release infrastructure requires CTO and
CEO review.

The [web-image run](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38117500187)
failed during reclamation inside the admission step. Its last sweep was
incomplete; both subsequent attempts rejected a reduced older-artifact count.
A deterministic reproduction using the pinned reader observes a due-expiry
artifact in an incomplete attempt, then refuses a complete inventory after that
artifact disappears: `older artifact count changed during inventory`.

The reader now defers the older-count comparison until all pages are parsed.
A smaller complete sweep is accepted only when its exact missing, previously
observed older IDs were flagged expired or have a timezone-aware `expires_at`
at or before the current time plus a fixed five-minute margin. Every absent
ID must have this evidence, and live older IDs plus those removals must equal
the original older count. Missing expiry metadata supplies no permission.
An unseen older removal cannot be guessed from the count. A deletion that
shifts a still-live row behind an already-read page forces a fresh sweep.

Older identity/size changes still fail immediately. Every accepted sweep must
cover the largest count its pages reported, so expiry does not conceal unseen
uploads. Recent size maxima still survive retries. The three-attempt bound,
artifact ceiling, deletion eligibility, replacement credits and retention
policies are unchanged.

The inbox suggested two concurrent reclaimers. All four packaging workflows
already share the repository-wide job concurrency group
`application-release-packaging`, with `cancel-in-progress: false`. This covers
admission, upload and cleanup, including native and recovery packaging. A new
cross-workflow regression pins that guard. The failed web job ran from
06:18:57 to 06:35:18 UTC; at the 06:45 UTC application-job inspection there was
no `package-release-images` job. Thus the available evidence does not establish
an overlapping application reclaimer. No workflow change is necessary, and an
unexplained non-expiring disappearance remains fail-closed rather than being
attributed to another reclaimer. GitHub's repository-wide concurrency behavior
is documented in [Control workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

Validation on the AC server:

- Focused inventory, real workflow-step, reclamation and release-pool tests:
  **138 cases**, including **16 new cases**. Every original test function and
  assertion in the touched files is AST-identical to the pinned main source.
- Regressions cover expired/due/near-expiry removals; malformed, missing,
  timezone-free and future expiry; unseen removals; expiry mixed with size
  changes or non-expiring loss; expiry combined with unseen uploads; the
  shared reclaimer reader; and real admission/cleanup shell steps.
- Focused Ruff, formatting, incremental mypy on the two reader modules and
  `git diff --check` pass. No open PR overlaps these paths.
- Receipts: `expiry-baseline-reproduction.json`, `expiry-test-preservation.json`,
  `expiry-pool-tests-final.xml` and `expiry-file-overlap.json`, in
  `/home/acdev/strikes/1355`.

No live artifact deletion, workflow dispatch, deployment, manual merge or
production/staging mutation was performed. A passing local regression does not
establish current pool admission or green GitHub CI.
