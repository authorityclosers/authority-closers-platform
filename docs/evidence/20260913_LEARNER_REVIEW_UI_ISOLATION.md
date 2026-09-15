# Learner review UI isolation

Date: 2026-09-13

Follow-on status: `20260913_REVIEWER_ACCESS_ISOLATION_AND_ADMIN_DETAILS.md`
records the completed generic learner API hold and separate Admin detail read.
The dedicated reviewer admission described as pending below is still unfinished.

The legacy learner review entry points now terminate with Next.js `notFound()`:

- `/sales-xray/review/[assignmentId]`
- `/sales-xray/review/invite`

Neither route mounts `LearnerShell`, `ReviewAssignmentAdapter`, or
`ReviewInvitationAcceptance`. The learner shell also no longer imports or calls
the review navigation guard; ordinary command-palette and keyboard navigation
continues through its direct router fallback.

Focused evidence is in:

- `apps/learner-web/app/sales-xray/review/legacy-routes.test.ts`
- `apps/learner-web/app/components/site-shell-sales-xray.test.tsx`

The shared review adapter, invitation components, API clients, and assets remain
in place for migration into a dedicated reviewer surface. Dedicated reviewer
route ownership, session/cookie audience, API paths, invitation admission, and
Admin detail reads remain pending backend/auth and reviewer-surface work.
