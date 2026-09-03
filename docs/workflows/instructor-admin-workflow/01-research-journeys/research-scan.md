# Research scan and authority notes

This scan is a compact handoff, not a replacement for the controlled
documents in the manifest. The package uses the sources in the required order
and separates facts from layout inference.

## What is controlled

The platform has one Learning & Practice OS. Its content kernel is
`Program → Module → Activity`; content is versioned, and a published version
is immutable. The learner shell and Admin control plane have separate hosts.
The Admin specification names Content Manager and Coach / Reviewer as separate
canonical roles. “Instructor” is therefore a product label proposal, not a
new role.

The controlled Admin route list registers `/admin`, `/admin/users`,
`/admin/users/{person}`, `/admin/programs` and
`/admin/programs/{program}/content`. `/admin/progress` or support diagnostics
and `/admin/audit` are named as appropriate Admin surfaces, but their exact
route contract is not frozen. Module names such as Media, Assessments, Health
and View-as do not by themselves authorize new routes.

The first-slice Admin boundary is narrow: locate a learner, inspect canonical
enrollment/progress/evidence, create or edit a draft, publish/version in a
controlled way, inspect stuck or inconsistent state, and make authorized
corrections with a reason and audit trail. There is no direct database repair
path.

Assessment data is versioned and evidence-bound. The official score boundary
is human-confirmed until AC-SVAL gates are satisfied; the package does not
invent score classes, a lifetime average, autonomous AI authority, rubric
schema or attempt limits. Real-call recording/transcription/external AI is
gated and remains blocked.

Media has a platform-owned lifecycle with a provider adapter. Provider
selection, limits, codec requirements, resumability guarantees, retention and
SLA are not specified here. Analytics is derived and cannot grant access or
rewrite canonical progress, entitlement, scores or audit history.

## Research implications for workflows

| Finding | Design consequence | Evidence label |
| --- | --- | --- |
| Admin is an auditable control plane | Keep actor, tenant/context, target, reason, result and recovery visible around sensitive actions | controlled |
| Content changes can corrupt learner history | Show version identity and pin historical evidence; never silently edit a published version | controlled |
| Support recovery has layered ownership | Every failure names a safe next action and escalation boundary; never send operators to raw DB | controlled |
| Dense Admin is not learner mobile | Use responsive reflow, stacked records and focused detail on compact widths; do not force a wide table | controlled + design inference |
| Instructor role is not canonical | Reuse existing role checks and expose only granted actions; show the role decision as blocked | controlled |
| Assessment and real-call behavior is gated | Render an explicit “capability blocked / contract required” state, not a fake editor | controlled |
| Visual brand tokens are not approved | Use semantic tokens and text-only wireframes; keep brand palette/type blocked | controlled |

## Important non-findings

The sources do not provide a safe basis for inventing learner counts,
revenue, payment status, billing actions, provider names or performance,
moderation queues, messaging/reminder behavior, approval ownership, exact
admin MFA/view-as timing, or B2B manager/seat behavior. Those gaps are
registered as `BLK-*` in `00-start-here/scope-and-authority.md` and referenced
at the point of use.
