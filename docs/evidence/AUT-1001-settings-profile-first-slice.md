# E9: Profile photo and language in Settings

Source pin: `5092cbe` (main, 5 October 2026). Task:
[AUT-1001](/AUT/issues/AUT-1001).

Scope choice: ship the existing private profile photo in the account pop-up and
profile pane, plus the current app-language information in General. This is one
small E9 delivery slice; it does not complete the epic's release acceptance.

## Implementation

- The persistent shell passes its already-loaded profile photo to the account
  pop-up. Both it and the larger profile-pane avatar use `AccountAvatarImage`,
  which admits only `/v1/me/sales-xray-profile/photo`, sends no referrer and
  falls back on missing, foreign or failed images. Account identity changes
  reset each avatar's error fallback.
- General shows English as the current app language and directs people to
  select the report language when starting an analysis. This preserves the
  existing menu's distinction between app and report languages.
- The existing photo-copy backend, profile write contract and owner-approved
  report, document and Calls sections are preserved.

Allowed files for this slice: `account-settings.tsx`, `account-view.module.css`,
`account-photo.test.tsx`, `account-view.test.tsx`, `shell/settings-menu.tsx`,
`shell/lightbox-shell.tsx` within `apps/sales-xray-web/app/`, and this evidence.
No currently open PR overlaps these paths.

## Verification

- `pnpm --filter @ac/sales-xray-web exec vitest run
  app/account-photo.test.tsx app/account-view.test.tsx
  app/shell/settings-menu.test.tsx app/settings-dialog.test.tsx
  app/profile-menu.test.tsx app/shell/profile-store.test.ts`: **54 passed**.
- `pnpm --filter @ac/sales-xray-web lint`: passed.
- `pnpm --filter @ac/sales-xray-web typecheck`: passed.
- Prettier write and check for all six changed app files: passed.
- `git diff --check`: passed.

Regression coverage includes private photos on both new surfaces, missing and
foreign URLs, image failures, changed accounts after an image failure, viewport
positioning, settings navigation, and independent profile and billing reads.
All fixture identities are fictional.

## Sources and limitations

Read the repository guardrails and fetched the controlled sources by the exact
IDs in `docs/workflows/learner-product-v1/06-screen-family-v0.1-alpha/01-research-journeys/source-manifest.csv`:
Master Index, BRD, IMP-00/01/03/04/05, then the first-slice domain sources and
AC-UXA-01. Read ADR 0054 and the accepted product-updates technical plan at
[AUT-433](/AUT/issues/AUT-433#document-plan). The installed Next.js client
component guide was read locally.

Signed-in dev access was unavailable: the unauthenticated Settings request
redirected to Cloudflare Access. No signed-in visual or deployed acceptance is
claimed. The named `ac-orchestra` skill and an authorized Chrome Pro session
were unavailable in this environment. This slice reuses the existing avatar
component and settings rows; no new visual system or cloud design is claimed.

## Dev check after merge

On salesxray-dev, use a fictional sandbox account with a saved Google photo.
Open the account pop-up, then Settings → Profile: both should show the private
photo. Simulate an image failure and verify initials. Switch to a second
fictional account and verify that its photo loads. Repeat at 390 px and desktop
width. Settings → General should show English and explain where to choose the
report language. Repeat after the release train reaches staging.

## Remaining E9 scope

The update feed, bell and corner cards retain their existing implementation
owner in [AUT-474](/AUT/issues/AUT-474); this slice does not duplicate its store
or alter the handwritten changelog. Notification preferences and compulsory
delivery rules, photo upload, the E10 analytics entries, and per-version email
and Telegram delivery remain open. A photo-upload write contract is absent;
no upload control or save success is fabricated. E9 stays open until its full
release acceptance is met, including the requested v0.16 channel evidence.
