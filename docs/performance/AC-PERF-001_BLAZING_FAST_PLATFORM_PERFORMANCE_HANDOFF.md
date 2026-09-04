# AC-PERF-001 — Blazing-Fast Platform Performance Handoff

**Status:** Proposed execution specification

**Date:** 2026-09-04

**Audience:** Authority Closers engineering agents, product/UX, QA, DevOps, and leadership
**Scope:** Public learner catalog, authenticated learner navigation/data delivery, admin access boundary, assets, telemetry, and staged performance experiments

## Executive decision

The platform should optimize for a fast-feeling, measurable experience rather than promise literal few-millisecond global page loads. The contract is:

- A user action is acknowledged immediately in the UI (target under 100 ms where the browser can do so).
- Public and authenticated learner routes are delivered in phases with explicit criticality, not one all-or-nothing loading state.
- Core Web Vitals are the field outcome: p75 LCP at or below 2.5 s, INP at or below 200 ms, and CLS at or below 0.1.
- Private access, progress, payment, entitlement, tenant, and audit state remain server-authoritative. Performance work must not weaken those boundaries.
- Every optimization ships behind a measured control/treatment, a kill switch, and a correctness guardrail.

The first high-confidence wins are media delivery and protected-route prefetch control. The next tier is a small public catalog read model/cache and a bounded private learner bootstrap. Microservices, Redis, read replicas, full browser OpenTelemetry, and aggressive speculative prefetch are not justified by the current evidence.

## Evidence snapshot

Measurements below were collected on 2026-09-04 from the `ac` SSH target and Playwright against the proper AC staging domains. They are diagnostic baselines, not a production SLO and not a substitute for authenticated field RUM.

| Surface                 |                                     Cold browser observation |                SSH response observation | Interpretation                                                                              |
| ----------------------- | -----------------------------------------------------------: | --------------------------------------: | ------------------------------------------------------------------------------------------- |
| Public learner home     | DOM loaded 1.43 s; network idle 3.51 s; 3.26 MiB transferred | HTTP 200; TTFB 0.65 s; 23,763-byte HTML | The visible page is usable before all assets settle, but two PNGs dominate the transfer.    |
| Learner Discover        | DOM loaded 0.99 s; network idle 3.39 s; 0.41 MiB transferred | HTTP 200; TTFB 0.70 s; 29,770-byte HTML | Route shell is reasonably light; unauthenticated protected requests still fail.             |
| Learner Learning        | DOM loaded 0.98 s; network idle 3.67 s; 0.41 MiB transferred |                  Not separately sampled | Warm route shell is fast, but protected prefetch/API failures add noise.                    |
| Warm learner navigation |             Discover→Learning client navigation about 0.35 s |                                       — | Existing client navigation is promising; preserve it while reducing unneeded work.          |
| Admin root/catalog      |            Cloudflare Access login observed; app not reached |             HTTP 302; TTFB about 0.31 s | Admin performance is unverified until an authenticated Access browser session is available. |
| API health/ready        |                                                            — |        HTTP 200; TTFB about 0.65–0.68 s | Origin/network latency is material; do not hide it with client over-fetching.               |

### Current high-cost resources

On the public home baseline, the hero PNG transferred about 1.37 MB and the visible module-card PNG about 1.68 MB. Together they were about 89% of the measured 3.26 MiB transfer. A local, in-memory encoding experiment produced illustrative WebP sizes of about 25 KB and 45 KB for those two images. If visual and browser-compatibility QA passes, the modeled initial transfer would fall by roughly 87–88%. This is a simulation, not a deployed measurement.

The image transform response currently returns `image/png` with a content length of about 1.37 MB and a four-hour public cache directive. The asset pipeline should explicitly negotiate modern formats and responsive widths; it should not assume that an image transform endpoint alone creates a small payload.

### Current client behavior that matters

- `apps/learner-web/app/components/public-catalog-home.tsx` is a client component that calls `listPrograms(50)` on mount. The public hero is marked `priority`; a module-card image can also enter the initial viewport. This explains why image delivery is the first optimization lane.
- `apps/learner-web/app/components/site-shell.tsx` renders protected sidebar links without an explicit prefetch policy. Next production `<Link>` prefetching can request routes as links enter the viewport. The live anonymous learner run observed protected RSC prefetch failures and 401s for routes such as Discover, Settings, Notifications, and Progress.
- `apps/learner-web/app/lib/learner-api.ts` already has useful single-flight GET deduplication, `cache: "no-store"` for API calls, offline-cache allowlisting, 401/403 private-cache purge, idempotency keys, and `If-Match`. These are safety properties, not obstacles; preserve them.
- `apps/learner-web/public/sw.js` deliberately excludes protected `/v1/` API paths from its offline cache. Do not broaden that allowlist without an explicit privacy and ownership review.
- The deployed Discover observation did not expose a tag-editing or tag-filter control. Do not infer tag semantics from this run. When tag/filter interactions are introduced or enabled, instrument them as a separate route-scoped experiment.

## Performance architecture

### 1. Phase every route by user value

Use the following loading contract for every learner/admin surface:

```text
T0 critical   HTML shell, CSS, above-fold text, dimensions, auth/capability boundary, primary CTA
T1 interactive current route read model, current activity, progress summary, visible controls
T2 intent     next route/data only after authenticated intent or a safe, measured signal
T3 idle      below-fold media, avatars, secondary panels, non-blocking RUM delivery
T4 deferred  heavy AI/media/analytics/admin extras and work not needed for the current intent
```

T0 must never wait on T3/T4. T1 must render a stable skeleton or partial state with an explicit retry path. A control should enter a pending/committed state synchronously; show a spinner only when the operation crosses a short delay budget, and never replace the entire page with a global overlay for a local action.

Each phase needs a route-level budget and an owner. “Loaded” must be defined as the route’s interactive contract being satisfied, not as network idle. Network idle remains a diagnostic signal only because analytics, retries, prefetches, and third-party activity can keep it open.

### 2. Protected navigation: intent-gated prefetch

Make the protected navigation policy explicit in `LearnerNavLink`:

1. Default protected links to no automatic prefetch.
2. On authenticated user intent (pointer hover with a short dwell, keyboard focus, or deliberate touch intent), allow at most one route prefetch when the connection is suitable and the route is not already cached/in flight.
3. Do not prefetch protected RSC/data for anonymous users. Do not prefetch on `saveData`, offline, or obviously constrained connections.
4. Keep public catalog prefetch separate from private learner prefetch.
5. Use the existing request deduplication and private-cache purge behavior; an optimization must not create a second cache or a second authority.

This is directly motivated by the live 401/RSC failures and by Next’s documented viewport prefetch behavior. The implementation should prefer the smallest policy change first: an explicit `prefetch={false}`/equivalent for protected links, followed by an intent experiment. Do not add a custom speculative scheduler before the baseline and guardrails exist.

### 3. Read models without changing authority

Keep the modular monolith, FastAPI, SQLAlchemy/PostgreSQL, durable outbox/jobs, and existing access/provider gates. Add read-shaping only where measurements show over-fetching or serial waterfalls.

Recommended boundaries:

- **Public catalog summary:** published program/module summaries, public media references, ordering, and version identifiers only. It must contain no user, tenant-private, entitlement, payment, progress, or access decision. It may use ETags and a scoped edge cache after publish invalidation is defined.
- **Private learner bootstrap:** identity/session capability state plus the minimum route-specific learning summary and next action needed for the first interactive view. It must not become a hidden entitlement authority or a giant “return everything” endpoint.
- **Route detail:** fetch the activity/module detail required by the current route, with pagination or bounded fields. Keep large media and secondary panels out of the bootstrap.

The current dashboard path appears to make several reads in sequence (`me` → onboarding → programs → learning → optional calendar). Treat this as a hypothesis. Compare serial, safe-parallel, and bounded-bootstrap variants with contract tests. Parallelize only reads whose authorization, tenant context, and error semantics are independent. If a response combines state, document the source fields and canonical owners.

For API/DB work, require projection queries, pagination, index/explain evidence, N+1 checks, bounded response sizes, and measured pool behavior. Do not introduce a new datastore to compensate for an unmeasured query or payload problem.

### 4. Media pipeline

- Use intrinsic dimensions or static imports so layout is reserved before image decode.
- Serve responsive widths; keep `sizes` accurate to the actual layout.
- Serve AVIF/WebP where supported, with a safe JPEG/PNG fallback. Cloudflare Image Transform supports format negotiation via `format=auto`; validate the returned content type and bytes in staging.
- Keep `priority`/preload limited to the actual LCP candidate. Defer below-fold cards and secondary media.
- Give every image a stable aspect ratio and a deliberate placeholder.
- Load video players and posters in phases. Real-call media remains gated by consent, retention, provenance, provider, and professional controls; performance work does not activate that capability.

The local encoding experiment must be followed by visual regression, browser compatibility, cache-key, and accessibility checks before rollout.

### 5. Edge and cache policy

The learner home and APIs currently present dynamic/no-store behavior. This is a safe default for private state, but it means public delivery needs an explicit split:

- Immutable, content-addressed public assets: long-lived public caching with hashed URLs.
- Anonymous public catalog summaries: only after the response is proven free of private/access state; use ETag or scoped `s-maxage`/stale-while-revalidate policy and publish-triggered invalidation.
- Authenticated learner/admin HTML, RSC, APIs, access redirects, progress, payment, and entitlement: no shared cache. Preserve private/no-store semantics unless a documented owner-safe design proves otherwise.

Cloudflare’s cache documentation distinguishes reusable public responses from per-user or non-idempotent responses. Use that distinction as the review rule; never cache an auth response merely because it is fast to serve.

### 6. Telemetry and adaptive scheduling

The repository already has server-side OpenTelemetry collector wiring and Prometheus export. Add a bounded browser layer rather than making a full experimental browser OTel SDK a critical dependency.

Record route-template and interaction measurements, sampled and free of query strings, tokens, message bodies, or unnecessary personal data:

```text
ac.route.start        route template, navigation type, connection class
ac.route.ready        route template, ready phase, duration, outcome
ac.interaction.commit action name, route template, duration, outcome
ac.resource.summary   route template, bytes, request count, largest resources
ac.media.first_frame  media kind, route template, duration, outcome
```

Prefer `PerformanceObserver`/the small `web-vitals` package for Web Vitals and `navigator.sendBeacon` to a first-party endpoint with sampling, batching, size limits, and a kill switch. Propagate correlation IDs/trace context to the server where supported. Telemetry is evidence only: it must not become canonical progress, payment, entitlement, access, or official assessment state.

The live run also found a Cloudflare Insights beacon blocked by the app’s CSP. Resolve this as a controlled telemetry integration decision: either allow the required source after a CSP report-only review and data/retention check, or use the existing first-party RUM path. Do not duplicate uncontrolled beacons or put provider tokens in documentation, logs, or client state.

Adaptive prefetch should be an experiment, not a permanent inference engine. Start with a simple allow/deny policy using route intent, authentication state, connection quality, `saveData`, and one-request budget. Aggregate results by route/cohort; never make per-person protected inferences authoritative.

## Experiment plan

Every experiment needs a named control, one primary metric, correctness guardrails, sample/traffic scope, exposure logging, and a rollback switch.

| ID                | Control vs treatment                                                     | Primary measure                            | Guardrails                                                         |
| ----------------- | ------------------------------------------------------------------------ | ------------------------------------------ | ------------------------------------------------------------------ |
| E1 Media          | Current PNG vs negotiated WebP/AVIF, responsive sizing, below-fold defer | p75 LCP and initial transfer bytes         | CLS ≤0.1, visual parity, alt text, no broken fallback              |
| E2 Navigation     | Default Next prefetch vs explicit protected no-prefetch + intent         | route-ready latency after deliberate click | zero anonymous protected prefetches/401 noise; no access leakage   |
| E3 Learner data   | Current serial reads vs safe parallel vs bounded bootstrap               | T1 route-ready duration                    | exact contract, tenant isolation, authz, canonical state unchanged |
| E4 Public catalog | Dynamic/no-store summary vs ETag/scoped edge cache                       | cache hit/origin work and route-ready time | published-version correctness; no private fields                   |
| E5 Scheduler      | Static intent policy vs connection-aware one-prefetch policy             | unused prefetch rate and click latency     | max one speculative request; no save-data/offline prefetch         |
| E6 Telemetry      | Current CSP-blocked beacon vs approved first-party/Cloudflare path       | delivered Web Vitals coverage              | no CSP console error, bounded payload, retention/PII approval      |

### Modeled media impact

The following numbers are directional planning evidence from local Pillow re-encoding, not acceptance results:

| Asset pair                                    | Current measured PNG bytes |                    Modeled WebP bytes |               Modeled reduction |
| --------------------------------------------- | -------------------------: | ------------------------------------: | ------------------------------: |
| Hero + visible module card                    |                  3,052,659 |                                69,922 | 97.7% for those two image files |
| Home total including other measured resources |                  3,420,964 | about 438,227 if both images are WebP |               about 87.2% total |
| Home total with hero WebP and card deferred   |                  3,420,964 |   about 393,105 modeled initial bytes |               about 88.5% total |

The pair-level percentage is not the page-level percentage. Do not use these modeled values as a production promise; remeasure with the browser, visual QA, and field data.

## Agent-ready work queue

Workstreams are intentionally separable. Each agent must attach implementation evidence, tests, and before/after measurements to its work item. No workstream may change business semantics as a “performance improvement.”

| Work item     | Capability                  | Likely scope                                                   | Definition of done                                                                                                          |
| ------------- | --------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| PERF-WEB-001  | Asset pipeline              | learner public media components, image transform/config        | Modern-format negotiation, responsive sizes, stable dimensions, visual regression, byte report, rollback flag               |
| PERF-WEB-002  | Protected navigation        | `site-shell.tsx`, link policy, route prefetch tests            | Anonymous protected prefetch eliminated; intent path bounded; auth/private cache behavior preserved                         |
| PERF-WEB-003  | Loading UX                  | route `loading.tsx`, Suspense boundaries, local pending states | T0/T1/T2 contract documented; no global blocking overlay; keyboard/reduced-motion/accessibility checks                      |
| PERF-API-001  | Public/private read shaping | public catalog summary and bounded learner bootstrap proposal  | API contract, owner fields, authz tests, payload budget, failure/retry semantics, no new authority                          |
| PERF-DB-001   | Query evidence              | measured query paths only                                      | EXPLAIN/query-count/N+1 evidence, indexes justified, pool behavior recorded; no direct operational SQL edits                |
| PERF-EDGE-001 | Cache/CSP                   | public headers, immutable assets, telemetry CSP decision       | Cache matrix reviewed; private routes remain no-store; no auth redirect caching; CSP errors resolved or explicitly deferred |
| PERF-OBS-001  | RUM and correlation         | browser performance marks, first-party ingest, server spans    | Bounded schema, sampling, redaction, trace correlation, dashboard/query, kill switch; telemetry remains non-canonical       |
| PERF-QA-001   | Performance harness         | Playwright/SSH staging runner                                  | Cold/warm mobile+desktop runs, route budgets, JSON artifacts, visual checks, authenticated-path fixture requirement         |
| PERF-OPS-001  | Release/rollback            | staging config, dashboards, rollout notes                      | Feature flags, canary/rollback procedure, alert thresholds, owner/runbook, evidence archived                                |

### Suggested sequencing

1. **P0 — Measure and contract:** land the runner, route budgets, RUM schema decision, and test fixtures. No architectural cache change yet.
2. **P1 — Highest-ROI learner wins:** ship E1 and E2 behind flags: modern media and protected prefetch policy.
3. **P2 — Public delivery:** implement the public summary/read model only if E1/E2 leave origin/API work as the limiting factor.
4. **P3 — Authenticated learner route:** test route-level loading and the bounded bootstrap against the current serial path.
5. **P4 — Data-path tuning:** use query/payload evidence to optimize projections, pagination, indexes, and pool settings.
6. **P5 — Telemetry/adaptation:** enable field RUM and the one-prefetch scheduler only after data quality and privacy review.
7. **P6 — Hardening:** authenticated admin test, regression matrix, accessibility/reduced-motion pass, staged rollout, and rollback rehearsal.

Map these steps to the controlled AC implementation gates. G0/G1/G2 work remains the control plane, route/state freeze, and walking skeleton; performance work must not bypass those gates.

## Verification contract

### Browser and SSH test matrix

- Run on the `ac` target and proper domains only: `https://staging.authorityclosers.com` and `https://admin-staging.authorityclosers.com`.
- Use Playwright at mobile 390×844 and desktop dimensions, with cold context and warm repeat runs.
- Capture DOM-ready, route-ready, LCP/INP/CLS, request count, transfer bytes, largest resources, console errors, failed requests, and visible state.
- Use network idle for diagnosis, never as the sole definition of ready.
- Use an authenticated staging browser session for learner protected routes and Cloudflare Access for admin. An unauthenticated Access redirect is not admin-app performance evidence.
- Compare control and treatment with the same route, viewport, account/tenant fixture, and network profile.

### Release gates

The following are initial gates for the first performance slices:

- p75 LCP ≤2.5 s, p75 INP ≤200 ms, and p75 CLS ≤0.1 for the relevant public/learner route cohort.
- No protected RSC/data prefetch from an anonymous learner shell.
- No new 401/403/cross-owner cache behavior caused by navigation or offline changes.
- No CSP console errors for the approved telemetry path.
- Public initial transfer budget is measured and enforced. A starting hypothesis is 0.5–0.8 MiB for the public home, with hero ≤150 KB and a visible card ≤100 KB after format negotiation; adjust only from evidence and design fidelity.
- The first interactive contract is met without waiting for below-fold media, AI, analytics, or secondary panels.
- Every changed canonical state path has contract tests and an implementation evidence note.
- Rollback restores the control behavior without data migration or manual production DB/VPS state edits.

Targets are not permission to falsify or weaken correctness. If a gate fails, the affected capability is held while unrelated capabilities can continue, consistent with AC guardrails.

## Non-negotiable boundaries

- Do not cache authenticated/private HTML, RSC, APIs, progress, payment, entitlement, or access decisions in a shared cache.
- Do not couple payment-provider state directly to access as a latency shortcut.
- Do not turn RUM, analytics, prefetch exposure, or Web Vitals into canonical progress, payment, entitlement, or assessment state.
- Do not overwrite audit-critical history; supersede corrections.
- Do not activate real-call processing or media before consent, retention, provenance, provider, and professional gates.
- Do not introduce official autonomous AI scoring; AC-SVAL gates remain mandatory.
- Do not use direct SQL edits or manual VPS/production state as operational recovery.
- Do not infer tag, entitlement, score, tenant, retention, or completion semantics from the performance trace.

## Known limitations and next evidence

- This baseline is a small number of staging runs, not p75 production field data.
- No authenticated learner session was available in the browser run; protected route behavior needs a controlled fixture.
- Cloudflare Access blocked the admin app before its application shell, so admin performance is unverified.
- The non-privileged `ac` SSH user could not inspect Docker because access to `/var/run/docker.sock` was denied. No container-health claim is made here.
- A Chrome DevTools MCP/Lighthouse trace was unavailable in this session. The evidence uses Playwright timing/resource/console capture plus SSH `curl` timing and headers.
- The image re-encoding figures are local simulations and require visual regression, browser compatibility, cache, and accessibility QA.
- Tag/filter interaction is not represented in the observed public Discover surface; add a dedicated trace only when the controlled UI exists.

## Source ledger

### Controlled AC sources

The source order and exact Drive IDs come from the AC implementation handoff and local Knowledge Fabric cards. Use the exact IDs/URLs; do not fetch by guessed filename.

- [Master Index](https://docs.google.com/document/d/1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus/edit)
- [BRD](https://docs.google.com/document/d/1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk/edit)
- [PRD](https://docs.google.com/document/d/1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k/edit)
- [IA](https://docs.google.com/document/d/1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs/edit)
- [UX States](https://docs.google.com/document/d/10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E/edit)
- [UI System](https://docs.google.com/document/d/1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI/edit)
- [SRS](https://docs.google.com/document/d/1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g/edit)
- [Data and Tenancy](https://docs.google.com/document/d/1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw/edit)
- [API/MCP](https://docs.google.com/document/d/1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0/edit)
- [Security](https://docs.google.com/document/d/1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw/edit)
- [QA](https://docs.google.com/document/d/1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg/edit)
- [DevOps](https://docs.google.com/document/d/1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs/edit)
- [Admin](https://docs.google.com/document/d/12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY/edit)
- [Telemetry](https://docs.google.com/document/d/1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I/edit)
- [ADR/Risk](https://docs.google.com/document/d/1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY/edit)

Implementation handoff evidence used locally:

- `docs/architecture/G1_MODULAR_MONOLITH.md`
- `docs/architecture/G1_APPLICATION_WIRING.md`
- `docs/architecture/BENCHMARK_QUALITY_DOCTRINE.md`
- `docs/evidence/G1_IMPLEMENTATION_EVIDENCE.md`
- `apps/learner-web/app/components/site-shell.tsx`
- `apps/learner-web/app/components/public-catalog-home.tsx`
- `apps/learner-web/app/components/dashboard-runtime.tsx`
- `apps/learner-web/app/lib/learner-api.ts`
- `apps/learner-web/public/sw.js`
- `packages/python/ac_platform/outbox/repository.py`

### Primary technical references

- [Next.js prefetching](https://nextjs.org/docs/app/guides/prefetching)
- [Next.js Image optimization](https://nextjs.org/docs/app/getting-started/images)
- [Next.js caching without Cache Components](https://nextjs.org/docs/app/guides/caching-without-cache-components)
- [web.dev LCP](https://web.dev/articles/lcp), [INP](https://web.dev/articles/inp), and [CLS](https://web.dev/articles/cls)
- [OpenTelemetry browser JavaScript](https://opentelemetry.io/docs/languages/js/getting-started/browser/)
- [Cloudflare Image optimization](https://developers.cloudflare.com/images/optimization/features/)
- [Cloudflare cache](https://developers.cloudflare.com/workers/cache/)
- [Cloudflare Web Analytics CSP FAQ](https://developers.cloudflare.com/web-analytics/faq/)

## Handoff outcome

This document is the performance build specification and evidence ledger for the next agents. The next safe action is to implement and verify `PERF-QA-001`, then run `PERF-WEB-001` and `PERF-WEB-002` as controlled slices. No production deployment, data migration, payment/access change, or real-call/AI activation is authorized by this handoff.
