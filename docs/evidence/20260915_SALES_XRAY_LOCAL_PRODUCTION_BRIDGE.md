# Sales Xray local production bridge

This is a development-only local workspace for the dedicated Sales Xray UI. It
is not a staging bridge and it is not a production deployment.

## Runtime contract

- Browser origin: `http://salesxray.localhost:3016`.
- Next development server: `http://127.0.0.1:3116`.
- Listener: `127.0.0.1` only; absolute or remote proxy targets are rejected.
- Production API origin: exactly `https://salesxray.authorityclosers.com`.
- Existing learner/admin staging bridge allowlists are unchanged.
- The browser receives only a random, ephemeral HttpOnly local handle. The
  opaque `__Host-ac_session` value remains in an in-memory server-side map and
  is cleared when the bridge stops or the local session expires.
- Existing browser cookies, bearer tokens, API keys, and guest cookies are
  rejected; they are never extracted or copied into the local workspace.
- Sign in normally with the account that owns the saved report. The production
  API remains authoritative for account, workspace, report, retention, and
  ownership checks; the local bridge does not impersonate another account.

## Sales Xray API surface

The bridge forwards only the UI's explicit Sales Xray surface: workspace/auth,
acquisition entry/session/library/submission report evidence, transcript,
source, waveform, measurements, DOCX export, recording review, and the
explicit plan/run actions. Unknown routes and admin routes return 404.

Guest challenge-cookie flow is intentionally unsupported in this local
workspace. Authenticated account flow is the supported path for the saved-call
review requested here.

OAuth start/callback are not locally cookie-mapped. They redirect only to the
canonical production Sales Xray host with a filtered Sales Xray callback
parameter set. Password login is the normal local path.

## Live-data and provider boundary

The start script enables local development settings. The banner is hidden by
default; its details live under the Settings gear in desktop and mobile
navigation. The Settings checkbox, banner dismiss button, and `Ctrl+Alt+B`
shortcut update a preference remembered in this browser. The shortcut ignores
editable fields and repeated keydown events. These controls change only banner
visibility. The settings explain that reads and explicit mutations use live AC
data and link authorized administrators to the canonical production page:

`https://admin.authorityclosers.com/sales-xray/settings`

There is no arbitrary per-run provider/model override in this bridge. Provider
selection, plan approval, consent, allowance, and any provider execution remain
backend-governed. Changes in the production settings page affect future live
plans; they do not change this local CSS or invent a completed analysis. The
bridge starts no provider jobs automatically.

## Verification and known boundaries

`node --test scripts/sales-xray-production-bridge.test.mjs` covers the pinned
destination, endpoint matrix, owner-session mapping, cookie/redirect behavior,
credential rejection, CSRF-origin rejection, and absolute-target rejection.

This bridge cannot make a production upload faster. The reported 408 on the
native source PUT remains a backend/admission performance issue and must be
fixed and verified in the core service. The progress visual is phase-aware UI
copy and animation only; it does not fabricate provider progress, scores, or
analysis results.

## Settings visibility verification

- Seven targeted tests passed for hidden default, settings access and close,
  checkbox/dismiss behavior, shortcut persistence, typing/repeat exclusions,
  absence outside the local layout, and CSS scope integration.
- Sales Xray lint and TypeScript checks passed.
- In-app browser: verified the Settings gear, styled native modal, Escape
  dismissal, shortcut showing/hiding the banner, and hidden default after refresh.
  Left the signed-in upload screen with the banner hidden.
