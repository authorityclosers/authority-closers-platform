# AUT-1798 — Every legacy Moments pin remains reachable

The older Details → Moments call map stacked four nearby clips on the same
16 px target. The map now keeps each supplied time position and places
colliding targets on separate rows. Targets use the shared 32 px desktop /
44 px touch token. Filter and row Play controls also respect that token.

The map measures its available width and recomputes rows when resized. Each
finding and standalone listen clip keeps its id, evidence and exact playback
interval. Map clicks still open the matching row; no report data is rewritten.

## Source and scope

- Request: B → G, 1798 INBOX, continuing A's 22:57 UTC finding.
- Source HEAD before the repair: `67992169`.
- Binding document: `/home/acdev/scratch/specs/final-xray-structure-2026-10-09.md`.
- Existing phone proof:
  `/home/acdev/strikes/1663/shots/2026-10-11/slate-listen-pins-rest/`.
- Owned changes: `report-moments.tsx`, its CSS module and focused test.

## Focused checks

- `ac-heavy pnpm --dir apps/sales-xray-web exec vitest run app/report-moments.test.tsx`:
  **15/15 pass**. Cases cover nearby targets at both sizes, coincident pins,
  selected rewatch times and exact source playback for four standalone clips.
- `ac-heavy pnpm --dir apps/sales-xray-web exec tsc --noEmit --incremental`:
  pass.
- Cached ESLint on the touched TS/TSX files and `git diff --check`: pass.
- New heavy checks began after the coordinator's 23:08 UTC window.

Post-commit shared-dev screenshots and browser readback are pending. The
read-only harness is `/home/acdev/strikes/1798/harness/moments-map-proof.mjs`.

## Check on dev

Open `http://127.0.0.1:3026/review-fixture/shell?call=00000000-0000-4000-8000-000000000002&view=tabs&section=moments`.
Each early pin opens its own moment; use that row's Play button to hear the
supplied clip. Keyboard Enter also opens the matching row.
