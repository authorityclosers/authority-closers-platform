# Organisation Overview: calls analysed (AUT-1616, in strike AUT-1663)

Date: 10 Oct 2026. Branch `task/ui/1663-strike-screens`, PR #419.

## What changed

- `app/organisation/organisation-api.ts`: `readReceiptActivity` reads
  `GET /v1/conversation/acquisition/organisation/activity` through the signed-in
  acquisition client, with no selectors. `parseReceiptActivity` accepts the
  exact contract only. It needs `Asia/Kolkata` and 30 chronological days, and
  each person needs a UUID that appears once. The day, organisation and person
  totals must agree for counts and seconds. A 404 means the server does not
  serve the read yet. This parser is separate from the personal
  `parseCallActivity`.
- `app/organisation/receipt-activity.tsx`: the Overview section "Calls
  analysed", shown to live owners and admins only. It has:
  - the 30-day chart from the Dashboard (`DayBars`);
  - the change against the previous 30 days;
  - a person table in API order: calls, time (from seconds through `callTime`)
    and the previous 30 days. People with the same name show their email, or
    "Former member" if they have left;
  - one footnote saying why it can differ from the saved calls above.
- States:
  - Loading shows the chart skeleton.
  - Empty shows zeros and "Nobody … in the last 60 days".
  - 404 shows one quiet line.
  - Malformed or failed reads show "could not be loaded" with Try again.
  - 401/403 hide the section and refresh access.
  - The section is keyed by tenant, so a workspace switch aborts the old read
    and starts empty. Members never request this read.

## Checks

- `npx vitest run app/organisation/ app/dashboard/ app/owner-surfaces.test.tsx`:
  9 files, 211 tests passed. New tests use the complete tested fictional
  response attached to AUT-1616 (`receipt-activity.fixture.ts`, checked equal
  to the attachment).
- `npx tsc --noEmit -p .`, `npx eslint app/organisation/ app/dashboard/` and
  Prettier: clean.
- Browser (Playwright through `ac-heavy`, mocked fictional `/v1` routes,
  1440 and 390, light and dark): no sideways scroll, no overflow, no writes.

## Not verified

- A signed-in owner on dev with real data: no dev credentials are available to
  this seat. The dev API runs release `ce753781` (6 Oct), which predates the
  route (`bc61dbf`, #370). Until dev is refreshed, an owner sees the quiet line.
