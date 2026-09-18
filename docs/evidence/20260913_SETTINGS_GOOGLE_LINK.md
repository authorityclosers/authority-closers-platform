# Settings Google account linking

Date: 2026-09-13 (Asia/Kolkata). Source base: `15a8ee8`.

The release owner found that callback recovery directed existing password users
to link Google from Settings, but Settings offered no such action. This bounded
follow-up adds the existing authenticated Google LINK entry and a canonical
read-only status. Implementation, automated validation and canonical local
browser acceptance are complete at source/API
`4d49d9a66883263ec44c66882162ff5187551f3a`. This document does not claim deployment
or an external Google authorization.

## Contract and authority

`GET /v1/me/google-link` returns only `{linked: boolean}` for the person resolved
by the existing authenticated session dependency. The read checks canonical
provider identities against the two issuer strings already accepted by the
Google OIDC adapter: `accounts.google.com` and `https://accounts.google.com`.
It exposes no external subject, provider identity ID, email or token. Query
parameters cannot select a person or tenant. The response is private and
uncacheable. The existing `/v1/me` response remains unchanged.

The action uses a full document navigation to the existing same-origin route
with `action=link`, `surface=learner` and `return_path=/settings`. The existing
server transaction, session ownership, Google assertion and identity-linking
checks remain authoritative. There is no email-based automatic linking,
identity creation, membership change, migration or provider activation.

Settings must render linked status only from the canonical response, never a
query parameter, local storage marker or the fact that navigation returned to
Settings. Loading and failure states must preserve that distinction. Status
responses from a previous identity must not survive a session/identity change.

## Acceptance scope

Backend validation passed 155 auth, transaction, Google adapter, password and
context-continuity tests, including nine new status cases. The repository tests
execute the actual predicate against an in-memory SQLite database, covering
canonical person and exact issuer isolation. The new route also checks session
denial, query-selector rejection, cache headers and unchanged `/me` fields.
Ruff, Python formatting, mypy and diff whitespace checks passed. The expanded
receipt is recovery packet `settings-google-python-final.log`; its one warning
is the existing Starlette/httpx deprecation.

Final learner validation passed **1,736 tests in 99 files** on Node 24.19.0,
using one worker and a 384 MiB heap (`settings-google-learner-all-final.log`).
The focused 29-test run and learner TypeScript check (640 MiB heap) also passed.
Scoped lint and formatting passed before the source commit. Independent Luna
review found no additional blocker. Main review identified three edges
closed in the final source: a status 401 invalidates current identity, an
onboarding retry restarts the cancelled status read, and cached offline identity
cannot enable linking. Mounted tests verify late responses from an earlier
identity/generation cannot overwrite the current status.

The local helper is recovery packet `probe-canonical-google-settings.py`, run
through `verify-canonical-google-settings.ps1`. It creates a synthetic account
through the normal registration UI, resolves its canonical verification outbox
message through the actual worker resolver, and verifies in the browser. The
unlinked read and post-logout 401 use the actual API and local PostgreSQL.

Linked and temporary-error presentation checks use explicitly named status-only
fixtures. The Google start document navigation is intercepted before any
provider request and checked for the fixed action, surface and return route.
These checks do not claim a real Google link. The release owner separately owns
normal hosted Google authorization and canonical linked-state acceptance.

The accepted receipt is recovery packet
`canonical-google-settings-20260913T010432Z/proof.json`. Normal synthetic
registration and verification established the browser session; the live endpoint
returned exactly `{linked:false}`. Keyboard activation reached the fixed Google
LINK document destination, intercepted as described above. Canonical unlinked
Settings passed at 320, 390 and 1440 px. Named linked and 503 presentation
fixtures passed at 320 px; retry returned to the real unlinked response. A
status-only 401 fixture invalidated previously ready identity and displayed
sign-in recovery. Finally, real logout returned 204, the real status endpoint
returned 401, and the link control disappeared after reload.

All five viewport checks had no horizontal overflow; there were zero page errors
or unexpected requests. The unlinked, linked-fixture and error-fixture mobile
screenshots were visually inspected. The receipt binds the four implementation
sources and helper by SHA-256. The UI remains frozen for release integration;
hosted Google authorization is not replaced by these local fixtures.
