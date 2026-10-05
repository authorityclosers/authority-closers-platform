# AUT-1246: Prospects page session wiring

Source pin: `f7b280648297d8cb79fee99a2dd214bfb569161e` (main at task start).
Lane/branch: `sx-prospects`, `task/sx-prospects/1246-prospects-session`.

The list and UUID detail pages mounted outside AppSession's admitted routes,
so `useWorkspaceAccess()` never received the existing authenticated context
and the pages never issued their Prospects GET. AppSession now admits
`/prospects` and exactly one UUID detail segment using the detail page's
existing `UUID_RE`. Its existing trailing-slash normalization still applies.
Both routes reuse StandaloneStudio's session and workspace bootstrap.

The regression mounts the actual list page and the actual async detail page
through AppSession. Only navigation and HTTP responses are test doubles;
AppSession, StandaloneStudio, the workspace provider, pages and Prospects
client are real. A probe checks the server-confirmed person/session/tenant
context. The list response is empty and the detail response is a fictional
404, so the rendered empty/error state proves completion of the actual GET.
Link rendering uses inert anchors to avoid Next prefetch network traffic.

## Verification

- Before the implementation: 6 new session/page cases failed because no
  workspace request occurred; 14 cases passed.
- After the implementation: 5 focused files / 62 tests passed (AppSession,
  Prospects screens/client, StandaloneStudio and shell navigation).
- Final AppSession suite: 28 tests passed, including both trailing-slash forms,
  signed-out GET suppression, unsupported routes, invalid UUID page rejection,
  existing shell/Calls routes, plans checkout, login/auth and review bypass.
- App lint and typecheck passed. Final changed-code ESLint and typecheck
  also passed after the additional route tests. Changed-file Prettier,
  diff whitespace and latest `ac-gate check` passed.

## Live checks and handoff

The unauthenticated read of `https://salesxray-dev.authorityclosers.com/prospects/`
returned HTTP 403. No authenticated dev or phone/laptop visual check is claimed.
The task explicitly assigns existing-credential live acceptance to Root.

After governed merge/delivery, use the accepted fictional session on dev/staging:
open `/prospects/`, confirm the Prospects sidebar and workspace bootstrap,
then inspect the network GET `/v1/conversation/prospects` and the server-backed
empty state. Open `/prospects/aaaaaaaa-1111-4111-8111-111111111111/` and confirm
the detail GET and unavailable state for that missing fictional UUID.
Invalid UUID pages must remain 404. Check phone and laptop widths when access
is available. Root records subsequent live acceptance on AUT-1219.

This session route boundary change requires CTO review and sensitive-change
approval. Merge and delivery remain outside this engineering run.
