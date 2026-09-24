# Sales Xray Lightbox: implementation plan

- **Phase:** P0 (plan and data mapping only; no product source changed)
- **Base commit:** `1d6d84a9d53adb16d9385f8f832d2016ab067f05` on `codex/sales-xray-lightbox-ui-20260925`
- **Author:** Claude Code (`claude-opus-5-5`), for Codex review
- **Date:** 25 September 2026
- **Later phases** update §14 (status log) and any section whose decision changes. They do not rewrite history. Where an entry is superseded, they say so.

---

## 0. Authority, guard and reading scope

**Order of authority, used to settle every conflict in this plan:**

1. The owner's direct requirements, as recorded in `INTEGRATION_DECISIONS.md`.
2. The current contracts and tests: `report-contract.ts`, `overview-contract.ts`, `acquisition-client.ts` and their suites.
3. `DESIGN_SPEC.md` for behaviour.
4. The canvas boards for look, hierarchy and copy.

Every deviation from a board or the spec is listed in §10, with the requirement or contract it follows.

**Guard (applies to every phase):**
- Claude edits only `apps/sales-xray-web/app/**` and `apps/sales-xray-web/public/lightbox/**`. P0 adds this file only.
- Codex owns commands, dependency and lockfile changes, tests, formatting runs, commits and release.
- Every phase report states the gates as `not run: delegated to Codex` and gives `commit: null`.
- No backend, infra, CI, other apps, git configuration or security settings are touched.
- Backend needs are written as requests (§11).

**Reading scope used for this plan:**
- The Lightbox package in this folder: decisions, brief, spec, README, Codex handoff, tokens, assets and boards.
- `AGENTS.md` and `apps/sales-xray-web/AGENTS.md`.
- `apps/sales-xray-web/app/**` source and test names.
- `tests/fixtures/dipak-overview.json`.
- `package.json`, `next.config.ts`, `vitest.config.mjs`, `eslint.config.mjs`.
- The installed Next 16 view-transitions guide.

**Deliberately not read:**
- `docs/evidence/sales-xray-bug-handoff-20260924/HANDOFF.md`. It sits outside the permitted reading set, so bug IDs (U/R/A) are taken from the summaries in `CLAUDE_UI_BRIEF.md` §3, and each phase re-verifies the behaviour against source.
- `apps/learner-web/**`. It embeds this app (see §1, fact F17). Its constraints are inferred only from `app/styles.integration.test.ts`, and Codex is asked to run its tests every phase.

**The canvas HTML is reference text only.**
- Its `./support.js` and the Google Fonts `<link>` in each board's `<helmet>` were not executed and must never be copied.
- The contact-sheet page (`prototype/_asset-sheet.html`) was not opened or fetched.
- Board waveforms come from a sine formula in `<script type="text/x-dc">` (for example `Processing.dc.html:156-165`). They are illustrative and never reach production.

---

## 1. Baseline facts from the tested source

| # | Fact | Source |
|---|---|---|
| F1 | The overview version is `dipak-14-point-v1`, with exactly 14 required keys plus an optional top-level `business_impact`. | `overview-contract.ts:69-89`, `:105`, `:121-125` |
| F2 | `progress` must be `null`. There is no multi-call history. | `overview-contract.ts:234` |
| F3 | The UI presents 14 numbered Dipak review points: 01, 02–04, 05 … 14. | `dipak-overview.tsx:360-389` |
| F4 | A report always has exactly 8 dimensions. Status is one of `observed`, `insufficient_evidence`, `not_applicable`, `conflicted` or `unknown`. `evidence` is optional. | `report-contract.ts:19-25`, `:345-435` (`array(value, "report_dimensions", 8, 8)` at `:350`) |
| F5 | The actual dimension IDs, in server/profile order, are `human_connection_trust`, `discovery_deep_understanding`, `qualification`, `problem_impact_desire`, `solution_relevance_presentation`, `certainty_objection_intelligence`, `closing_decision_management` and `communication_tonality`. | `sales-skills.tsx:29-38`; `tests/fixtures/dipak-overview.json:83-215` |
| F6 | Transcript segments have only `id`, `speaker_id` (nullable free text), `start_ms`, `end_ms` and `text`. There are **no word timestamps**, **no speaker role** and **no per-segment language**. | `report-contract.ts:179-193` |
| F7 | The library row has only `id`, `createdAt`, `durationSeconds`, `state` and `hasReport`. It has **no title or filename, verdict, focus, language, marker positions or total count**. Pages hold 20 rows with a cursor. | `acquisition-client.ts:39-49`, `:355-410` |
| F8 | Progress has `state`, `local_state`, `failure_code`, `has_report`, `automatic_progression` and `stages` (`C2`/`C4`/`C5` only). It has **no `execution_hold`, reference ID, created date or duration**. | `acquisition-client.ts:50-57`, `:411-453` |
| F9 | The report projection has `source_label` (a technical label such as "Scribe transcript revision … · source-bound"), not a filename. The report title today is the local `file.name` when the same session uploaded it, otherwise "Your saved sales call". | `report-contract.ts:703-758`; `acquisition-studio.tsx:2728`; fixture `:80` |
| F10 | The upload is a `fetch` PUT with `redirect: "error"`, `credentials: "same-origin"` and the headers `Content-Type: application/octet-stream`, `X-Source-SHA256`, `X-Upload-Policy` and `X-Upload-Consent: accepted`. After a failed PUT, recovery reads the submission before any replay. There is **no byte progress**. | `acquisition-client.ts:107-117`; `acquisition-studio.tsx:960-1051` (recovery `:1003-1016`, PUT `:1019-1031`) |
| F11 | Status polling stops permanently after 3 failures or on 401/403/404/409 (U3). | `acquisition-studio.tsx:698-772` (`:750-760`) |
| F12 | The auto-accept effect cleanup clears `consentedSubmissionId` when its dependencies change (U4 consent loss). | `acquisition-studio.tsx:780-858` (`:834-843`) |
| F13 | Account gate: standalone guests can select and preview locally. Analysis calls `requestAnalysisAccess`, which opens the in-page `AccountAuth` with the selected file preserved, then the profile-eligibility gate. | `standalone-studio.tsx:336-357`, `:450-511`; `pending-analysis.tsx` |
| F14 | `PendingAnalysisProvider` is mounted per page, inside `StandaloneStudio`, so a client route change discards it. The rail's "Analyse a call" is a **full navigation** `<a href="/?new=1">`. | `standalone-studio.tsx:155-174`; `acquisition-shell.tsx:136-144`; `new-call-navigation.ts:2-7` |
| F15 | `view=reading|tabs` and `section=` are parsed only for the bound `?call=`. Sections are `overview`, `prospect`, `moments`, `skills`, `next-call-plan` and `transcript`. | `report-modes.tsx:31`, `:58-78`, `:167-195`; `acquisition-studio.tsx:2642-2722` |
| F16 | `report-navigation.ts` (a separate `REPORT_SECTIONS`, without transcript) serves only the legacy `ReportExplorer` inside `CallStudio`. | `report-navigation.ts:3-9`; `call-studio.tsx:19` |
| F17 | **`learner-web` embeds `AcquisitionStudio variant="embedded"` and imports this app's `styles.css`.** The stylesheet must keep its `@scope (.xray-app)` boundary. | `styles.integration.test.ts:8-42` |
| F18 | The waveform endpoint `/submissions/{id}/waveform` returns `ac.sales-xray.waveform/1` `rms_envelope` with ≤ 1200 points. The provider re-renders every consumer on each `timeupdate` (R6). | `source-waveform.tsx:13-53`, `:79-81`, `:101-116`, `:129-149` |
| F19 | The dock re-renders on every `timeupdate`. Speeds are 1 → 1.25 → 1.5 → 2 → 0.75. Pressing Play in the dock clears the clip bound (R1 appears implemented). | `call-audio-dock.tsx:14`, `:79-82`; `acquisition-studio.tsx:2730-2740` |
| F20 | Transcript times show milliseconds (`mm:ss.mmm`). Speaker shows the raw `speaker_id`. Rows load in pages of 50. | `report-transcript.tsx:9`, `:16-28` |
| F21 | With an overview, Moments shows only the curated `rewatch` clips. Legacy reports flatten findings in report order. Duplicate ranges stay attached to each finding (the existing test "keeps duplicate source ranges attached to each original finding and quote"). | `report-moments.tsx:52-92`; `report-moments.test.tsx:311` |
| F22 | "Settings" is the local development/live-data dialog. It renders only where `LiveDataBanner` provides it (`AC_SALES_XRAY_DEV_LIVE_DATA=true`). | `live-data-banner.tsx:45-60`, `:81-163`; `layout.tsx:14-18` |
| F23 | The synthetic report route exists only in development. **There is no production sample route.** | `review-fixture/report/page.tsx:7` |
| F24 | No CSP is set by this app; any CSP comes from the edge. Fonts: only `@fontsource-variable/plus-jakarta-sans` is imported, and `--font-sans`/`--font-plus-jakarta` are never defined. Source Sans 3 is installed and used for reports. | `next.config.ts`; `layout.tsx:2`; `styles.css:7`; `acquisition-studio.module.css:1317` |
| F25 | The processing "known" state list lacks `quoted` and `awaiting_upload` (U8). | `processing-state.ts:57-70` |
| F26 | The failure copy only special-cases broker identity and `conversation_provider_http_*`. Other paused codes produce an empty string (U5). | `acquisition-studio.tsx:97-109`, `:731-734` |
| F27 | Orphaned modules: `workbench.tsx` and `processing-experience.tsx` are imported only by tests. `processing-status-copy.tsx` borrows `processing-experience.module.css`. | grep of imports |
| F28 | Test inventory: 52 test files, 356 `it(` blocks. The baseline records 457 passing web tests. `acquisition-studio.test.tsx` alone has 58. | vitest grep; `INTEGRATION_DECISIONS.md:11` |
| F29 | The glyph sprite has no `closing` kind glyph and no `unknown` ("Not assessed") skill glyph. The Lens SVGs read `var(--lx-*, fallback)` and use fixed gradient/filter IDs. | `assets/glyphs/lightbox-glyphs.svg:9-130`; `assets/lens/lens-idle.svg:15-26` |

---

## 2. What each owner decision means for the build

| Decision (`INTEGRATION_DECISIONS.md`) | Plan consequence |
|---|---|
| 1 · Keep both report modes | Lightbox continuous reading is the default. A Lightbox-styled **tabbed view** shows one chapter at a time with the same chapter components, playback and deep links. `view=reading|tabs` is kept, and old `section` values stay as aliases (§3.7). A compact Reading/Tabs control stays in the report header. |
| 2 · First use is quiet | First run shows the upload action, compact limits and privacy, and an optional fictional-sample link only once a production sample route exists (§13, Q2). No empty tables, checklists, Example card or "latest verdict" card. Returning users get a real Recent calls list, with loading, error and empty states kept distinct. |
| 3 · Account first | Keep `requestAnalysisAccess` and the in-page `AccountAuth` → `AccountProfile` gates (F13). Local select and preview stay available. No guest processing is restored: Turnstile continues to render only where the current code already renders it. The claim flow stays for legacy guest reports. |
| 4 · Let people navigate | An upload session provider in the root layout owns the XHR (§3.5). The shell shows a minimized indicator on other routes. No full navigation happens during a live upload. "You can close this tab" appears only after the server has accepted the upload **and** dispatch is confirmed. |
| 5 · Measured progress | The upload bar is `xhr.upload.onprogress` (`loaded/total`), labelled "Uploading" until the PUT response is parsed and bound. Then it shows "Checking with the server…" with no percentage. Stages come only from `progress.stages`. The Lens loop is activity only. There is no ETA and no invented waveform. |
| 6 · Recovery copy follows capability | Replace spec §7.3 promises with a capability-true map (§7.2). Only existing server-authorized actions are offered. "Check now" (polling) is visibly distinct from "Request a fresh plan" / "Review and continue" (paid analysis). |
| 7 · Evidence stays visible | No ellipsis or line-clamp on the key takeaway, finding explanations or primary quotes; they wrap. Only compact transport labels (file name in the upload bar, library title) may truncate, with the full name available accessibly. Speaker labels are the raw label plus "unverified" (F6). Seller examples stay seller examples. |
| 8 · No lost report data | Full mappings in §4.1 and §4.2. Shared clips keep every observation. Original script is kept, with `lang`/`data-script` handling (§4.8). The source label, disclosure, legacy/guest shapes and permissions are kept. Transcript sync is by segment (F6). |
| 9 · Useful settings stay | Keep the development Settings dialog, `ProfileMenu` identity, avatar initials and sign-out. Remove only empty placeholders: the "Need help?" card, the slogan, the welcome banner and the dashboard lower panels. |
| 10 · Minimal chrome | A compact transparent top bar and account control. Help moves to a `?` popover. Responsive rules are in §5. |
| 11 · Titles and names | Title = persisted title when one exists (none today, F7/F9), else the local filename for the uploading session, else "Sales call · {date}" (library) or "Sales call" (report). No rename affordance (no API). The chapter title is "The prospect". Names only appear inside evidence. |
| 12 · Theme and samples | Ship the dark tokens but do **not** set `data-theme="dark"`, follow `prefers-color-scheme`, or show a toggle until P6 contrast and visual checks pass (§6.4). Samples are opt-in and labelled fictional. |

---

## 3. Target architecture

### 3.1 File plan

Filenames follow the repository idiom: kebab-case `.tsx`/`.ts` files with co-located `*.module.css` and `*.test.tsx`. Exported component names follow the spec (`Lens`, `CallFilm`, …). The spec allows renaming (DESIGN_SPEC §10).

```
apps/sales-xray-web/app/
  lightbox/                      P1 · primitives (no route; no page.tsx)
    tokens.css                   verbatim copy of the package tokens.css (parity test)
    tokens-scope.css             same light values scoped to .xray-app for the learner-web embed (parity test; §6.2)
    fonts.css                    @fontsource-variable imports + --lx-font-* confirmation
    glyph.tsx / glyph-paths.ts   inline symbols copied from the sprite (works on any host; parity test)
    lens.tsx / lens-states.ts    inline SVG, 6 states, useId-scoped defs, reduced-motion freeze
    film-surface.tsx(.module.css) variants drop|panel|player|focus, film-local token overrides
    quote-chip.tsx               ▶ mm:ss + full quote (wraps; never clamped), kind tint, lang/data-script
    status-chip.tsx              library/processing state chips
    stepper.tsx                  Choose call · Confirm · Analyse · Report
    toast.tsx                    polite live region; one "Report ready" announcement
    segmented.tsx                radiogroup primitive (language; later theme when allowed)
    time.ts                      one time format: m:ss / h:mm:ss (R10); "under 1 sec" helper
    script.ts                    Devanagari detection → data-script, lang choice (§4.8)
  shell/                         P1 · replaces acquisition-shell presentation
    lightbox-shell.tsx           rail 248/72, top bar, mobile top bar, bottom nav, skip link
    rail.tsx · top-bar.tsx · bottom-nav.tsx · minutes-meter.tsx · account-row.tsx · help-menu.tsx
    upload-indicator.tsx         P2/P3 · minimized upload/processing pill (only with a live session)
    use-account-name.ts          extracted from profile-menu.tsx (same PROFILE_UPDATED_EVENT)
  new-analysis/                  P2
    new-analysis.tsx · drop-zone.tsx · file-card.tsx · language-segment.tsx · consent-row.tsx
    analyse-button.tsx (CTA ↔ real-bytes bar) · next-steps.tsx · recent-calls.tsx · trust-row.tsx
    file-checks.ts               U2: extension+MIME, size, loadedmetadata duration (unknown allowed)
  analysing/                     P3
    analysing-panel.tsx · stage-list.tsx · stage-row.tsx · measured-strip.tsx · offline-pill.tsx
    needs-ok-card.tsx · paused-card.tsx · failure-copy.ts (§7.2) · lens-for-progress.ts
  report/                        P4
    report-view.tsx (modes) · report-header.tsx · call-film.tsx · playhead-store.ts · waveform.ts
    chapter-rail.tsx · chip-bar.tsx · report-tabs.tsx · report-chapters.ts (ids, aliases, 14-point map)
    verdict.tsx · moments-timeline.tsx · moment-item.tsx · moments-model.ts (pure)
    skills-grid.tsx · skill-tile.tsx · prospect-pairs.tsx · next-call-focus.tsx
    transcript-sync.tsx · report-footer.tsx · develop-reveal.tsx · locked-teaser.tsx
  library/                       P5
    calls-list.tsx · call-row.tsx · mini-film.tsx · library-state.ts · use-library-pages.ts
  hooks/                         P2–P4
    use-call-entry.ts            P2 · entry/policy/session/saved-call load (studio :327-534)
    use-submission-flow.ts       P2 · choose/add/remove/reset/upload/claim/erase (U1, U4, A4)
    use-upload-progress.ts       P2 · XHR PUT with identical semantics (§3.5)
    upload-session.tsx           P2 · root-layout provider + external store (§3.5)
    use-plan-approval.ts         P3 · quote/accept/expiry/stale refresh (studio :536-696, :780-858, :1053-1095)
    use-status-polling.ts        P3 · U3 backoff + restart
    use-online-visible.ts        P3 · online/visibility/focus signals (also data-motion-suspended)
    use-playback.ts              P4 · clip bounds, keep listening (R1), speed/mute
    use-allowance.ts             P1/P5 · shared verified allowance for the meter

apps/sales-xray-web/public/lightbox/   P1
  lightbox-glyphs.svg            verbatim copy (brief requirement; standalone host)
  illustrations/empty-calls.svg, offline.svg (verbatim)
  fonts/<family>-OFL.txt         licence texts for new font packages (repo idiom: public/fonts)
```

### 3.2 Board element → component map

**Home (`Home.dc.html`) and Mobile-Upload.**

| Board element | Component | Data | Notes |
|---|---|---|---|
| Rail (brand, New analysis, Calls, Account, minutes, account row) | `LightboxShell` → `Rail`, `MinutesMeter`, `AccountRow` | `Allowance` (`acquisition-client.ts:22-27`); profile name | No call count (F7). The meter shows only when an allowance is verified. |
| Top bar "New analysis" + "Private to your account" + `?` | `TopBar`, `HelpMenu` | none | Help keeps the old tips plus Privacy, Terms and Help mail links from the removed footer. |
| Eyebrow, H1, lede | `NewAnalysis` header | copy | H1 is kept at H1 size, not "display", to satisfy minimal chrome (§10, D2). |
| Stepper | `Stepper` | local stage | |
| Lightbox drop zone | `DropZone` in `FilmSurface variant="drop"` + `Lens state="ready"` | `UploadPolicy` limits | The whole zone is a `<label for>`. Limits come from the policy, never hard-coded. |
| Trust row | `TrustRow` (compact, one line on mobile) | copy | |
| Recent calls (returning users) | `RecentCalls` | first library page (`GET /submissions`) | Loading, error and empty are distinct. No moment strip or language (F7). |
| "Your latest verdict" / Example card | not rendered | none | F7; decision 2. See D4 and B3. |
| Mobile top bar (logo, "42 min left", avatar) and bottom nav | `LightboxShell` mobile parts | allowance, profile | |

**Confirm (`Confirm.dc.html`).**

| Board element | Component | Data | Notes |
|---|---|---|---|
| File card (film tile, name, size, "about N min", Preview, Change) | `FileCard` | `File`, measured metadata duration | Name truncates with a full `title` and accessible name (transport label). Preview plays the local object URL. |
| Report language segmented | `LanguageSegment` (`Segmented`, radiogroup) | `entry.report_languages` (`report-language.ts`) | Rendered only when the server advertises languages, as today. |
| Consent row | `ConsentRow` (real, visually hidden checkbox) | existing consent text + Privacy details disclosure (`policy.description`, `retention_days`, `privacy_details`) | Consent wording is unchanged (D18). |
| Turnstile area | existing `UploadCheck` inside `ConsentRow` | `entry.site_key` | Same render condition as `acquisition-studio.tsx:2237-2252`. |
| CTA "Analyse my call" + allowance line | `AnalyseButton` | allowance; "about" duration | Disabled rules from `:2257-2269`. |
| "What happens next" + honesty line | `NextSteps` | copy | |

**Uploading (States card 1).** `AnalyseButton` becomes the upload bar, driven by the `UploadSession` store:
- The label reads "Uploading privately · 12.4 of 18.2 MB".
- "Cancel upload" is shown while bytes are in flight.
- At 100% it reads "Checking with the server…".
- On an unknown outcome, reconcile status before copy (§7.2).

**Processing (`Processing.dc.html`) and Mobile-Processing.**

| Board element | Component | Data | Notes |
|---|---|---|---|
| Breadcrumb + "Copy link to this call" | `TopBar` | opaque `?call=` | Copies the same URL the current "This call's link" builds (`:2375-2381`). |
| Eyebrow, H1 by stage, "Last confirmed N s ago" | `AnalysingPanel` header | time of last successful status read | Dots animate; they stop under reduced motion. |
| Lens 176px + caption | `Lens state={lensForProgress()}` | confirmed stages (§4.6) | |
| Stage rows with receipts | `StageList` / `StageRow` | `projectProcessing` rows | Receipts only from real facts (§4.6). |
| Measured strip | `MeasuredStrip` | `/waveform` envelope | Omitted when there is no envelope. |
| "You can close this tab" + Go to Calls | `AnalysingPanel` footer | dispatch-confirmed flag | Shown only when truthful (decision 4). |
| "While you wait" card | not rendered | none | D7. |

**States (`States.dc.html`).**
- Needs your OK → `NeedsOkCard`, reading plan `max_entitlement_seconds` as "up to".
- Paused → `PausedCard`, using `failure-copy.ts` plus the reference.
- Can't use this file → an error state of `DropZone` with the precise reason.
- Offline → `OfflinePill`.
- Empty first run → the quiet intake (decision 2; no "No calls yet" panel on Home). The `empty-calls` illustration is used in the Library empty state.
- Report-ready toast → `Toast` with `Lens state="done"`.

**Report (`Report.dc.html`), Mobile-Report and Report-Dark.**

| Board element | Component | Data |
|---|---|---|
| Header (eyebrow, title, meta chips, Download, ⋯) | `ReportHeader` | title rule (decision 11), `transcript.duration_ms`, `plan.report_language` (only when `plan.report_run_id === runId`, `:2559-2566`), `overview.outcome.kind`; DOCX download; Delete and Copy link |
| Call player with markers | `CallFilm` + `playhead-store` | envelope, moments model markers |
| "On this page" rail + disclosure | `ChapterRail` (desktop), `ChipBar` (tablet/mobile) | chapter list, hiding empty chapters |
| Verdict + 3 cards | `Verdict` | §4.1 |
| Moments | `MomentsTimeline` / `MomentItem` | §4.4 |
| Skills | `SkillsGrid` / `SkillTile` | §4.3 |
| The prospect | `ProspectPairs` | §4.1 point 07 |
| Your next call | `NextCallFocus` | §4.1 points 11–13 |
| Transcript | `TranscriptSync` | segments (F6) |
| Footer disclosure + Delete | `ReportFooter` | disclosure + source label |
| Mobile docked mini-player | `CallFilm variant="docked"` | same store |
| Theme segmented (Report-Dark) | not rendered until P6 verification | decision 12 |

**Library (`Library.dc.html`).** `CallsList` / `CallRow` / `MiniFilm`:
- Titles are "Sales call · {date}".
- Each row shows duration and a status chip.
- Mini film: a plain film tile for ready calls (no ticks), a scanline for analysing, a pause glyph for paused.
- Filter chips work client-side over the loaded rows, without totals.
- No search: there are no titles to search (F7).

### 3.3 Existing files: keep, replace or delete

| File | Fate | Phase |
|---|---|---|
| `acquisition-client.ts`, `report-contract.ts`, `overview-contract.ts`, `observe-submission.ts`, `report-language.ts`, `report-ui-copy.ts`, `account-*-client.ts`, `existing-call-entry.ts`, `new-call-navigation.ts`, `workspace-access.tsx`, `pending-analysis.tsx`, `processing-review-port*.ts`, `fixture-review-states.ts`, `measurement-*` | **Keep** as the contract and logic layer. The only planned edit is additive: export a shared error translator from `acquisition()` so the XHR path matches `:118-192` exactly (P2). The parser change for `execution_hold` happens only if Codex confirms the server sends it (B6). | P2/P3 |
| `processing-state.ts` | **Keep.** Add `quoted` and `awaiting_upload` to the known states (U8). | P3 |
| `acquisition-studio.tsx` | **Keep the export and props** (`variant`, `homeHref`, `requestedCallId`, `deferRouteSelection`), because page.tsx and learner-web use them. State moves into hooks (§3.4). Rendering moves to `new-analysis/`, `analysing/` and `report/`. | P2–P4 |
| `acquisition-shell.tsx` | **Keep the export as a thin wrapper** over `LightboxShell` (same props; `heroStage`/`welcome`/`displayName`/`previewHero` become no-ops, then are removed in P6 once callers are updated). | P1 |
| `standalone-studio.tsx`, `account-auth.tsx`, `account-profile.tsx`, `sales-xray-preloader.tsx`, `profile-menu.tsx`, `account-navigation.tsx`, `auth/complete/*`, `login/page.tsx` | **Keep the behaviour; restyle.** Fixes A1–A9 happen in P5. `profile-menu.tsx` logic is reused by `AccountRow`. | P5 |
| `live-data-banner.tsx`, `analysis-availability.tsx`, `upload-check.tsx` | **Keep; restyle** containers only. | P1–P2 |
| `call-studio.tsx` + `report-explorer.tsx`, `report-factors.tsx`, `recording-measurements.tsx`, `finding-evidence.tsx`, `report-navigation*.ts`, `report-section-copy.ts` | **Keep.** This is the legacy disabled-entry studio for retained reports (`acquisition-studio.tsx:1330-1342`). Restyle with tokens only in P6. No functional change. | P6 |
| `acquisition-dashboard-panels.tsx`, `acquisition-file-stage.tsx`, `acquisition-processing-panel.tsx`, `processing-visual.tsx`, `processing-status-copy.tsx` | **Replace.** Logic worth keeping moves across (the 60 s "No new stage update yet…" notice from `processing-status-copy.tsx:9-52`). Delete once they are unimported, including by `sales-xray-fixture-preview.tsx`. | P2–P3 → delete P6 |
| `report-modes.tsx`, `report-reading-context.tsx`, `dipak-overview.tsx`, `overview-dashboard.tsx`, `report-moments.tsx`, `sales-skills.tsx`, `prospect-snapshot.tsx`, `next-call-plan.tsx`, `report-transcript.tsx`, `review-dialog.tsx`, `call-audio-dock.tsx`, `source-waveform.tsx` | **Replace.** Logic that moves: URL rules → `report-chapters.ts`; `parseWaveform` and `waveformBins` → `report/waveform.ts`; `countReportMoments` semantics → `moments-model.ts`. `formatTranscriptTime` stays exported until `call-studio.tsx` no longer imports it. | P4 → delete P6 |
| `workbench.tsx`, `processing-experience.tsx` (+ their tests) | **Delete in P6** if still unimported. Their tests cover dead code only; Codex confirms before deletion. | P6 |
| `sales-xray-fixture-preview.tsx`, `review-fixture/report/*` | **Keep** as development review routes. Point them at the new components. | P2–P4 |
| `styles.css` | **Keep** the `@scope (.xray-app)` boundary (F17). Legacy rules are removed as surfaces migrate. | P1–P6 |

### 3.4 Extracting state from `acquisition-studio.tsx` into hooks

The goal is to move behaviour without changing it, then change the presentation.

- **Behaviour-preserving extraction first.** Each phase first extracts its hooks with the existing DOM still rendered, so the existing suites prove parity. The phase then swaps in the Lightbox presentation and adapts tests.
- **Codex reviews the extraction as a separate hunk** within the same phase.

| Hook | Moves from (studio lines) | Owns | Invariants to keep |
|---|---|---|---|
| `useCallEntry` | `:327-534`, route resolution `:201-222`, dismissed/requested IDs | entry, policy, session, allowance, claimAvailable, saved-call load, deletion-only, `savedCallNeedsSession`, 12 s timeout | Captures the route before any await. Guest 401 keeps the selector. 403/404 → deletion-only path. Never renders server bodies. |
| `useSubmissionFlow` | `:860-958`, `:960-1051`, `:1097-1211` | file selection (via `PendingAnalysis` when present), `operation` lock, upload, reset, `startAnotherCall`, forget, claim, erase | `inFlight` single operation. Consent is ephemeral and bound to the new submission. Only the opaque selector is stored. `setNewCallRequested(false)` on upload. Allowance is refreshed from its authority, never estimated. |
| `useUploadProgress` | `:989-1031` | SHA-256 digest, recovery read before replay, XHR PUT | Identical headers and consent. Recovery read before any replay. Denied or malformed reads never authorize another PUT. |
| `usePlanApproval` | `:536-696`, `:780-858`, `:1053-1095` | quote, accept, expiry, stale refresh, owner plan read, auto-accept | Idempotency keys unchanged (`report-plan:…`, `accept-plan:{id}`). Language mismatch → manual review. Paused or read-only blocks writes. |
| `useStatusPolling` | `:698-772` | GET-only observation, result verification | Adds the U3 schedule (§8, P3) and keeps 401/403/404 handling distinct. |
| `usePlayback` | `:1242-1256`, dock `:47-61`, `:2730-2740` | clip bound, keep listening, speed, mute, error message | A clip pauses at `end_ms`. Play or "keep listening" clears the bound (R1). |

The review-port substitution (`:1289-1307`) stays in the composing component. Observed frames never enter the operational hooks (the comment at `:1289-1290`).

### 3.5 Upload session and navigation (decision 4)

- **`UploadSessionProvider`** is a client component mounted once in `app/layout.tsx` around the body content. The root layout persists across App Router client navigation.
  - It owns the XHR, the `File` reference for the live upload, and an external store (`useSyncExternalStore`) with `{ intentId, fileName, totalBytes, sentBytes, phase: "preparing"|"uploading"|"confirming"|"accepted"|"failed"|"cancelled"|"unknown", submissionId?, requestId? }`.
  - Progress events update the store only, so progress never re-renders the page tree.
- **Studio integration.** `useSubmissionFlow` starts the upload through the provider when present. It falls back to component-local XHR when absent: the learner-web embed has no provider, and there the UI never claims background continuity.
- **Shell.** `UploadIndicator` renders on routes other than the owning intake while the phase is `preparing`, `uploading` or `confirming`, or while the accepted submission is still processing. It links back to the intake or `?call=`.
- **No full navigation during a live upload:**
  - Rail and bottom-nav "New analysis" switch from `<a href>` to client navigation plus the studio's `startAnotherCall` reset while a session is live. An in-flight upload is never reset; the user is offered "Cancel upload" first.
  - Sign-out during a live upload asks for confirmation.
  - `beforeunload` prompts while bytes are in flight.
- **XHR parity with `fetch`:**
  - Method `PUT` to `${ACQUISITION}/submissions/{id}/source`, with `withCredentials` false (same origin), the same headers and `Accept: application/json`.
  - The response goes through the shared `acquisition()` error translator (status, `x-request-id`, 403/422/503 detail rules).
  - `fetch` used `redirect: "error"`, but **XHR follows redirects**. After load, `responseURL` must equal the requested URL; otherwise treat the outcome as `unknown` and run the recovery read. Risk K2 covers what this cannot undo.
- **Outcome states:**
  - Nothing is described as saved until the PUT response parses and binds (`bound.id === id && bound.sha === sha`, `:1033-1035`).
  - A network error or abort **after bytes were sent** means the outcome is unknown. The UI says "Checking whether your upload arrived…" and runs the recovery GET before offering a retry (U1; decision 6).
  - "Nothing was saved" is said only after that GET returns 404.
- **Pending vs promoted selector (U1).** Keep `ac.xray.submission.v1` for promoted (server-bound) IDs only. Record the pending intent under a separate key before the PUT. On reload, a pending intent triggers the recovery read. A 404 clears it with "The upload didn't finish. Nothing was saved." That replaces today's deletion-only phantom.

### 3.6 Playback and playhead store (R1, R4, R6–R8, R10)

- **One `<audio>` element**, owned by `CallFilm`. `playhead-store.ts` is an external store updated from `timeupdate`/`seeked`, throttled with `requestAnimationFrame` while playing.
  - Consumers subscribe with selectors: `currentMs` for the playhead, `activeMomentId` for the active marker and row, and `playing`.
  - Nothing else re-renders on time updates.
- **Waveform bins** are memoised per `(envelope, laneWidth)` with at most 1 bin per 3 CSS px.
  - Without an envelope, show a flat line with a visible progress fill and thumb (R7).
  - Markers are `<button>`s placed at `start_ms / duration` and shaped by kind. Markers closer than 8 px cluster into a count bubble that expands on activation.
- **Keyboard:** ← / → move between markers, Space toggles play, Home / End. There is a throttled `aria-live` time announcement.
- **Review content is inline or non-modal.** No `showModal()` in report chapters (R4). Mobile sheets push a history entry, so Back closes them (R10).
- **The mobile docked mini-player is 62 px** above the bottom nav. Its Play button always works (R8).

### 3.7 Report modes and deep links

| URL value | Meaning |
|---|---|
| `view=reading` (default) · `view=tabs` · anything else | Reading; tabs; reading (no error) |
| `section=verdict` · old `overview` | Verdict chapter |
| `section=moments` · `skills` · `prospect` · `transcript` | Same name |
| `section=plan` · old `next-call-plan` | Your next call |

- Parsing keeps the bound-call guard (`report-modes.tsx:58-78`): exactly one `call` equal to the bound ID, and one `section`.
- Links written by the new UI use new IDs and `replaceState`, as today (`:182-185`).
- No name or title ever appears in a URL.
- `report-navigation.ts` stays for the legacy `ReportExplorer` (F16).

---

## 4. Data mapping

### 4.1 The fourteen Dipak points → chapters

Chapters: **verdict**, **moments**, **skills**, **prospect**, **plan**, **transcript**. Every point below has a DOM anchor `data-dipak-point="NN"` so P4 tests can assert that nothing is dropped.

| Point | Label (`dipak-overview.tsx:360-389`) | Contract source | Chapter and placement | Empty / legacy / guest |
|---|---|---|---|---|
| 01 | What you're already good at | `strengths[]` + `strength_details[].why_it_matters` | **verdict** "Keep doing" card = `strengths[0]` (title, explanation, why-it-matters, quote chip). **moments**: every strength evidence item, with explanation and why-it-matters. | "No supported strength recorded" (existing copy). Guest teaser `preview.sections.strengths`. |
| 02–04 | Priority fixes 1–3 | `improvements[0..2]` + `improvement_details[]` (`what_happened` {text, evidence}, `why_it_matters`, `replacement_behavior`, `business_impact`) | **verdict** "Change first · your one focus" card = `improvements[0]` (dominant). **moments**: each improvement's evidence, with What happened (plus its evidence chips), Why it matters, Try this next time (copyable, verbatim), and Business impact "Insufficient data" plus `missing_inputs`. | Legacy: explanation plus the existing impact limitation copy (`dipak-overview.tsx:955-976`). Guest teaser `improvements`. |
| 05 | Golden moments | `golden_moments[]` {strength_index, evidence_index, why_effective} | **moments**: a "Golden moment" badge plus `why_effective` on the matching strength evidence item. | Legacy: no badge. Unselected strengths are never relabelled (test `dipak-overview.test.tsx:429`). Guest teaser `golden_moments`. |
| 06 | Missed opportunities | `missed_opportunities[]` + `missed_details[]` (`prospect_signal`, `closer_response`, `follow_up`, `potential_impact`) | **verdict** "Missed opening" card = `missed_opportunities[0]`. **moments**: each missed item with What the prospect said (plus evidence), How you responded (plus evidence), Try this next time = `follow_up`, Possible value = `potential_impact`. | Legacy: explanation. Guest teaser `missed_opportunities`. |
| 07 | What the prospect may have meant | `prospect_interpretations[]` {source {text, evidence}, possible_concern, `interpretation_kind: "inference"`} | **prospect**: quote chips plus report observation → a dashed "Possible reading · not confirmed" card. "Still unknown after this call" uses the existing boundary copy (`prospect-snapshot.tsx:161-167`). | Existing empty copy (`:147-158`). Guest teaser `prospect_interpretations`. |
| 08 | Your rewatch list | `rewatch[]` {text, purpose, evidence[1]} | **moments**: a badge on the item whose evidence matches (`must_watch` "Must rewatch", `watch` "Worth a watch", `repeat` "Repeat this") plus `rewatch.text`. An unmatched rewatch clip becomes its own "Rewatch" item. There is a "Rewatch" filter. | Legacy: the curated-per-category fallback (`dipak-overview.tsx:318-330`) as badges. An intentionally empty rewatch selection stays empty (test `report-moments.test.tsx:253`). Guest teaser `rewatch`. |
| 09 | Where the conversation changed | `conversation_change` {before, change, after (each text + evidence), possible_effect, inference} | **moments**: a "Where the conversation changed" sequence block (before → change → after, each with chips); `possible_effect` in dashed inference style. | "A first breakpoint… has not been established" (existing). |
| 10 | Your sales skills | `dimensions[8]` | **skills**: all 8 tiles (§4.3). | "No skill observations were supplied" (existing). |
| 11 | Your next-call focus | `next_call_focus` {behavior, target} → fallback `final_assessment.next_focus` → `improvements[0].title` | **plan**: film focus card "Your one focus" + "Your target"; "Try this" = `improvement_details[0].replacement_behavior` verbatim (D12). | "A next-call focus has not been identified yet." |
| 12 | Personalized practice | `practice` {instructions, success_condition} | **plan**: "Practise once before the call" plus "You've done it when…". | "This saved report has no separately assessed drill…" |
| 13 | Across-call pattern | `progress` (always `null`, F2) | **plan** footnote: "Comparable multi-call history is not supplied for this report, so no trend or improvement claim is inferred." (existing copy). | Always this copy. |
| 14 | Final verdict | `diagnosis`, `outcome`, `final_assessment` {assessment, repeat, fix_first, next_focus}, `summary`, `verdict` | **verdict**: the verdict sentence = `diagnosis.text` (with its chips), falling back to `verdict`. The lede = `summary`. An outcome line = `outcome.text` + chips, with the header chip from `outcome.kind`. A "Final verdict" block holds `assessment` (fallback `verdict`), "Fix first" = `fix_first`, and "Report verdict" = `verdict` when an overview exists and it differs. **plan** "Keep doing" = `repeat`, and "One focus" = `next_focus` when it differs from the focus card. | Legacy: verdict plus "Fix first: {improvements[0].title}" (existing). |

**Findings outside the 14 numbered points, also preserved:**
- `objection_analysis[]` and `closing_analysis[]` become **moments** items (kinds objection and closing, each with explanation) plus guest teasers. Today they render under point 14 (`dipak-overview.tsx:1408-1433`).
- `ethics_notes[]` become a **plan** neutral callout "For human review", with evidence chips and a guest teaser. Today it sits beside point 10 (`:1256-1282`).
- Top-level `business_impact` (optional) goes in the **verdict** "Final verdict" block as "Business impact: not estimated", plus the missing inputs. It is not rendered today; it is added so nothing is lost.

### 4.2 Contract field coverage

| Field | Location |
|---|---|
| `summary` | verdict lede |
| `verdict` | verdict sentence (legacy) / Final verdict block |
| `strengths`, `improvements`, `missed_opportunities`, `objection_analysis`, `closing_analysis` | moments (all evidence); verdict cards use index 0 of the first three |
| `dimensions` | skills |
| `review_status` | footer disclosure ("Draft … Not reviewed by Dipak") |
| `source_label`, `source_sha256`, `transcript_revision` | footer "About this report" details (source label shown; hashes stay non-displayed bindings, as today) |
| `report_sections` | empty in acquisition projections (`report-contract.ts:627`); legacy `CallStudio` keeps its own display |
| `preview` | locked teasers in the matching chapters, with real counts only |
| overview `version` | gates detailed rendering |
| `diagnosis`, `outcome`, `final_assessment`, `business_impact` | verdict (and plan for `repeat` and `next_focus`) |
| `strength_details`, `improvement_details`, `golden_moments`, `missed_details`, `rewatch`, `conversation_change` | moments |
| `prospect_interpretations` | prospect |
| `next_call_focus`, `practice`, `ethics_notes`, `progress` (null) | plan |
| Transcript `segments` | transcript chapter; speaker lookup for moment items |
| `claimed` | "Sign in to save" action when false (`:2573-2577`) |
| `runId` + plan | report-language chip only when bound (`:2559-2566`) |

### 4.3 The eight dimensions

- **Order:** server order (F5). Labels, observations and citations are always the server's text.
- **Tile contents:**
  - The state glyph in ink, never performance colour.
  - The label and the full observation, never truncated.
  - "n moments" only when `evidence` is present. An empty array shows "No moments"; an absent field shows nothing.
  - Inline expand (no modal) with quote chips and "Coaching reference: Doc-N · §…" for each citation. Citations are labelled as document references, not timestamps (existing copy `sales-skills.tsx:249-252`).
- **Status copy:** reused from `getReportUiCopy().factorStatus` (`report-ui-copy.ts:28-34`). The legend lists only the statuses present, including "Not assessed".

| Status | Glyph |
|---|---|
| `observed` | `lx-skill-observed` |
| `conflicted` | `lx-skill-conflicted` |
| `insufficient_evidence` | `lx-skill-insufficient` |
| `not_applicable` | `lx-skill-na` |
| `unknown` | no sprite glyph (F29): lucide `CircleHelp`, labelled "Not assessed" |

| ID | Server label (fixture) |
|---|---|
| `human_connection_trust` | Human Connection & Trust |
| `discovery_deep_understanding` | Discovery & Deep Understanding |
| `qualification` | Qualification |
| `problem_impact_desire` | Problem, Impact & Desire Clarity |
| `solution_relevance_presentation` | Solution Relevance & Presentation |
| `certainty_objection_intelligence` | Certainty & Objection Intelligence |
| `closing_decision_management` | Closing & Decision Management |
| `communication_tonality` | Communication & Tonality |

An unknown future ID still renders with a neutral icon (current behaviour, `sales-skills.tsx:94-96`).

### 4.4 Moments model (`moments-model.ts`, pure and tested)

1. **Observations.** Emit one observation for every `(finding, evidence)` pair across strengths, improvements, missed, objection and closing. Its kind is:
   - `strength`,
   - `focus` for `improvements[0]` ("Change first"),
   - `improvement` for `improvements[1..2]`,
   - `missed`, `objection` or `closing`.

   Each carries its detail fields (§4.1) and its source index.
2. **Clips.** Key each clip by `segment_id:start_ms:end_ms`, and group observations that share a key into one item.
   - The item shows the quote once, followed by **every** observation's note stacked in report order (F21 preserved).
   - The same phrase in different segments or ranges stays separate (test `report-moments.test.tsx:291`).
3. **Badges and extra items.** Attach golden-moment and rewatch badges to matching clips. Unmatched rewatch clips become `rewatch` items.
4. **Order.** Sort items by `start_ms`, then `end_ms`, then first report index. This changes today's legacy report order (D22).
5. **Filters.** All · Strengths · Change first · Other improvements · Missed openings · Objection · Closing · Rewatch. Chips with a zero count are hidden. Counts are items, not observations.
6. **Visible items.** Show the first 4, then "Show N more moments". Print renders every item regardless of filter or paging (as `report-moments.tsx:479-502`).
7. **Speaker.** Look up the segment's `speaker_id`. Display "{label} · unverified", or "Unlabelled speaker" (existing copy). YOU or PROSPECT appear only if a future contract supplies roles (B9).
8. **Counts.** The moment count equals the number of distinct clips, the same semantics as `countReportMoments` (`report-moments.tsx:85-92`).

### 4.5 Outcome chip

| `outcome.kind` | Label |
|---|---|
| `closed` | Closed |
| `follow_up` | Follow-up (D10: the date cannot be detected) |
| `no_sale` | No sale |
| `future_date` | Decision date set |
| `disqualified` | Not a fit |
| `unclear` | Outcome unclear |

`outcome.text` is always shown in the verdict chapter.

### 4.6 Processing stages, receipts and the Lens

| Confirmed fact | Row | Receipt (only when true) | Lens |
|---|---|---|---|
| `local_state` not `completed` | Recording check · active | "Checking the recording's format and duration" | `ready` (static pose) |
| `local_state === "completed"` | Recording checked · Saved | "{m:ss} long · verified and stored privately", with the duration from the measured envelope `duration_ms` when loaded, otherwise "Verified and stored privately" | — |
| C2 running / completed | Listening / Listened · Saved | "Transcript saved" (no language claim: the plan language is the report language) | `listening` while C2 is running |
| C4 running / completed | Understanding / Understood · Saved | "Evidence saved" | `understanding` |
| C5 running | Writing your coaching | — | `writing` |
| `has_report` | — | — | `done` |
| `state === "held"` or any stage `uncertain` | paused row | failure copy (§7.2) | `paused` |

- Connectors fill only between confirmed rows.
- "Next" rows read "Starts as soon as {previous} is saved".
- "Last confirmed N s ago" counts from the last successful status read, as text only.
- The 60 s "No new stage update yet. This does not tell us how much work remains." notice is kept.

### 4.7 Library, Recent calls and the "latest verdict"

| Item | Rule |
|---|---|
| Title | "Sales call · {medium date, short time}", as today (`calls-library.tsx:316-318`) |
| Meta | "About m:ss" (duration) |
| State chip | Report ready / Analysing / Needs you / Paused / Cancelled, using the existing `STATE_COPY` families (`:41-55`) plus `quoted` |
| Mini film | Plain tile for ready calls, scanline for analysing, pause glyph for held. No marker ticks (F7). |
| Latest verdict card | Not rendered (F7; decision 2). A full report is never fetched for a card. |
| Counts | None beyond loaded rows (no total). |

### 4.8 Language and script (`lightbox/script.ts`)

- **Devanagari detection.** A quote or row containing Devanagari (U+0900–U+097F, U+A8E0–U+A8FF) gets `data-script="deva"`.
- **`lang` value for Devanagari text:**
  - `hi` when the bound plan language is `hi-Deva+en`,
  - `mr` when it is `mr-Deva+en`,
  - otherwise `und-Deva`.
- **Latin text** inherits the page `lang`, because romanised Hindi cannot be identified (B11).
- **Styling.** CSS keys "no italic, no letter-spacing, line-height ≥ 1.6" on `[data-script="deva"]` as well as the tokens' `:lang(hi|mr)` rule. Upright Devanagari then never depends on a guessed language.
- **Quotes** use `--lx-font-quote`, which falls back to Noto Serif Devanagari. The Latin italic applies only to Latin quotes.

### 4.9 Time format

- One display format everywhere: `m:ss`, or `h:mm:ss` from 1 h (R10). Milliseconds leave the visible UI.
- Clips shorter than 1 s keep the note "under 1 sec".
- Accessible names include start and end times.
- Tests asserting `mm:ss.mmm` are updated in the phase that replaces the component (D23).

---

## 5. Responsive layout

The layout follows the boards (1440 desktop, 390 mobile), decision 10, and spec §2.2.

| Width | Shell | New analysis | Processing | Report |
|---|---|---|---|---|
| ≥ 1200 | Rail 248 (collapsible to 72); 64 px top bar | Returning: `minmax(0,1fr) 360px` grid. First run: one centred column (max 760) with no sidebar. | Film panel 300 px + stage list | Chapter rail 196 sticky + reading column max 880; sticky film collapses 132 → 64 |
| 900–1199 | Rail defaults to 72 (tooltip labels); top bar | One column; Recent calls below the drop zone | Lens column stacks above the stages below 1024 | Chip bar sticky under the top bar instead of the rail |
| 620–899 | No rail; mobile top bar (logo, minutes pill, avatar) with inline New · Calls · Account | One column | One column | Chip bar + docked mini-player |
| < 620 | Mobile top bar + bottom nav (76 px) | Drop zone height `clamp(240px, 46vh, 392px)`; "Choose a file" visible in the first viewport at 375×667 | One column; the Lens drops to 112 px | Chip bar + 62 px mini-player above the bottom nav |

**Small or zoomed viewports (375×667 and 200% zoom):**
- `@media (max-height: 560px)` makes the top bar and bottom nav static, not fixed, and makes the mini-player non-sticky. Fixed chrome can then never cover essential actions at 200% zoom or on short screens.
- Confirm's CTA stays in document flow, directly after consent. It is never under fixed chrome, and long pages scroll by design.

**Always:**
- Touch targets are at least 44 px.
- Focus rings use `--lx-ring-focus`.
- The skip link stays.
- One H1 per view.

---

## 6. Visual system integration

### 6.1 Tokens and colours

- `app/lightbox/tokens.css` is a byte-for-byte copy of the package file, imported once in `app/layout.tsx`. A test compares the two files.
- New Lightbox modules use `var(--lx-*)` only. A grep test fails on hex colours in `app/lightbox`, `app/shell`, `app/new-analysis`, `app/analysing`, `app/report` and `app/library`.
  - Exception: inline Lens and glyph SVG, which carry the package's `var(--lx-*, #fallback)` pairs verbatim.

### 6.2 The learner-web embed (F17)

- Learner-web imports `styles.css`, not `layout.tsx`. It therefore gets neither `tokens.css` nor the fonts.
- **Plan:** add `app/lightbox/tokens-scope.css` with the same light custom properties declared on `.xray-app`, and include it from `styles.css`. It adds no global element rules; the `:lang` rule stays in root-only `tokens.css`.
  - A parity test asserts every light `--lx-*` value in the scoped file equals `tokens.css`.
  - The `@scope` boundary test must keep passing.
- **Glyphs, the Lens and illustrations are inline React SVG** in any component that can render embedded. A `/lightbox/…` URL would not exist on the learner-web host. The `public/lightbox` copies serve the standalone app and the brief.

### 6.3 Fonts

- **Families:**
  - Bricolage Grotesque (display),
  - Plus Jakarta Sans (UI; the wiring is fixed by defining the `--lx-font-*` usage globally),
  - Newsreader (quotes, including the italic axis for Latin quotes),
  - Noto Sans Devanagari and Noto Serif Devanagari.
- **Delivery:** `@fontsource-variable` CSS imports in `layout.tsx` via `lightbox/fonts.css`. `unicode-range` loads the Devanagari subsets on demand. `font-display: swap`.
- **Packages:** Codex adds them before P1 (C1).
- **Old fonts:** Source Sans 3, Georgia, Segoe Print and Cascadia are removed from Sales Xray surfaces as each migrates. The Source Sans package is removed in P6.

### 6.4 Dark mode (decision 12)

- The dark values stay in `tokens.css`, but no code sets `data-theme="dark"`, no `prefers-color-scheme` mapping is added, and no toggle is shown.
- **P6** measures every §11 state in dark at 1440×900 and 390×844. Only then may a System / Light / Dark control be added, with a pre-paint script. The script needs Codex to confirm the edge CSP policy for an inline script, hash or nonce (B13).
- Film surfaces are dark in the light theme by design, and they override `--lx-ink`/`--lx-paper` locally so the Lens outline matches the boards (#E8EDF5 on film).

### 6.5 Motion

- Transform and opacity only. Reduced motion stops loops and turns entrances into 120 ms fades.
- Ambient loops pause when `document.hidden` or offline, via the existing `data-motion-suspended` convention.
- The develop reveal runs once, and its `filter` is removed afterwards.
- View Transitions use React's `ViewTransition`, which the installed Next 16 supports (`dist/docs/01-app/02-guides/view-transitions.md`). Without support, a 240 ms cross-fade is used.

---

## 7. Copy rules

### 7.1 Kept or adopted strings

- Board H1s, chapter titles (with "The prospect" per decision 11), stage H1s and the honesty strings in spec §7.2.
- The disclosure stays: "Draft coaching generated from this recording. Not reviewed by Dipak. Speaker labels may be wrong. Quotes are shown exactly as spoken."
- All current recovery, denial and paused messages in `acquisition-client.ts:74-103` and `ACQUISITION_PAUSED_MESSAGE` are kept verbatim unless a phase shows a truthful improvement.
- Server or provider bodies are never rendered.

### 7.2 Failure copy map (replaces spec §7.3 per decision 6)

| Condition | Title | Body (capability-true) | Action |
|---|---|---|---|
| `conversation_provider_http_*` (held) | The AI service returned an error | Your recording is saved. Analysis is paused until the AC team checks the provider connection. | Check now (poll) · Copy reference |
| Broker identity codes (`conversation_broker_service_identity_*`) | The analysis service isn't connected | Your recording is saved. Ask the AC team to refresh the provider connection before continuing. | Contact the AC team · Copy reference |
| A stage is `uncertain` | We're confirming what happened | The last step's result isn't confirmed yet. This page keeps checking and updates by itself. | Check now (poll) |
| Plan expired / `plan_stale` | Your approval expired / The plan changed | Nothing was lost. Review the plan to continue. | Review and continue (existing `freshPlan`) |
| `account_profile_required` (if the server sends it, B6) | Finish your AC profile | We need a few details before analysis can start. | Complete profile (existing gate) |
| Upload: duration over the policy limit (client pre-check) | This recording is {n} minutes long | Sales Xray takes calls up to {policy minutes} minutes. Choose a shorter recording. | Choose another file |
| Upload: unsupported type or size (client pre-check) | This file type isn't supported / This file is too large | Use {policy formats}. / Up to {policy MB} MB. | Choose another file |
| Upload: known 422 reasons (`source_*`) | The existing `AcquisitionError` messages | — | Choose another file / Try again |
| Upload: network error, abort or redirect mismatch | Checking whether your upload arrived… → then "Upload interrupted. Nothing was saved." **only after** the recovery GET returns 404 | — | Try again |
| 429 | Another call is uploading | Please try again shortly. (existing) | Try again |
| Any other held or failed code, including unknown | Analysis paused | Your recording is saved. Share this reference with the AC team: {submission ID}. | Copy reference · Contact the AC team |

- The copy never says "we'll retry automatically", "no double charge", "the team has been alerted" or "safe to close" unless a server field proves it (B5).
- A test greps `failure-copy.ts` for those phrases and asserts that no mapping is empty.

---

## 8. Phase plan

Each phase does the following in order:
1. A behaviour-preserving hook extraction for that surface.
2. The Lightbox presentation.
3. Tests adapted, not deleted.
4. The report JSON with `commit: null` and gates `not run: delegated to Codex`.

### P1: Foundations and shell

- **Prerequisite (Codex, C1):** install the four font packages. Until they exist, imports would fail typecheck and build.
- **Copies:** `app/lightbox/tokens.css`, `public/lightbox/lightbox-glyphs.svg`, `public/lightbox/illustrations/*`, and font licence texts.
- **Tokens and fonts:** `tokens-scope.css` included from `styles.css`, and `fonts.css` imported in `layout.tsx`.
- **Primitives:** `Glyph`, `Lens` (6 states, `useId` defs, reduced motion, `aria-hidden`), `FilmSurface`, `QuoteChip`, `StatusChip`, `Stepper`, `Toast`, `Segmented`, `time.ts` and `script.ts`.
- **Shell:** `LightboxShell` and its parts, behind the unchanged `AcquisitionShell` API.
  - Removed: the "Need help?" card, slogan, welcome banner and footer. Their links move to `HelpMenu`.
  - `MinutesMeter` takes an optional verified `allowance` prop, passed from the studio. It is hidden when unknown.
  - The development Settings button is kept.
- **Not in P1:** dark theme; changes to navigation semantics (P2).

### P2: New analysis, Confirm, Uploading

- **Hooks:** `useCallEntry`, `useSubmissionFlow`, `useUploadProgress`, and `UploadSessionProvider` in `layout.tsx` plus `UploadIndicator`.
- **Also:** the shared error translator in `acquisition-client.ts`.
- **Components:** `DropZone` (label, drag states, U2 pre-checks), `FileCard` (Preview, Change), `LanguageSegment`, `ConsentRow` + `UploadCheck`, `AnalyseButton` (real-bytes bar, Cancel), `NextSteps`, `TrustRow`, `RecentCalls`.
- **Behaviour:**
  - The quiet first run.
  - No full navigation during a live upload.
  - The pending vs promoted selector (U1).
  - `SalesXrayFixturePreview` upload states point at the new components.
- **Bugs:**
  - U1.
  - U2 (client pre-checks and reason copy; server codes are B4).
  - U4.
  - A4: a mid-upload 401 opens the in-page sign-in with the file preserved, then the recovery read before any replay.

### P3: Analysing and edge states

- **Hooks:** `usePlanApproval`, `useStatusPolling`, `useOnlineVisible`.
- **Polling (U3):**
  - Base 3 s. After failures: 6 → 12 → 24 → 48 → 60 s cap.
  - Paused while hidden; restarts immediately on `online`, `visibilitychange` (visible) or `focus`.
  - Transient errors never stop it permanently.
  - 401 → sign-in (session), 403/404 → the existing unavailable or deletion path, 409 → slow retry with copy.
  - Held states keep slow polling (60 s).
- **Components:** `AnalysingPanel`, `StageList`, `MeasuredStrip`, `OfflinePill`, `NeedsOkCard` (manual controls disabled while auto-start is in flight; no flash), `PausedCard` + `failure-copy.ts`.
- **Also:** the dispatch-confirmed "You can close this tab" rule, and the processing indicator in the shell.
- **Bugs:**
  - U3.
  - U5 (§7.2).
  - U6 (profile prompt when the hold is present: `Job.executionHold` is already parsed at `report-contract.ts:824-840`; acquisition progress needs B6).
  - U8.

### P4: Report and player

- **Hook:** `usePlayback`.
- **Components:** `playhead-store`, `CallFilm` (desktop sticky, mobile docked), `ReportView` with both modes, `ChapterRail`/`ChipBar`/`ReportTabs`, and all chapter components (§4).
- **Also:**
  - `DevelopReveal` plus the report-ready `Toast`.
  - Legacy, guest and empty shapes.
  - `ReportFooter` with the delete confirmation (the existing `erase` flow) and "About this report".
  - Rename stays hidden unless B1 lands.
- **Bugs:**
  - R1 (keep and test).
  - R2 (every action works in both modes).
  - R3 (a single overview; no duplicate chapter render).
  - R4.
  - R6.
  - R7.
  - R8.
  - R10.

### P5: Library, auth and profile

- **Library:** `CallsList`/`CallRow`/`MiniFilm` with `use-library-pages`, which keeps loaded pages and scroll across back navigation (A9) using a module-level cache keyed by account context. A 401 re-checks the session and offers sign-in with `returnTo=/calls`.
- **Auth and profile:** restyle `AccountAuth`, `AccountProfile`, the preloader and the standalone chooser with the split film layout.
- **Bugs (frontend parts):**
  - A1 (closable sign-in).
  - A2 (client-validated `returnTo`, same-origin path allowlist).
  - A3 (visible OTP cooldown, reset on email change).
  - A5 (lockout copy).
  - A6 (12 s preloader timeout, then delayed and error states).
  - A7 (popup-closed detection, no-opener redirect, in-app browser guidance).
  - A8 (profile 403 → workspace chooser).
  - A9.
- **Optional:** an Account view that reuses `AccountProfile` in edit mode, only if Codex agrees (§13, Q4).

### P6: Responsive, keyboard, performance and proof

- **Checks:**
  - Visual QA against the boards across the spec §11 matrix.
  - Keyboard-only journey.
  - 200% zoom.
  - 375×667.
  - Fonts ≤ 180 KB for an English session.
  - CLS < 0.05.
  - No long tasks > 100 ms during playback.
- **Dark mode:** the contrast audit. The toggle and pre-paint script are added only if the audit passes and B13 is answered.
- **Cleanup:**
  - Delete the replaced modules and orphans (after Codex confirmation).
  - Remove legacy CSS and the Source Sans package.
  - Restyle `CallStudio` with tokens.
- **Codex:** the compiled account-required browser journey, the screenshots and evidence README, and the final update of this plan.

---

## 9. Test plan

### 9.1 Existing suites (F28)

Existing suites are adapted to the new DOM with role and label queries; coverage is not deleted.

| Suite | Adapt in | Intent that must survive |
|---|---|---|
| `acquisition-studio.test.tsx` (58) | P2–P4 | Entry, restore, deletion-only, claim, upload headers, recovery read, plan approval, polling, report composition, embedded variant |
| `acquisition-shell.test.tsx` | P1 | Navigation, landmarks, sign-in affordances. Hero and slogan assertions become absence checks. |
| `acquisition-file-stage`, `acquisition-dashboard-panels`, `acquisition-processing-panel`, `processing-visual`, `processing-status-copy` | P2–P3 | Their intents move to the new component tests before the old files are deleted. |
| `report-modes.test.tsx` (11) | P4 | Six sections in reading, tabs, keyboard tabs, bound-call guard, bookmark scroll, and switching modes without losing the section. Plus alias tests. |
| `dipak-overview.test.tsx` (23), `report-moments.test.tsx` (13), `sales-skills`, `prospect-snapshot`, `next-call-plan`, `report-transcript` | P4 | Every assertion about supplied data, empty copy, no scores and guest counts carries over to the chapter tests. Ordering assertions change per D22, with Codex approval. The time format changes per D23. |
| `call-audio-dock`, `source-waveform` | P4 | Parser and bin tests move to `report/waveform.test.ts`. The player tests move to `call-film.test.tsx`. |
| `calls-library.test.tsx`, `acquisition-library.test.ts` | P5 | Pagination, cursor loop and duplicate guards, open-call behaviour |
| `standalone-studio`, `account-auth`, `account-profile`, `profile-menu`, `login`, `auth/complete` | P5 | Gates, identity, sign-out. Plus A1–A8. |
| `styles.integration.test.ts` | every phase | `@scope` boundary; learner-web embed |
| `workbench.test.tsx`, `processing-experience` coverage | P6 | Deleted with the dead modules only if Codex confirms. |

### 9.2 New tests by phase

- **P1:**
  - Tokens are byte-equal to the package file, and `tokens-scope.css` matches its light values.
  - Glyph paths match the sprite.
  - Lens: 6 states, unique IDs across two instances, `aria-hidden`, reduced motion freezes.
  - `FilmSurface` variants.
  - `QuoteChip` accessible name "Play {kind} moment at m:ss: {quote}", no clamp class, and `lang`/`data-script`.
  - `time.ts` and `script.ts` units.
  - Shell: landmarks, one skip link, no "Need help?" or slogan, `HelpMenu` links, the meter only with an allowance, the bottom nav, the development Settings button only with its provider.
  - The no-hex grep.
- **P2:**
  - `file-checks` (extension, MIME, size, and duration with a mocked `HTMLAudioElement`; unknown duration allowed with a note).
  - `useUploadProgress` against an XHR mock: exact method, URL and headers; progress; abort; `responseURL` mismatch → unknown; error-translator parity with `acquisition()`; recovery read before replay.
  - U1: nothing is saved before binding, and the phantom selector is cleared on 404.
  - U4: consent survives a dependency change, and there is no manual-approval flash.
  - A4.
  - `DropZone` keyboard and drag.
  - `LanguageSegment` arrow keys.
  - `ConsentRow` real checkbox.
  - `RecentCalls` loading, error, empty and list.
  - The quiet first run: no Recent panel, sample card or empty tables.
  - No full navigation while an upload is live; the `beforeunload` guard.
  - `UploadIndicator` persists across a simulated route change with the provider mounted.
- **P3:**
  - The polling schedule with fake timers (backoff, cap, hidden pause, restart on online, visible or focus, never permanent on transient errors).
  - 401/403/404/409 branches.
  - Failure copy: never empty, forbidden-phrase grep, and the reference always present.
  - The Lens derives only from confirmed stages.
  - The "Last confirmed" counter resets only on successful reads.
  - The close-tab message is gated.
  - U6 (if B6), U8.
  - "Check now" is distinct from paid-analysis actions.
- **P4:**
  - Chapter mapping against `dipak-overview.json` and the synthetic report: each `data-dipak-point` 01–14 is present in its chapter per §4.1.
  - All 8 dimension IDs with label, status copy, observation and citations.
  - Every `(finding, evidence)` pair appears exactly once, and shared clips keep every note in report order.
  - Objection, closing and ethics findings are present.
  - No ellipsis or clamp on takeaways, explanations or quotes.
  - The no-score grep over rendered text (`/\b\d+(\.\d+)?\s*(\/\s*10|%|points?)\b/`, plus the "score"/"grade"/"rating" words, except the honesty strings).
  - `lang`/`data-script` on every quote and transcript row, and the Devanagari no-italic CSS check.
  - Modes: `view=reading|tabs|junk`, the section aliases and the bound-call guard.
  - Player:
    - R1 clip bound and keep listening.
    - Marker keyboard navigation.
    - R6 render-count test (a chapter does not re-render on playhead ticks).
    - R7 flat lane with a playhead.
    - R8 mini-player play.
    - R4 no modal dialogs.
    - R10 sheet history.
  - Transcript segment sync with no word highlight.
  - Guest teasers use real counts. Legacy (no overview), empty findings and hidden empty chapters are handled.
  - Rename is absent without the API.
- **P5:** A1–A9 units, and library back navigation that keeps pages and scroll.
- **P6:** Codex runs the compiled browser journey and axe where available.

---

## 10. Deviations from the boards and spec

| # | Deviation | Follows |
|---|---|---|
| D1 | The Reading/Tabs control is kept; the spec removes it. | Decision 1 |
| D2 | First run is one quiet column. There is no Recent calls, Example or latest-verdict panel, and no "No calls yet" card on Home. The H1 uses the H1 size, not display. | Decisions 2 and 10 |
| D3 | Recent calls have no moment strip and no language meta. Titles are "Sales call · date". | F7; decision 11 |
| D4 | The "Your latest verdict" card is not rendered. | F7; spec §12.2 forbids fetching reports for it |
| D5 | No call count in the rail. | F7 |
| D6 | Library: no search, no verdict line, no marker ticks. Filters apply to loaded rows without totals. No sort control (server order only). | F7 |
| D7 | No "While you wait" card. "You can close this tab" appears only after dispatch is confirmed. | Decisions 4 and 10 |
| D8 | The failure copy map is replaced (§7.2). | Decision 6 |
| D9 | Stage receipts use only real facts. There is no "Transcript saved · Hindi + English". | Decision 5; F8 |
| D10 | The outcome `follow_up` label is "Follow-up". The report header has no date chip unless a date is known. | F8; the contract has no date flag |
| D11 | Speakers show the raw label plus "unverified", not YOU or PROSPECT. | Decision 7; F6 |
| D12 | "Say it like this" becomes "Try this" and shows `replacement_behavior` verbatim. | The contract has no phrase field; spec §3.6.7 says never invent |
| D13 | "Still unknown" is the existing generic boundary copy, with no invented list. | Decision 8; the contract has no unknowns field |
| D14 | The prospect chapter H2 is "The prospect". | Decision 11 (overrides spec §12.4 heading) |
| D15 | Quote chips and evidence text wrap instead of clamping. | Decision 7 |
| D16 | No theme control; the Report-Dark board is deferred to the P6 audit. | Decision 12 |
| D17 | No rename affordance. | Decision 11; no API (B1) |
| D18 | Consent wording is unchanged; the board adds "I have permission to upload". | The consent is bound to `policy_sha256`; legal wording needs the owner |
| D19 | Help lives in a `?` popover that includes the former footer links. | Decision 10 |
| D20 | The development Settings entry is kept where its provider exists. | Decision 9 |
| D21 | The mobile chip bar includes Transcript, and moments filters add "Other improvements" and "Rewatch". | Decision 8 (no hidden chapter or data) |
| D22 | Moments are sorted by time, which changes the legacy report-order assertion. Shared clips keep report order internally. | Spec §3.6.4; decision 8 (all observations kept). Needs Codex approval of the test change. |
| D23 | The time format drops milliseconds. | Spec §0.3; R10 |
| D24 | `conversation_change` sits in Moments, not Next call. | It is evidence-linked conversation flow; the spec says "may"; decision 8 |
| D25 | Skills keep server order, and the legend includes "Not assessed". | F4/F5 |

---

## 11. Missing API capabilities: backend requests for Codex

| # | Request |
|---|---|
| B1 | A persisted `display_title` (null falls back to the original filename) returned in submission, progress and library payloads, plus the owner-authorised audited `PATCH` from spec §12.1. The UI shows rename only when this exists. |
| B2 | `created_at` (and `duration_seconds`) on the submission/progress payload, so the report header can show the date without a library read. |
| B3 | Library rows for ready calls: the latest verdict sentence, the Change-first focus, the report language, marker positions (`kind`, `start_ms`) for mini-film ticks, a total count, and server-side filter/search. |
| B4 | Stable upload rejection reasons, instead of matching detail strings (`acquisition-client.ts:168-189`): `source_duration_exceeded` with the measured `duration_ms`, `source_format_unsupported`, `source_too_large` (U2). |
| B5 | Capability fields before the UI may say more: `retry_scheduled` / `retry_after`, `support_notified`, charge or settlement state, a user-facing reference ID on held/failed progress (otherwise the submission ID is the reference), and a server-authorized "retry analysis" action (B2 in the bug plan). |
| B6 | Confirm whether acquisition progress (`GET /submissions/{id}`) sends `execution_hold`. If it does, the UI adds an optional parse (U6). |
| B7 | `Retry-After` on 429/503 (upload capacity), so client retries honour it. |
| B8 | Optional word-level timestamps. Until they exist, sync is by segment. |
| B9 | Optional speaker role attribution with a confidence value. Until it exists, labels stay raw and unverified. |
| B10 | Optional explicit "suggested phrase" field for "Say it like this". |
| B11 | Optional per-segment or per-evidence language, for accurate `lang` on quotes. |
| B12 | From the brief: the A2 server `returnTo` allowlist, and the A5 server lockout state. |
| B13 | Confirm that the source PUT never redirects (XHR follows redirects, K2), the edge CSP for self-hosted fonts, and whether an inline pre-paint theme script (hash or nonce) is allowed. |

---

## 12. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| K1 | The learner-web embed breaks: its tests mount `AcquisitionStudio` and it imports `styles.css`. | Keep the export, props and `@scope`. Scoped tokens and inline SVG (§6.2). Codex runs learner-web tests every phase (C3). |
| K2 | XHR follows redirects (a 307/308 would resend the body). | Server confirmation (B13). The `responseURL` check → unknown outcome → recovery read. Same-origin URL only. |
| K3 | `acquisition-studio.test.tsx` is tightly coupled to text and DOM. | Behaviour-preserving extraction first. Adapt to role and label queries. Codex reviews test diffs for weakened intent. |
| K4 | Upload continuity across routes needs a root-layout provider. The embed has none. | Graceful local fallback; background continuity is never claimed without the provider. |
| K5 | Changing the moments order and time format rewrites assertions. | D22 and D23 are explicit and approved by Codex before P4. Coverage of the data is kept, not reduced. |
| K6 | The font weight budget (≤ 180 KB for English). | Variable subsets; Devanagari by `unicode-range`; measured in P6. |
| K7 | Performance on 60-minute calls (≤ 20 000 segments, 1200 envelope points). | A windowed transcript, memoised bins, the playhead store, clustered markers. |
| K8 | Dark tokens without verification. | Not applied until P6 (decision 12). |
| K9 | The Lens and glyph assets have no closing or unknown glyph (F29). | A lucide fallback with a distinct shape and a text label. |
| K10 | A theme or other script blocked by the edge CSP. | Deferred with the theme; B13. |
| K11 | The spec (§12.3, §12.4, §7.3, §3.4) contradicts the integration decisions. | Decisions win (§0); deviations are listed in §10. |

---

## 13. Open questions for Codex and the owner

- **Q1 · Bare `/` restore.** Today `/` restores the last saved call from local storage.
  - Recommendation: keep auto-restore only for an upload or analysis started in this browser that is still in progress, and otherwise open clean intake with the call reachable from Calls and Recent calls. That reads decision 4 ("a held call remains in Calls").
  - Default: the current behaviour until Codex confirms.
- **Q2 · Sample link.** Should P4 add a production fictional sample route, clearly labelled, without audio, and built from the synthetic fixture? Until then, there is no sample link (F23).
- **Q3 · Test changes.** Approve D22 (time-sorted moments) and D23 (no milliseconds) before P4.
- **Q4 · Account page.** Should P5 add an Account view (profile edit via `AccountProfile`, plus sign-out)? Today "Account" goes to `/calls` or sign-in.

---

## 14. Phase status log

| Phase | Status | Notes |
|---|---|---|
| P0 | Done (plan only) | This file. No product source changed. Gates were not run (docs only; delegated to Codex). |
| P1–P6 | Not started | P1 needs C1 (font packages) first. |

### Codex requests carried forward

- **C1 (before P1):** add the pinned `@fontsource-variable/bricolage-grotesque`, `@fontsource-variable/newsreader`, `@fontsource-variable/noto-sans-devanagari` and `@fontsource-variable/noto-serif-devanagari` to `@ac/sales-xray-web`, update the lockfile, and confirm OFL licences.
- **C2 (every phase):** run `pnpm --filter @ac/sales-xray-web typecheck`, `lint`, `test`, `build`, and the repository formatter check on the changed files.
- **C3 (every phase from P1):** run the learner-web test suite, because it embeds `AcquisitionStudio` and imports `styles.css`.
- **C4:** review and answer B1–B13 and Q1–Q4. Tell the next phase which backend requests have landed.
- **C5 (P6):** the compiled account-required browser journey (no provider calls), visual evidence and release.

## 15. Codex review of P0 — 25 September 2026

Accepted as a source-linked implementation map, subject to the corrections below. This section supersedes conflicting proposals above; it preserves the original P0 review history. P0 completed on the exact requested Opus model, with file tools only and no denied tool calls. Product tests were not run for the plan. The four new OFL font packages are installed at 5.3.0 with exact lockfile integrities and lifecycle scripts disabled; their CSS entry is `wght.css`.

1. **Tokens:** preserve the design-package original, but correct the app token derivative: light muted-2 `#646D7F`; dedicated strength text ink `#06736F`; dark closing ink `#BFD0FF`. Do not assert that an intentionally corrected derivative is byte-identical. Test documented differences and the real foreground/background contrast pairs (minimum 4.5 for small text), including alpha fills. Keep token scope isolated for the learner embed.
2. **Evidence coverage:** look up detail records by `finding_index`, not detail-array position. The next-call replacement behavior belongs to the focus's referenced improvement. Do not discard findings with empty evidence. Clip grouping must preserve distinct quotes, every observation, and nested evidence such as what-happened/prospect-signal/closer-response. Reading view displays all report moments by default; it must not hide all but four behind Show more. Transcript windowing may be used for performance with accessible navigation. Tabs may offer explicit filters without silently dropping data.
3. **Language:** requested report language is not proof of the spoken/source language. Devanagari source quotes use an unknown-language script tag until actual source-language metadata is present. Generated report prose may use the bound report language. Never relabel a seller example as a prospect assertion, and never derive word timings from character counts.
4. **Theme:** build and test System/Light/Dark infrastructure during P1, with browser-safe pre-paint initialization and local preference. Validate it in every later phase. The final release still requires all states to pass the P6 theme matrix; deferring all theme implementation until the last phase would hide defects. Root inspected the current edge CSP: self-hosted fonts and the current inline-script policy are allowed. Preserve the actual policy; do not weaken CSP. Handle blocked storage and embed isolation.
5. **Navigation:** Q1 approved: bare intake must not trap users in a previous held or completed call. Keep active work in the persistent indicator and Calls; explicit call URLs restore that call. Q3 approved: chronological moments and readable times, preserving original millisecond seek bounds. Q4 approved: implement the real shared account profile view using existing authorized profile endpoints. Q2: no production sample route is needed for this release; keep first use quiet.
6. **Upload:** XHR redirect parity is not approved by this plan. A responseURL check happens after a redirected body could be sent. Before P2 changes transport, root must verify or implement an equivalent enforced destination boundary; do not silently relax `redirect:error`. Keep file/consent and status reconciliation behavior. Cancelling or navigating must not replay a paid request.
7. **Scope:** P1 implements foundations, theme and shell only; it must not alter upload, report, auth, permission or provider behavior. Preserve the unchanged AcquisitionShell/AcquisitionStudio embedding APIs. Prefer existing accessible controls over needless new primitives, and do not delete behavior tests. Subsequent phases must use the corrected mapping here.

Source review also found no evidence for automatic-retry or no-double-charge promises in the current runtime. Keep those claims conditional on actual backend capability. The separate provider benchmark is active in parallel and does not make the UI candidate or any report production-verified.
