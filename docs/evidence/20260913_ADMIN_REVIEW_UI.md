# Conversation review UI — implementation and local verification

This follow-up completes the contract-pending screens. Admin manages assignments
at `/sales-xray/review` and `/sales-xray/review/[assignmentId]`. Academy loads the
assigned report, exact evidence spans, guarded audio and saved review history at
`/sales-xray/review/[assignmentId]`.

The shared form displays the qualitative draft, findings, citations and report
framework. Reviewers choose an allowed Sales, Technical or UX lens, cite a
server-provided span, select confidence, and optionally propose a correction
within that lens's allowed target areas. Bodies contain no identity fields or
replacement evidence text. The API supplies identity and validates assignment,
source, tenant, run and checkpoint bindings. Wire schema discriminators are
required on reads and receipts.

Feedback is append-only. Unchanged failed requests retain their key; edited
drafts receive a new key. In-flight saves are locked, errors retain drafts and
confirmed receipts receive focus. History refresh failure preserves confirmed
feedback. The form guards unload, internal links, history navigation and shell
keyboard/command navigation while dirty. Assignment changes remount private
state. Protected reads use no-store, same-origin mode and redirect rejection.
Audio errors recheck assignment access and provide recovery without clearing
feedback. Audio seeks to the selected span and stops at its end.

Admin loads the actual queue (latest 50), creates assignments and confirms
revocation through the API. It validates configured Academy origins, preserves
retry keys and confirmed results through failed refreshes, and handles Strict
Mode mount replay. No client-generated identities or reviewer grants are used.
An assignment outside the bounded queue cannot currently load its Admin detail;
the UI explains that limit rather than inventing an unsupported detail endpoint.

## Local verification

- Node 24.19.0. Learner and Admin production Next builds passed, including
  TypeScript validation.
- Learner API, mounted adapter and navigation: 17 tests passed.
- Shared mounted form: four tests passed, covering receipt/save, unchanged and
  edited retries, focus and audio-access failure with retained draft.
- Admin API and mounted workspace: 16 tests passed, including Strict Mode,
  create/revoke, retry, mismatched receipt rejection and confirmed-result retention.
- Two shell tests and the five navigation tests passed together; six additional
  sidebar DOM tests passed.
- Scoped learner and Admin ESLint passed. Prettier and Python probe Ruff checked.
  An incomplete local ESLint utilities installation was repaired from the same
  locked version in the integration worktree; no dependency manifests changed.
- Independent Luna review identified dirty-navigation and response/state issues,
  followed by focused fixes. Its final delta-review turn hit the account usage
  limit before producing a report. Primary inspected and verified its last
  receipt-binding edits; no completed independent final sign-off is claimed.
- Final Admin copy removes misleading preview/audit placeholders. The optional
  shell footer preserves existing defaults for other pages.

## Browser and PostgreSQL evidence

Learner receipt `0044-review-ui-browser-09`: **one passed in 39.35 seconds**.
The browser uses the production Next build through a loopback test proxy.
Actual mounted review HTTP routes and service use backend
`44dde80b4ea8423d514342b933cbafed128ad232`, a disposable migrated PostgreSQL
schema and synthetic one-second WAV. The report fixture runs the actual local
worker and a synthetic reporting broker.

The save returned 201; an identical HTTP replay returned the same durable ID.
Reload read exactly one saved review, independently confirmed as one database
row. Technical/transcript correction and author binding were checked. Private
source byte-range read returned 206 with 128 bytes. Cancelling a sidebar link
and G H keyboard navigation preserved the route and draft.

Desktop 1440px and mobile 390px/320px were exercised with no page errors or
horizontal overflow. Mobile screenshots wait for the desktop sidebar transition
and require the form to occupy at least viewport width minus 80px. Dark theme
was visually inspected at 1440px and 320px.

Admin receipt `0045-admin-review-ui-browser-06`: **one passed in 49.69 seconds**.
Browser creation returned 201 and survived reload. Opening the detail, confirming
revocation and reloading returned the persisted revoked state. Width checks
passed at 390px and 320px without browser errors. Admin used Next development
mode with its explicit local preview setting. Browser API requests were
forwarded to the actual local HTTP server; responses were not manufactured.
The configured Academy link was checked against the created assignment ID, and
the old preview/audit placeholders were absent. Both final JSON receipts include
SHA-256 hashes of the corresponding frontend source files.

These tests fixture the session resolver and shell profile reads using synthetic
canonical actors. They prove UI-to-HTTP/PostgreSQL behavior, not production
login, the deployment proxy or external-provider activation. No real recording
or inference provider was used. Windows standalone startup separately failed
with an EPERM on a generated React dependency link; Linux packaged-image startup
remains part of release validation.

Initial failed receipts remain outside Git in the Sales Xray release-transfer
receipts. Failures exposed loopback RSC forwarding, accessible label ambiguity,
Admin fixture expiry/retention and development HMR transport issues. Final
successful receipts supersede those attempts. The browser helper requires the
reviewed disposable PostgreSQL runner and an already-running frontend.

## Artifacts

- [Learner proof](./review-ui-browser-20260913/review-browser-proof.json)
- [Admin proof](./review-ui-browser-20260913/admin-review-browser-proof.json)
- [Learner ready](./review-ui-browser-20260913/review-ready-desktop.png)
- [Learner saved](./review-ui-browser-20260913/review-saved-desktop.png)
- [Learner reloaded](./review-ui-browser-20260913/review-reloaded-desktop.png)
- [Learner 390px](./review-ui-browser-20260913/review-reloaded-390.png)
- [Learner 320px](./review-ui-browser-20260913/review-reloaded-320.png)
- [Dark desktop](./review-ui-browser-20260913/review-dark-1440.png)
- [Dark 320px](./review-ui-browser-20260913/review-dark-320.png)
- [Admin created](./review-ui-browser-20260913/admin-review-created-desktop.png)
- [Admin detail](./review-ui-browser-20260913/admin-review-detail-desktop.png)
- [Admin revoked](./review-ui-browser-20260913/admin-review-revoked-desktop.png)
- Reproducible probe: `scripts/prove-review-assignment-browser.py`.

Earlier `20260913_ADMIN_REVIEW_UI_BROWSER.png` and
`20260913_ACADEMY_REVIEW_UI_BROWSER.png` remain historical skeleton captures.
They are not evidence of the completed workflow.

## Release boundary

Integration proof: the UI was applied to consolidation baseline
`ef6f9514f682048ab210a01400ac434dd00346ca` as `d04d067`, preserving the
consolidation shell navigation and People footer. The Admin review selects its
Sales Xray navigation item. Combined Admin review/shell tests passed (36);
combined learner review/shell tests passed (21). Both combined production Next
builds passed. Browser source hashes above describe the original UI packet;
the combined shell retains additional release functionality.

The final UI commit must be integrated into the consolidated release. Its exact
Linux CI/image validation and staging/production deployment smoke are separate
steps. This local evidence does not claim the UI is deployed.
