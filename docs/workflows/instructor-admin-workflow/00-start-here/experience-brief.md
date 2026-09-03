# Experience brief

## Problem

Future AC operators and content practitioners need a trustworthy place to
author/version curriculum, inspect learner state and close routine recovery
cases. A dense admin surface is useful only when each action names its scope,
preserves history and leaves a traceable result.

## Audiences and jobs

| Audience | Job to be done | Safe first value |
| --- | --- | --- |
| Content Manager | Compose Program → Module → Activity content and prepare a version for review/publication | See the current version, dependencies and exact next action |
| Coach / Reviewer | Inspect evidence and review/approve within the controlled assessment boundary | Open a prioritized evidence item with rubric/version context |
| Business Administrator | Operate catalog, people, enrollment and support workflows | Locate a person/content item and understand what is safe to do |
| Platform Owner | Govern product control-plane decisions | Read a source-backed operating summary and audit trail |
| Technical Administrator | Diagnose integrations, jobs and system health | Identify an affected capability and recovery/runbook path |
| Support Agent | Diagnose access/identity/content issues with limited actions | Trace the case without raw DB access or sensitive leakage |
| Auditor / Read-only | Inspect audit history and permitted reports | Verify actor, target, reason, consequence and trace |

No learner counts, revenue, scores, SLAs or provider success rates are supplied
by this package. A screen may display a metric definition or data freshness
state only when the owning read model returns it under permission.

## Product surfaces

1. **Instructor Studio label** inside the Admin Catalog and Assessment Review
   modules. It is not a separate identity, hostname or database.
2. **AC Admin control plane** at `admin.authorityclosers.com`, separated from
   the learner product and ERPNext.
3. **Canonical API/data boundary** on the platform service. All role,
   tenant/context, resource and action checks remain server-side.

## Bounded workflows

- Course authoring and versioned publication.
- Enrollment/progress oversight and safe diagnosis.
- Assessment authoring gate and human review boundary.
- Course-media upload and provider lifecycle gate.
- Audit, recovery and escalation without direct database operations.

## Success criteria for this package

- Stable IDs, routes and states are consistent across the inventory, behavior
  spec, CSV, PlantUML and manifests.
- Every primary action has a system response and recovery behavior.
- Unsupported behavior is visibly blocked and listed in the authority register.
- Desktop-dense and compact/mobile compositions share semantics without
  turning mobile into a horizontal table.
- No visual direction is called branded, approved or production-ready.

## Handoff boundary

The package is ready for human review and future contract refinement. It is not
ready for app implementation until the blocked role/permission, route,
assessment, media-provider and high-risk recovery decisions are resolved and
their acceptance tests are written.
