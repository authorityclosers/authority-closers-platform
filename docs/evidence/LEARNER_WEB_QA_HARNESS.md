# Learner web visual and accessibility QA harness

Status: **local v0.1-alpha QA harness; not release approval**

This harness adds a browser-level contract gate for the learner web routes. It
uses the repository's existing `pytest` e2e marker and native Python
Playwright, with the shared `webapp-testing` server lifecycle helper. It does
not create a learner, enroll an account, submit evidence, issue a certificate,
or treat a browser fixture as canonical product state.

## Run

On Windows, from the repository root:

```powershell
scripts\Run-LearnerWebQA.ps1
```

The script starts the learner Next.js dev server on port `3000`, sets the
browser base URL, waits for the port to be ready, and runs the focused e2e
module. To use another port:

```powershell
scripts\Run-LearnerWebQA.ps1 -Port 3100
```

The browser harness is intentionally opt-in in the normal repository test
suite. To run it against an already-running learner server:

```powershell
$env:AC_LEARNER_E2E_BASE_URL = "http://localhost:3000"
uv run pytest -m e2e tests/e2e/test_learner_web_qa.py
```

Use the same `localhost` origin that started the Next.js dev server. Next.js
blocks cross-origin development chunks by default, so substituting
`127.0.0.1` can leave the server-rendered page visible without hydrating its
interactive controls.

Playwright and a Chromium browser must be available to run the gate. If the
browser dependency or base URL is absent, the module skips, matching the
existing `tests/e2e/test_google_registration_browser.py` convention.

## Coverage and traceability

The route matrix uses stable IDs from
`docs/workflows/learner-product-v1/06-screen-family-v0.1-alpha/` and exercises
the following implementation-facing surfaces:

| Flow | Screen IDs | Route coverage |
| --- | --- | --- |
| `FLOW-AUTH-ONB-01` | `AUTH-01..07`, `ONB-01` | Sign in, registration, verification, recovery, reset, callback, session expiry, onboarding |
| `FLOW-SHELL-PLAN-01` | `HOME-01`, `PLAN-01..03` | Learner home shell; plan IDs share the home route/subview boundary |
| `FLOW-DISCOVER-01` | `DISC-01`, `COURSE-01` | Catalog and public program preview |
| `FLOW-LEARNING-01` | `LEARN-01`, `COURSE-02`, `MOD-01` | Library, owned program, and module path |
| `FLOW-ACTIVITY-01` | `ACT-01..05`, `MEDIA-01` | Activity route and activity-owned media region boundary |
| `FLOW-PROGRESS-01` | `PROG-01`, `INSIGHT-01` | Progress route and descriptive insight boundary |
| `FLOW-NOTIFY-01` | `NOTIF-01` | Notification center |
| `FLOW-PROFILE-01` | `PROF-01`, `AVATAR-01` | Profile route and avatar overlay boundary |
| `FLOW-SETTINGS-01` | `SET-01..05` | Account, theme, learning setup, privacy, session sections |
| `FLOW-CERT-01` | `CERT-01` | Certificate boundary |
| `FLOW-RESILIENCE-01` | `SYS-01..04` | Loading, retry, offline, lock, and permission-denied semantics |

For routes whose implementation shares one URL, the harness records each
stable screen ID in `ROUTE_SPECS` while de-duplicating the actual geometry
navigation. This keeps traceability without performing the same browser load
five times for `ACT-01..05`.

The route contract runs at exact reference widths `320`, `390`, `430`, `768`,
`1024`, and `1440` CSS pixels. The checks cover:

- one page heading, main/skip-link landmarks, accessible names, and comfortable
  target sizing for action controls;
- document and visible-element geometry with no horizontal overflow;
- compact learner navigation visibility, fixed-nav content clearance, and
  mobile More-drawer focus trapping/restoration;
- reduced-motion media preference, disabled skeleton animation, and automatic
  scrolling;
- `viewport-fit=cover` plus the app's top/bottom safe-area declarations;
- all shared non-production surface states, including retryable/terminal
  errors, offline, permission denied, locked, partial, and success feedback;
- explicit registration consent gating for the Google action;
- optional screenshot evidence at every reference viewport.

State coverage is driven by the app's non-production `?state=` parser. That
parser is ignored in production builds. The state gate therefore proves named
presentation behavior and recovery affordances, not server authorization,
identity, enrollment, progress, evidence, provider, or payment semantics.

## Screenshot evidence

Screenshots are opt-in because `.artifacts/` is ignored by repository policy
and an image alone cannot approve a route or capability. Capture them with:

```powershell
scripts\Run-LearnerWebQA.ps1 -CaptureScreenshots
```

The output directory is `.artifacts/learner-web-qa/`. Filenames carry the
stable screen ID, state, and viewport, for example
`HOME-01-loading-390.png`. Use same-viewport comparisons against an approved
visual direction when that direction and exact runtime evidence exist. No
tracked visual baseline or release claim is created by this harness.

## Remaining P0/P1 release gaps

The local harness introduces no new P0/P1 finding when its checks pass. The
following controlled gaps remain open and are intentionally outside a local
state simulation:

1. `GAP-RUNTIME-001`: exact-current candidate SHA browser/device evidence is
   still required, including an authenticated learner journey on Windows Edge
   and iOS Safari/PWA. A local Node 22 run is not Node 24 or staging proof.
2. Candidate exact-SHA proof remains required for canonical `/home`, learning
   path/module/activity ready states, progress/locks, onboarding, settings,
   and learner evidence mutations. The harness only asserts shell and named
   presentation states without protected API data.
3. `MEDIA-01`, `AVATAR-01`, `CERT-01`, plan/notification delivery, and any
   provider-backed activation remain capability-gated. The harness does not
   activate or score these capabilities.

These are proof/capability gates, not a reason to infer a product defect from
the fixture-driven browser run. See the workflow package's
`05-handoff-qa/qa-release-checklist.md` and
`docs/traceability/PLATFORM_SURFACE_STATUS.md` for the owning release
evidence.
