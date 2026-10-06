# E9: First-call guide in Settings

Task: [AUT-1001](/AUT/issues/AUT-1001). Source pin:
`ce753781ba69f9b2e74b9300619473173bab2be1` (main, 5 October 2026).

Scope choice: make the existing first-call guide available from Settings → Help
& support. Notification preferences need a persisted contract and explicit
compulsory-category rules; this slice makes progress on the independently
available help requirement. It does not complete E9.

Allowed files: `apps/sales-xray-web/app/account-settings.tsx`,
`apps/sales-xray-web/app/settings-dialog.test.tsx`, and this evidence. No open PR
overlapped those paths at the pre-edit check. The task branch retains the
notification-preferences name chosen before contract inspection.

## Behavior

- Help & support reuses `useFirstCallGuideSwitch` and the existing Settings row
  and button styles. The switch appears only when the authenticated person is
  known; the support email remains available while identity is loading.
- On restarts the guide at its first step and closes the Settings dialog so the
  existing guide can be seen. Off keeps Help open. The switch follows the same
  per-person browser preference as the account menu, including remembered
  dismissal. The copy states that the choice is kept in this browser.
- This uses presentation preferences only. No notification delivery policy,
  account preference API, call processing, canonical progress, or access state
  is introduced. The existing guide engine and account-menu switch remain the
  implementation owners of guide behavior.

## Verification

- `pnpm --filter @ac/sales-xray-web exec vitest run
app/settings-dialog.test.tsx app/guide-host.test.tsx app/guide-progress.test.ts
app/shell/settings-menu.test.tsx app/account-view.test.tsx`: **48 passed**.
- Sales Xray lint and typecheck: passed.
- Changed-file Prettier write/check and `git diff --check`: passed.
- Latest-main `ac-gate check`: passed for the owning admin branch. The PR
  admission result is recorded on the task after opening the PR.

Regression cases exercise a previously dismissed guide restarting from Help,
closing the dialog on activation, keeping it open on dismissal, reopen
persistence, isolation when changing fictional accounts, and withheld controls
while the authenticated identity is unknown. Existing guide-engine, progress,
account-menu and account tests run alongside these cases.

## Sources and limitations

The original E9 slice records the completed controlled-source intake in
[its evidence](AUT-1001-settings-profile-first-slice.md). This continuation reads
ADR 0054, the saved accepted product-updates policy and technical design, and
the existing guide registry, progress store, switch, and tests at the source
pin. AC-UXA-01 was fetched again by its exact manifest Drive ID
`1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-` for accessible controls and recovery.
This slice reuses existing UI and guide components and needs no substantive
interface redesign or cloud artifact.

Dev `/settings` returned HTTP 302 before editing; the later HEAD probe returned 403. Signed-in dev access is unavailable; neither deployed visual acceptance nor
staging acceptance is claimed. No production/staging state or settings were
changed.

## Dev check after merge

With a fictional account, close the existing guide, then open Settings → Help
& support. First call guide should be Off. Turn it On: Settings closes and the
guide starts from Welcome. Reopen Help and switch Off: Settings stays open.
Close and reopen Settings; it should still be Off. Switch to another fictional
account and verify its independent preference. Repeat at 390 px and desktop,
and then on staging after the release train arrives.

## Remaining E9 scope

Notification preferences and compulsory delivery rules, photo upload, E10
analytics entries, and per-version email/Telegram delivery remain open.
[AUT-474](/AUT/issues/AUT-474) retains ownership of the API-backed What's new,
bell and corner-card journey. Full E9 completion still requires its original
release and channel acceptance; approval of this PR does not complete the epic.
