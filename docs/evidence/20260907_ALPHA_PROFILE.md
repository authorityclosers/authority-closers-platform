# Alpha profile refinement — 7 September 2026

Status: implemented and isolated browser acceptance passed; independent review pending. Not committed or deployed by this workstream. Settings and Notifications files are frozen and untouched by this profile task.

## Scope and visual decision

The actual `/profile` route now uses a compact, responsive identity composition: photo, display name, email, one truthful verification indicator, and Change photo. Saved learning goals, experience, weekly commitment, and practice situation remain source-backed. Continue learning, Progress, Settings, and the existing sign-out control provide clear next actions. No username, streak, XP, achievement, completion, or account-role meaning was invented.

The supplied mobile screenshot exposed an actual layout defect: the legacy avatar panel's desktop `flex-basis: 300px` became vertical space after a mobile column layout. The profile now has an isolated CSS module with content-sized grid rows, responsive typography and wrapping, existing branded Inter/theme tokens, 44px controls, focus-visible styling, and reduced-motion behavior. It does not rewrite global theme or shared shell geometry.

The workflow-ui-production implementation mode guided route-mounted behavior, explicit state/error recovery, source-backed copy, and before/after evidence. Frontend-design guided hierarchy and composition within the already-selected brand, not a new visual identity.

## Owned implementation

- `apps/learner-web/app/components/profile-runtime.tsx`
- `apps/learner-web/app/components/profile-runtime.module.css`
- `apps/learner-web/app/components/profile-runtime.test.tsx`
- `apps/learner-web/app/components/avatar-crop-dialog.tsx` — separately approved minimal lifecycle fix only.
- `apps/learner-web/app/components/avatar-crop-dialog-interaction.test.tsx`
- `scripts/qa_alpha_profile.py`
- This evidence document and `docs/evidence/screenshots/alpha-profile-2026-09-07/`.

Photo retry refreshes only the secondary avatar read, retaining the mounted identity. The upload adapter is memoized so an unrelated signed-photo refresh cannot recreate the adapter of an open editor. Existing request abort/generation checks, current-photo preservation, signed delivery refresh, server-confirmed success publication, crop preview, and local URL cleanup remain intact.

## Real browser defect found and fixed

The first full interaction check found that selecting a real PNG displayed its preview but remained on “Checking image…”. `AvatarCropDialog` initialized a mounted ref, then cleared it in effect cleanup without restoring it in setup. React Strict Mode's setup/cleanup replay therefore made later successful image decodes look obsolete. The fix restores the mounted flag in effect setup; cleanup still increments the selection epoch and aborts outstanding work.

Five new mounted Strict Mode tests cover decoded-image readiness, keyboard crop/reset and cancel without upload; an older image decode settling after a newer selection; URL cleanup and late decode after unmount; upload-error preview preservation and retry; and cancellation followed by a late upload success. Nine mounted profile tests cover real source-backed composition, missing verification, membership boundaries, partial-read recovery, unset goals, stale identity responses, confirmed avatar host success, signed-image refresh/adapter stability, and obsolete avatar responses after context changes. Browser checks use the actual crop dialog, not the unit-test host seam.

## Source-of-truth and state acceptance

| Screen/state | Source and visible behavior | Recovery / preservation | Evidence |
| --- | --- | --- | --- |
| PROFILE-01 / ready | Authenticated `/v1/me`, `/v1/onboarding`, `/v1/profile/avatar`; no fabricated progress | Edit links to `/onboarding?return=profile` | Mounted tests and eight-size/theme browser matrix |
| PROFILE-01 / no membership | Existing membership boundary; secondary reads not requested | Existing authorized recovery only | Mounted test |
| PROFILE-01 / secondary unavailable | Identity remains visible; concise photo and setup error | Retry photo only refreshes avatar; retry setup reloads source | Mounted test + locally fulfilled 503 browser checks |
| PROFILE-01 / stale context | Old identity/photo responses cannot replace newer context | Existing abort/generation guards retained | Mounted tests |
| PROFILE-01 / offline read | Existing offline-read provenance notice | Reconnect-to-edit gate retained; no new offline authority | Existing behavior preserved; not newly browser-certified here |
| PHOTO-01 / preview | Local PNG preview and bounded crop | Keyboard +/arrows/Home; cancel restores focus; no upload on selection | Real browser and Strict Mode mounted tests |
| PHOTO-01 / upload unavailable | Error shown, current photo unchanged, no success claim | Local preview and retry remain available | Real dialog with locally intercepted upload-503 fixture |
| PHOTO-01 / canceled/unmounted | No late success committed | Abort, request/selection guards, object URL cleanup | Mounted tests |
| PHOTO-01 / server-confirmed ready | Only adapter-confirmed ready version updates host and publishes profile event | Existing current version retained until confirmation | Explicit synthetic adapter seam; **not live persistence proof** |

No new analytics events, server mutations, provider activation, account provisioning, or enrollment changes were made. The fresh browser contexts import no existing profile, cookies, authentication, or storage state. Unknown API reads and all actual API writes are blocked. The synthetic upload requests are fulfilled locally with 503 before they can reach a server. The PNG chosen in these tests is the repository's public academy icon, explicitly a test fixture, not a learner or instructor photograph.

## Evidence runs and limitations

- Before: `before/run-20260907T141635Z` — four captures at 390/1440, light/dark, before product edits.
- Initial composition verification: `after/run-20260907T142122Z` — four cases passed; did not yet exercise image decoding.
- `acceptance/run-20260907T142624Z` — failed QA locator: contrast lookup matched both header identity and profile identity. Preserved, not counted as acceptance. Locator was scoped to `main`.
- `acceptance/run-20260907T142756Z` — preserved **real image-decoding defect reproduction** at 320px light/dark. Not acceptance.
- `acceptance/run-20260907T143215Z` — both 320px cases passed after lifecycle fix, including PNG preview/crop, synthetic upload-503 recovery, keyboard focus, and long-identity wrapping.
- Final acceptance: `acceptance-final/run-20260907T143318Z/report.json` — **8/8 cases passed**, 320/390/768/1440 in light and dark, Chrome 152.0.7977.82. **37 PNG captures, 4,084,625 bytes**. Zero horizontal overflow, page errors, unknown API reads, or actual server/provider writes. Four attempted upload intents were explicitly intercepted and fulfilled locally with 503. **64 solid-background text-contrast measurements**, minimum **6.04:1**. Reduced-motion transitions were checked; the real editor's keyboard focus stayed contained and returned to Change photo after Escape. Normal synthetic identity card heights were 197.75px at 320, 210.63px at 390, 230.55px at 768, and 154.23px at 1440. Long synthetic identity wrapping was additionally checked at 320 dark.

Selected final captures, visually inspected: `320-dark-long-identity.png`, `390-light-profile.png` (initial composition pass), `768-light-profile.png`, `1440-dark-profile.png` (initial composition pass), and `1440-dark-avatar-fixture-unavailable.png`. Captures and JSON remain in timestamped directories; the before images and failed reproductions were not deleted.

Validation: final full learner Vitest **578 tests / 41 files passed** at 20:07:53 local time (22.51 seconds), full learner ESLint with zero warnings passed, learner TypeScript passed, scoped Prettier passed, QA Python Ruff passed, and `git diff --check` passed. The earlier full run passed 546 tests / 39 files; the shared worktree acquired other agents' additional tests before the final run. Two earlier fixture-only TypeScript errors (incomplete response types / inferred mock signatures) were corrected; they were not product-runtime fixes. The final focused profile + Strict Mode editor run passes **14 mounted tests**. Existing upload-adapter tests remain in the full learner suite.

All captures are local development UI with synthetic API reads. The visible development badge, Next development indicator, and fixed mobile navigation are not production-release evidence. A full-page screenshot places fixed browser-viewport chrome at its real viewport position, so scrollable content continues beneath it in the image; no hidden private browser state is used. No Lighthouse, Core Web Vitals, production latency, native app, screen-reader, or live provider performance claim is made.

## Avatar API and activation audit

The implementation is not a fake local-only avatar button. `createApiAvatarUploadPort` validates and hashes the file in bounded chunks, creates an authenticated upload intent, PUTs to its signed upload URL without credentials/redirects, completes the upload with checksum/size, and polls the profile for the exact ready media version. It preserves the current version while processing and reports bounded retryable/terminal failures.

The server exposes authenticated `/profile/avatar` GET/POST and avatar-only upload completion in `packages/python/ac_platform/http/media.py`, with safe-origin/idempotency handling and person audit records. `MediaService.get_profile_avatar` resolves only the current authenticated person's tenant-scoped avatar, retains the current ready version during replacements, verifies a ready variant/private namespace/storage presence, and mints delivery only through the configured delivery port.

However, checked-in `infra/application/compose.yaml` and `compose.staging-public-films.yaml` explicitly keep `AC_MEDIA_PROVIDER_ENABLED: "false"`. Existing public-film delivery is not evidence that avatar upload/storage/scanning/processing is activated. This task did not inspect private environment secrets, change provider configuration, or perform a real account upload. Live persistence must be verified in the separately controlled media-provider slice; do not describe these local fixture tests as proof of live photo storage.

The crop dialog's broader copy/visual structure and the existing shared profile loading/terminal-error skeleton were not redesigned by this bounded composition task. Their existing controls and boundaries are retained. There are no new profile editing, gamification, username, or server-backed preference features in this change.

## Reproduction

Independent review subsequently found no Critical/Important issue in the scoped
profile/avatar change against `2607368`. The reviewer independently passed
14/14 mounted tests in 8.11 seconds, inspected seven final mobile/tablet/desktop
captures and checked the 8/8-case report. Decode-generation, cancellation and
stale-result protections remained intact. This closes code/UI review only;
live avatar-provider persistence remains unproved as described above.

```powershell
pnpm --filter @ac/learner-web test
pnpm --filter @ac/learner-web lint
pnpm --filter @ac/learner-web typecheck
uv run ruff check scripts/qa_alpha_profile.py
uv run --python 3.12 --with playwright python scripts/qa_alpha_profile.py --base-url http://learner.localhost:3100 --output docs/evidence/screenshots/alpha-profile-2026-09-07/acceptance-final --after
```

Use the configured Node 24 runtime. The browser script requires an already-running local learner origin, rejects non-local origins, and creates a new timestamped directory rather than overwriting evidence. No commits, pushes, deployments, or Drive publication were performed by this subtask; independent review and release orchestration remain with the parent task.
