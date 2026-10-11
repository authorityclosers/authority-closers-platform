# AUT-1677 — Prospect access recovery

Strike A's page matrix recorded that signed-out visitors to `/prospects` had no
sign-in action. The list asked them to choose a signed-in workspace; direct
profile links appeared unavailable. Before the workspace check finished, those
messages could also appear in place of a loading skeleton.

Both owned views now use the same small access presentation:

- While account/workspace access is being checked or selected, show the existing
  list skeleton and its busy status.
- For a confirmed signed-out visitor, show **Sign in to see your prospects** and
  a keyboard-accessible Sign in link. The provider's existing account action
  keeps the current page when available; otherwise the link goes to `/login`.
- For an unavailable workspace service, show a small corner card with the
  provider's existing Try again action. Workspace selection remains with the
  shared provider.

Private list/profile reads still require confirmed ready access and its scoped
context. A previously loaded customer disappears immediately on sign-out, and
the existing read cancellation remains in force. No session, login service,
permission, tenancy or API behavior is changed.

## Assurance and verification

AC-UXA-01 was fetched using its exact registered Drive ID
`1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`. Its recovery, asynchronous status and reauth
focus findings guide this presentation change; provider/server authority is
retained. The existing semantic tokens and 32px desktop/44px phone targets are
used, with a visible keyboard focus outline and no new raw colors.

All 26 focused list/profile cases pass, including confirmed guest access,
missing provider callback, unresolved/loading/selecting access, workspace retry,
immediate hiding/read cancellation on sign-out, and retained scoped pagination
and six-section profile behavior. Incremental typecheck, cached changed-file
ESLint, Prettier and browser-script Ruff/format are required before push; the
strike notes retain the result and any interrupted attempt.

The development-only `/review-fixture/prospects/library` adds explicit access
state controls. The bounded browser proof supplies a fictional populated list
and six-section profile through the actual client ports, then checks access
loss, skeleton clearing, sign-in callback, no private reads without ready access,
corner retry, phone targets, overflow and page errors. Screenshots at 390/1440 in
light/dark follow the committed shared-dev refresh and are listed individually
in strike NOTES.md. No separate server or build is started.

This is a Prospect recovery repair. Production Report acceptance remains with
H/QA, and canonical Company/outcome persistence still awaits the shared
migration slot and authority integration.
