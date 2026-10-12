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

## Shared-dev readback

Repair commit: `9ee9cf6b`. The read-only browser harness exited successfully:
**4/4 pairs pass**, 1440/390 px in light/dark. Every pair has all four supplied
pins on four separate rows, with 32/44 px targets, zero overlaps and all four
centres reachable through browser hit testing. Every pin opens its own row;
keyboard Enter works. Runtime errors and sideways overflow: zero.

All four screenshots were visually inspected. The two standalone listen clips
are now visible separately, and touch Play/filter controls reach 44 px. The
four rows are needed on this fixture because every selected clip falls in the
first 31 seconds of a 59:58 call. Wider-spaced clips reuse a row; the focused
test also verifies that widening a map reduces its row count.

Receipt and screenshots:
`/home/acdev/strikes/1798/shots/2026-10-11/moments-map-2311/`:

- `receipt.json`: stable source HEAD `9ee9cf6b` throughout the four-pair run.
- `moments-1440-light.png`: all four early pins are individually visible.
- `moments-1440-dark.png`: slate/teal/warm pins remain clear on the dark tracks.
- `moments-390-light.png`: four separate 44 px targets; filters fit in two rows.
- `moments-390-dark.png`: each early pin remains clear; first clip text is readable.

Source hashes stayed unchanged during readback:

- TSX: `d425067d20aee468e2bf10f2af73ffc4feb7d81dc5828e9ef343109ea033c5b0`.
- CSS: `e2d958777cf53dcfec33debb0c08fa4f4dae4bddc78328b59591fe3da5fef7a7`.

Harness: `/home/acdev/strikes/1798/harness/moments-map-proof.mjs`, run through
`ac-heavy` after the post-commit warm-up. It closes every browser/context.
This proof uses the fictional fixture; it makes no authenticated persistence or
immutable release claim. The coordinator owns versioning and shipping.

## Check on dev

Open `http://127.0.0.1:3026/review-fixture/shell?call=00000000-0000-4000-8000-000000000002&view=tabs&section=moments`.
Each early pin opens its own moment; use that row's Play button to hear the
supplied clip. Keyboard Enter also opens the matching row.
