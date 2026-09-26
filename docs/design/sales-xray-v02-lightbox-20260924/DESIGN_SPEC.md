# Sales Xray v0.2 — "Lightbox" UI/UX specification

- **Date:** 24 September 2026
- **Author:** Claude Code (Opus 5.5), commissioned by Suyash (founder)
- **Status:** approved direction for the v0.2 production release. Implementation by Claude Code, directed by Codex (see `CODEX_UI_HANDOFF.md`).
- **Visual prototype (canvas):** https://claude.ai/artifact/5TYWjU7XhUd3gVGV2HzLKS
  - Private to Suyash until shared. The same source is in `prototype/canvas/project/*.dc.html` in this folder.
- **Assets:** `assets/lens/*.svg` (character states), `assets/glyphs/lightbox-glyphs.svg` (semantic glyph sprite), `assets/illustrations/*.svg`
- **Tokens:** `tokens.css`
- **Companion bug handoff:** `docs/evidence/sales-xray-bug-handoff-20260924/HANDOFF.md`. Its U/R/A bug IDs are referenced below.

The prototype boards are the visual source of truth for **look, hierarchy and copy**. This document is the source of truth for **behaviour, data mapping and constraints**. Where they disagree, this document wins; flag the conflict in the PR.

---

## 0. Why this redesign

What the current v0.2 UI gets wrong (observed on the integration branch `7ff3581f` and in `docs/evidence/sales-xray-v02-20260923/*.png`):

1. **Type doesn't actually apply.**
   - `@fontsource-variable/plus-jakarta-sans` is imported, but `--font-sans` / `--font-plus-jakarta` are never defined, so the shell renders in **Segoe UI**. `synthetic-report-visual-qa-20260924.md` measured this.
   - The report uses Source Sans 3; legacy headings use Georgia.
   - The result is three unrelated voices.
2. **No token system.** Colour lives in about 12 CSS modules with near-duplicate teals (`#087e79`, `#087b79`, `#007d79`, `#08776e`, `#0f766e`…), four blues and five oranges. There is no dark mode.
3. **Card-in-card nesting and developer leakage.** The report shows `00:31.000–00:35.000 · Source segment synthetic-respect`, which is internal IDs and milliseconds.
4. **Two competing report modes** (Reading / Tabbed), a 14-point "review map" behind modal dialogs, and dialogs that lock the audio (R4). Several buttons do nothing (R2).
5. **Clutter in the shell:** "Need help?" card, handwritten slogan, "Better conversations. Win more deals" flourish, dashboard panels ("Invite your team", "Sample insight", "Recent activity") that compete with the one thing a user came to do.
6. **Progress feels broken, even when it isn't.** The frontend bugs are U1–U8. The visual language also doesn't separate "confirmed" from "waiting", so honest status reads as a stall.

The fix is not a reskin. It is one coherent system: **Lightbox**.

---

## 1. Concept: Lightbox

> A calm light table for sales calls. **The call is the film; the moments light up; the coaching sits in the margin.**

- **The film:** a dark, precise surface (`--lx-film`) used only where the call itself is present: the drop zone, the analysing panel, the call player and the one-focus card. It carries a faint 32px grid (a light table) and a teal glow.
- **The paper:** a warm, quiet reading surface (`--lx-paper`) for everything a person reads.
- **The Lens:** one small character, an aperture with a scanning "pupil", that shows the *real* state of the system. It is never decorative filler. Six states: ready, listening, understanding, writing, done, paused (`assets/lens/`).
- **The margin note:** coaching is laid out like an annotated manuscript. The quote is on the page, set in a serif in the original words. The note is beside or below it. "Try this next time" is highlighted and copyable.

### 1.1 Principles (use them to settle design disputes)

| Principle | Means | Never |
|---|---|---|
| **Evidence first** | Every claim carries a playable quote (time + words). | A claim without a source moment; paraphrased quotes. |
| **Truthful progress** | Only server-confirmed steps light up; show "last confirmed N s ago". | Percent bars, ETAs or timers that advance a stage (the upload bar is real bytes only). |
| **One focus** | Exactly one "Change first" per report, visually dominant. | Five equal-weight takeaways. |
| **Your words, untouched** | Quotes shown in the spoken language and script, marked with `lang`. | Translating or transliterating quotes; italicising Devanagari. |
| **Calm, then alive** | Still at rest; motion answers a person or a real event. | Ambient motion on reading surfaces; motion that implies progress. |

### 1.2 Hard constraints (from code and policy; non-negotiable)

- **No numeric scores, grades, ratings or percentages** about performance, anywhere (`numeric_publication === false`, `official_score: false`, AC-SVAL). Skill status is qualitative: Evidence found / Mixed / Need more evidence / Not relevant / Not assessed.
- **Waveforms are measured only.** Render the envelope from `/submissions/{id}/waveform`. If it is unavailable, show a flat line **with** a visible playhead and markers (fixes R7). Never draw a synthetic waveform for a real call. Decorative waveform icons in illustrations are fine.
- **No fabricated progress or ETA** (`processing-state.ts:29`, `ac-preloader.js`).
  - Scanline and lens motion are *activity*, never *progress*. They loop and must not map to completion.
- **Inferences are labelled:** prospect interpretations and `conversation_change` render with the dashed "Possible reading · not confirmed" style.
- **Disclosure stays visible:** "Draft coaching generated from this recording. Not reviewed by Dipak. Speaker labels may be wrong."
- **Privacy:** never echo server or provider error bodies. Never put personal data in URLs beyond the existing opaque `?call=<uuid>`.
- **Fonts self-hosted** (the CSP blocks third-party font hosts): use `@fontsource-variable/*` packages (§4.2).

---

## 2. Information architecture

### 2.1 Sitemap and routes (URLs unchanged; behaviour refined)

```
/                     New analysis (drop → confirm → analyse) · also restores ?call=<uuid>
/?call=<uuid>         That call: processing view OR report view (same route, state-driven)
/?call=<uuid>&section=<chapter>   Deep link to a report chapter (verdict|moments|skills|prospect|plan|transcript)
/calls                Calls library
/login                Sign in (honours validated returnTo; see A2)
/auth/complete        Google completion (redirects to returnTo when there is no opener; see A7)
```

- **Remove `view=reading|tabs`.** There is one reading experience. Accept the old parameter and ignore it, so old links still open.
- **Map old `section` values** to the new chapter IDs (§6.5.1).

### 2.2 Navigation model

**Desktop and tablet (≥ 900px): left rail, 248px, collapsible to 72px.**

| Order | Item | Notes |
|---|---|---|
| 1 | Brand lockup | AC symbol + "Sales ✕ray" wordmark (teal-gradient crossed X) + "BY AUTHORITY CLOSERS" |
| 2 | **New analysis** | Primary ink button |
| 3 | **Calls** | With count |
| 4 | **Account** | |
| — | Spacer | |
| 5 | **Trial minutes** meter | Real allowance only, e.g. "42 of 60 left" |
| 6 | Account row | Avatar initials, name, "AC account" / "Guest" |

- Remove: "Settings" (until it has content), "Need help?" card, slogans.
- Help moves to a `?` icon button in the top bar, which opens the existing help links.

**Top bar (64px):**
- Breadcrumb: "Calls / {call title}".
- Right side: contextual actions (Download, ⋯) and the trust chip "Private to your account" on New analysis.

**Mobile (< 900px; bottom nav appears below 620px as today):**
- Top bar: logo, minutes pill, avatar.
- Bottom nav with **New · Calls · Account** (76px).
- In a report, a **docked mini-player** sits above the bottom nav (§5.3).

### 2.3 The core journey as one continuous surface

```
Drop  →  Confirm  →  Uploading (button becomes real-bytes bar)  →  Analysing (film panel, lens, confirmed steps)
      →  [Needs your OK]  →  Report "develops"  →  Calls
                 ↘ Paused (reason + one action + reference)     ↘ Offline (auto-resume)
```

- A **stepper** (Choose call · Confirm · Analyse · Report) sits at the top of the New analysis surface.
- Transitions use the View Transitions API where supported: the CTA morphs into the upload bar, then into the first confirmed step. Otherwise use a cross-fade (240ms).

---

## 3. Screen specs

Board names refer to the canvas. "Data" names existing contract fields; no backend changes are required for v0.2 UI.

### 3.1 New analysis (board: Home / Mobile-Upload)

**Layout (desktop):** `grid-template-columns: minmax(0,1fr) 360px; gap: 32px`, padding `36px 48px`.

- **Left column:**
  - eyebrow "NEW ANALYSIS"
  - H1 "Drop a sales call. See what really happened." (`--lx-text-display`)
  - Lede (16px, `--lx-muted`)
  - Stepper
  - Lightbox drop zone
  - Trust row with three items:
    - Private by default
    - Your words, untouched
    - Coaching, not a score
- **Right column:**
  - **Recent calls:** the 3 latest, each with a status chip. Ready calls also get a mini "moment strip" of kind-coloured ticks at real marker positions, taken from the report evidence.
  - **Example card:** a serif example verdict clearly labelled "EXAMPLE" and three kind bullets.
  - **First-run users:** Recent calls is replaced by the empty state (States board, "No calls yet").

**Lightbox drop zone:**
- Height 392px, `--lx-radius-xl`, film background with grid and a radial glow, dashed `rgba(45,212,191,.38)` border, and four crop-mark corners.
- A small "LIGHTBOX · READY" label and the idle Lens (112px).
- Title "Drop your call recording here". Sub-line "We check it privately before anything is analysed."
- "Choose a file" white button, and limit chips: formats · 32 MB · 60 minutes (values from `upload-policy`, never hard-coded).
- A slow scanline sweeps every 7s. This is ambient on the film only, and allowed because it isn't a reading surface.
- **Drag-over:** the border goes solid glow, the background brightens by 6%, the scanline speeds up to one quick pass, and the Lens pupil widens.
- **Drop:** the file card rises from the drop point (240ms, `--lx-ease-move`).
- The whole zone is a `<label>` for the file input: keyboard focusable, with Enter/Space to open.

**Client pre-checks (fixes U2):**
1. Extension and MIME against the policy.
2. Size.
3. Duration via `HTMLAudioElement` `loadedmetadata`, without decoding.
- **Over-limit duration** blocks with the States board copy: "This recording is 72 minutes long…".
- **Unknown duration** is allowed, with a note. The server remains authoritative.

### 3.2 Confirm (board: Confirm)

- H1 "Looks good. One last check."
- **File card:** film tile + name (ellipsis) + "18.2 MB · about 18 min · stays on this device until you confirm".
  - Actions: **Preview** (plays the local file through an object URL) and **Change**.
- **Report language** as a segmented radio group: English / Hindi + English / Marathi + English. The thumb slides 240ms.
  - Helper: "Coaching is written in your choice. Quotes from the call always stay exactly as spoken."
- **Consent row:** a large hit area with a custom checkbox whose tick draws 450ms. Real `<input type="checkbox">`, visually hidden.
- **Turnstile challenge**, when required: render inline in the consent area, styled container, with timeout and retry states.
- **CTA "Analyse my call":** 58px, teal, with a sheen every 3.2s *only while enabled and idle*.
  - Beneath it: "This call is about 18 minutes. You have 42 trial minutes left." Allowance is real; duration comes from metadata and is labelled "about".
- **Right rail:** "What happens next" (Listen · Understand · Coach) and the honesty line "We never show a fake timer. Each step lights up only when it is confirmed."

### 3.3 Uploading (States board, first card)

- The CTA **becomes** the upload bar: same box, a striped teal fill whose width is the real `bytesSent / total`.
  - Use `XMLHttpRequest.upload.onprogress`; `fetch` has no upload progress.
  - Label: "Uploading privately · 12.4 of 18.2 MB".
  - Secondary action: "Cancel upload" (aborts the XHR).
- If the network drops, see U1: nothing is "saved" until the server confirms. Copy: "Upload interrupted — nothing was saved. Try again."

### 3.4 Analysing (board: Processing / Mobile-Processing)

- **Header:** eyebrow "STEP 3 OF 3 · ANALYSING", H1 per stage, and a right-aligned `role="status"` "Last confirmed update N seconds ago".
  - H1 per stage: listening → "Listening to your call"; understanding → "Reading between the lines…"; writing → "Writing your coaching".
  - The dots animate; they stop under reduced motion.
- **Film panel:** 300px left column with the stage-matched Lens (176px) and caption; stage list on the right.
- **Stage list rows:**
  - **Completed:** filled glow check, a *receipt* line ("Transcript saved · Hindi + English", "18:42 long · verified and stored privately"), and a "Saved" tag.
  - **Active:** tinted row with a pulsing ring and "Working now. This step is confirmed by the server, not estimated."
  - **Next:** dashed circle and "Starts as soon as understanding is saved".
  - Connectors fill only between confirmed stages.
- **Measured waveform strip** at the bottom of the panel: the real envelope (C1 measurement exists after upload) with a looping scanline, labelled "YOUR RECORDING · MEASURED". Omit the strip if no envelope is available.
- **Below the panel:**
  - "You can close this tab — we keep working. Your report will appear in Calls." with a **Go to Calls** button.
  - A light "While you wait" card.
- **Stage mapping:**

| Server | Label | Lens |
|---|---|---|
| upload / C1 | Recording checked | — |
| C2 | Listening | `listening` |
| C4 | Understanding | `understanding` |
| C5 | Writing your coaching | `writing` |

- **Polling:** follow U3. Back off on failures (3 → 6 → 12 → … 60s), restart on `online` / `visibilitychange` / `focus`, pause while hidden, and never stop permanently for transient errors.
- **Offline:** show the dark offline pill (States board): "You're offline. We'll check again the moment you're back. Nothing is lost."

### 3.5 Needs your OK / Paused / Errors (board: States)

- **Needs your OK:** a clear card: "Ready to start the analysis · uses 26 of your 42 trial minutes" and **Start analysis**. Fixes U4: no flashing, and manual controls are disabled while auto-start is in flight.
- **Paused:** the paused Lens plus a **specific** reason, what happens next, one action and a copyable reference.
  - Map every failure code (see §7.3 and U5). An empty message is a bug.
  - Keep polling slowly while held, so backend or admin recovery appears without a refresh.
- **Can't use this file:** danger edge, the precise reason (duration, format, size) and "Choose another file".
- **Account/profile hold** (U6): "Complete your AC profile to continue", linking to the profile step.

### 3.6 Report — "the debrief" (board: Report / Mobile-Report)

The heart of the product. It is one continuous reading page. Order:

0. **Header**
   - Eyebrow "CALL REPORT · DRAFT COACHING" and H1 = call title (the filename without extension, editable later).
   - Meta chips: date, duration, report language, and outcome.
   - Outcome chip comes from `overview.outcome.kind`:

| `outcome.kind` | Label |
|---|---|
| `closed` | Closed |
| `follow_up` | Follow-up agreed / Follow-up, no date set (when no date is present) |
| `no_sale` | No sale |
| `future_date` | Decision date set |
| `disqualified` | Not a fit |
| `unclear` | Outcome unclear |

   - Actions: **Download** (existing DOCX export) and ⋯ (Delete, Copy link).

1. **The film (call player)** — see §5.3. It is sticky: it collapses to a 64px bar after scrolling past it on desktop, and becomes the docked mini-player on mobile.

2. **Chapter rail** (desktop, 196px, sticky)
   - Chapters: The verdict · Moments (n) · Sales skills (8) · The prospect · Your next call · Transcript.
   - The active chapter is a raised pill. Chapters read past get a teal tick (local UI state only; not persisted, not "progress").
   - The disclosure sits under the rail.
   - Mobile: a horizontal chip bar, sticky under the top bar.

3. **The verdict**
   - Eyebrow, then the verdict sentence in `--lx-text-verdict` serif. Data: `overview.diagnosis`, falling back to `verdict`.
   - Three cards:
     - **Keep doing:** `strengths[0]` / `strength_details[0]`.
     - **Change first · your one focus:** `next_call_focus` → `improvements[0]` / `improvement_details[0]` (`improvement_index 0`). Amber edge and warm gradient; visually dominant.
     - **Missed opening:** `missed_opportunities[0]` / `missed_details[0]`.
   - Each card has a title and a **quote chip**: ▶ mm:ss + serif quote, `lang`-tagged; clicking plays that clip.
   - If a slot has no supported finding, show the existing honest empty copy (e.g. "No supported strength recorded"), never a filler.

4. **Moments that mattered** — "Replay the call, with notes in the margin"
   - **Filter chips:** All · Strengths · Change first · Missed openings · Objection · Closing, with counts. Hide chips whose count is 0.
   - **Timeline list,** sorted by `start_ms`. Each item has:
     - A left 92px column: time pill (kind-coloured; shows an equaliser while playing) and a vertical connector.
     - Kind label with glyph; rewatch badge from `rewatch.purpose`: `must_watch` → "Must rewatch", `watch` → "Worth a watch", `repeat` → "Repeat this".
     - Speaker label (YOU / PROSPECT; unverified); keep the existing role wording.
     - The quote (`--lx-text-quote-lg`, original script, `lang`).
     - The note:
       - Improvements: `what_happened`, `why_it_matters`.
       - Missed: `prospect_signal`, `closer_response`, `potential_impact`.
       - Strengths and findings: `explanation`.
     - **Try this next time:** `replacement_behavior` / `follow_up` shown verbatim, with a **Copy** button that shows "Copied ✓" for 1.6s.
   - **Grouping:** identical excerpts keep *every* linked observation (preserve #65 behaviour). Show one quote with stacked notes.
   - **Playing state:** the row lifts (surface card, kind edge, soft kind shadow) and a thin progress line under the quote tracks the clip.
   - Show the first 4; then "Show N more moments".
   - **Playback (fixes R1):** a clip auto-pauses at `end_ms`. Pressing Play, or clicking "keep listening", clears the clip bound and continues.

5. **Sales skills** — "What this call shows about each skill"
   - Subtitle "Draft observations from one call. Never a score."
   - Legend of the four evidence states.
   - **2-column grid of the 8 dimensions** from `dimensions[]`, in profile order: Human Connection & Trust · Discovery & Deep Understanding · Qualification · Problem, Impact & Desire Clarity · Solution Relevance & Presentation · Certainty & Objection Intelligence · Closing & Decision Management · Communication & Tonality.
   - **Tile:** state glyph (ink, never performance colour), label, one-line `observation`, "n moments" link.
   - **Expand inline** (no modal; the grid spans full width). Show evidence quote chips and "Coaching reference: …" from `citations`. Animate with `grid-template-rows: 0fr → 1fr` over 240ms.
   - Status copy is reused from `report-ui-copy.ts`.

6. **The prospect · this call only** — "What the prospect revealed" (never the prospect's name; §12.4)
   - Pairs of **quote → possible reading**, from `prospect_interpretations` with `interpretation_kind: "inference"` and its evidence.
   - The reading card is dashed, labelled "POSSIBLE READING · NOT CONFIRMED" with the hypothesis glyph.
   - A "Still unknown after this call" well, from the existing limits source. Keep the locked teaser behaviour for guests as it is today.

7. **Your next call** — "One focus. Practised once. Done."
   - **Film focus card:** "YOUR ONE FOCUS" plus the focus sentence (`next_call_focus` / `final_assessment.next_focus`).
     - "SAY IT LIKE THIS" = the sample phrase in the provided replacement text, if present. Otherwise omit this block; never invent a phrase.
     - "You've done it when…" = `practice.success_condition`.
   - **Side cards:**
     - "Practise once before the call" = `practice.instructions`.
     - "Keep doing" = `final_assessment.repeat`.
   - `conversation_change{before, change, after}` may render as a small inference strip ("If you had…") with the dashed style.
   - `ethics_notes` render as a neutral callout when present.

8. **Transcript** — "Every word, in sync"
   - Search box, then rows in a 64px time · 92px speaker · text grid. The playing line is highlighted in its moment kind's soft colour. Clicking a line plays from its start.
   - Show the first N rows around the current time, then "Open full transcript" (in-page expand, virtualised for 60-minute calls).
   - Devanagari rows use `lang` and 1.7 line-height.

9. **Footer:** disclosure plus **Delete this call** (danger outline) → confirmation dialog.

**"Develop" reveal:** when a report first appears after processing, sections fade from `blur(6px) saturate(0)` to clear. 700ms each, 60ms stagger, verdict first. At the same moment the toast "Your report is ready" appears with the Done lens. Under reduced motion, use a 120ms opacity fade.

#### 3.6.1 Legacy and edge report shapes
- Missing `overview`: render the verdict from `verdict` and build moments from findings. Hide empty chapters from the rail.
- `preview` / guest reports: keep the existing locked teasers, styled with Lightbox tokens.
- 60-minute calls: virtualise the transcript; limit rendered waveform bins (R5/R6); markers must stay distinguishable (cluster markers closer than 8px into a count bubble).

### 3.7 Calls library (board: Library)

- H1 "Every call, one place", search, filter chips (All · Ready · Analysing · Needs you) and sort.
- **Row:** 150px mini film (real marker ticks for ready calls; a scanline for analysing; a pause glyph for paused) · title + one-line serif verdict (or current status line) · meta · status chip · chevron.
- **Hover:** the row lifts to surface with shadow-2.
- **Load more:** keep loaded pages and scroll position when returning from a call (fixes A9).
- **401:** re-check the session, switch the header to signed-out and offer Sign in with `returnTo=/calls` (A2, A9).

### 3.8 Sign-in, profile, account

Apply the shell, tokens and type. Behaviour fixes come from A1–A9:
- **Return to app / logo** calls `onCancel`.
- **Validated `returnTo`.**
- **OTP countdown** is visible; "Change email" resets the cooldown.
- **Google popup:** watch `child.closed`; without an opener, redirect to `returnTo`; detect in-app browsers and show guidance.
- **Preloader:** 12s timeout, then `delayed` and `error` phases with Retry.
- **Profile 403:** send the user to the workspace chooser instead of an infinite retry.
- **Visual:** a split layout, with a film panel on the left (Lens idle, "Hear the opportunity in every call.") and the form on the right. On mobile the film panel collapses to a 120px band.

---

## 4. Visual system

### 4.1 Colour usage
- **Paper** for reading, **surface** for cards, **film** only for call-bound surfaces (drop zone, analysing panel, player, focus card, library thumbnails).
- **Teal** is the action and brand colour. **Glow** (`#2DD4BF`) appears only on film; it fails contrast as text on light.
- **Moment-kind colours** are semantic and identical everywhere (glyph, marker, chip, filter, transcript highlight). Colour never encodes performance.
- Pair every colour distinction with a glyph or shape difference: circle-check, target, diamond, speech-bubble, dashed circle.
- **Contrast:** body text ≥ 4.5:1; `--lx-muted-2` only at ≥ 12px.

### 4.2 Typography

| Role | Family | Package |
|---|---|---|
| Display / headings | Bricolage Grotesque Variable | `@fontsource-variable/bricolage-grotesque` |
| UI / body | Plus Jakarta Sans Variable (already installed — **fix the wiring**) | `@fontsource-variable/plus-jakarta-sans` |
| Verdict and quotes | Newsreader Variable | `@fontsource-variable/newsreader` |
| Devanagari UI | Noto Sans Devanagari Variable | `@fontsource-variable/noto-sans-devanagari` |
| Devanagari quotes | Noto Serif Devanagari Variable | `@fontsource-variable/noto-serif-devanagari` |

- Define the families as `--lx-font-*` in `tokens.css` and apply them globally in `layout.tsx` / `styles.css`.
- **Remove** Source Sans 3 and the Georgia / Segoe Print / Cascadia usages after migration.
- **Scale:** display 46/1.04 (−0.035em) · H1 42 · H2 30/1.1 (−0.025em) · verdict 34/1.28 serif · quote-lg 22/1.42 serif italic (Latin only) · body 15/1.65 · UI 14 · meta 12.5 · eyebrow 12/800/0.14em uppercase.
- **Devanagari:** never italic or letter-spaced; line-height ≥ 1.6. Mark every quote and transcript row with `lang` (`hi`, `mr`, `en`; `hi-Latn` for romanised Hindi where known).
- **Numbers:** `font-variant-numeric: tabular-nums` for times, sizes and allowance.

### 4.3 Iconography
- **Generic UI icons:** keep `lucide-react` at 1.75–2 stroke.
- **Semantic icons:** use the **Lightbox glyph sprite** (`assets/glyphs/lightbox-glyphs.svg`, copy to `public/lightbox/`) for moment kinds, skill evidence states, chapters and journey steps. They inherit `currentColor`.

### 4.4 Shape and elevation
- **Radii:** 10 (controls), 14 (inner), 20 (cards), 26 (film panels), pill.
- Cards are 1px `--lx-line` with `shadow-1`; hover lifts to `shadow-2`. Film panels use `shadow-film`.
- No left-border accent cards, no gradient washes on reading surfaces, and no nested cards more than one level deep.

---

## 5. Signature components

### 5.1 The Lens (`assets/lens/*.svg`)
- A React component `<Lens state="ready|listening|understanding|writing|done|paused" size={n} />` rendering inline SVG (animations need inline, not `<img>`).
- Colours come from CSS variables, so it themes automatically.
- **State is derived only from confirmed server state.** Never advance the Lens on a timer.
- `aria-hidden`: the adjacent text carries the meaning.
- **Reduced motion:** freeze in pose (no blink, orbit, scan or equaliser).

### 5.2 Lightbox surface
- A reusable `<FilmSurface variant="drop|panel|player|focus">`.
- It provides background (grid + glow), radius and shadow, the optional crop-mark corners, and an optional ambient scanline (drop and panel only).

### 5.3 The film: call player (`<CallFilm>`) — replaces `call-audio-dock` + `source-waveform` presentation
- **Rows:**
  - Row 1: 52px play/pause (glow) · time `07:14 / 18:42` + state line ("Playing · Objection") · waveform lane with markers · speed (1× → 1.25 → 1.5 → 2 → 0.75) and mute.
  - Row 2: legend with counts and the keyboard hint.
- **Waveform:**
  - Measured envelope; played part in glow, unplayed in `--lx-film-wave`.
  - The backend should max-pool per stride (R5); until then, render what is provided.
  - Memoise bins per `(envelope, width)`.
  - Drive the playhead with a `requestAnimationFrame`-throttled external store (`useSyncExternalStore` with a selector), so only the playhead and active marker re-render (fixes R6).
- **Markers:** real `<button>`s positioned at `start_ms / duration`, shaped by kind (circle / diamond / target / bubble).
  - Hover or focus shows a quote preview card above.
  - Click seeks and plays the clip and scrolls the matching moment into view.
  - **Keyboard:** ← / → move between markers, Space toggles play, Home / End.
  - The active marker pings once, then holds a glow.
- **Sticky behaviour:** after scrolling past, it collapses to a 64px bar (play, time, compact lane). Mobile uses the docked mini-player (62px) above the bottom nav.
- **Never modal-blocked:** review content opens inline or in non-modal sheets, so the player stays usable (fixes R4).
- **Unavailable waveform:** a flat line with a visible progress fill and thumb (R7).

### 5.4 Quote chip (`<QuoteChip evidence kind>`)
- A button: ▶ mm:ss in kind ink + quote in serif (≤ 2 lines, ellipsis) + kind-tinted background.
- **Playing:** the ▶ becomes an equaliser. **Ended:** it shows a replay icon.
- **Accessible name:** "Play {kind} moment at 03:18: {quote}".

### 5.5 Moment item, skill tile, focus card, stage row, status chip
- Build these from the boards.
- Each is a small component with props typed from `report-contract.ts` / `overview-contract.ts`.
- **No component invents data;** each has an explicit empty state.

---

## 6. Microinteractions and motion catalogue

All motion uses transform and opacity (and filter only for the one-time develop reveal). Honour `prefers-reduced-motion`: loops stop, and enters become 120ms fades. Pause ambient loops when `document.hidden` or offline (keep the existing `data-motion-suspended`).

| # | Trigger | Motion | Timing | Reduced motion |
|---|---|---|---|---|
| 1 | Drop zone idle | Scanline sweep across film | 7s loop, ease-in-out | Static glow |
| 2 | Drag over drop zone | Border solid glow, bg +6%, lens pupil widens, one fast sweep | 120ms / 600ms | Border change only |
| 3 | File dropped | File card rises from drop point | 240ms move | Fade |
| 4 | Language choice | Segmented thumb slides | 240ms move | Instant |
| 5 | Consent checked | Tick stroke draws | 450ms quick | Instant |
| 6 | CTA idle (enabled) | Sheen passes | every 3.2s | None |
| 7 | CTA press → upload | Button morphs into striped progress bar (real bytes) | View Transition 240ms | Cross-fade |
| 8 | Stage confirmed | Node fills, check draws, connector fills, receipt slides in | 420ms reveal | Fade |
| 9 | Active stage | Ring pulse | 1.8s loop | Static ring |
| 10 | Lens | State-specific loop (blink / equaliser / scan / pen / smile / breathe) | see assets | Frozen pose |
| 11 | "Last confirmed N s ago" | Number ticks every second (text only) | — | Same |
| 12 | Report ready | Toast rises with Done lens; sections "develop" | 500ms / 700ms + 60ms stagger | 120ms fade |
| 13 | Marker hover/focus | Preview card fades up 4px | 160ms | Fade |
| 14 | Marker activated | One ping, then glow | 1.8s once | Glow only |
| 15 | Moment playing | Equaliser in time pill; progress line under quote | loop / live | Static icon; line still tracks |
| 16 | Copy phrase | Button morphs to "Copied ✓" | 1.6s hold | Same, no morph |
| 17 | Skill tile expand | `grid-template-rows` 0fr→1fr + chevron rotate | 240ms move | Instant |
| 18 | Chapter rail | Active pill slides; read tick draws | 240ms | Instant |
| 19 | Film sticky collapse | Height 132→64 with content cross-fade | 240ms | Instant |
| 20 | Library row hover | Lift + shadow | 120ms | None |
| 21 | Offline pill | Slides down; dashed link marches | 240ms / 1.6s loop | Static |
| 22 | Skeletons | Content-shaped blocks with teal-tinted shimmer | 1.4s loop | Static blocks |

---

## 7. Copy system

**Voice:** direct, warm and specific; one idea per sentence; no hype, no exclamation marks, and no "AI" boasting. Second person. The coach's voice appears in the notes, not in the chrome.

### 7.1 Key strings

| Screen | String |
|---|---|
| New analysis | H1 "Drop a sales call. See what really happened." · Drop zone "Drop your call recording here" |
| Confirm | H1 "Looks good. One last check." |
| Analysing (H1 by stage) | "Listening to your call" / "Reading between the lines…" / "Writing your coaching" |
| Analysing reassurance | "You can close this tab. We keep working. Your report will appear in Calls." |
| Report ready | "Your report is ready" |
| Report chapters | "The verdict" · "Moments that mattered" · "What this call shows about each skill" · "What the prospect revealed" · "One focus. Practised once. Done." · "Every word, in sync" |

### 7.2 Honesty strings (must appear)
- "We never show a fake timer. Each step lights up only when it is confirmed."
- "Draft observations from one call. Never a score."
- "Possible reading · not confirmed"
- "Draft coaching generated from this recording. Not reviewed by Dipak. Speaker labels may be wrong. Quotes are shown exactly as spoken."

### 7.3 Failure copy map (implements U5; extend as the backend adds codes)

| Code family | Title | Body | Action |
|---|---|---|---|
| `conversation_provider_http_429/5xx` (retrying) | The AI service was busy | Your recording and transcript are saved. We'll retry automatically, with no need to re-upload and no double charge. | Check now |
| `conversation_provider_http_*` (final) / broker identity | We couldn't reach the AI service | Your recording is saved. The AC team has been alerted to reconnect it. | Copy reference |
| `stage_uncertain` / unknown-outcome codes | We're confirming the result | We're checking with the AI provider what happened. You won't be charged twice. This page updates by itself. | — (keep polling) |
| `report_*` / validation | The report didn't pass our evidence checks | We keep your transcript and try again with stricter checks. | Retry analysis (when B2 enables it) |
| `plan_approval_expired` | Your approval expired | Nothing was lost. Review and start again when you're ready. | Review and continue |
| `account_profile_required` | Finish your AC profile | We need a few details before analysis can start. | Complete profile |
| Upload `source_duration_exceeded` | This recording is {n} minutes long | Sales Xray takes calls up to 60 minutes… | Choose another file |
| Upload `source_format_unsupported` | This file type isn't supported | Use MP3, WAV, M4A, OGG or FLAC. | Choose another file |
| Upload network error | Upload interrupted | Nothing was saved. Check your connection and try again. | Try again |
| `upload_capacity_busy` | The server is busy | Retrying automatically… | — |
| Unknown | Analysis paused | Your recording is saved. Reference {ref}. | Contact support |

Never render an empty message. Always include the reference ID for paused and error states.

---

## 8. Accessibility

- **Semantic landmarks:** `header`, `nav` (main and chapters), `main`, `aside`, `footer`. One H1 per view.
- **Real controls:** buttons, links, inputs, a radiogroup for language, a checkbox for consent. Icon-only buttons have `aria-label`.
- **Focus:** a visible ring (`--lx-ring-focus`) on every interactive element. The skip link stays.
- **Player:** keyboard operable (§5.3). Markers are buttons with descriptive names. Time announcements are throttled.
- **Live regions:** stage changes and upload milestones (25/50/75/100%) announce politely. "Report ready" announces once.
- **Targets:** ≥ 44px on touch (the mobile nav is 76px).
- **Contrast** as in §4.1. Colour is never the only signal.
- **Sheets on mobile** push a history entry, so Back closes them (R10).
- **Motion:** as in §6.
- **Language:** `lang` on quotes and transcript rows; `<html lang>` follows the UI language.

---

## 9. Performance budget

- **Fonts:** variable WOFF2 through `@fontsource-variable`, with Latin plus Devanagari subsets. Preload display and UI only. Load the Devanagari faces on demand (via `unicode-range`). Use `font-display: swap`. Target ≤ 180 KB of font transfer for an English-only session.
- **CLS < 0.05:** reserve heights for film panels, the player, skeletons and quote chips.
- **Report with 60-minute transcript:** virtualise the transcript. Keep waveform bins ≤ 1 per 3 CSS px of lane width. Don't re-render the page per `timeupdate` (§5.3).
- **Animations:** only transform and opacity. `filter` is used once for the develop reveal and removed after.
- **CSS:** consolidate into tokens plus component modules. Delete dead modules (`workbench.tsx` and `processing-experience.tsx` are orphaned).

---

## 10. Implementation map (apps/sales-xray-web)

Suggested structure. The implementer may adjust names, but not the concepts.

```
app/lightbox/
  tokens.css                ← from this package (import once in layout.tsx)
  fonts.ts                  ← @fontsource-variable imports + CSS variable wiring
  Lens.tsx                  ← inline SVG states (assets/lens)
  FilmSurface.tsx
  Glyph.tsx                 ← <svg><use href="/lightbox/lightbox-glyphs.svg#lx-…"/></svg>
  QuoteChip.tsx
  StatusChip.tsx
  Stepper.tsx
  Toast.tsx
app/shell/                  ← replaces acquisition-shell presentation (rail, top bar, bottom nav, minutes meter)
app/new-analysis/           ← DropZone, FileCard, LanguageSegment, ConsentRow, AnalyseButton(upload bar), NextSteps
app/analysing/              ← AnalysingPanel, StageList, StageRow, MeasuredStrip, OfflinePill
app/report/                 ← ReportHeader, CallFilm, ChapterRail, Verdict, MomentsTimeline, MomentItem, SkillsGrid,
                               SkillTile, ProspectPairs, NextCallFocus, TranscriptSync, ReportFooter, DevelopReveal
app/library/                ← CallsList, CallRow, MiniFilm
hooks/                      ← useSubmissionFlow (U1,U4), useStatusPolling (U3), usePlayback + playhead store (R1,R6),
                               useUploadProgress (XHR), useOnlineVisible
public/lightbox/            ← lightbox-glyphs.svg, illustrations/*.svg
```

- **Keep all network and contract logic** in `acquisition-client.ts`, `report-contract.ts`, `overview-contract.ts` and friends. Extract state machines out of the 2,700-line `acquisition-studio.tsx` into hooks, then compose the new presentation. Do not change API contracts for v0.2 UI.
- **Replace** the presentation layer of: `acquisition-shell`, `acquisition-studio` (rendering), `acquisition-file-stage`, `acquisition-processing-panel`, `processing-visual`, `report-modes`, `report-explorer`, `dipak-overview`, `overview-dashboard`, `report-moments`, `sales-skills`, `prospect-snapshot`, `next-call-plan`, `report-transcript`, `call-audio-dock`, `source-waveform`, `review-dialog` (non-modal), `calls-library`, `account-auth` (visual) and `sales-xray-preloader` (visual).
- **Tests:** keep and adapt the existing vitest suites (355+ web tests) to the new DOM. Add tests for every U/R/A item touched, plus the new components. Keep the compiled browser gate green.

---

## 11. Visual QA and acceptance

**Matrix:**

| Axis | Values |
|---|---|
| Viewports | 1440×900 · 1366×768 · 1024×768 · 390×844 · 375×667 |
| Motion | normal · reduced |
| Report language and content | English · Hindi + English (Devanagari quotes) · Marathi + English |
| Report shapes | short call (1 min) · 60-minute call · legacy report (no `overview`) · guest preview · empty findings |
| States | first run (no calls) · analysing each stage · needs OK · paused (each code family) · offline · upload error |

**Acceptance:**
1. Every board on the canvas has a pixel-faithful implementation (±4px, same hierarchy and copy) at 1440×900 and 390×844.
2. No numeric score, synthetic waveform, fake progress or translated quote anywhere. Verified by a grep-based test plus a manual pass.
3. Lighthouse accessibility ≥ 95 on New analysis, Analysing and Report. Keyboard-only walkthrough of the full journey passes.
4. Frontend bugs U1–U8, R1–R10 and A1–A9 from the bug handoff are fixed with tests (or explicitly deferred with a reason).
5. CLS < 0.05. Report interaction stays smooth on a mid-range Android (no long tasks > 100ms during playback).
6. Staging, then production, runs the new UI on the exact release SHA, with screenshots of each board-equivalent state saved under `docs/evidence/sales-xray-lightbox-<date>/`.

---

## 12. Founder decisions (25 Sep 2026) — all binding for v0.2

### 12.1 Users can rename a call — YES
- **Default title:** the uploaded filename without its extension.
- **Report header:** a pencil button next to the H1 turns it into an inline text input.
  - Enter or blur saves; Esc cancels.
  - 1–80 characters, trimmed; emoji allowed; no newlines.
  - While saving, the H1 shows the new text right away (optimistic) with a subtle "Saving…".
  - On failure, it reverts with an inline error: "Couldn't rename. Try again."
- **Library:** a row overflow menu (⋯) with **Rename** opens the same inline edit on the row title.
- The title is private to the owner and never goes in URLs, analytics or logs.
- **Backend dependency (Codex):** no rename API exists today. Add an owner-authorised `PATCH` on the submission with a bounded `display_title` (null = fall back to the filename), return it in submission, progress and library payloads, and audit it like other owner mutations.
  - The UI ships the affordance **only when the API is available**; hide the pencil and the menu item otherwise.

### 12.2 The Example card on New analysis — decided: becomes "Your latest verdict"
- **No ready report yet:** keep the clearly labelled **EXAMPLE** card (Home board).
- **At least one ready report:** replace it with **"Your latest verdict"**. Data comes from the most recent `Ready` call in the library payload.
  - Call title and date.
  - Its verdict sentence (serif, clamped to 3 lines).
  - Its **Change first** focus as one line with the amber target glyph.
  - An **Open report** link.
  - This reminds the user of their one focus right before they upload the next call.
- If the latest call is still analysing, show the latest *ready* one. If the verdict isn't available in the library payload, show title, date and "Open report" only; never fetch a full report just to fill the card.

### 12.3 Dark mode — SHIPS in v0.2
- **Theme control:** **System** (default) · **Light** · **Dark**, as a small segmented control in the Account page and the profile menu.
  - Persist it per viewer in `localStorage`, wrapped in try/catch; a missing value means System.
  - Apply `data-theme` on `<html>` **before first paint** with a tiny inline script in `layout.tsx`, so there's no flash. System follows `prefers-color-scheme` live.
- **Tokens:** `tokens.css` `:root[data-theme="dark"]` (already defined) plus the same values under `@media (prefers-color-scheme: dark)` when `data-theme` is absent or `system`.
- **Film surfaces stay dark in both themes.** In dark mode they are separated from the page by `--lx-line` borders and a slightly lighter `--lx-film-2` gradient instead of drop shadows.
- **Every semantic colour has a dark value** (see tokens). Re-verify 4.5:1 text contrast for every pairing in dark. The glow and moment-kind "on film" colours are shared.
- **Illustrations and the Lens** use CSS variables, so they adapt automatically. Check the Lens outline (`--lx-ink`) in dark: use `--lx-ink` = `#E8EDF5` with a `--lx-paper` fill, per the tokens.
- **QA matrix:** every §11 state is also verified in dark at 1440×900 and 390×844. Reference board: **Report-Dark** on the canvas.

### 12.4 Prospect name in headings — NO
- **Headings never contain the prospect's name.** The chapter title is always **"What the prospect revealed"**, and the rail/chip label is **"The prospect"**.
- Names may appear only where they occur inside quoted evidence or AI-written coaching text, exactly as produced.
