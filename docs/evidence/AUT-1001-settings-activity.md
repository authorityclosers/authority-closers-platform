# E9: Usage and activity in Settings

Task: [AUT-1001](/AUT/issues/AUT-1001). Source pin:
`79472b03d6bc3f62dcb260d89f152947e00e4ad7` (main, 6 October 2026).

Scope choice: replace the Settings pane's "Analysis time" heading with
"Usage & activity" and show the existing Dashboard's verified call counts and
30-day analysis activity. This is a bounded E9 slice using existing contracts,
not the full E10 analytics page or API. [AUT-474](/AUT/issues/AUT-474) retains
the updates client, rewrites, store, bell and corner-card ownership; its open
PR #366 overlaps none of this slice's files.

Allowed files: `apps/sales-xray-web/app/account-settings.tsx`, the new
`apps/sales-xray-web/app/account-activity.test.tsx`, and this evidence. The
admin checkout was clean before the gate started
`task/admin/1001-notifications-pane`; that branch name records the initial
candidate, while the reviewed diff is the independent activity slice. All open
PR file lists were checked before editing. No shared, billing, manifest,
infrastructure or owner-surface file is changed.

## Behavior

- The existing `usage` section, account links and `settings-usage` dialog links
  remain valid. The tab and pane use "Usage & activity" and an existing Lucide
  activity icon. The current allowance display and purchase controls remain.
- Opening Usage reads `/v1/conversation/acquisition/submissions/summary` and
  `/v1/conversation/acquisition/activity` through the existing Dashboard
  client and strict parsers. Hidden usage panes make neither read.
- Rows show saved, completed, processing and attention counts, followed by
  analysed calls in the current and previous 30-day windows. The existing
  trend helper compares the two windows; the calendar is labelled India time.
  These are saved call states and analysis activity, without any score fields.
- Each read has independent loading, failed and unserved states. A confirmed
  empty response shows zeros; unavailable or malformed responses show no
  invented counts. Failure of either source does not hide the other source
  or the balance. Reload activity retries the two read-only requests.
- Leaving the pane aborts its requests. The existing account, session and
  workspace keys remount Settings on identity changes; aborted or late
  responses cannot update the replacement pane.
- "Open Dashboard" links to the existing live charts. Dialog navigation uses
  replacement history, following the other Settings links.

## Verification

`pnpm --filter @ac/sales-xray-web exec vitest run
app/account-activity.test.tsx app/account-view.test.tsx
app/settings-dialog.test.tsx app/account-photo.test.tsx
app/dashboard/dashboard-data.test.ts`: **71 passed** across five files.

Coverage includes lazy reads, server counts, true zeros, pending reads,
unserved routes, 401/403/503 failures and retry, malformed counts, independent
successful reads, late responses after account/workspace switches, preserved
allowances and the existing dialog deep link. All identities and activity
fixtures are fictional.

- Sales Xray app typecheck: passed.
- Sales Xray app lint: passed.
- Changed-file Prettier write/check and `git diff --check`: passed.
- Latest-main `ac-gate check`: passed.
- PR admission and CI are recorded in the task handoff.

## Sources and deployed checks

This continuation uses the owner E9 card, the existing Dashboard contracts
and the [first-slice source intake](AUT-1001-settings-profile-first-slice.md).
The installed Next.js client-component guide was read. Existing Settings
rows, icon library and Dashboard helpers supply the presentation and data;
no new visual system or external research artifact is used.

Before editing, GET `https://salesxray-dev.authorityclosers.com/settings`
returned HTTP 302 to Cloudflare Access. Signed-in dev and staging acceptance
are unverified. No deployment, external processing or live data change was made.

After merge, sign in on dev with a fictional sandbox account. Open Settings
from Calls, then Usage & activity. Compare saved/completed/processing/attention
counts and both 30-day totals with Dashboard; verify the balance still matches
the existing account allowance. Test `#settings-usage` and `/account#usage`,
an empty account, failed activity requests, retry and an account/workspace
switch while a request is pending. Check at 390 px and desktop widths and
repeat after the release train reaches staging. These are acceptance steps,
not a claim that the signed-in deployed journey was tested.

## Remaining E9 scope

E9 stays open. Notifications UI/client/read-all wiring, persisted notification
preferences and approved compulsory categories, photo upload, the full E10
analytics deliverable, per-version email/Telegram delivery and signed-in
dev/staging acceptance remain outstanding. Review this slice without closing
the epic or changing the existing updates UI ownership.
