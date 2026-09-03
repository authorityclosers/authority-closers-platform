# G0 — controlled implementation foundation

G0 is complete only when the implementation can be reproduced, reviewed, recovered, and operated without relying on undocumented workstation or VPS state.

## Required evidence

- [x] Three canonical AC-owned repositories exist privately under the `authorityclosers` organization.
- [x] The approved handoff bootstrap is preserved as the initial `main` commit in each repository.
- [x] The working branch is `codex/g0-control-plane`.
- [x] The live VPS foundation source is migrated into the platform repository with provenance.
- [ ] All currently live operational scripts and systemd units are committed and released immutably.
- [x] CI validates shell syntax, ShellCheck, credential signatures, line endings, and digest-only container images (GitHub Actions run `33270276432`).
- [ ] Re-running host hardening cannot silently reopen public SSH.
- [ ] Current host package updates are assessed, applied safely, and verified.
- [ ] R2 documentation matches the enabled encrypted backup and restore state.
- [ ] Recovery objectives are approved and a measured restore drill is recorded.
- [ ] Restored application jobs/outbox are held before side effects and explicitly reconciled.
- [ ] Named access, MFA, break-glass recovery, and Infisical workload separation are evidenced.
- [ ] Controlled Drive sources are indexed with version, URL, decision authority, and implementation traceability.
- [x] CODEOWNERS and CI are enabled; GitHub Free's private-branch-protection limitation and compensating controls are documented in `REPOSITORY_GOVERNANCE.md`.
- [ ] No product endpoint is publicly exposed before the applicable authorization, isolation, recovery, and negative-path gates pass.

## Initial recovery objectives

These are conservative stage targets and must be replaced by observed measurements:

| Stage | Maximum data loss (RPO) | Maximum service recovery (RTO) |
|---|---:|---:|
| Foundation before application state | 24 hours | 4 hours |
| Internal Free Course release | 1 hour | 2 hours |
| Controlled external cohort | 15 minutes for canonical PostgreSQL state | 1 hour for critical learner journeys |

Meeting later-stage objectives may require WAL/PITR, more frequent database backups, independent monitoring, and provider-specific recovery controls. A daily Restic snapshot alone does not satisfy the external-cohort objective.

The bounded five-minute logical PostgreSQL writer is implemented in the foundation release but is disabled until its separate activation gate proves exact units, live R2 usage plus the conservative projection, a no-write dry-run, and local capture/`pg_restore --list` evidence. The faster cadence leaves healthy-run processing time inside the 900-second objective; this implementation change does not constitute live activation, a measured RPO, or a completed recovery drill.
