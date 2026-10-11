# AUT-1694: staging organisation administration

Base: `43d6eafd7c6f9c58df89903a1873ebb107c14d23`. Implements the owner's
11 Oct inbox request for a reviewed backend operational tool. This evidence
covers source and fictional local fixtures; it claims no staging data application,
snapshot, hosted email delivery, authenticated dev journey or release.

`scripts/data-changes/staging-org-admin.py` provides read-only preview and an
explicit apply of exact email/person/recording targets in one transaction. A
named active verified operator, owner/issue/run references, injected staging
settings, baked release and a snapshot receipt are required. Approval/snapshot
references record the operator's externally verified authority; they are not
automatic proof or grants. Protected tenants, organisation status/owner and
command intent are fenced. Email output is masked and errors suppress inputs.

Memberships use `OrganisationService`. Verified people are added directly;
missing/unverified people get seven-day operator invitations, delivered through
the canonical invitation outbox and joined through the existing verified sign-in
service. This policy is separately sealed in the creation audit. Self-serve
explicit acceptance and existing pending policies remain intact. Expired invite
replacement appends expiry evidence. Removal ends membership and preserves the
person/history. Existing active roles are preserved.

Erasure uses `ConversationApplication._request_owned_deletion`, also called by
in-app Delete, with the original locked recording and canonical submission/lease
binding. No actor session or processing permission is fabricated. The caller's
exact owner-approved operator authority is recorded in an additional append-only
audit. The app fences reads, increments generation and queues its existing erase
job; it does not assert that the worker has already finished. Personal or
registered-organisation source tenant is explicitly pinned; cross-tenant batches
refuse and roll back. Usage/charges/credits/source lineage are preserved.

Actual mutations append `organisation.staging_admin_applied`, including the
real operator person, approver, issue, run, snapshot, canonical child command,
intent and before/after. Stable command replay changes nothing after invitation
acceptance or membership removal. Conflicting intent/attribution refuses.
Post-commit output failure has a separate exit code and supports same-key readback
or replay without repeating the effect.

Focused verification:

- 89 service/HTTP/operator-sign-in/default-worker/race cases passed in 162.80 s
  before the final tool-only Personal/output additions. Commands covered
  `test_service.py`, `test_organisation_invites.py`,
  `test_organisation_sign_in_postgresql.py`,
  `test_organisation_invites_postgresql.py`, and the two new tool modules.
- The final new tool modules passed **39 cases in 25.77 s** after those additions.
  They cover read-only preview, verified/missing/
  unverified people, mailbox verification, expiry and mail denial, replay and
  attribution conflicts, append-only chain integrity, removal, full rollback,
  wrong-tenant deletion, canonical erase job, preserved usage, Personal source
  deletion, and post-commit receipt failure/replay.
- Ruff check/format passed for all seven changed Python files; targeted mypy
  passed for the tool and four service/provider files; diff and API task admission
  passed. Actual combined-tree default-worker tests passed; no replacement
  module or candidate-worker substitution was used.

Runbook and exact operator command bodies:
`scripts/data-changes/STAGING-ORG-ADMIN.md` and Strike E NOTES.md “API ready”.
No web file, worker implementation, sign-in core, migration, dependency, billing,
live approval or deployment was changed. No browser/server/watcher was started.
The username/password account flow remains separate, requires minimal identity
schema/session changes and the owner's sign-in approval, and is not API ready.
