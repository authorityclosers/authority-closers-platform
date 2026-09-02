# Learner PWA platform hardening evidence

Date: 2026-09-02

This record covers source-level PWA/platform hardening for the learner web
candidate. It is not a deployment or device-certification claim.

## Implemented boundary

- `app/manifest.ts` keeps `/` as the stable app identity/start URL and uses
  `standalone` with an explicit standalone display override, all-orientation
  support, `lang`/`dir`, and `prefer_related_applications: false`.
- `app/layout.tsx` links the manifest and 180×180 Apple touch icon, emits the
  Next Apple web-app metadata, and explicitly emits
  `apple-mobile-web-app-capable=yes`. The viewport remains
  `width=device-width, initial-scale=1, viewport-fit=cover` for iOS safe areas.
- `app/components/pwa-register.tsx` registers only in production secure
  contexts (with localhost loopback exceptions), opts out of the HTTP cache
  for worker update checks, and catches registration/storage failures without
  affecting the normal browser app.
- `public/sw.js` uses versioned shell cache `ac-learner-shell-v0.1.1`. It
  caches only the public offline shell, manifest/icons/theme initializer, and
  same-origin immutable Next static assets. Shell/static fetches omit
  credentials and reject redirects, non-basic responses, and any exposed
  `Set-Cookie` header before writing Cache Storage. `/v1` and `/v1/*` are never
  handled by the worker. Navigation fallback reads only the current shell cache.
- Updated workers remain waiting until the normal lifecycle boundary; there is
  no `skipWaiting()` or forced page reload that could interrupt dirty learner
  work.

## Verification evidence

- `pnpm --filter @ac/learner-web exec vitest run app/lib/pwa-assets.test.ts` —
  4 tests passed.
- `pnpm --filter @ac/learner-web test` — 17 files / 241 tests passed.
- `pnpm --filter @ac/learner-web typecheck` — passed.
- `pnpm --filter @ac/learner-web build` — passed; the generated manifest route
  returned `application/manifest+json` in the local build/dev check.
- `pnpm --filter @ac/learner-web lint` — passed.
- `pnpm format:check` — passed (180 files formatted; Python formatter check
  passed as well).
- `node --check apps/learner-web/public/sw.js` — passed.
- Local Playwright Chromium smoke check confirmed manifest/Apple metadata,
  one heading, and no horizontal overflow at 390px. A temporary isolated
  service-worker check confirmed shell/static responses work offline,
  navigation falls back to `/offline`, and `/v1/me` is not served from Cache
  Storage. The temporary browser registration/cache were removed afterward.

The local commands emitted the workspace engine warning because this machine is
running Node 22.17.0 while the package declares Node `>=24.0.0 <25`; repeat
the exact checks on the required Node 24 runtime in CI/release validation.

## Required manual release checks

Run these checks against the exact immutable release and record browser/device
versions separately:

1. Desktop Chrome/Edge: install from the manifest, launch in standalone mode,
   open deep links, go offline, and confirm the safe offline page plus static
   shell assets.
2. Android Chrome: install, verify the launcher/maskable icon and portrait and
   landscape layout, then repeat offline navigation and reconnect.
3. iOS Safari: verify browser mode and Home Screen/standalone mode on a real
   supported iPhone/iPad, including status bar, safe-area insets, keyboard,
   back/forward navigation, and offline/reconnect behavior.
4. With a dirty learner draft open, stage a worker update and confirm no page
   reload or draft loss; after the normal lifecycle boundary, confirm the new
   worker and cache version take effect.
5. Inspect Application/Storage panels to confirm no `/v1`, authenticated
   route document, progress, evidence, draft, cookie, or mutation response is
   in the service-worker cache.
