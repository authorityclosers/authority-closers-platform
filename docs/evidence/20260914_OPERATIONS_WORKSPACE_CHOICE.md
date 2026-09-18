# Admin sign-in preserves academy choice

Scope: finite routing correction requested by Release Recovery, based on
`2beddc4`. This leaf changes no grants, identity contracts, database, provider
configuration or deployment state.

## Problem and resulting behavior

A person with a platform grant was automatically sent to `/platform` from
`/login`, before academy workspace selection. Even after selecting an academy,
the Admin middleware sent `/` back to `/platform`. This hid the academy's Sales
Xray controls from an otherwise assigned administrator.

The shared login now offers the server-listed academy selector alongside an
explicit **Open Platform Admin** action. Platform identity must match the
workspace response's person, session and selected context. Returning sessions and
password sign-in follow the same rule. Selection still uses the existing
`POST /v1/context` and canonical identity/permission checks. There is no automatic
selection, invented tenant, membership or role. Confirmed sign-out clears both
choices. Pending selection disables platform navigation; stale responses cannot
navigate after unmount or a surface change.

The Admin `/` route honors an already verified academy admin context. Explicit
`/platform` still requires its separate platform grant. A platform-only account
keeps its existing platform home; that grant does not admit People or Sales Xray
routes. Coach admission and the explicit synthetic local login remain unchanged.
The selector's label is now separate from its options for an unambiguous
accessible name.

## Validation performed here

Environment: Windows, Node 24 runtime, Next 16.3.3 production compilation,
Vitest 4.1.11, Python 3.12-compatible project runtime and headless Chromium.

| Check | Observed result | Receipt |
| --- | --- | --- |
| Mounted login, workspace client, server route access and platform identity | 90 passed, 0 failed, 4 files; 8.02 s | [JUnit](operations-workspace-choice-20260914/routing.junit.xml) |
| Platform identity rerun after adding a required empty capability field to the synthetic test fixture | 34 passed; 2.62 s. This is a subset of the 90, not additional coverage. | [JUnit](operations-workspace-choice-20260914/platform-fixture.junit.xml) |
| Production build including TypeScript | Passed; build ID `QJhPrzqxGtv8K61MsPvr4` | [Build output](operations-workspace-choice-20260914/build.log) |
| Actual compiled `/login` in Chromium | 1 passed; 20.96 s. Desktop 1280×900, mobile 390×844, explicit choices, keyboard focus and no document overflow. | [JUnit](operations-workspace-choice-20260914/browser.junit.xml), [request/check receipt](operations-workspace-choice-20260914/browser-receipt.json) |
| Scoped ESLint, Prettier, browser-test Ruff and `git diff --check` | Passed | External logs under `D:/AC-authority-closers-release-audit/operations-workspace-choice-20260914.*` |

The browser used the real compiled page and explicitly intercepted four API GET
responses with synthetic account/workspace fixtures. It did not authenticate a
real account, write context, verify production middleware over the network,
exercise Google OAuth, or call a provider. Context selection and middleware
admission are covered by the behavioral tests; hosted identity acceptance belongs
to Release Recovery.

Desktop and mobile captures were visually inspected at
`D:/AC-authority-closers-release-audit/operations-workspace-choice-20260914-browser-keyboard/`:
`choice-desktop.png` and `choice-mobile.png`. Both show legible choices, the
existing visual system and visible focus. This is local fixture evidence.

## Failed checks retained and resolved

- The first browser run could not locate the exact Workspace label because the
  old nested label included option text. Corrected the actual component markup.
- The next browser run pressed Enter after changing a native select, submitting
  the form instead of only checking focus traversal. The presentation test now
  uses ArrowDown then Tab; production Enter behavior was not disabled.
- The second build found a missing `studioCapabilities` field in a newly added
  test fixture. Added the required empty list; the affected tests and build pass.
- The initial shared-package lint command ran outside ESLint's app base path.
  The corrected root invocation uses the Admin config, with only the app-pages
  directory rule inapplicable to this shared package. Full-document platform
  navigation has a local documented rule exception to discard cached context
  and re-enter server admission, matching existing academy navigation.

Earlier failure logs remain outside Git with the same date prefix. No failed
check is counted as passing. Portable receipts and their SHA-256 hashes are in
[the index](operations-workspace-choice-20260914/receipt-index.json).

## Release handoff

Implemented and locally tested. Provider-tested: not applicable to this change.
Staging/production: not performed in this leaf. Release Recovery must exercise
the actual `admin@` session through `/login`, explicit academy selection, `/`,
`/sales-xray`, and explicit `/platform` on the exact integrated build.
