# E9: Direct Profile action in the account pop-up

Task: [AUT-1001](/AUT/issues/AUT-1001). Source pin:
`c559d1fd8c5c1cfafde1e5afbe32167f68073198` (main, 6 October 2026).

Scope choice: expose the existing Profile pane directly from the account
pop-up. Allowed files: `apps/sales-xray-web/app/profile-menu.tsx`, its test,
`apps/sales-xray-web/app/settings-dialog.test.tsx`, and this evidence.
The pre-edit open-PR file lists contained no overlap with these paths.

## Behavior

- Signed-in header and rail pop-ups offer Profile with the existing menu-row
  styling and a profile icon. The separate Settings entry remains available.
- A plain click outside `/account` opens the existing Settings Profile pane
  over the current screen. The pathname and query remain intact, and the
  pop-up closes. The hash is `#settings/profile`, which the existing dialog
  can reopen from a copied link.
- Focus moves to the persistent menu trigger before opening the dialog, so
  closing the dialog returns focus to a control that still exists.
- On `/account`, and for Control/Command/Shift clicks, the link keeps ordinary
  navigation to `/account#profile`. Guests retain the existing sign-in action.
- Existing profile reads, photos and editing stay in their established
  components. No new profile storage or notification delivery policy is added.

## Verification

- `pnpm --filter @ac/sales-xray-web exec vitest run
app/profile-menu.test.tsx app/settings-dialog.test.tsx
app/account-photo.test.tsx`: **41 passed**.
- Sales Xray ESLint and TypeScript: **passed**.
- Changed-file Prettier and `git diff --check`: **passed**.
- Branch gate: **passed**. PR admission results are recorded on the task.

Tests cover both menu variants, guest behavior, ordinary and modified link
navigation, the actual Settings Profile pane over a fictional call URL,
closing the pop-up, return focus, and existing private-photo fallbacks.
The dialog test's Link adapter now calls the supplied click handler before
simulating navigation, so the integration test exercises the actual menu
behavior. All fixture identities and call URLs are fictional.

## Sources and dev checks

This continuation preserves the controlled-source intake recorded in
[AUT-1001's first-slice evidence](AUT-1001-settings-profile-first-slice.md).
AC-UXA-01 was fetched by exact manifest ID
`1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`; its focus and return-focus requirements
inform this entry. Installed Next.js client-component and Link guides were
read locally. Existing menu rows, icons and dialog are reused; no new visual
system or substantive interface design is introduced.

Before editing, dev GET `/settings` returned **302** to Cloudflare Access.
Signed-in dev and staging acceptance are unverified. The named AC Orchestra
skill and authorized Chrome Pro session remain unavailable in this environment.
No deployment or infrastructure setting was changed.

After merge, use a fictional account on salesxray-dev. From a call or Dashboard,
open the header or rail account pop-up and choose Profile. Confirm the Profile
pane, current account details, unchanged underlying page, and returned focus
when closing. Verify keyboard activation, 390 px and desktop layouts, a guest,
modified-click opening in another tab, and `/account` navigation. Repeat on
staging after the release train arrives.

## Remaining E9 scope

This PR is one navigation slice and does not complete E9. Notification
preferences and compulsory delivery rules, the separate notifications pane,
photo upload, full E10 analytics, per-version email/Telegram delivery and
signed-in deployed checks remain open. [AUT-474](/AUT/issues/AUT-474) retains
updates-client, rewrite, bell and corner-card ownership. Preserve the full
epic and remove its temporary review stage after reviewing this PR only.
