# AC / Closers Academy / Cohorva v0.1 Alpha acceptance contract

Date: 2026-09-07. Status: active delivery target, **not an acceptance or release claim**.
Workstream: `AC-WF-V01-ALPHA`. Machine status: [Alpha scorecard](../05-handoff-qa/alpha-scorecard.json).

## Outcome and authority

Consolidate and polish the existing Learning & Practice platform into a coherent,
responsive, fast web/PWA Alpha. Authority Closers is the company, Closers Academy
is the first reference academy/tenant, and **Cohorva** is the provisional platform
codename selected from the supplied kit. Reuse existing learner, Academy Studio
inside `admin-web`, and separately authorized administrative surfaces. Do not
restart the platform or invent an `Instructor` authorization role.

The September 7 user direction selects the supplied Learning Experience V3 and
Brand/Motion kit for this consolidation, superseding earlier visual-only locks
where they conflict. Existing authorization, tenancy, content/version, consent,
enrollment, evidence and canonical progress contracts remain authoritative.
Editorial curricula, reward rules, sample scores and demonstration video in the
ZIPs do not become live product data. Cohorva is provisional, not a trademark
clearance claim. Verify Dipak/legacy-logo provenance before publication.

The user also explicitly permits revisiting all prior documentation, not just
visual specifications. Treat earlier documents as reviewable baselines: record
the evidence and dated superseding decision when changing them, preserve their
history, and add matching implementation tests. This does not authorize silently
inventing protected business semantics or bypassing consent, access or audit
controls. Those changes require their own explicit controlled decisions.

Continue in the single implementation lane
`C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`, branch
`codex/local-staging-dev-bridge`; keep root `main` clean. Preserve the existing
six-file learner UI patch, its evidence, the unrelated user DOCX, and preserved
stash. Coordinate file ownership; no overlapping concurrent writers or new
worktrees by default. AI-on-VPS research/implementation is outside this pass.
Thread controls are unavailable in the current tool inventory, so an external
chat pause must not be represented as confirmed.

## Three planned iterations

The user requested a two-to-three-iteration target. Plan three passes, each
ending in a scored review; a pass may contain multiple small commits. The count
is not permission to waive a failed gate. Ship coherent safe slices while
continuing the target, with capability-specific blockers kept visible.

| Pass                        | Deliverable                                                                                                                                                                | Exit evidence                                                                                                                                        |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 — foundation and baseline | Reconcile both kits, existing route/capability inventory and UI work; selected brand + reusable shell/theme/components; fix actual-runtime latency and interaction defects | Frozen must-ship inventory, source/asset register, before/after shell screenshots, tests, production-build baseline and candidate measurements       |
| 2 — complete journeys       | Apply the shared system across current learner and Studio/admin journeys, responsive layouts and meaningful recovery states; preserve real API/media/data contracts        | Every in-scope route/action/state has owner and test; visual review desktop/mobile; no orphan controls or fabricated product state                   |
| 3 — verify and publish      | Close regression/review findings, exact-SHA staging acceptance, durable Drive evidence, then identical-artifact production promotion when its separate gates pass          | Green required checks, live journey evidence, version/rollback record, verified screenshots/Drive IDs, staging and production independently declared |

Reconcile discovered routes against runtime feature gates in Pass 1. Freeze the
denominator before reporting a completion percentage: total in-scope journeys,
routes, actions and applicable states. New findings are added; removals require a
dated scope decision and rationale. A missing backend or runtime credential is
`blocked`, not silently removed or counted as passed.

## Must-ship experience inventory

- Identity: landing/catalog entry, login, registration/consent, verification,
  password recovery, OAuth callback/recovery, session expiry and onboarding.
- Learner: Today/home, My learning, Discover/program overview, course/module
  entry, activity lifecycle, progress, profile, settings/theme, notifications,
  calendar and certificates **only to their existing implemented and authorized
  capabilities**. Unsupported actions have honest recovery, not pretend content.
- Learning workspace: authorized lesson player; persistent playback where
  appropriate; Watch -> Reflect -> Implement -> Review -> Improve; safe draft,
  save/retry/conflict behavior; server-determined evidence and progress.
- Operator: existing admin shell, catalog, people/correction/grant operations,
  learning operations, Academy Studio Today/content readiness and program/version
  visibility. Reads and mutations retain named server permissions and audits.
- Universal: expanded/collapsed desktop sidebar, mobile navigation, search/help,
  overlays, empty/error/access-denied, legal pages, offline and update recovery.

No decorative score, streak, badge, unread count, availability, certificate,
coach decision or deadline is invented. Feedback and motion may celebrate only
the actual authorized event. Full B2B, billing, native applications, voice,
real-call processing and autonomous official AI scoring stay outside this Alpha
consolidation. Responsive/PWA and adapter boundaries prepare for future native
work; they do not constitute tested native apps.

## Acceptance metrics

These are targets. Blank/unknown results do not pass. `pass`, `fail`, `blocked`,
`pending`, and justified `not_applicable` remain distinct.

| ID                            | Required result                                                                                                                                                                                                                                                                     | Measurement / evidence                                                                                                                                                                                                                                                                                                                               |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A01 Scope and preservation    | 100% of discovered product routes classified; 100% of must-ship actions/states mapped; zero lost existing changes                                                                                                                                                                   | Route/capability inventory, diff reconciliation, exact source/asset provenance and component ownership                                                                                                                                                                                                                                               |
| A02 Functional journeys       | 100% of must-ship acceptance scenarios pass on exact candidate; zero fake success or state                                                                                                                                                                                          | Behavioral/component/API tests plus authenticated end-to-end results, with fixture and live results separated                                                                                                                                                                                                                                        |
| A03 Responsive composition    | Zero unintended page-level horizontal overflow, inaccessible controls, clipped primary actions or overlapping navigation at 320, 360, 390, 768, 1024, 1440 and 1920 CSS px                                                                                                          | Automated layout checks for all included route families; human comparison at mobile/desktop, each breakpoint-changing composition, long-content cases and keyboard-open viewport                                                                                                                                                                     |
| A04 Accessibility             | Zero known critical/serious automated findings and zero unresolved task-blocking keyboard/focus/reflow defects on audited routes                                                                                                                                                    | Named audit coverage; 200% text zoom and 320-CSS-px reflow; keyboard/focus/dialog restoration; accessible labels; light/dark contrast and reduced-motion checks. Not a blanket WCAG certificate                                                                                                                                                      |
| A05 Visual coherence          | Zero open Important visual/interaction findings; each of hierarchy, brand consistency, readability, recovery clarity and responsiveness rated at least 4/5 by an independent reviewer                                                                                               | Before/after selected-reference comparisons and concrete findings. Subjective ratings are design judgments, not user-research proof; Dipak's approval remains a separate human outcome                                                                                                                                                               |
| A06 Lab speed                 | Production-build representative routes: median LCP <= 2.5 s and CLS <= 0.1 across five cold-load runs per declared mobile/desktop profile; p95 observed interaction-to-next-paint <= 200 ms across >=30 scripted meaningful interactions per profile                                | Record build SHA, browser/version, viewport, CPU/network, route/data state, cache, each sample and transferred bytes. Include `/home`'s mounted DashboardRuntime, not an unused similarly named loader. Report failures and distribution; do not label these field INP/p75                                                                           |
| A07 Runtime/bundle discipline | Optional dashboard panels cannot block the main task; no stuck navigation feedback; selected optimized runtime assets only; no unexplained >5% critical-route JS/CSS transfer regression from baseline                                                                              | Deferred-promise/navigation-cancellation tests, actual network traces and same-profile production-build comparison; justify unavoidable variance and re-review                                                                                                                                                                                       |
| A08 PWA and work safety       | First install, offline reload, reconnect, deep link and update-with-dirty-work scenarios all pass in production mode; zero protected API cache entries or unsupported queued mutations                                                                                              | Service-worker-enabled browser tests, safe-area/keyboard checks; clearly separate emulated and real device evidence                                                                                                                                                                                                                                  |
| A09 Security/data invariants  | 100% relevant tenant/role/session/CSRF/consent/idempotency and stale-response negatives pass; zero canonical progress derived from analytics or client presentation                                                                                                                 | Existing security/contract suites plus targeted changed-path tests; no raw SQL recovery or bypassed account access                                                                                                                                                                                                                                   |
| A10 Engineering quality       | All required lint/typecheck/unit/integration/build/CI checks pass for exact SHA; zero open Critical/Important release defects on included capabilities                                                                                                                              | Reproducible commands/results, independent review, retests; a string-matching test alone cannot prove runtime behavior                                                                                                                                                                                                                               |
| A11 Release documentation     | Every published version has exact SHA/artifact/rollback identity, included capabilities, known limits, and verified before/after/live screenshot records in the existing Drive ledger                                                                                               | Capture each distinct changed route/state family in desktop/mobile, plus material theme/overlay/error variants; record time, viewport, environment, data provenance, path/hash, Drive file/parent ID and verified readback                                                                                                                           |
| A12 Environment promotion     | Exact tested artifact healthy on staging; production independently passes DNS/ingress/Access, secrets/bootstrap/provider, migration, backup/restore, auth/health/smoke and rollback gates before promotion                                                                          | Environment-specific results. No whole-platform/live-production declaration while production is absent or a must-ship journey is blocked                                                                                                                                                                                                             |
| A13 VPS video streaming QA    | A few explicitly licensed high-quality test videos (at least two, including a 4K source) are downloaded with provenance, processed and bound through authorized application commands to a clearly labeled staging test version; all required playback/control/access scenarios pass | Source URL/license/attribution/hash; upload/processing/binding audit; VPS-served media/manifest evidence; play/pause/seek/resume, speed, volume/mute, captions where supplied, fullscreen, quality switching where ABR exists, keyboard/mobile/reduced motion, expired/revoked/wrong-tenant access, stalls/reconnect and bounded concurrency results |

Project touch targets aim for 44 CSS px on primary mobile controls; applicable
WCAG 2.2 AA minimum-target rules and exceptions must still be evaluated. Reflow
and target-size references: [W3C reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html),
[W3C target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

Field performance target, when authorized data and sufficient samples exist:
mobile/desktop p75 LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1. Lab evidence is not
field validation, and Lighthouse TBT is not INP. If field data is unavailable,
record `not_measured`, retain the lab release gate and a separately authorized
post-release observation plan. Do not activate telemetry/consent processing just
to populate this metric. Source: [Google Web Vitals](https://web.dev/articles/vitals),
checked 2026-09-07.

## Known baseline and capability gates — September 7

- Staging is healthy at `31aee3ce5915e476c08a722f8b28768b49b514cf`;
  the existing dirty UI patch and new brand kit are not yet deployed.
- Package integrity checks passed: learning 1,272/1,272 listed hashes and brand
  706/706. This establishes consistency, not copyright/business/runtime approval.
- Full actual lesson playback remains unproven until approved source, upload,
  processing/binding and playback/evidence checks pass. ZIP demonstration videos
  cannot close this gate. Presentation polish can ship separately; the complete
  learning journey cannot be labeled finished without this proof.
- Production has no application DNS/ingress, runtime or configured application
  secret set. Production admin Access and provider/bootstrap evidence are absent.
- Backup readiness is not green: daily foundation/weekly restore jobs encounter
  shared-lock contention, and a recent off-host logical snapshot failed. Preserve
  sanitized diagnostics; repair through reviewed repository-controlled operations.
- `configure-cloudflare.ps1` replaces the entire tunnel ingress array; it must not
  be used as an additive host-adder in its current form.

### Added user decision — licensed test media

The user authorized downloading a few open-source/openly licensed 4K or other
high-quality videos for VPS streaming and player testing. Record the actual
redistribution/derivative license; availability to download alone is insufficient.
Use synthetic/public footage, not real sales calls or private learner content.
Label it test media in the course's staging test content/version; preserve pinned
published instructional versions and do not impersonate Dipak's actual teaching.
Staging test-video acceptance is distinct from readiness of the real course media.

Use existing asset-ingestion, processing, authorized binding and playback seams;
implement missing pieces in the repository rather than manually editing the DB.
Preserve storage/provider adapters, server authorization and versioned evidence.
Measure VPS disk/CPU/network headroom before choosing source sizes or concurrency;
avoid running unbounded load or transcoding alongside production services. Keep
masters outside initial app delivery. Test adaptive delivery if implemented;
otherwise record the capability gap rather than calling progressive MP4 adaptive
streaming. Each failure has a retry/recovery path and no false watch completion.

These findings do not authorize weakening gates. They determine the next
capability-specific implementation/operational slice. Staging deployment remains
available through the existing checksum-verified `Deploy-Staging.ps1` path after
candidate review and applicable pre-deployment checks.

## Goal and maintenance status

The persistent thread already has an unfinished release-program goal and reports
`usageLimited`. On September 7, `create_goal` refused this replacement because
the existing goal is unfinished. Do not mark it complete to bypass that rule.
This contract and scorecard are the current measurable Alpha delivery plan;
they do **not** claim that the app's persistent goal was replaced or resumed.

`workflow-ui-production` was revised under the user's authorization to separate
exploration, implementation and release modes; make artifacts proportional;
verify mounted runtime paths; add measurable responsiveness/performance/PWA
checks; distinguish fixture/local/staging/production evidence; and use scoped,
validated improvements based on observed weaknesses. Iteration count cannot
waive acceptance. Skill validation and behavioral forward-test evidence are
recorded with this workstream.
