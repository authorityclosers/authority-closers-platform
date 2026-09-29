# Opus independent study: delivering the selected Sales Xray designs

27 September 2026. Author: Claude Code, `claude-opus-5-5`, effort `xhigh` (verified, see §1.1). Study and handoff only: no application code, dependency, image, setting, deployment or customer communication was changed. This file is the only file this study wrote.

Labels used throughout:

- **[Verified]** I observed it directly in this session (file bytes, source, image pixels, session metadata or a primary web page fetched today).
- **[Inherited]** Stated by Codex's research or the design package; I read it but did not re-establish it.
- **[Recommendation]** My judgement.
- **[Untested]** An assumption or proposed check that no one has run.

---

## 0. Bottom line

### The owner's question: one screen at a time, or a whole-app interactive prototype first?

**Neither extreme. Build in the real app, one screen *family* at a time, starting with a small shared foundation. Do not build a separate whole-app prototype for screens whose design is already chosen.** [Recommendation]

- **Not "205 images one by one".** 205 files are 204 distinct images plus one duplicate copy of the upload screen [Verified: identical SHA-256 prefix `80d26780cab88012`]. They are 16 workflows × 6 states × desktop/mobile, plus corrections and two concepts. The unit of work is a **screen family** (for example the report overview with its tabs and player), not an image. The whole library comes to about 8 implementation packets, so you review about 8 times on laptop and phone, not 204.
- **Why not a full interactive prototype first (Claude Design, an artifact, or any HTML mock-up).** Your look is already chosen: the Drive images. A prototype would be a third rendering of it (images → prototype → app), and each translation drifts. The previous attempt already drifted into model-default styling (§2.1, F3). The hard problems you listed are also behavioural and data-bound: Pause that really pauses, one player, return to reading position, no invented outcomes, recovery without restarts. A prototype can fake all of those convincingly and solve none of them. Its code would not be reused either, because the app already has typed report contracts, a mounted navigation system and an audio state machine. So prototype iteration tokens are mostly spent twice. **I did not measure this [Untested];** it is reasoning from how this codebase is built.
- **What gives you prototype-speed iteration without the waste.** The app already has deterministic fixture data and a browser QA script that intercepts every API call (§1.4). The "prototype" should be *the real app running on fixture data*. You get fast visual iteration, and every accepted change is already production code.
- **When a prototype would be worth paying for.** Only for a genuinely undecided or missing design, such as the Prospects domain whose data rules are still open, or a motion study. Not for already-selected screens.

### What actually decides quality here (more than model or effort)

1. **The live app currently runs a different visual system.** It uses "Lightbox": warm cream paper, 42 px heavy display headings, a serif verdict sentence, 20 px corners and dark "film" player bands. The Drive designs are cool white, one sans-serif, 28 px titles, about 8 px corners and a light player. Unless the shared tokens are re-based first, no screen can match the images (§2.1, F1).
2. **An unmerged commit rewrites exactly the files the first screen needs**, in the older Lightbox direction: `07527dcd` "Polish Sales Xray report overview, moments, and player", 11 files, about ±2,600 lines. It must be parked before anyone starts (§2.1, F2).
3. **The images contain things the data cannot truthfully show.** Examples: "Next step confirmed / Product demo Apr 29", coloured call-phase bands, "Attendees", and a Needs/Competitors evidence map. The implementation keeps the *look* and fills it only with real report fields (§4.7 lists every substitution).
4. **Phone mock-ups are drawn "zoomed out".** Taken literally at a 390 px phone width, their body text would be about 11 px. A faithful phone build keeps the order, grouping, colours and shapes at readable sizes, so pages are about 1.3–1.4× longer than the picture (§2.1, F4).

### Modes, in one paragraph

This study (reading references, measuring pixels, writing the contract) is the judgement-dense step, and it ran at Opus `xhigh`. For the implementation writer, I recommend **Opus 5.5 at `high`, escalating an individual failed repair to `xhigh`**. The fresh read-only reviewer runs at **Astra `xhigh`**, where noticing visual defects matters most. Use `max` only once, for a reproducible logic bug that survived `xhigh`. Keep Fast, Ultracode and automatic delegation off.

Codex proposed `xhigh` as the writer's default with a later comparison. I replace that with a **small reusable A/B on one component slice**: the winner's slice becomes production code, so the experiment wastes little.

Reasons: Anthropic's own data shows `xhigh` about +1.4 points over `high` at about 2.5× the cost on SWE-bench Pro. Its guidance is to reserve `xhigh`/`max` for measured gains and to re-run failures at higher effort [Verified, §2.3]. This account is on the **Claude Pro** plan with extra usage disabled [Verified], and this study alone moved the 5-hour window by several points.

---

## 1. What I inspected and understood

### 1.1 Effective settings (verified through the session tools, not prose)

| Item | Observed value | Source |
|---|---|---|
| Model | `claude-opus-5-5` | `get_session(self)` |
| Effort | `xhigh` | `get_session(self)` |
| Fast mode | `off`, `disabledReason: disabled_by_env` | `get_session(self)` |
| Permission mode | `auto` (not Plan mode) | `get_session(self)` |
| Ultracode / delegation | Not used; no subagent, workflow or team was launched | This session's tool log |
| Plan | **Claude Pro**; `extraUsage.enabled: false` | `get_usage` |
| Usage checkpoints | 5-hour window 13 % → 21 %, weekly 2 % → 3 %, context 355k → 437k tokens, all during the reading phase. Final reading is in §6.4. | `get_usage`, shared account, so task attribution is approximate |
| PC health | `heavy_work_ready: false`, 0.83 GiB RAM available, exit 2 | `python C:/Users/Suyash/.codex/tools/pc-health/health_check.py` |

Because of the health gate I started no build, dev server, browser export or test run. Reading and small Pillow image measurements only.

### 1.2 Repository state

| Checkout | Branch / HEAD | Relevant state |
|---|---|---|
| `D:/Projects/authority-closers-platform` (research output) | `main` @ `65b1f36c2507fba706eecee4e565158cc7492baa` | Research directory untracked. |
| `C:/Users/Suyash/.codex/worktrees/sales-xray-v02-core-release-20260925/authority-closers-platform` (source, read-only) | `codex/sales-xray-v02-release-20260925` @ `e488f952b1aafc10761f304630965d8233a2e39b` | 53 dirty entries: Python conversation-intelligence modules, migrations 0049/0050, `apps/admin-web/app/sales-xray/analysis-settings*`, tests, untracked docs. **No dirty file under `apps/sales-xray-web`.** Frontend hashes match those recorded in `docs/research/sales-xray-ui-completeness-20260927/EVIDENCE-DATA-CONTRACTS.md` (for example `dipak-overview.tsx` `92158b49…`, `report-modes.tsx` `6937cf73…`). |
| `C:/Users/Suyash/.codex/worktrees/sales-xray-lightbox-ui/authority-closers-platform` | `codex/sales-xray-lightbox-ui-20260925` @ `07527dcd` | **Not an ancestor of `e488f952`.** One commit ahead, touching `call-audio-dock.*`, `dipak-overview.*`, `report-modes.module.css`, `report-moments.*` and `acquisition-studio.test.tsx` (11 files, +2640/−2691). |

Staging and production revisions were not checked. The last recorded note in `docs/evidence/20260925_LIGHTBOX_CORE_INTEGRATION.md` says staging was `234ca575` [Inherited].

### 1.3 Documents read

Research directory, complete: `OPUS-STUDY-HANDOFF.md`, `ASTRA-OPUS-MODES.md`, `MODE-REVIEW.md`, `MODE-SOURCES.json`, `README.md`, `SCREEN-PACKET-TEMPLATE.md`, `PILOT.md`, `RESEARCH-REVIEW.md`, `INPUTS.json`, `SOURCES.json`, `MANIFEST.json`.

Design directory (`docs/design/sales-xray-v02-refresh-20260926` in the source worktree): `OWNER-VISUAL-DIRECTION-20260927.md`, `README-START-HERE.md`, `DEVELOPMENT-PLAN.md`, `DELIVERY-STATUS-20260926.md`, `IMAGE-GENERATION-STATUS.md` and `DRIVE-DESTINATION.md` were read completely. `INTERACTION-CONTRACTS.md` was read completely except the per-image checkbox appendix. `VISUAL-REVIEW.md` was read completely. `state-manifest.json` was parsed for structure only; per-state decisions came from the `VISUAL-REVIEW.md` tables (204 decisions parsed: 50 / 120 / 34). `index.html` was not opened; the gallery was not needed once image files and decisions were available.

Instructions and skills: root `AGENTS.md` in both checkouts (the worktree copy adds the AC Orchestra section), `apps/sales-xray-web/AGENTS.md` and `CLAUDE.md` (Next.js 16 warning), `ac-orchestra/SKILL.md` with `references/decision-routing.md` and `references/prompts.md`, and `workflow-ui-production/SKILL.md` with `references/implementation-quality.md` and `references/qa-and-iteration.md`.

Not in the reading list but decisive, found by inspection: `docs/research/sales-xray-ui-completeness-20260927/` in the source worktree. I read `EVIDENCE-DATA-CONTRACTS.md`, `GAP-MATRIX.csv` and `FOLLOWTHROUGH.md` completely; the other files there were not read.

Not executed, as instructed: `C:/Users/Suyash/.codex/private-artifacts/ui-reference-refresh-20260926/OPUS-TASK.md`.

### 1.4 Source inspected (`apps/sales-xray-web/app/…` at `e488f952`)

| File | What it establishes |
|---|---|
| `acquisition-studio.tsx` (lines 3040–3292) | The mounted report path: `ReportHeader` → `ReportModes` with six real panels (Overview, Prospect, Moments, Sales skills, Next-call plan, Transcript) → `CallAudioDock`. Clip-end pause lives in the studio `onTimeUpdate` using `moment` state. |
| `report-modes.tsx` (complete) | Tabs with `role=tablist` and arrow/Home/End keys; Reading view; URL bookmarks `?call&view&section`; push/replace history rules; `arriveAt` focus and scroll settle; Return bar that restores origin focus; sticky offsets that measure the mobile bar and dock. **Working navigation to keep, not rebuild.** |
| `dipak-overview.tsx` (1–919) | The current summary: verdict, summary, "Draft report" chip, metrics (call length, replay clips, suggested changes), four summary rows (Keep doing / Change first / Outcome / Next call) with `ClipListenButton` and review links, then `ReplayStrip`. The detailed 14-point chapters follow. |
| `report-contract.ts` (1–140, greps) | `SalesReport` fields; `REPORT_REVIEW_STATUS = draft_not_dipak_adjudicated`; evidence `{segment_id, quote, start_ms, end_ms}`; `source_label` is technical text (fixture: "Scribe transcript revision … source-bound"). |
| `overview-contract.ts` (1–130) | Strict `dipak-14-point-v1`; outcome kinds `closed, follow_up, no_sale, future_date, disqualified, unclear`; `progress` forced to null. |
| `report-header.tsx` (complete) | Title and rename (C1 label), duration, language label only when the run matches, "Draft coaching", primary "Analyse another call", overflow (Download, Request deletion), collapsed provenance disclosure. |
| `call-audio-dock.tsx` + CSS (first 80 lines) | One `<audio>`; always fixed at the bottom; offsets for rail/bottom navigation; play/seek/speed/mute; no skip, no clip-ended UI. |
| `source-waveform.tsx` (1–120) | Shared source context; `clipIsPlaying` and `clipPressAction` → pause / resume / start. **The inline Pause/Resume logic already exists.** |
| `replay-strip.tsx` (complete), `report-moments.tsx` (`reportReplayClips`) | Truthful clip placement: invalid, beyond-duration and unknown-duration handling; markers are pointer-only and the list is the keyboard path. |
| `shell/lightbox-shell.tsx` (60–275) | Rail with brand plus collapse toggle in the top row; nav: New analysis, Calls, Account, local settings; desktop `topBar` (crumb + help); mobile bar; bottom nav New / Calls / Account / Settings. No Prospects route. |
| `lightbox/tokens.css` (complete), `layout.tsx`, `page.tsx`, `calls/page.tsx`, `acquisition-shell.tsx` | Token values in §4.4. Fonts installed: Bricolage, Newsreader, Plus Jakarta Sans, Source Sans 3, Noto Sans/Serif Devanagari. **No Inter.** |
| `tests/acquisition-fixture.ts`, `tests/fixtures/dipak-overview.json` | Envelope fixture: 3 transcript segments, 1 strength, 1 improvement, 1 missed, 2 rewatch. **Too thin for this composition.** |
| `review-fixture/report/*` | Dev-only synthetic route (404 outside development) mounting `ReportModes` directly, not the acquisition path. |
| `scripts/verify-sales-xray-viewport.mjs` (head) | Playwright with every API request intercepted; viewports 1440×900, 1024×626, 390×844, 375×667, 320×568; long-content and motion modes; one-viewport assertions for some states. |
| Style ownership counts | Report modules (`dipak-overview`, `report-modes`, `call-audio-dock`, `replay-strip`, shell) use only `--lx-*` tokens (0 hex). `acquisition-studio.module.css` has 187 hard-coded hex values and holds the report header styles; `styles.css` has 130. |
| Root `package.json` | `playwright 1.58.2`; **no axe-core package** installed. |

### 1.5 Images actually viewed

All under the design directory. Hashes of the overview pair match `INPUTS.json` [Verified: `498711ee…` desktop, `1f40f0b7…` mobile].

| Family | Exact files opened (decision) |
|---|---|
| Report | `06-report-01-overview-desktop` (S), `06-report-01-overview-mobile` (S), `06-report-02-timeline-hover-desktop` (S), `06-report-03-evidence-jump-desktop` (R), `06-report-05-tabbed-desktop` (R) |
| Evidence/audio | `07-evidence-01-moment-list-desktop` (S), `revisions/07-evidence-03-paused-mobile-v2` (S) |
| Shell | `01-shell-03-account-menu-desktop` (S) |
| Upload | `revisions/02-upload-01-empty-desktop-v2` (S), `02-upload-03-selected-mobile` (S) |
| Processing/recovery | `03-processing-06-background-mobile` (S), `revisions/04-recovery-02-checking-status-desktop-v2` (S) |
| Calls | `05-calls-01-populated-desktop` (S) |
| Skills / next call | `08-skills-01-map-desktop` (S), `09-next-call-01-plan-desktop` (S) |
| Prospects | `12-prospect-detail-01-profile-desktop` (S) |
| Account | `revisions/13-account-01-profile-desktop-v2` (S) |
| Providers / admin | `revisions/14-providers-01-pipeline-desktop-v2` (S), `15-admin-users-03-grant-form-desktop` (S), `16-admin-operations-05-audioatlas-mobile` (S) |

S = selected-with-corrections, R = revise. That is 20 images viewed, plus four enlarged crops of the overview pair (cards, header, timeline, mobile cards).

I measured the headings of nine more images programmatically without viewing them fully: `08-skills-01`, `01-shell-03`, `05-calls-01`, `02-upload-v2`, `13-account-v2`, `14-providers-v2`, `12-prospect-01`, `04-recovery-v2` and `06-report-01`.

I did **not** view the other ~180 images. Families 10 (transcript), 11 (prospect directory) and most mobile states were not opened; see the checklist in §3.3.

### 1.6 Demonstrated access versus missing inputs

| Input | Status |
|---|---|
| Local design library bytes | Demonstrated; the overview hashes equal `INPUTS.json`. |
| Company Drive folder | Not accessed. `DRIVE-DESTINATION.md` says the connected Drive API belongs to another account. Local copies are the delivered set per the receipt [Inherited]. |
| Existing Pro research chat | Not opened. No question needed cloud work (see §5, AC Orchestra). |
| Controlled documents (BRD, AC-IMP, AC-UXA-01 …) | Not fetched. Not needed for a visual study; required before code per `AGENTS.md` (listed as a precondition in §4.2). |
| Current rendered app | Not run (health gate exit 2). The first writer task captures the baseline. |
| Staging / production | Not checked. |
| Primary web sources | Fetched today: Claude model-config, cost-and-intelligence, Opus 5.5 prompting, fast mode; OpenAI Astra model page and Codex models page (§2.3). |

### 1.7 What I understand

The owner has chosen a visual direction: the Drive library. The job is to reproduce that direction in the existing Next.js app without losing proportion and hierarchy, while keeping truthful data and working behaviour.

The existing code already has strong behavioural seams: tab and reading navigation, return-to-origin, the clip Pause/Resume state machine, and truthful clip placement. But it is dressed in a different, older visual system, and an unmerged commit is still polishing that older system. The references themselves are internally inconsistent and sometimes contradict the fixture and data contracts. The previous whole-library attempt failed because nothing pinned the shared decisions (tokens, type, player placement, tab set) before screens were built, and because nothing forced a real-browser comparison per family.

---

## 2. Independent critique

### 2.1 Findings the existing research missed or under-weighted

**F1: two visual systems; the packet template forbids the one change that makes fidelity possible.** [Verified]

The live tokens are Lightbox:

- paper `#f6f5f1` and line `#e6e3da` (warm)
- H1 `800 42px` Bricolage Grotesque, verdict `400 34px` Newsreader serif
- body `500 15px` Plus Jakarta Sans
- card radius 20 px, rail 248 px
- dark `--lx-film` bands for the drop zone, analysing panel and player

The Drive overview measures:

- ground `#f6fafe`–`#f7fbfe`, rail `#eff7fc`–`#eff8fd`, cards `#fdfdfe`, hairline `#eaeff5`–`#ebf0f6` (all cool)
- primary `#006d7d` (6.0:1 with white; Lightbox `#087e79` is 4.9:1)
- title ≈ 28 px, headline ≈ 25 px, body ≈ 15 px, card text ≈ 13 px, one sans-serif
- corner radius ≈ 7–8 px, a light player

`DEVELOPMENT-PLAN.md` says "start with the existing tokens", and `SCREEN-PACKET-TEMPLATE.md` excludes "global tokens unless explicitly assigned". Followed literally, those two rules give a Drive layout in Lightbox clothing, which is the complaint. The first packet must explicitly own a foundation re-base (§4.4). Because report modules use tokens only (0 hex), the re-base propagates cleanly. The two hex-heavy files are left alone and noted.

**F2: an unmerged competing polish on the first-screen files.** [Verified]

`07527dcd` (25 Sep, before the Drive library existed and before the owner's 27 Sep selection) rewrites `dipak-overview.tsx`/`.module.css`, `call-audio-dock.*`, `report-moments.*` and `report-modes.module.css` in the Lightbox direction. Dispatching a writer on `e488f952` while that branch stays mergeable guarantees a large conflict later, or a silent revert of whichever lands second. **Coordinator decision before dispatch: park it** (do not merge), and optionally harvest its behavioural dock tests into a later packet.

**F3: the Lightbox look matches the model's documented default style.** [Verified]

Anthropic's Opus 5.5 prompting guide says generic "avoid AI-looking design" instructions just swap one default for another. It gives an explicit avoid-list example: "cream or off-white background, italic accent words in headlines, numbered '01/02/03' section labels, monospace labels, or pill-shaped buttons".

The current app has the cream paper, numbered `01–14` review labels with an `01—04` chapter range, uppercase letter-spaced eyebrows and a serif verdict. My own prior-session notes record that Claude produced the Lightbox package on 24 September. That is likely part of why the result "looked worse". **The writer prompt must name these patterns as forbidden in the first viewport** (§7.3).

**F4: phone references are drawn zoomed out.** [Verified by measurement]

The mobile PNG is 853×1844 for an intended 390×844 CSS viewport, a scale of 2.187. At that scale:

| Mobile element | Implied CSS size |
|---|---|
| Title | ≈ 18–19 px |
| Takeaway body (line pitch 16.7 px) | ≈ 11.5 px |
| Four-card body (line pitch 12.8 px) | ≈ 9–10 px |
| Bottom navigation | ≈ 54 px tall |

Desktop, by contrast, maps almost 1:1 at 1440 CSS px (scale 1.101). So the phone image is a composition reference, not a size reference. At legible sizes (body 15 px, card text 14 px, 44 px targets) the page runs about 1.3–1.4× the drawn height [Untested estimate]. Codex noted "raster ≠ CSS" but did not draw this consequence. It should be told to the owner up front so the mobile build is not judged "unfaithful" for being taller.

**F5: the references drift from one another.** [Verified]

| Attribute | Range across references |
|---|---|
| Page-heading size | 28 px (report, skills) to 34–40 px (Calls, Add a call, Account, AI settings, Checking your call) |
| Rail width | ≈ 242–291 CSS px |
| Player position | Bottom dock (07-evidence-01, 09-next-call-01), inline top card (06-report-03/05, 08-skills-01), top of page (01-shell-03), or absent (06-report-01) |
| Report tab set | 4 (overview), 5 (evidence-jump), 6 (tabbed), 4 (skills) |

"Match each image" would therefore make the app inconsistent with itself. **Pin one decision per attribute from the anchor pair plus the selected player references, then conform later screens to those decisions rather than to their own drift** (§4.4, §4.7).

**F6: the anchor image breaks its own fixture, and the review missed it.** [Verified]

`06-report-01-overview-desktop/mobile` show "Good discovery… next step set", "Next step confirmed", "Product demo Apr 29, 2025 at 11:00 AM" and "Attendees: You, Priya Rao". XR-UI-F01 says no next meeting was agreed and speakers are unverified. `VISUAL-REVIEW.md` flags only "timeline events are illustrative".

`06-report-02-timeline-hover-desktop` (selected) quotes "That's higher than what we budgeted…", not the fixture quote E1 ("I need to understand the total cost before I can decide."). The review flagged the mobile quote mismatch only.

The coloured phase bands (Introduction / Discovery / Solution / Next steps) and the "Evidence map" rows (Needs, Challenges, Decision process, Competitors, Next steps) have **no data source** in `SalesReport` or the overview contract. The interaction contract explicitly forbids "invented phase boundaries". None of this changes the style; it changes what fills each slot (§4.6, §4.7).

**F7: the most useful contract research was not in the reading list.** [Verified]

`docs/research/sales-xray-ui-completeness-20260927/EVIDENCE-DATA-CONTRACTS.md` maps all 14 report points to fields and states that acquisition mounts `ReportModes`, which already implements arrival, Return and section history. Without it, a writer following `DEVELOPMENT-PLAN.md`'s older seam list could rebuild navigation that already works, or edit the legacy `ReportExplorer`. The packet cites it as required reading.

**F8: capacity is a Pro plan.** [Verified]

The account shows plan `Pro` with extra usage disabled. This study, which only reads and measures, moved the 5-hour window by at least 8 points (13 → 21 %) between checkpoints. A writer session that edits, builds, screenshots and repairs is heavier. `xhigh` by default for every packet risks long waits for resets, and the owner's no-paid-fallback rule makes that a real throughput limit. It does not by itself justify lower quality, but it is a legitimate input the mode docs did not have [Inherited: the research said capacity was unverified].

**F9: fixtures and tooling gaps.** [Verified]

- The only report fixture is too sparse to exercise a four-card grid, a five-row key-moments list, markers on a 24-minute timeline, Marathi or long text.
- `axe-core` is not installed, so automated accessibility scans need a dependency approval.
- `verify-sales-xray-viewport.mjs` asserts one-viewport fit for some states. Put the new report sequence in a **new** script so existing gates are not weakened.

**F10: shared-file risk around the header.** [Verified] The report header's styles live in `acquisition-studio.module.css`, a 2,816-line file with 187 hex values shared with upload and processing. Give the header its own CSS module rather than editing that file.

### 2.2 Workflow recommendations: accept / change / reject

| Recommendation (source) | Verdict | Reason |
|---|---|---|
| One screen family in progress; one writer; fresh read-only reviewer; Codex coordinates and integrates (README, PILOT, handoff) | **Accept** | Dependent, same-file work. Anthropic's guidance says orchestration does not pay "when the work is one dependent chain, or fits in a single context" [Verified]. |
| First candidate = report overview with required shell/player (README, template) | **Accept, re-scoped** | Most selected references (a complete S pair plus the S timeline-hover and S player refs) and the owner's most visible pain. Re-scoped to include the **foundation token re-base** (F1) and to **exclude** shell restructuring (Prospects nav, rail content). |
| "Start with existing tokens and components" (DEVELOPMENT-PLAN §4) | **Change** | Keep the components and behaviour; replace the token *values* (F1). |
| Packet excludes global tokens unless assigned (template) | **Change** | P1 explicitly assigns `lightbox/tokens.css`, with a regression sweep of other routes. |
| Pilot A/B of "writer alone vs writer + Luna helper" on matched Calls/report pairs (PILOT) | **Reject for now** | Adds a variable before the foundation exists; costs a second implementation. Revisit after two accepted families if mechanical test work visibly slows the writer. |
| Human owner sign-off on every screen (cloud proposal) | **Keep rejected**, with a change | Owner reviews once per *family*, on staging, on a real laptop and phone, from a five-minute checklist (§5.4). That is the one owner gate that reliably catches "doesn't feel like the image". |
| Two repair rounds then diagnose (README, PILOT) | **Accept, sharpened** | Two repairs per defect cluster at `high`; the third attempt at `xhigh` in a fresh, defect-scoped context; then coordinator diagnosis. |
| Regression baseline only after acceptance; reference images are not snapshots (README) | **Accept** | Correct and important. |
| Paperclip / Storybook / Radix / shadcn (README) | **Accept "not now"** | Nothing in P1 needs them. |
| Luna helper for test mapping (README) | **Change** | Not for P1: fixture creation *is* design understanding and belongs to the writer. |
| Test viewports 1366×768, 1440×900, 390×844, 360×800, 320 (README) | **Accept, extended** | Add 1280×800, 1024×768, 899/900 breakpoint edges, 768×1024, 430×932, and 200 % zoom at 1280. |
| Reuse existing QA scripts (README) | **Change** | Reuse the interception and fixture pattern in a *new* `verify-sales-xray-report-overview.mjs`; do not edit the old one's gates. |
| Implementation order shell → upload → report … (README-START-HERE) versus report first (research) | **Report first**, then the rest of the report tabs | After P1, the other five tabs of the same page would still look Lightbox; finish the report family next (§7.1). |

### 2.3 Mode recommendations: accept / change / reject

Primary sources checked today:

- Claude `model-config`: Opus 5.5 efforts low–max, default `medium`; `max` "may show diminishing returns and is prone to overthinking"; Ultracode "sends `xhigh` … and additionally has Claude orchestrate dynamic workflows"; requires Claude Code v2.1.280.
- Cost and intelligence: "`xhigh` scored about 1.4 points higher for 2.5 times the cost of `high`"; "re-run failures at higher effort": run lower first and re-run failures at `high`, about 97 % solved at about $0.17 against 95.3 % at $0.29 for all-`high`; this needs a failure signal and costs latency.
- Opus 5.5 prompting: "Reserve `xhigh` and `max` for work where you've measured a quality gain"; Opus 5.5 "tends to think more per turn … especially at `xhigh` and `max`"; it "uses these [crop/zoom/measure] tools more effectively at higher effort levels"; frontend-default avoid list.
- Fast mode: on Pro and Max it is "available via usage credits only and not included in the subscription rate limits"; it is the same model quality.
- OpenAI Astra page: efforts low–max; image input supported.
- Codex models page: Max = "more time to reason about a single task"; Ultra = "uses subagents … in parallel".
- The research's claim that "a per-turn cap truncated two xhigh attempts" was **not found** in the fetched page text. It may sit in the reference footnote, which my fetch did not return, so it is not re-verified by me.

| Proposal | Verdict | Reasoning |
|---|---|---|
| Astra `xhigh` writes the screen contract (ASTRA-OPUS-MODES) | **Change** | The contract is §4 of this study, produced at Opus `xhigh` with pixel tools, which is where the docs say higher effort helps. Codex should *verify* it (paths, contracts, line ranges) at Astra `high`, not re-author it. |
| Opus 5.5 `xhigh` as sole writer of P1 (ASTRA-OPUS-MODES) | **Change** | Default the writer to `high` and escalate specific failures. The heavy judgement is front-loaded here and in the review. Offer a reusable slice A/B (E1, §6.2) if Codex or the owner want calibration before committing P1b. |
| Compare Opus `high` vs `xhigh` by building the whole P1 twice | **Reject** | Too expensive on a Pro plan and a 7 GB PC; n = 1 is noise. The E1 slice keeps the question and discards only one slice. |
| Fresh Astra `xhigh` reviewer (ASTRA-OPUS-MODES) | **Accept** | Cross-model review of screenshots is where extra reasoning pays. Calibrate reviewer effort later on frozen candidates with seeded defects (E4). |
| Cloud Pro: `high` as the general baseline | **Accept for writers** | Consistent with the vendor data above. |
| `max` for a diagnosed persistent blocker (ASTRA-OPUS-MODES) | **Accept, narrowed** | Only for a reproducible logic defect with a failing automated test after one `xhigh` attempt (audio state, scroll settle, history). Never for spacing or colour. |
| Ultracode and Fast off; no automatic delegation (all) | **Accept** | Verified off in this session. Fast would draw usage credits, which are disabled. |
| Plan mode as a "planning stage" (ASTRA-OPUS-MODES) | **Reject for P1** | The packet is the plan. Plan mode only changes permissions; scope control comes from the allow-list and the worktree. |
| "If Opus lacks capacity, Astra can own the same packet" | **Accept** | This is also the only honest route to a writer-model comparison later (E3). |

**When `high` is enough:** mechanical token edits; restyling components whose behaviour exists; repeating an accepted composition; fixture authoring against a strict parser (the parser is the checker).

**When `xhigh` could matter [Untested]:** first-time composition decisions with measurement tools in the loop (the E1 slice tests exactly this); a repair the writer failed twice at `high`; any review.

**What warrants `max`:** one bounded attempt on a reproducible multi-component timing bug that `xhigh` did not fix, with its failing test attached.

### 2.4 Contradictions surfaced rather than silently resolved

| Contradiction | Resolution |
|---|---|
| Owner: "use the exact selected image" versus 34 REJECT / 120 REVISE images | Style and composition come from the image. Content and behaviour come from contracts plus the review corrections. For states without a selected image, take composition from the nearest selected sibling [Recommendation]. |
| DEVELOPMENT-PLAN targets (16 px body, 200–224 px rail, ~12 px radius) versus measured reference (13–15 px, ≈242 px, ≈7–8 px) versus Lightbox (15 px, 248 px, 20 px) | P1 fixes body 15 px (card text 14 px), rail 248 px (existing), card radius 10 px. The reviewer accepts ±2 px. |
| Overview image shows no player versus the review demanding a shared dock on the overview | The dock appears on first playback and then stays for the session (§4.10). The first viewport matches the image; playback matches 07-evidence. |
| Desktop default view: code defaults to Tabbed at ≥1100 px; the image shows tabs; mobile images show a tab strip while code defaults to Reading below 1100 px | Keep the code defaults. Render the Reading contents nav on mobile as the same horizontal scrollable strip (visual parity with 07-evidence-03-paused-mobile-v2). |
| Drive nav has "Prospects"; no route exists | Do not add it in P1. A dead nav item would violate the owner's "no non-functional items". Deviation D9. |
| My prior-session notes (25 Sep) record the founder decisions "dark mode ships in v0.2" and "prospect name never in headings"; the Drive references are light-only | Not re-verified. P1 keeps the report surface forced light, as today, so nothing blocks. Dark mode needs an owner confirmation before the shell or account packets. |

### 2.5 The owner's prototype question, decision-ready

| Option | Quality | Token and time efficiency [Untested] | Risk |
|---|---|---|---|
| A. Whole-app interactive prototype, iterate, then hand to coding | Looks good early; behaviour is simulated | Worst for chosen screens: iterations plus a near-full re-implementation | A third visual rendering drifts; fake behaviour hides the real problems |
| B. Implement image by image (205) | Inconsistent; reproduces image drift | Poor: no reuse discipline, 200+ reviews | Repeats the previous failure |
| **C. Foundation, then one screen family at a time in the real app on fixtures; owner review per family on staging** | Highest: real behaviour, one visual system, comparisons against the images | Best: each accepted change is production code; shared components are reused by later families | Needs discipline: packet, allow-list, reviewer |

---

## 3. Workflow coverage

### 3.1 Per family

S / R / X = selected-with-corrections / revise / reject, from `VISUAL-REVIEW.md` (204 decisions). "Code" is what I observed in source; nothing was run.

| Family | S / R / X | Selected exact references | Code observed | Gap class |
|---|---|---|---|---|
| 01 Shell | 1 / 9 / 2 | 01-shell-03-account-menu-desktop | Lightbox rail, toggle in brand row, top bar, mobile bar, bottom nav | Visual correction; compact rail and mobile More sheet have no selected image (missing design); dark-mode question |
| 02 Upload | 3 / 9 / 1 | 02-upload-01-empty-desktop-v2, 02-upload-03-selected-desktop / mobile | `acquisition-file-stage`, dark film drop zone | Visual correction; batch queue is proposed only |
| 03 Processing | 2 / 10 / 0 | 03-processing-06-background-desktop / mobile | `processing-experience`, film panel | Visual correction; listening/understanding/writing stage images all REVISE (unsupported monthly usage) |
| 04 Recovery | 2 / 10 / 1 | 04-recovery-02-checking-status-desktop-v2, 04-recovery-06-needs-review-mobile | Partial; reconciliation depends on backend | **Backend dependency** (idempotent reconcile, paid-call history) plus missing implementation |
| 05 Calls | 9 / 3 / 1 | populated-desktop, search-desktop / mobile, rename-desktop / mobile-v2, filters-mobile, empty-desktop / mobile, row-menu-desktop | `calls-library`: pagination, loaded-row filter, rename; **no search** | Missing implementation (search needs a server query contract); visual correction |
| 06 Report | 3 / 8 / 1 | overview desktop / mobile, timeline-hover desktop | `ReportModes`, `DipakOverview`, header | **P1**; reading / evidence-jump / tabbed / language images are REVISE or REJECT: take composition from the selected pair |
| 07 Evidence | 4 / 7 / 3 | moment-list desktop / mobile, paused desktop-v2 / mobile-v2 | Pause/resume logic exists; no clip-ended UI or skip | Missing implementation (clip-ended Replay / Continue) |
| 08 Skills | 4 / 6 / 2 | map desktop / mobile, practice-focus desktop / mobile | `sales-skills` | Persistent focus is a backend dependency |
| 09 Next call | 4 / 5 / 3 | plan, script, edit, no-followup (desktop) | `next-call-plan`, no persistence | Persistence contract missing; mobile designs all REVISE |
| 10 Transcript | 4 / 7 / 2 | read-desktop-v2, playing-highlight, speaker-review, copy-selection (desktop) | `report-transcript` | Word-level timing unavailable; mobile REVISE |
| 11 Prospects | 2 / 10 / 0 | directory-desktop, empty-desktop | None (no route) | **Backend dependency** (entities, tenancy, retention); fixture-only design work |
| 12 Prospect detail | 1 / 6 / 5 | profile-desktop | Fact-value primitives only (untracked Python) | Backend dependency; 5 REJECT; missing design for conflict and retention |
| 13 Account | 4 / 8 / 2 | profile desktop-v2 / mobile-v2, avatar desktop / mobile | `account-view`, `account-profile` | Usage ledger semantics; request flow |
| 14 Providers | 2 / 7 / 5 | pipeline-desktop-v2, openai-both-mobile-v2 | admin-web `analysis-settings*` **dirty in the worktree (concurrent work)** | Backend dependency (C4/C5 validation); ownership conflict risk |
| 15 Admin users | 4 / 8 / 0 | grant-form / review / confirmed / access-request (desktop) | Grants in a separate branch (`codex/sales-xray-access-grants-20260925`) | Backend and database verification |
| 16 Admin ops | 1 / 5 / 6 | audioatlas-mobile | Unknown | 6 REJECT: largest missing-design family |

Only **11 of 96 states have both viewports selected** (report-01, calls-02, calls-03 with v2, calls-05, processing-06, evidence-01, evidence-03 v2, skills-01, skills-05, account-01 v2, account-02). Every other state is implemented from a selected sibling plus written corrections. That is expected and does not require new images [Recommendation]. It is not evidence of completeness either way.

### 3.2 Gap legend

- **Visual correction:** fix in code against the selected composition; no new image.
- **Missing design:** no selected composition and the state changes a decision. Derive from an exact selected sibling; generate only after a semantic audit, per the owner.
- **Missing implementation:** design selected, code absent.
- **Backend dependency:** a UI can only be fixture-only until the contract exists.

### 3.3 Coverage checklist for deeper per-screen study

- **Viewed (§1.5):** 20 images.
- **To view before their packet:** all remaining images of that packet's family, both viewports, including REVISE/REJECT versions (they carry useful corrections).
- **Per packet, the reviewer confirms:** exact image ID and hash, decision, corrections applied, and deviations recorded. No image-count completion claim is made anywhere in this study.

---

## 4. First screen packet: P1 "report-overview-01"

### 4.0 Why this slice

- It has a fully selected desktop/mobile pair, a selected hover state and selected player references (07-evidence).
- The behaviour it needs mostly exists (tabs, return, pause/resume, clip placement).
- It forces every foundation decision (type, colour, radius, player placement, tab row) that later families reuse.
- The owner's complaints about hierarchy, headers, tabs and play/pause concentrate here.

### 4.1 Identity

```yaml
id: P1-report-overview-01
status: specified-not-implemented
base: codex/sales-xray-v02-release-20260925 @ e488f952b1aafc10761f304630965d8233a2e39b  # or current release HEAD at dispatch; record it
frontend_delta_at_study: none under apps/sales-xray-web (backend/admin dirty files unrelated, do not touch)
writer: one Claude Code session, claude-opus-5-5, effort high (escalation rule §6)
reviewer: fresh read-only session (GPT-6 Astra xhigh preferred; Opus xhigh fresh if Codex writes)
phases: [P1a foundation, P1b composition+player, P1c states+tests+captures]
objective: Open a saved call and, in the first viewport, understand the takeaway, the observed outcome, where the key moments are, and what to keep and change; play or pause any cited clip; reach any detail and return.
```

### 4.2 Preconditions (coordinator decisions before dispatch)

1. **PD1** Park `07527dcd`: do not merge it into P1's base or the release branch. Record the decision.
2. **PD2** Create a fresh worktree and branch from the base for the writer (for example `codex/sales-xray-ui-p1-report-overview`). Never write in the release worktree, which has concurrent dirty backend work.
3. **PD3** Run the controlled-document fetch required by `AGENTS.md` for UI System, UX States and AC-UXA-01, by exact source IDs, and record them. If they conflict with §4.6 on data meaning, the controlled document wins and the writer records the conflict.
4. **PD4** Health check exit 0 before any build or browser job; one heavy job at a time.
5. **PD5** Record the usage baseline: 5-hour and weekly percentages, with extra usage off.
6. **PD6** Dependencies: none allowed in P1. axe and Inter are out of scope unless separately approved.

### 4.3 References

| Role | Path (design directory) | Take from it |
|---|---|---|
| Anchor desktop | `images/06-report/06-report-01-overview-desktop.png` (sha256 `498711ee…c55a`) | Composition, proportions, type hierarchy, card tones, header, tab row |
| Anchor mobile | `images/06-report/06-report-01-overview-mobile.png` (`1f40f0b7…a69a`) | Order and grouping only; not literal sizes (F4) |
| Hover / focus | `images/06-report/06-report-02-timeline-hover-desktop.png` | Anchored preview card (title, range, quote preview, Play (0:35)); selected-row tint |
| Desktop dock | `images/07-evidence/07-evidence-01-moment-list-desktop.png` | Bottom dock anatomy: play circle, ±15, time, track, speed, volume. Spans the content area, not the rail |
| Mobile dock and tabs | `revisions/07-evidence-03-paused-mobile-v2.png` | Compact dock above bottom nav; paused state "Resume"; horizontal tab strip; "Speaker 1 · unverified" wording |
| Tab set | `images/06-report/06-report-05-tabbed-desktop.png` (R) | Six labels only: Overview, Prospect, Moments, Skills, Next call, Transcript |
| Account menu | `images/01-shell/01-shell-03-account-menu-desktop.png` | Rail item styling, active tint, collapse glyph position |

Corrections to apply are from `VISUAL-REVIEW.md` rows for these IDs, plus F6 (§2.1).

### 4.4 Foundation re-base (P1a): `app/lightbox/tokens.css` values

Light block and `[data-lx-surface="light"]` block, kept in sync; update `tokens.test.ts` assertions rather than deleting them. Dark values are unchanged in P1.

| Token | Now (Lightbox) | P1 | Reference evidence |
|---|---|---|---|
| `--lx-paper` | `#f6f5f1` | `#f7fafd` | Ground sampled `#f6fafe`–`#f7fbfe` |
| `--lx-paper-2` (rail and nested ground) | `#fbfaf7` | `#eff6fb` | Rail `#eff7fc`–`#eff8fd` |
| `--lx-line` / `--lx-line-soft` / `--lx-line-strong` | `#e6e3da` / `#ece9e1` / `#cfcabe` | `#e3e9f0` / `#edf2f7` / `#cdd6e0` | Card edges `#eaeff5`–`#ebf0f6`, divider `#eff4f8` |
| `--lx-sunken` | `#ece9e1` | `#eef3f8` | Overflow button fill `#f4f7fb` |
| `--lx-teal` / `--lx-teal-hover` | `#087e79` / `#06635f` | `#006d7d` / `#005866` | Primary button `#006d7d`; contrast 6.0:1 |
| `--lx-teal-soft` | `#e6f5f2` | `#e3f0f5` | Active nav `#e3f0f5` |
| `--lx-font-display`, `--lx-font-quote` | Bricolage / Newsreader | `var(--lx-font-ui)` (Plus Jakarta Sans, Noto Sans Devanagari fallback) | One sans throughout the references |
| `--lx-text-h1` | `800 42px/1.04` display | `700 28px/1.2` ui | Title cap ≈20 px → ≈28 px |
| `--lx-text-verdict` | `400 34px/1.28` serif | `700 24px/1.25` ui | Headline ≈25 px |
| `--lx-text-body` | `500 15px/1.65` | `400 15px/1.55` | Line pitch 22.7 px |
| New `--lx-text-card` | – | `400 14px/1.45` ui | Card pitch 17.9 px at 13 px; 14 px for legibility |
| `--lx-text-meta` | `600 12.5px/1.45` | `500 13px/1.4` | Breadcrumb / meta ≈12–13 px |
| `--lx-radius-lg` / `--lx-radius-md` | 20 / 14 px | 10 / 8 px | Corner ≈7–8 CSS px |
| `--lx-rail-w` | 248 px | 248 px (keep) | Measured ≈242 px |

Keep the moment-kind tone tokens and use them for the four cards: Keep → strength, Change → focus, Next → closing, Outcome → a new neutral `--lx-neutral-soft: #f3f5f8`. The measured tints were keep `#ebf8f6`, change `#fdf5ee`, outcome `#f3f5f8`, next `#eef7fe`. The reviewer judges whether the existing tone softs are close enough; if not, change the soft values, not the component.

The font imports in `layout.tsx` may be removed **only** if a grep proves nothing else references Bricolage or Newsreader afterwards. Otherwise leave them and note the unused bytes.

**P1a regression sweep:** capture every existing route (New analysis, processing preview, Calls, Account, login) at 1440×900 and 390×844 before and after. The acceptance criterion is "no breakage": overflow, invisible text, contrast < 4.5:1, lost focus rings. Not fidelity. Film bands stay dark until their own packet.

### 4.5 Desktop layout (from measurement at 1440 CSS px; scale 1.101)

| Region | Reference geometry | P1 spec |
|---|---|---|
| Rail | 0–242 px | 248 px (existing); ground `--lx-paper-2`; right hairline |
| Content | x 263–1420 | 24 px gutters; no max-width at ≥1280 |
| Header block | Breadcrumb y≈22, title top y≈49, meta y≈95, tabs y≈128–151, first card y≈168 | Header plus tabs ≤ 176 px tall. **Remove the desktop `topBar` on the report view** (its crumb moves into the header) |
| Row 1 | Takeaway 263–973 (710 w) and Outcome 987–1420 (433 w), height 184, gap 14 | Grid `1.64fr 1fr`, gap 14 px, equal height |
| Row 2 | Timeline card, height 129 | Full width, 120–136 px |
| Row 3 | Four cards 279 w each, gap 14, height 160 | 4 equal columns, gap 14 px, equal height per row |
| Row 4 | Key moments 263–809 (546 w) and Report map 822–1420 (598 w), height 175 | Grid `0.91fr 1fr`, gap 14 px |
| Vertical gaps | ≈15–17 px | 16 px |

Use **container queries on the overview container** so rail collapse or expand re-flows the grid:

- Row 1 has 2 columns at ≥ 900 px container width.
- Four cards: 4-up at ≥ 1040 px, 2×2 at ≥ 360 px, 1 column below that.
- Row 4 has 2 columns at ≥ 900 px.

First-viewport target at 1440×900 with the dock hidden: header, tabs, rows 1–3 fully visible, and the row 4 headings visible.

### 4.6 Slot-by-slot data mapping (real fields only)

| Drive element | Source (current code) | Fallback / state |
|---|---|---|
| Breadcrumb "Calls / {name}" | Link `/calls`; `callTitle(label, "Sales call report")` | Unclaimed guest: "Report" with no Calls link |
| Title + pencil | Existing `CallLabelEditor` (C1 label and revision) | Pencil only when `claimed && label` |
| Meta row (image: person · business · email) | **Replace (D1):** duration from `transcript.duration_ms`; saved date only if the bound submission exposes `created_at` (writer verifies the `Submission` type, else omits); report language only when the plan's `report_run_id` matches; "Draft coaching" chip; "Source details" text button | Never show `source_label`, hashes or revision in the row |
| Primary button | "New analysis" → `startAnotherCall` | – |
| Overflow "…" | Download report, Request deletion (existing governed confirm), Source details | Disabled items explain why |
| Tabs | `ReportModes` panels: text-only tabs (drop the section icons), 2 px teal underline; compact Tabs/Reading segmented toggle at the row's trailing edge | Mobile: Reading view by default, with a horizontal scrollable section strip that highlights the current section |
| Takeaway headline | `report.verdict` | Never clamp |
| Takeaway body | `report.summary` | Clamp 4 lines on desktop / 6 on mobile, with an in-place "Show full summary"; never clamp without that control |
| "Listen to call (24:06)" | Starts or resumes full-call playback in the dock (clears any excerpt) | Audio unavailable → disabled with the reason |
| File name · size | **Replace (D2):** "Recording · 24:06" | Filename only if known for the bound call; size omitted |
| Outcome panel header and badge | `overview.outcome.kind` → label. Tone: `closed` teal; `follow_up` / `future_date` blue; `no_sale` / `disqualified` / `unclear` neutral grey. **Never red.** | No overview → no badge; text "No separate outcome statement in this report." |
| Outcome rows (Duration / Next step / Attendees) | **Replace (D3):** Duration; Replay clips (`countReportMoments`); Suggested changes (`improvements.length`); Report language if bound | **No "Next step" date and no "Attendees" rows** |
| Call timeline | New `CallTimeline` using an extracted pure `placeReplayClips()` from `ReplayStrip` (identical validity rules). **Replace phase bands (D4)** with evidence markers on a neutral pastel track, tinted by source category, with a legend; axis ticks every 4:00 for 24:06 (nice interval, 5–7 ticks); live playhead with a time bubble while the dock is active | Unknown duration or beyond-range: existing notes |
| Four cards | Keep doing: `strengths[0]` (title; explanation clamped 2 lines). Change first: `improvements[0]` title plus "Try: {replacement_behavior}" when present. Outcome: `overview.outcome.text`. Next call: `next_call_focus.behavior ?? improvements[0].title` plus `practice.instructions` | Empty → neutral "None supplied in this report", no Play |
| Card footer "Play (0:52)" and "See evidence" | `ClipListenButton` for the first evidence of each (shows Play / Pause / Resume); "See evidence" → `navigateToReport("overview", "01" / "02" / "14" / "11")`, landing on that point's evidence and setting the Return bar | Header label plus chevron is a single link to the same review point (no nested controls) |
| Key moments | First five of `reportReplayClips()` by time: Play, `mm:ss`, title, rewatch purpose label when present; "View all moments →" goes to the Moments tab | Fewer clips → fewer rows; none → "No replay clips in this report" |
| Evidence map | **Replace (D5):** "Report map": rows for Strengths (01), Priority changes (02–04), Missed opportunities (06), What the prospect may have meant (07, labelled "possible meaning"), Final verdict (14). Each row: icon, label, first title (1 line), count; opens its point | Rows with no data show "None in this report" muted; never a zero score |
| Guest preview | Existing `unlock()` aside, placed in the grid | Counts from `report.preview` only |

### 4.7 Accepted deviations (the reviewer must not flag these as defects)

| ID | Deviation | Reason |
|---|---|---|
| D1 | Meta row shows duration / date / language / draft instead of person / business / email | No prospect entity; founder note "prospect name never in headings" (prior-session record) |
| D2 | "Recording · 24:06" instead of filename · size | Size unavailable for reopened calls; `source_label` is technical |
| D3 | Outcome panel rows are measured facts; no next-step date or attendees | XR-UI-F01 no agreed meeting; speakers unverified |
| D4 | Timeline markers instead of labelled phase bands | No phase data; contract forbids invented phase boundaries |
| D5 | "Report map" of real report sections instead of Needs / Challenges / Decision / Competitors / Next steps | No such taxonomy in the report contract |
| D6 | Mobile "‹ Calls" back link in the eyebrow position instead of "CALL REPORT" | Functional return path; same slot and weight |
| D7 | Mobile cards keep a 44×44 icon Play button (absent in the image) | Owner requirement "contextual play and pause everywhere" outranks the image omission |
| D8 | Dock hidden until first playback | The overview image has no player; the evidence images define the player |
| D9 | No Prospects nav item | No route; no dead controls |
| D10 | Text sizes on mobile larger than the drawn image (page ≈1.3–1.4× taller) | F4 legibility |

### 4.8 Mobile composition (< 900 px uses the existing mobile shell)

Order, following the anchor mobile image:

1. Mobile bar (brand + avatar)
2. "‹ Calls"
3. Title 24/30 px
4. Meta line 13 px
5. Takeaway card (icon tile, verdict 20/26, summary 15/22, full-width "Listen to call (24:06)" ≥ 44 px)
6. Outcome card
7. Call timeline (legend above the track; tap a marker for an inline detail card under the track, no hover dependency)
8. Four cards in 2×2 at 360–899 px (icon stacked above label; label 16 px; body 14 px; 44 px Play icon button; chevron header link), 1 column below 360 px
9. Key moments
10. Report map
11. The remaining reading sections

- Sticky horizontal section strip under the mobile bar; the active item scrolls into view.
- The dock sits above the bottom nav plus the safe area (existing offsets), with "11:38 / 24:06", seek and speed; ±15 hidden on mobile.
- The Return bar floats above the dock.

### 4.9 Responsive matrix (CSS px; test all)

| Viewport | Expectation |
|---|---|
| 1440×900 (reference) | §4.5 first-viewport target; compared side by side with the anchor |
| 1366×768, 1280×800 | Rows 1–2 fully visible and row 3 labels visible; title never wraps under the actions (actions wrap below first) |
| 1024×768 | Row 1 two columns; cards 2×2; row 4 stacked |
| 900 / 899 edge | Shell switches between desktop and mobile without horizontal overflow; dock offset changes correctly |
| 768×1024 | Mobile shell; cards 2×2 |
| 430×932, 390×844, 360×800 | §4.8; no overlap with bottom nav or dock; 44 px targets |
| 320×568 | Single-column cards; no horizontal scroll (WCAG reflow) |
| 1280 at 200 % zoom | Reflows like ≈640 px; all actions reachable |
| Rail collapsed at 1440 | Container queries re-flow; toggle stays in the brand row |

### 4.10 Interactions and microstates

| Interaction | Required behaviour |
|---|---|
| Card Play | One shared audio: select range → seek → play. Label becomes Pause (same width, icon crossfade 120 ms). Previous active clip returns to Play. Dock appears on first playback (220 ms slide-up; instant under reduced motion) and stays visible after pause |
| Pause mid-clip | Freezes; time stable ≥ 2 s; inline label "Resume"; dock shows Play at the same time; focus stays on the pressed button |
| Resume | Continues from the paused time, not the clip start |
| Clip end | Pauses once at `end_ms`. Inline shows "Replay". Dock shows "Excerpt ended · Replay · Continue full call". Continue clears the range and plays past the end without re-pausing (small prop change to the dock; the logic stays in the studio's existing `moment` state) |
| Listen to call | Full recording from the current position (0 if none); clears the excerpt |
| Dock | Play/Pause, ±15 s (desktop, clamped), seek (preview while dragging, commit on release, keyboard arrows ±5 s), speed cycle, mute; `aria-valuetext` "11:38 of 24:06" |
| Timeline marker | Roving tabindex (one tab stop; ←/→ between markers; Home/End). Hover (100 ms intent) or focus shows the preview card: title, `11:20–11:55`, quote preview ≤ 90 chars, "Play (0:35)". Escape closes; pointer can move into the card; click or Enter plays |
| Tab change | Underline indicator slides 180 ms (`--lx-ease-move`); panel fades 120 ms; audio continues; URL per existing `ReportModes` rules |
| See evidence / card header | Existing `navigateToReport` + `arriveAt`: focus on the destination, smooth scroll (instant under reduced motion), teal-tint arrival highlight fading 1.2 s, Return bar "Back to Overview" restores the origin control focus and position |
| Rename | Existing editor; visual restyle only |
| Overflow | Existing `details` menu; restyled; Escape returns focus to the trigger |
| Card hover / press / focus | Border → tone edge + `--lx-shadow-1` in 120 ms; press translateY(1 px); focus-visible 2 px teal ring with 2 px offset. Hover never reveals essential information |
| Loading (reopening a finished call) | Writer inspects the existing-call entry path. If a gap exists, show neutral skeleton frames in this grid; **no processing stage names** for a completed call |
| Audio unavailable | One call-level notice; inline Play disabled with an accessible reason; report readable |

### 4.11 Motion and focus

- All transitions honour `prefers-reduced-motion` (no translate or scale, no smooth scroll; state cues remain).
- The tab order is logical: skip link → rail → breadcrumb → title/rename → New analysis → overflow → tabs (roving) → view toggle → panel content in reading order → dock.
- Focus never lands under the sticky tab row (existing scroll-margin logic).
- Status changes are announced once (for example "Clip ended"). Seconds of playback are never announced.

### 4.12 Allowed and excluded files

Paths under `apps/sales-xray-web/` unless marked.

**Modify:**

- `app/lightbox/tokens.css`, `app/lightbox/tokens.test.ts` (P1a)
- `app/layout.tsx`: font imports only, and only if proven unused
- `app/dipak-overview.tsx`: replace only the summary `<section>` (currently lines ~598–758) with `<OverviewSummary …/>`; the chapter stack and review dialog stay untouched
- `app/dipak-overview.module.css`: remove only summary rules; `app/dipak-overview.test.tsx`: update summary assertions
- `app/report-header.tsx`, `app/report-header.test.tsx`, `app/report-header-rename.test.tsx` if affected
- `app/report-modes.tsx`: tab label rendering and view-toggle presentation only. **No change** to history, return, settle or offset logic. Also `app/report-modes.module.css` and `app/report-modes.test.tsx`
- `app/call-audio-dock.tsx`, `.module.css`, `.test.tsx`
- `app/acquisition-studio.tsx`: **only** the report render block (currently lines 3085–3265), to pass props (active range and clear callback, optional date, audio-unavailable flag)
- `app/shell/lightbox-shell.tsx` + `.module.css`: only a prop that hides the desktop `topBar` for the report view, and token-driven rail visuals. No nav structure change
- `app/replay-strip.tsx`: only to import the extracted placement helper (behaviour identical, existing tests pass)

**Create:**

- `app/overview-summary.tsx` / `.module.css` / `.test.tsx`
- `app/call-timeline.tsx` / `.module.css` / `.test.tsx`
- `app/replay-placement.ts` / `.test.ts`
- `app/report-header.module.css`
- `tests/fixtures/xr-ui-f01-report*.json`, `tests/xr-ui-f01-fixture.ts`
- `scripts/verify-sales-xray-report-overview.mjs` (repo root)
- `docs/evidence/sales-xray-ui-p1-report-overview/` (repo root): receipt, capture manifest, discrepancy log. Screenshots stay under `.tmp/`; the manifest records hashes

**Excluded:** everything else. In particular:

- `acquisition-studio.module.css`, `styles.css`
- calls, upload, processing, recovery, moments, transcript, skills, next-call and prospect-snapshot components
- `report-explorer*`, `call-studio*`
- `apps/admin-web/**`, `apps/learner-web/**`, `packages/**`, `db/**`
- `package.json`, `pnpm-lock.yaml`, `next.config*`, auth and middleware

Also: no dependency installs and no edits to existing QA scripts' assertions.

### 4.13 Fixtures (XR-UI-F01 report set; all must pass the strict parsers)

| File | Content |
|---|---|
| `xr-ui-f01-report.json` (EN) | Duration 1,446,000 ms. About 10 transcript segments, including 680,000–697,000 with quote E1 (fictional prospect line, exact text from INTERACTION-CONTRACTS D) and 697,000–715,000 with E2. 2 strengths, 3 improvements, 2 missed, 1 objection (evidence E1). Overview `dipak-14-point-v1` with `outcome {kind: "unclear", text: "No next meeting was agreed. The prospect is still weighing the total cost."}`, 3 rewatch items, golden moment, next_call_focus, practice, final_assessment, `progress: null`. Speakers unverified |
| `-mr` | Same identities and quotes; prose (verdict, summary, titles, explanations) in Marathi + English mixed script; quotes unchanged |
| `-long` | Summary about 1,200 chars; titles about 120 chars; explanations about 700 chars |
| `-sparse` | 1 strength, 0 improvements, 1 clip |
| `-legacy` | No `overview` (legacy path) |
| `-guest` | `preview` with hidden counts |

The audio-unavailable variant is produced by the script returning an error for the audio request.

### 4.14 Tests

**Unit (vitest, single worker):**

- Slot mapping for every row of §4.6, including: no "Next step" or "Attendees" text; neutral tone for `unclear`; no fabricated date.
- Fallbacks for sparse, legacy and guest.
- `placeReplayClips` parity with the old strip on invalid, beyond-duration and unknown-duration inputs.
- Tick generation (24:06 gives 0, 4, 8, 12, 16, 20, 24:06); marker percentages; roving keys.
- Dock hidden → visible on first play; Continue clears the range; ±15 s clamps.
- Tabs render text labels with arrow-key behaviour unchanged.

**Browser (new script; intercepted API; real mounted acquisition route; Playwright Chromium; fixed TZ Asia/Kolkata; fixed clock):**

1. **M05 sequence** on the Change-first card clip: Play → Pause mid-clip → 2 s stable (`currentTime` Δ ≤ 0.05) → labels Resume / Play and dock time equal → Resume continues from the paused time → end pauses once → Replay / Continue → Continue passes the end with no re-pause. Record labels and actual `audio.paused` / `currentTime`.
2. Tab switch while playing: audio continues and time is monotonic; the URL section changes.
3. **M04:** See evidence → focus on the destination → Return → focus on the origin button; scroll within ±40 px; audio unchanged.
4. Timeline keyboard: Tab into the markers, → moves, Enter plays the correct range, Escape closes the preview.
5. Geometry at every §4.9 viewport:
   - `scrollWidth ≤ innerWidth`
   - no interactive element's bottom below `dock.top` or `bottomNav.top` when scrolled into view
   - desktop tab row on one line
   - four cards fully inside 1440×900 with the dock hidden
   - rail toggle's y inside the brand row, expanded and collapsed (M01)
   - mobile targets ≥ 44×44
   - Devanagari card bodies either unclamped or showing the expander
6. Captures: viewport plus full page for EN, MR, long, sparse, legacy, guest, playing (dock), hover preview open, overflow open, mobile strip scrolled, reduced motion. PNGs and a JSON manifest (viewport, DPR 1, browser version, fixture, motion, sha256).
7. **Branded Chrome** (`channel: "chrome"`, isolated temporary profile, never the company profile): M05 only, sequentially, for codec parity.
8. **Accessibility without axe:** accessibility-tree snapshot per state (roles and names of tabs, dock, cards, markers) plus a manual keyboard pass recorded in the receipt. Automated axe is **blocked pending dependency approval**, stated in the receipt.

### 4.15 Visual acceptance (reviewer)

Compare the 1440×900 capture with the anchor scaled to 1440×900 side by side (and optionally as an overlay). Compare mobile by order and grouping, not pixels.

| Check | Pass condition |
|---|---|
| Composition | Same regions in the same order; column ratios within ±4 % of §4.5; card heights within ±15 % (real text) |
| Type | Title 28 ± 2 px bold; headline 24 ± 2; card label 16–17; body 15; card text 14; meta 13; **one sans family**; no serif, no uppercase letter-spaced eyebrow on desktop, no "01/02" numbering in the first viewport |
| Colour and material | Cool ground, white cards with cool hairline, four tone tints, primary `#006d7d` family, no dark film band on the report, radius 8–10 px, buttons rectangular (8–10 px), not pills |
| Truth | Every value traceable to §4.6; the D1–D10 deviations present and nothing else invented |
| Behaviour | §4.10 and §4.14 evidence present |

**Severity:**

- **Critical:** fabricated or wrong data, broken playback or pause, focus trap, action hidden behind dock or nav, horizontal overflow.
- **High:** wrong region order, missing card, wrong type family or scale class, dock covering content, keyboard path missing.
- **Medium:** spacing or size outside tolerance; tint off-family.
- **Low:** polish.

Acceptance requires zero open Critical or High issues.

### 4.16 Done

- Writer receipt (§5.2) at a final SHA.
- Reviewer "pass" at that SHA.
- Codex re-ran the unit tests and the browser script on that SHA (§5.3).
- Staging deployed through the normal release path, and the owner's family review done (§5.4).

A pass on staging is recorded as staging evidence only. Production follows the existing release gates.

---

## 5. Collaboration protocol

### 5.1 Roles and ownership

- **Codex coordinator:** owns PD1–PD6, dispatch, integration, CI, staging, and the ledger. Never edits files the writer owns while a packet is open.
- **Writer:** owns exactly §4.12 in its worktree; one packet at a time; no subagents.
- **Reviewer:** read-only, fresh context, at a named SHA; returns defects only.
- **Owner:** one review per family on staging.
- No Codex → Claude → Codex chains. A writer never dispatches agents.

### 5.2 What the writer sends Codex (concise)

```yaml
packet: P1-report-overview-01
base_sha: ...
final_sha: ...
branch: ...
model_effort_observed: claude-opus-5-5 / high   # from /status or session metadata, plus any escalations with reason
files_changed: [...]           # must be a subset of §4.12
tests: [{command, env, result, duration}]
captures_manifest: docs/evidence/sales-xray-ui-p1-report-overview/captures.json
deviations_used: [D1..D10]     # plus any new one, with reason: needs coordinator approval
conflicts_found: []            # contract vs packet
self_discrepancies: []         # writer's own remaining differences vs reference, ranked
blocked: [axe (dependency), ...]
usage: {five_hour_before, five_hour_after, weekly_before, weekly_after, active_minutes}
```

### 5.3 What Codex independently verifies before integration

1. `git diff --name-only base..final` ⊆ allow-list; `07527dcd` absent.
2. Lint, typecheck and vitest (single worker) on the final SHA; health check first.
3. Re-run `verify-sales-xray-report-overview.mjs` and compare three captures (1440, 390 and one state) with the writer's hashes. Differences are investigated, not averaged.
4. Grep for forbidden strings in product code: "Next step confirmed", "Attendees", phase labels, hex hashes in UI copy, fixture names.
5. `tokens.test.ts` updated rather than removed; contrast assertions present.
6. Reviewer pass at the same SHA.

Only then merge and deploy to staging.

### 5.4 Owner family review (five minutes, laptop and phone, staging)

1. Does the first screen feel like the chosen image?
2. Can you read everything on the phone without zooming?
3. Play a card clip, pause it, wait, resume: did it continue from where you paused?
4. Switch tabs while playing: did audio keep going?
5. Open a card's evidence, then press Back to Overview: did you return to the same place?

Spacing and routine layout decisions do not need the owner. Feedback goes to Codex, who triages it into repairs or the next packet.

### 5.5 Escalation and stopping

The writer stops and reports when:

- a contract conflict needs a product decision (records it and continues independent work);
- the health check returns exit 2 before heavy work (waits, or does unit-level work only);
- a dependency is needed (skips that item);
- the 5-hour window reaches ≥ 85 % (writes a continuation note to the receipt and stops);
- the same defect cluster fails twice.

---

## 6. Mode comparison and resource plan

### 6.1 Defaults

| Role | Model / effort | Rule |
|---|---|---|
| Coordinator verification of this packet | GPT-6 Astra `high` | `xhigh` only for integration conflicts |
| P1a foundation writer | Opus 5.5 `high` | Mechanical |
| P1b/P1c writer | Opus 5.5 `high` (or E1's winner) | Defect cluster failed twice → one `xhigh` attempt in a fresh defect-scoped context → coordinator diagnosis → `max` once only for a reproducible logic bug with a failing test |
| Reviewer | GPT-6 Astra `xhigh`, fresh | Opus `xhigh` fresh when Codex wrote the code |
| Helpers | None in P1 | – |
| Always off | Fast, Ultracode / Ultra, Plan mode, automatic delegation, API keys, usage credits | – |

### 6.2 Experiments (all **unrun**)

- **E1 (optional, the smallest fair effort test).** After P1a lands, build the same slice twice from the same SHA: `OverviewSummary` row 1 plus the four cards at 1440 and 390, on the EN fixture.
  - Arms: Opus `high` versus Opus `xhigh`, fresh sessions, identical prompt, a 75-minute active cap each, no reviewer feedback, sequential runs.
  - A blind fresh reviewer scores both against §4.15 by severity.
  - Record 5-hour and weekly percentages before and after each arm.
  - **Pre-declared rule:** use `xhigh` for P1b if it has ≥ 2 fewer Critical+High defects, *or* wins ≥ 3 of the 4 rubric rows while its usage delta is ≤ 2.5× high's; otherwise use `high`.
  - The winning slice is kept as P1b's starting point, so only one slice is discarded.
  - If Codex or the owner skip E1, run P1b at `high` and rely on E2.
- **E2 (always on, near-free).** An escalation log: for every defect, record the effort that fixed it and the attempts. After 2–3 families this shows whether `xhigh` repairs succeed where `high` failed.
- **E3 (deferred).** Writer-model comparison, Opus versus Astra, only on a matched pair of later families (for example Calls desktop / mobile), or naturally if Opus capacity forces Astra to write a packet.
- **E4 (after P1 acceptance).** Reviewer effort: Astra `high` versus `xhigh` on frozen P1 candidates with 6 seeded defects (2 Critical, 2 High, 2 Medium), separate contexts; measure missed seeds and false alarms.

### 6.3 Fixed controls

- Packet text, base SHA, fixture files and reference hashes (§4.3).
- Viewports (§4.9); Playwright 1.58.2 Chromium plus branded Chrome for M05; Windows 11 with bundled fontsource fonts; TZ Asia/Kolkata; fixed clock; reduced-motion both on and off.
- Same timeouts, same repair limits, same severity rubric.
- Truncation or cap events are recorded, not hidden.

### 6.4 Accounting

- Usage is recorded as plan-window deltas: shared account, approximate, never zero. Settled cash must be $0 (extra usage verified disabled).
- Also recorded: active minutes, repair rounds and causes, escaped defects found at staging, and owner minutes.
- This study's own consumption, cumulative for the account: 5-hour window 13 % at the first check, 21 % at the second, **26 % after writing this file**; weekly 2 % → 3 % → **4 %**; context about 483k tokens. How much of the first 13 % predates this session is unknown. This is an order-of-magnitude reference for a reading-heavy `xhigh` session, not task-exact.

---

## 7. Next execution handoff

### 7.1 Ordered bounded tasks

| # | Owner | Task | Depends on | Exit |
|---|---|---|---|---|
| T0 | Codex | Verify this study's source claims (paths, line ranges, hashes); make PD1–PD6; create writer worktree and branch; record the usage baseline | – | Decisions recorded |
| T1 | Writer (Opus high) | **P1a**: fixtures (§4.13) with parser tests; baseline captures of current routes; token re-base; regression sweep | T0 | Receipt; no-breakage evidence |
| T2 (optional) | Codex, then 2 writer sessions, then reviewer | **E1** slice A/B | T1 | Effort choice for T3 recorded |
| T3 | Writer | **P1b/P1c**: header, tabs, `OverviewSummary`, `CallTimeline`, dock, mobile, states, browser script, captures | T1 (T2) | Receipt at final SHA |
| T4 | Reviewer (fresh, read-only) | Review against §4.15 with the D1–D10 list | T3 | Pass or defect list |
| T5 | Writer | Repairs under the escalation rule | T4 | Pass |
| T6 | Codex | §5.3 verification → staging → owner family review (§5.4) | T5 | Staging receipt; owner notes |
| T7 | Codex | Ledger event; E2 data; open P2 | T6 | – |

**Next packets** (each gets its own packet in this format; no new images unless a semantic audit proves a missing state):

- **P2a** Moments + Transcript (07/10: clip-ended UI everywhere, follow playback)
- **P2b** Skills + Next call + Prospect snapshot tabs (08/09)
- **P3** Shell + Calls + reopen finished call (01/05)
- **P4** Upload / processing / recovery (02/03/04; backend reconciliation evidence first)
- **P5** Account / usage / access (13)
- **P6** Admin providers / users / ops (14–16; admin-web; coordinate with the dirty `analysis-settings` work and the grants branch)
- **P7** Prospects (11/12; fixture-only until contracts exist)

### 7.2 Ledger event (for Codex to append; AC Orchestra)

`2026-09-27 · UI-DELIVERY-STUDY · Opus 5.5 xhigh (verified) · study accepted-for-review · inputs: research dir + design dir @ e488f952 (frontend clean) · findings F1–F10 · next: T0 PD1 park 07527dcd, PD3 controlled docs · usage: 5h 13→26 %, weekly 2→4 % (shared) · no code/images/deploy.`

No cloud chat was dispatched. No question here needed separable cloud research; source, pixel and contract questions were answered locally, and the primary-source spot checks used direct fetches.

### 7.3 Exact first writer prompt (T1 + T3; send T1 first, T3 after T1's receipt)

```text
You are the sole implementation writer for packet P1-report-overview-01 of Sales Xray. Work only in the worktree/branch the coordinator named: <WORKTREE> on <BRANCH>, base <BASE_SHA>. Model claude-opus-5-5, effort high. Fast mode, Ultracode, Plan mode and subagents stay off. Do not install dependencies. Before any build, dev server, browser or test job run `python C:/Users/Suyash/.codex/tools/pc-health/health_check.py`; on exit 2 do only light work. One heavy job at a time.

Read first, completely: D:/Projects/authority-closers-platform/docs/research/ui-delivery-orchestration-20260927/OPUS-INDEPENDENT-STUDY.md §4 (your packet) and §2.1; apps/sales-xray-web/AGENTS.md and the Next.js guide it points to; docs/research/sales-xray-ui-completeness-20260927/EVIDENCE-DATA-CONTRACTS.md (G06–G08); the interaction contract rows 06-report-01/02 and state machines B and C in docs/design/sales-xray-v02-refresh-20260926/INTERACTION-CONTRACTS.md. Open and look at these images before editing: 06-report-01-overview-desktop.png, 06-report-01-overview-mobile.png, 06-report-02-timeline-hover-desktop.png, 07-evidence-01-moment-list-desktop.png, revisions/07-evidence-03-paused-mobile-v2.png. Treat the phone image as order and grouping, not literal sizes.

PHASE T1 (stop after it and send the receipt): (1) Build the XR-UI-F01 report fixtures in §4.13 so they pass the existing strict parsers, with unit tests proving that. (2) Capture the current app (before) on the routes in §4.4 at 1440×900 and 390×844 using fixture interception, never real data. (3) Re-base tokens exactly as §4.4, keeping the light and [data-lx-surface="light"] blocks in sync and updating tokens.test.ts assertions. (4) Capture again and report any breakage (overflow, unreadable text, contrast < 4.5:1, lost focus rings). Do not start the report composition.

PHASE T3 (after the coordinator says go, with the effort it names): implement §4.5–§4.11 on the mounted acquisition report path (acquisition-studio → ReportHeader → ReportModes → DipakOverview summary → CallAudioDock). Reuse ReportModes navigation/return and the clip press state machine; do not rewrite them. Extract replay placement into a pure helper and keep ReplayStrip behaviour identical. Every displayed value must come from §4.6; use the D1–D10 substitutions and invent nothing else. In the first viewport, do NOT use: a cream or warm off-white ground, a serif or italic display sentence, numbered "01/02/03" labels, uppercase letter-spaced eyebrow labels on desktop, pill-shaped primary buttons, dark "film" bands, or icons inside the report tabs. Write the browser script and unit tests in §4.14 and produce the captures and manifest. Edit only the files in §4.12; if you believe another file must change, stop that item and explain.

Work loop: change one region → render → look at your capture next to the reference at the same size → list the three largest differences → fix → repeat. Measure (cap height, column widths) rather than eyeballing when unsure. Do not update any approved screenshot baseline and do not mark yourself accepted.

Return the §5.2 receipt YAML plus a ranked list of the remaining differences you can see. If a real contract conflicts with the packet, record the conflict, use the honest fallback, and continue. If the 5-hour usage window reaches 85 %, write a continuation note into the receipt and stop.
```

### 7.4 Reviewer prompt (T4)

```text
Read-only review of P1-report-overview-01 at SHA <FINAL_SHA>. Do not edit files. Inputs: OPUS-INDEPENDENT-STUDY.md §4.3–§4.15 (the packet, including deviations D1–D10, which are not defects), the five reference images named in §4.3, and the writer's captures and manifest. Re-run scripts/verify-sales-xray-report-overview.mjs yourself only if the health check exits 0; otherwise review the supplied captures and mark behaviour "unverified".

Compare the 1440×900 capture to the anchor scaled to 1440×900, and mobile captures by order and grouping. Check truth (every value traceable to §4.6), composition, type, colour and material, and the behaviour evidence for M05, M04, the timeline keyboard path and tab-while-playing. Return at most 15 defects, most severe first, each with: location, expected result, observed result, severity (Critical/High/Medium/Low per §4.15), and the evidence path. Then give a verdict: pass (no open Critical or High) or rework. Do not restyle the product, propose new features, or use a pixel-difference percentage as the verdict.
```

---

## Appendix A: measurement method

- Scale factors: desktop 1586/1440 = 1.101; mobile 853/390 = 2.187 (intended CSS sizes come from the recorded prompts [Inherited]).
- Colours: single-pixel samples in flat regions.
- Font size ≈ cap height ÷ 0.72; body sizes cross-checked by line pitch.
- Geometry: colour-transition scans along rows and columns (Pillow 11.1).
- Accuracy: ±1–2 CSS px; generated images are not typeset documents, so the targets in §4 carry tolerances.
- Crops and scripts lived in the session scratchpad only; nothing was added to the repository besides this file.

## Appendix B: sources checked today (verified) versus inherited

| Claim | Status |
|---|---|
| Opus 5.5 efforts, default medium, `max` overthinking caveat, Ultracode = `xhigh` + orchestration, CLI ≥ 2.1.280 | Verified: code.claude.com/docs/en/model-config |
| `xhigh` +1.4 pts for 2.5× the cost of `high`; 478-problem subset; re-run-failures policy | Verified: platform.claude.com/…/optimizing-for-cost-and-intelligence |
| "Truncated two xhigh attempts" | **Not found** in the fetched text; unverified |
| Reserve `xhigh`/`max` for measured gains; more thinking per turn at `xhigh`; tools used better at higher effort; frontend avoid-list | Verified: platform.claude.com/…/prompting-claude-opus-5-5 |
| Fast mode draws usage credits on Pro/Max, same quality | Verified: code.claude.com/docs/en/fast-mode |
| Astra efforts low–max, image input | Verified: developers.openai.com/api/docs/models/gpt-6-astra |
| Codex Max / Ultra semantics | Verified: learn.chatgpt.com/docs/models |
| Paperclip, Playwright, WCAG and Apple sources in SOURCES.json | Inherited; not needed for these decisions |
