# Admin People directory

The user's requested CRM-style People page now loads academy members on entry,
including owners, admins, support and learners. It provides partial name/email/
username search, role and lifecycle filters, bounded pagination, joined dates,
verification status, active enrollment counts, and an accessible member panel.
The panel opens existing canonical learner access/progress/draft metadata for an
active learner. It does not change roles, grant access or invent registered users.

The new POST `/v1/admin/people/directory` retains the verified Admin surface,
current named `learner_diagnose` permission and server-selected tenant. Search
input is in the body, not URLs or audit payloads. Each successful read, including
empty results, commits its learner-support audit before a no-store response.
Deleted persons are omitted; inactive/suspended and unverified records remain
visible with their actual status. Counts are scoped to this academy, not all
tenants or both environments. The user explicitly requested automatic listing;
this supersedes the earlier UI-only exact-lookup/purpose-picker restriction.
The existing exact lookup and diagnosis endpoints retain their original contract.

Summary counts use canonical memberships and account status. Course counts are
active enrollment records, not an assertion of current entitlement or completion.
Missing accounts and unrelated tenants are never synthesized into the directory.
The selected academy boundary remains important: public learner and operations
tenants are separate, as are staging and production.

Validation on the working source after `43b7aa6`:

- Python domain/HTTP and existing diagnosis suite: 33 passed.
- Actual disposable PostgreSQL: all 6 Admin HTTP integration cases passed,
  including the new directory, owner/admin inclusion, pagination, partial search,
  cross-tenant exclusion, committed audits and unchanged protected learning rows.
- Mounted People/directory/API/transport/Admin-shell checks: 153 passed.
- Admin ESLint and TypeScript passed; scoped Python Ruff and mypy passed.
- Browser: six groups passed on the actual `/people` route in the supported
  local development preview with explicitly synthetic responses. Initial listing,
  member open/close focus, search/filter, empty/retry and 390/320px contained
  table scrolling passed with zero page errors. Desktop and dark 320px screenshots
  were visually inspected. An initial mobile failure exposed an absolutely
  positioned accessibility label escaping the table's scroll container; positioning
  the container fixed the overflow. These are UI proofs, not live account evidence.
- Root audit packet: `D:/AC-authority-closers-release-audit/people-directory-browser/`
  and `ui-admin-people-directory-postgres.log`. Disposable PostgreSQL was dropped.

This extends the existing Admin/Coach workspace correction; exact integrated CI,
deployment and hosted verification are still release-owner work. A linked reviewer
workspace does not assert that dedicated reviewer admission/invite delivery is done.
