# ADR 0041: Standing owner approval for automatic production promotion (release train)

Date: 2026-09-29. Status: proposed for review under AUT-297; records the
owner's standing approval in AUT-72 at 2026-09-29 19:05 UTC.

## Context

The owner ordered an automatic release train from dev through main and staging
to production. The same CI-built artifacts must move between environments;
production must not depend on laptop deploys, manual server edits or rebuilds.
[ADR 0034](0034-admin-release-control-through-engine-inbox.md) requires the
owner to type the resulting version for each production promotion through
Admin. Requiring that interaction on every routine patch would stop the train.

The standing approval is bounded to verified patch promotions. It does not
transfer general owner authority to an agent or weaken the production inbox
boundary. The associated UI Guard rule delegates review of a narrow UI-only
merge scope, independently of production promotion authority.

## Decision

### Standing approval and eligibility

Only `ac-release train` promotions may substitute the recorded standing
approval for ADR 0034's per-promotion typed-version confirmation. Every train
promotion must satisfy all of these conditions at execution time:

1. The engine derives a patch bump only, using the version rules in ADR 0034.
2. The exact core/web artifact pair passed staging smoke. Record both source
   revisions and artifact identities; a newer core or web build invalidates
   that pair's smoke evidence. Both commits are on `main`, CI is green, and
   promotion reuses the same artifacts without rebuilding them.
3. The T2 migration classifier allows the transition: either no migration
   change or additive migrations only. A destructive or unknown classification
   is refused; missing evidence is not treated as additive.
4. A fresh pre-promotion database dump has been taken and verified for the
   production target. A failed or unverified dump prevents promotion.
5. The latest off-host restore check passed and is no older than eight days.
6. All ADR 0034 safety guards remain in force: production enablement, staging
   provenance, engine locking, expected production commit/version comparison,
   foundation support for a new migration head, and Sales Xray approval with
   at least one day remaining. Stale or concurrent requests are refused.

The train is an engine-owned path under standing owner authority. It grants no
new API capability or inbox access. ADR 0034's production Admin path retains
its owner-only `platform_release_manage` capability, safe-origin check,
request-file validation, at-most-once processing and audit-event requirement;
staging Admin remains read-only. The typed-version exception applies only to
the train, never to an agent's direct Admin or CLI request.

Minor/major bumps and destructive or unknown migrations remain manual through
Admin typed confirmation or supervised CLI. Core rollback across a migration
head also requires supervised recovery; this ADR does not authorize the
engine to cross that head or roll the database back. A manual path is not a
bypass for ADR 0034 guards or permission for direct SQL recovery.

### Post-promotion smoke and failure

Run production smoke against the promoted pair. If it fails, automatically
roll back the web component to its immediately previous release. Roll back
core to its immediately previous release only if the migration head is
unchanged. When the head changed, retain core and require supervised recovery.

After the failed smoke, mark the pair failed and pause production, including
when rollback succeeds. Record rollback outcomes; a rollback failure does not
clear the pause. Do not automatically retry the failed pair. A later train tick
must respect both its failure mark and the production pause.

### Kill switches and audit

The train requires `/etc/ac-release/train.enabled` as well as ADR 0034's
`/etc/ac-release/production.enabled`. Removing the train enablement file stops
new train promotions. `ac-release pause production` also stops them. Check
both controls under the engine lock before production mutation. Enabling the
train does not clear a production pause or a failed-pair record.

Each train release record must contain:

- `requested_by: standing-approval:AUT-72@2026-09-29T19:05Z`;
- the exact core/web revisions, artifact digests and resulting patch version;
- the staging and post-promotion smoke record digests, including failed smoke;
- the migration classification, verified dump and off-host restore evidence;
- the promotion outcome, any rollback outcomes and the resulting pause state.

Preserve audit-critical history; append outcomes or superseding records rather
than overwriting evidence. Missing required evidence prevents promotion.

### UI Guard merge rule (CTO Q1)

UI Guard (agent `2b432c77`) may authorize an eligible PR using exactly
`UI Guard approved: PR #n @ <sha7>`. The approval is bound to the reviewed head
SHA. As with the CEO line, it carries over only when an update from `main` is
the sole new commit and the PR's own diff is unchanged. Any other change needs
new review.

At merge time, the watchdog must verify all of the following:

- GitHub's complete changed-file list is entirely within
  `apps/sales-xray-web/app/**` or `apps/sales-xray-web/public/**`.
- No changed file is `package.json`, `next.config.ts`, a tsconfig, ESLint or
  Vitest configuration, within `tests/`, or the web folder's `AGENTS.md` or
  `CLAUDE.md`. These exclusions apply even to a path otherwise inside the
  allowed directories; mixed-scope PRs are ineligible.
- CI and `single-track` are green, there are no unresolved review threads,
  and the approved change is re-tested on the latest `main`.
- Changes to consent, payment, pricing or score-display text follow CTO
  review then CEO approval, even when their paths meet the UI-only rule.
- A `Merge hold: PR #n` from the CEO or CTO stops the merge.

All other merges follow the ordinary or sensitive merge rule in the
amendment below. UI Guard approval does not approve production data changes,
billing, secrets, purchases or deletion, and does not bypass train promotion
eligibility.

## Amendment (2026-10-02): one-review merges and CEO release decisions

Owner decisions of 2 Oct 2026 (the AUT-544 direction approved on 30 Sep, and
the delegation of production promotions to the CEO), recorded under AUT-740.
[AGENTS.md](../../AGENTS.md) items 5 and 6 carry the binding text.

### Merge classes

The watchdog classifies each pull request from GitHub's complete changed-file
list; an unreadable list counts as sensitive.

- **Ordinary change:** CI green plus one review merges it. The reviewer is the
  lane's pod lead (`Review: approved PR #N @ <sha7>`) or the CTO
  (`CTO review: approved PR #N @ <sha7>`). A pod lead never approves a change
  on its own task.
- **Sensitive change:** CTO review, then CEO approval
  (`Merge approved: PR #N @ <sha7>`). Sensitive means billing, payments,
  identity, auth, security or secrets, database migrations, infrastructure,
  workflows, the gate, data-change scripts, AGENTS.md, and lockfiles or package
  manifests.
- **UI-only studio change:** UI Guard under the rule above, unchanged.

Every approval is bound to the reviewed head SHA and carries over only when an
update from `main` is the sole new commit and the PR's own diff is unchanged.
Owner permission is still required for billing settings, payment settings,
purchases, secrets and data deletion.

### Production promotion outside the train

Train promotions keep the standing approval and eligibility rules above. The
CEO decides every other production promotion on the owner's behalf by posting
`Promote approved: <sha7> as vX.Y.Z` on the `Release decision` task.
`/opt/ac-watchdog/ac_release_decision.py`, run by `ac-release-decision.timer`
every 10 minutes, then takes a fresh backup, promotes that same build and runs
the production canary. The owner can still promote from Admin -> Releases.
This amendment does not widen train eligibility or change the release engine's
guards; it records the decision route only.

## Alternatives (rejected)

- Keep typed confirmation for every patch: defeats the owner's automatic train.
- Promote any green main build: omits exact-pair staging smoke and recovery proof.
- Automatically promote minor/major or unknown migrations: exceeds the bounded
  approval and can make recovery unsafe.
- Roll core back across a migration head, or retry failed smoke indefinitely:
  risks incompatible application/database state and hides a failed release.
- Allow UI Guard approval by filename hints or stale file lists: misses mixed
  scope and changes introduced after review.

## Consequences

Routine verified patches can reach production without a new owner interaction.
The engine must retain exact-pair evidence and fail closed on missing guards.
Higher-risk releases stay supervised; failed smoke pauses the train for review.
This docs-only decision does not install or enable the train or merge watchdog
changes. Their implementation, tests and deployment remain separate tasks.

## Reversal cost

Disable the train and retain manual Admin confirmation. Return every merge to
CTO review and CEO approval if the one-review rule or the UI Guard delegation
is withdrawn, and return non-train promotions to the owner if the CEO
delegation is withdrawn. Preserve historical
approval, smoke and release records through either reversal.

## Evidence

- Owner order: AUT-72, 2026-09-29 19:05 UTC; recorded in the AUT-297 spec card.
- AUT-293 design revision 2 and AUT-297 acceptance criteria, including CTO Q1.
- [ADR 0034](0034-admin-release-control-through-engine-inbox.md).
- [Release engine runbook](../runbooks/RELEASE_ENGINE.md).
- [Delivery constitution](../../AGENTS.md), items 5 and 6.
- Owner decisions of 2 Oct 2026 (one-review merges; CEO release decisions),
  recorded in AUT-740.

## Owner

Owner: AC owner (standing order above). Dev Environment Lead performs first
review; CTO reviews the ADR and CEO approves its merge.

## Supersedes

Amends ADR 0034's typed-version requirement only for eligible `ac-release train`
promotions. Other ADR 0034 requirements and the manual Admin route remain.

## Trigger to revisit

Revisit if owner approval is withdrawn or widened, migration classification
changes, restore evidence exceeds eight days, or UI Guard scope cannot be
verified from GitHub at merge time.
