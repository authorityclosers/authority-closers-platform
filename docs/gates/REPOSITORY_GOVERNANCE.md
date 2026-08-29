# Repository governance on the current GitHub plan

## Verified limitation

On 2026-08-30, GitHub's branch-protection API returned HTTP 403 for the private `authority-closers-platform` repository with: `Upgrade to GitHub Pro or make this repository public to enable this feature.`

The repositories will remain private and no purchase is authorized by this implementation task.

## Current controls

- `main` contains only the approved handoff bootstrap baseline.
- Implementation occurs on `codex/*` branches through visible draft pull requests.
- CODEOWNERS identifies the current accountable maintainer.
- CI runs on every push and pull request.
- Commits and operational evidence use immutable SHAs.
- Direct pushes, force pushes, branch deletions, and bypassing failed CI are prohibited by operating policy even though the free plan cannot enforce them server-side.
- Independent review findings must be closed before a PR is marked ready or merged.

## Upgrade gate

Before adding regular developers or external production users, move to a GitHub plan that supports private branch protection or an equivalent enforcement mechanism, then require:

- pull requests into `main`;
- passing required checks;
- stale-review dismissal;
- conversation resolution;
- linear history;
- force-push and branch-deletion denial;
- at least one independent approval when a second authorized maintainer exists.

This limitation is an accepted G0 residual risk, not evidence that equivalent enforcement exists.
