# Coach Studio shell workflow evidence

Date: 2026-09-13
Branch: `codex/v02-coach-workflow-20260913`
Base: `c06d3a0`

## Scope

The Coach shell now keeps the course workspace usable while reducing navigation noise:

- desktop sidebar collapse is persistent in browser storage, with icon titles and accessible expanded state;
- mobile navigation opens as a drawer with a scrim, close button, Escape handling, focus on the first destination, and focus return to the menu button;
- the signed-in account control presents the display name, truncated email, settings link, and the existing `POST /v1/auth/logout` flow;
- signed-out sessions expose a clear `Sign in` action, while pending/error session checks show a neutral access placeholder without reusing a previous identity;
- the shared session provider accepts optional public chrome around its existing checking boundary. The private session tree remains hidden and inert until verification succeeds, preserving draft state during revalidation.

Logout continues with a full navigation to `/login`, so the course editor and upload session `beforeunload` guards remain active when there is unsaved work or an in-progress transfer.

## Validation

- `pnpm --filter @ac/coach-web test` — 3 files, 44 tests passed
- `pnpm --filter @ac/coach-web typecheck` — passed
- `pnpm --filter @ac/coach-web lint` — passed with zero warnings
- targeted Prettier check for the scoped shell, styles, test, and session files — passed

The parent release pass owns the combined production build and browser capture; this branch does not run that build concurrently.
