# Sales Xray web: report, Calls, Account and call-name increment

Local implementation evidence, based on commit 2c2f8d0919c402eb4ef51e7f440083e07433ad87. This record does not claim staging or production deployment.

## Scope
Frontend only (`apps/sales-xray-web`). It consumes the separately reviewed call-label API; no backend, schema or configuration change is part of this frontend increment.

## Changes
- **Shell:** the collapse control is a hover/focus-revealed overlay in the brand row, so the brand does not move when the rail collapses. The top bar is slimmer. Account is its own destination, separate from Calls.
- **Report header:** one compact title row showing the saved call name (or "Sales call report"), measured length, report language and draft status. It has one primary action and an overflow for Download and Request deletion (Escape and outside-click close). Provenance sits in a collapsed Source details disclosure.
- **Report surface:** a light report surface re-declares the theme tokens, so a dark app theme never mixes with fixed light report colours. Report navigation uses semantic tokens only.
- **Report navigation:** one horizontal row in both Reading and Tabbed views, with no second report sidebar. Tabbed is the desktop default only when neither the URL nor the reader has chosen a view. Section jumps are smooth (instant with reduced motion), with destination focus and highlight, a Return control, and browser Back support.
- **Playback:** one media session. A clip control shows Pause only while the clip it started is playing, pauses without reseeking, resumes in place, and restarts after the clip ends. Full-recording play or a manual seek releases clip ownership, in both the standalone and embedded studios. Source-bound context playback is preserved.
- **Times:** mm:ss everywhere. A clip under one second reads "at mm:ss · under 1 second". Invalid intervals are not playable.
- **Overview:** a short full-width takeaway, a facts line (call length, replay clips, suggested changes), and Keep doing / Change first / Outcome / Next call as a two-by-two open layout that stacks on narrow widths.
- **Replay strip:** draws only the report's own replay clips at their exact positions, with a full-size chronological list for keyboard and touch. It distinguishes unknown length, invalid intervals and ranges beyond a known recording; those beyond it are listed but never playable.
- **Sales skills:** coaching-material references are behind a closed disclosure. The recording panel appears only when an excerpt exists.
- **Calls:** one heading and a full-width list with document scrolling. Each row shows the saved call name (or a dated fallback), an estimated length ("About mm:ss", labelled as an estimate), a status chip and a per-row opening state. Status filters apply to the loaded rows. New analysis always starts a fresh call.
- **Call names:** rename from Calls and the report header through the call-label API.
  - A name counts as saved only after the server confirms it; the typed text is kept on every error.
  - A conflict, and any unconfirmed outcome (connection loss, server error, or an unusable confirmation after the request was sent), is reported as unconfirmed. It blocks further writes until a read-only check of the current name succeeds; that check confirms a save that did land.
  - Text typed after an unconfirmed save is never discarded: if the check confirms the earlier name, the newer text stays open and unsaved until the reader saves it.
  - When the saved name differs, the copy says the earlier change is not the current saved name, rather than claiming it failed.
  - A server without call names makes rename unavailable. It is never shown as an unnamed, writable call.
- **Account:** the signed-in profile (edits confirmed by a server re-read), the analysis allowance ("Unlimited" without a percentage when applicable), and sign-out with the existing unfinished-upload guard. There is no photo upload, because no supported contract exists.
- **New analysis:** a compact heading and drop zone, the allowance shown as a readable value, and no redundant step header before a call exists. The upload and analysis flow is unchanged.
- **Development-only fixture:** `/review-fixture/shell` mounts the real shell, header, all six report sections and the player with fictional data. It returns 404 outside development.

## Tests (latest local runs)
- Vitest (`@ac/sales-xray-web`, 2 workers): **73 files, 659 tests passed** (full suite). After the final rename-editor change: the focused rename suites, **4 files, 44 tests**, passed.
- `tsc --noEmit`: passed (an earlier intermediate Account type error was fixed before this run)
- ESLint (max warnings 0): passed

New or extended integration coverage:
- shared clip controls against one controllable media element (standalone and embedded)
- subsecond clip labels; the manual-seek escape after a completed clip
- return-to-origin and browser Back, including an origin URL without a section; reduced motion
- the light-surface token mirror; the replay strip's dataset, positions and unavailable states
- the Calls estimated-length semantics and fresh-call link
- call-name parsing for old and new servers
- rename:
  - confirmation only on the server response
  - lost or malformed responses resolved by a read-only check with no duplicate write
  - newer drafts preserved when a check confirms an earlier save, including text typed during the check
  - conflict refresh
  - a missing label contract making rename unavailable
- Account profile and allowance states; fixture routing

## Browser observations (local development, fictional data only)
- 1440×900 with the expanded shell: the header, the six-section navigation and the view switch fit without overlap, with no horizontal document overflow. Keep doing and Change first are visible; Outcome and Next call extend below the player.
- 1920×1080: all four readout sections are visible above the player with short fictional content.
- The brand link stays at the same position when the rail is expanded or collapsed, and the toggle stays in the brand row.
- Keyboard: arrow keys, Home and End move across all six tabs and update the URL. Section jump, Return and browser Back restore focus and position.
- Reflow at a 720×450 CSS viewport had no horizontal document overflow. This is reflow evidence, not an actual 200% browser-zoom check.

## Known limits
- The simulated media tests and fictional fixture do not prove real recording playback or audio alignment.
- Real 200% browser zoom, long Marathi report composition in the full shell, signed-in Account and rename browser checks, and production verification are pending.
- Prospect records need a backend contract and are not included.
