# Sales Xray public policy pages: owner decisions, 16 Oct 2026

Relayed by the supervisor session at about 17:45 IST; recorded beside the
3 Oct 2026 decision (AUT-725, PR #219), which removed time promises such as
"working day" and "within 30" from the policy pages.

1. Data deletion page (`/data-deletion`) approved, with the backups line as
   drafted ("he said it's fine").
2. Deadline for deletion requests: "2 days deadline for this to be completed".
   The page now says receipt is confirmed as soon as a request arrives and the
   deletion is completed within 2 days. This supersedes the 3 Oct no-deadline
   rule for deletion requests only; every other page still makes no time
   promise (enforced in `apps/sales-xray-web/app/policy-content.test.tsx`).
3. Contact address: "admin@ is the one ... no need for EA, I mean we need it
   for AC". All Sales Xray public pages (privacy, refunds, contact, data
   deletion) use admin@authorityclosers.com.

Operational note: Sales Xray has no in-app lead delete yet, so lead deletions go
through the approved-deletions path, and the 2-day promise applies to them.
