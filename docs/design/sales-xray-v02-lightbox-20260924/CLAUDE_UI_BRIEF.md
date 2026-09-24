# Brief for Claude Code (Opus 5.5, effort xhigh): implement Sales Xray v0.2 "Lightbox" UI

You are Claude Code, invoked headless by **Codex**, the integration and release owner of this repository, on behalf of the founder, Suyash. You implement the Sales Xray v0.2 "Lightbox" redesign in `apps/sales-xray-web`, one **phase** per invocation. Codex reviews your diff, runs the gates, integrates and releases. You never push, deploy or touch servers.

The current phase is given in the invocation prompt as `PHASE=<id>`. Do only that phase, then stop and report.

---

## 1. Read first (every phase)

1. `docs/design/sales-xray-v02-lightbox-20260924/DESIGN_SPEC.md`: behaviour, data mapping, constraints. **Authoritative.**
2. `docs/design/sales-xray-v02-lightbox-20260924/prototype/canvas/project/*.dc.html`: the visual boards.
   - They are self-contained HTML with inline styles. Treat them as the pixel reference for layout, hierarchy, spacing and copy.
   - `{{holes}}` and the `<script type="text/x-dc">` blocks are prototype-only. The waveforms there are illustrative; production uses measured data.
3. `docs/design/sales-xray-v02-lightbox-20260924/tokens.css` and `assets/**`: ship these as-is (copy them into the app as the spec says).
4. `docs/evidence/sales-xray-bug-handoff-20260924/HANDOFF.md`: the frontend bugs you own (§3 below).
5. The existing code you are replacing: `apps/sales-xray-web/app/*` (start with `acquisition-studio.tsx`, `acquisition-client.ts`, `report-contract.ts`, `overview-contract.ts`, `processing-state.ts`, `acquisition-shell.tsx`, `call-audio-dock.tsx`, `source-waveform.tsx`).

If `docs/design/sales-xray-v02-lightbox-20260924/IMPLEMENTATION_PLAN.md` exists (written in P0), follow it and keep it updated.

---

## 2. Non-negotiables

- **Scope:** `apps/sales-xray-web/**` and, only if needed, `packages/typescript/sales-xray-client/**`.
  - Do **not** modify `packages/python/**`, `db/**`, `infra/**`, `.github/**` or other apps.
  - If the UI needs a backend change (e.g. stable upload `reason` codes for U2, `Retry-After`), write it under "Backend requests" in your report; Codex owns it.
- **No API contract changes.** Keep using the existing client, parsers and contracts. You may add *optional* parsing of fields the server already sends (e.g. `execution_hold`, see U6).
- **Product truth rules (DESIGN_SPEC §1.2):**
  - No numeric scores.
  - Measured waveforms only.
  - No fabricated progress or ETA; the upload bar is real bytes only.
  - Inferences are labelled.
  - Quotes stay in their original language and script, with `lang`. Devanagari is never italic.
  - The disclosure stays visible.
  - Never render provider or server error bodies.
- **Fonts self-hosted** through `@fontsource-variable/*` (the CSP blocks third-party font hosts). Add packages with `pnpm --filter @ac/sales-xray-web add …` and commit the lockfile change.
- **Accessibility:** real controls, focus rings, keyboard player, reduced-motion support, ≥ 44px touch targets, 4.5:1 contrast.
- **Keep tests green:**
  - Adapt existing vitest suites to the new DOM instead of deleting coverage.
  - Every bug you fix gets a test.
  - Don't disable lint rules to pass.
- **Git:**
  - Work on the current branch Codex gave you. Commit at the end of the phase with a clear message.
  - End the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - **Never** `git push`, never force, never rewrite history, never touch other worktrees.
- **Secrets and data:** never read `.env*` values, cookies, provider payloads or customer audio or transcripts. Use the synthetic fixtures only (`app/review-fixture/report/*`, `app/fixture-review-states.ts`, `tests/fixtures/*`).
- **No servers:** don't run `ssh`, don't deploy, don't call providers, don't hit staging or production URLs.

---

## 3. Frontend bugs you own (fold into the relevant phase)

IDs come from `HANDOFF.md`. Some are already fixed on the integration branch; verify each before changing it.

| Phase | Bugs |
|---|---|
| P2 | **U1** phantom saved call (pending vs promoted id) · **U2** client-side duration/format pre-checks and reason-based copy (backend reason codes requested from Codex) · **U4** auto-start race and consent loss · **A4** mid-upload 401 in-page sign-in |
| P3 | **U3** polling backoff and restart on online/visible/focus; never permanent stop · **U5** failure copy map, never empty (DESIGN_SPEC §7.3) · **U6** `execution_hold` → profile prompt · **U8** `quoted` / `awaiting_upload` known states |
| P4 | **R1** keep listening past clip (may already be fixed; keep it) · **R2** Overview actions work in reading view (superseded by the new IA; make sure every action works) · **R3** no duplicate overview · **R4** player never blocked by modal · **R6** playhead store, no re-render storm · **R7** visible playhead without waveform · **R8** no dead mobile Playback button · **R10** sheet history entry and one time format |
| P5 | **A1** closable in-page sign-in · **A2** validated `returnTo` (client side; server allowlist is a Codex backend request) · **A3** OTP cooldown visible and reset on email change · **A5** lockout copy · **A6** preloader timeout, delayed and error states · **A7** Google popup-closed detection, no-opener redirect, in-app browser guidance · **A8** profile 403 → workspace chooser · **A9** library 401 handling, keep pages and scroll |

R5 (backend max-pooling) and R9 (streaming) are Codex's. For R5, render whatever envelope is provided, well.

---

## 4. Phases

Each phase ends with the gates in §5 and a report in the §6 format.

### P0 — Plan (no product code)
- Read everything in §1.
- Write `docs/design/sales-xray-v02-lightbox-20260924/IMPLEMENTATION_PLAN.md` covering:
  - The component tree and file plan (map every board element to a component).
  - Which existing files are replaced, kept or deleted.
  - How state machines are extracted from `acquisition-studio.tsx` into hooks.
  - The test plan.
  - Risks.
  - How the 14-point Dipak overview (`dipak-14-point-v1`) maps onto the new chapters. No point may be dropped.
- Commit that file only.

### P1 — Foundations and shell
- `app/lightbox/tokens.css` (copy), imported once in `app/layout.tsx`.
- **Fonts:** Bricolage Grotesque, Newsreader, Noto Sans and Noto Serif Devanagari (new packages) plus Plus Jakarta Sans (fix the wiring: define `--lx-font-*` and apply them globally). Remove Source Sans 3, Georgia, Segoe Print and Cascadia usage from Sales Xray surfaces.
- `public/lightbox/lightbox-glyphs.svg` and illustrations (copy).
- **Components:** `Glyph`, `Lens` (inline SVG, 6 states, reduced motion), `FilmSurface`, `QuoteChip`, `StatusChip`, `Stepper`, `Toast`.
- **Shell:** rail (248/72), top bar, mobile top bar and bottom nav, trial-minutes meter (real allowance), account row.
  - Remove the "Need help?" card, slogans and the Settings item (if empty). Help goes to a top-bar `?`.
- **Dark mode ships in v0.2** (DESIGN_SPEC §12.3):
  - A System / Light / Dark theme control (Account page and profile menu), persisted in `localStorage` with try/catch.
  - A pre-paint inline script in `layout.tsx` sets `data-theme` (no flash).
  - A `prefers-color-scheme` fallback for System.
  - Every Lightbox component reads tokens only, so it themes automatically.
  - Film surfaces stay dark in both themes.
  - Visual reference: the `Report-Dark` board.
- **Tests:** component tests plus a shell snapshot or DOM test. Grep test: no hard-coded hex colours in new Lightbox modules (tokens only). Theme tests: pre-paint script, persistence, System follows the media query.

### P2 — New analysis, Confirm, Uploading
- Boards: Home, Confirm, Mobile-Upload, and the States cards "Uploading" and "Can't use this file".
- **Hooks:**
  - `useSubmissionFlow` (U1, U4).
  - `useUploadProgress`: an XHR PUT with real bytes, preserving *exactly* the current headers and semantics of the PUT in `acquisition-studio.tsx`, including recovery-read-before-replay.
- **Drop zone:** a keyboard-accessible `<label>`, drag states, client pre-checks (U2).
- **Controls:** segmented language radio group, consent row, Turnstile area (existing `upload-check.tsx` behaviour), and the CTA that morphs into the upload bar.
- Recent calls panel (real data from the library endpoint) plus the first-run empty state.
- **"Your latest verdict" card** (DESIGN_SPEC §12.2): shows the EXAMPLE card until the user has a ready report, then the latest ready call's verdict and Change-first focus from the library payload. Never fetch a full report just for this card.

### P3 — Analysing and edge states
- Boards: Processing, Mobile-Processing, and the States cards: Needs your OK, Paused, Offline, report-ready Toast.
- **`useStatusPolling` (U3).**
- **Stage list** with receipts from progress data and a `role="status"` "last confirmed N s ago".
- **Lens** state derived only from confirmed server stage.
- **Measured waveform strip** when the envelope exists.
- **Failure copy map (U5)**, the profile hold (U6) and the known-state fixes (U8).

### P4 — The report
- Boards: Report, Mobile-Report.
- **`CallFilm`** (§5.3 of the spec): measured envelope, kind-shaped marker buttons with preview, keyboard nav, sticky collapse, mobile docked mini-player. Playhead via `useSyncExternalStore` and rAF (R6). Clip bounds with keep-listening (R1). Visible playhead without a waveform (R7).
- **Chapters:** ChapterRail (desktop) and ChipBar (mobile) with deep links (`?section=`, old values mapped). Remove the Reading/Tabs toggle but accept `view=` without error.
- **Verdict:** 3 cards; "Change first" is dominant.
- **MomentsTimeline:** filters, grouping that preserves all observations, rewatch badges, notes, copyable "Try this next time", "Show more".
- **SkillsGrid:** 8 dimensions, evidence glyphs, inline expand.
- **ProspectPairs:** inference styling, "still unknown". The heading is always "What the prospect revealed", never the name (§12.4).
- **Rename a call** (DESIGN_SPEC §12.1): inline title edit in ReportHeader (pencil, Enter/blur saves, Esc cancels, optimistic with revert). Render it **only if** the backend rename API exists on this branch; otherwise hide it and list it under `backend_requests`.
- **NextCallFocus:** "Say it like this" only when a phrase is provided.
- **TranscriptSync:** search, synced highlight, click to play, virtualised.
- ReportFooter with delete confirmation; DevelopReveal on first view; legacy, guest and empty shapes (§3.6.1).
- Review sheets become inline or non-modal (R4); mobile sheets push history (R10).
- **Tests:** a data-mapping test per chapter against `apps/sales-xray-web/tests/fixtures/dipak-overview.json` and the synthetic report. Also no-score grep, `lang` attributes on quotes, and no italic on Devanagari.

### P5 — Library, auth, profile
- Boards: Library, plus the shell applied to sign-in, profile and preloader (§3.8).
- Fix A1–A9 (frontend parts).
- Keep library pages and scroll on back navigation.
- Library row ⋯ menu with **Rename**, using the same API gate as P4.

### P6 — Polish, QA, cleanup
- **Visual QA** against the boards across the DESIGN_SPEC §11 matrix.
  - Run the dev server (`pnpm --filter @ac/sales-xray-web dev`) and use the synthetic routes (`/review-fixture/report`, the `sx-fixture=` states from `fixture-review-states.ts`).
  - Capture screenshots into `docs/evidence/sales-xray-lightbox-<YYYYMMDD>/` with a README table: state × viewport, and differences from the boards.
- **Accessibility pass:** keyboard-only journey and axe checks where available.
- **Performance:** fonts, CLS, playback long tasks.
- **Cleanup:** delete dead code (`workbench.tsx` and `processing-experience.tsx` if still unimported, old modules replaced in P1–P5), remove unused dependencies, and make sure no legacy CSS remains on the Sales Xray surfaces.
- Update `IMPLEMENTATION_PLAN.md` with final status and remaining gaps.

---

## 5. Gates (run at the end of every phase that changes code)

```powershell
pnpm --filter @ac/sales-xray-web typecheck
pnpm --filter @ac/sales-xray-web lint
pnpm --filter @ac/sales-xray-web test
pnpm --filter @ac/sales-xray-web build
```

- If formatting is enforced in CI (Prettier or similar per repo config), run the repo's formatter on changed files.
- A phase is **not done** if any gate fails. Fix it, or report the exact failure and stop.
- Do not skip or silence tests.

---

## 6. Report format (end every run with exactly this block)

```json
{
  "phase": "P1",
  "status": "done | partial | blocked",
  "commit": "<sha or null>",
  "summary": "<3-6 sentences, plain English>",
  "files_changed": <int>,
  "gates": { "typecheck": "pass|fail", "lint": "pass|fail", "test": "pass|fail (<n> tests)", "build": "pass|fail" },
  "bugs_fixed": ["U1", "..."],
  "bugs_verified_already_fixed": ["R1", "..."],
  "deviations_from_boards": ["<what and why>"],
  "backend_requests": ["<precise ask for Codex, e.g. 'PUT /source 422 should include reason=source_duration_exceeded and measured duration_ms'>"],
  "risks_or_followups": ["..."],
  "next_phase_ready": true
}
```
