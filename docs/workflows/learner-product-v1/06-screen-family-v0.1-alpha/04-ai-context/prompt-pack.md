# AI design and implementation prompt pack

Use these prompts only with the exact source manifest and state matrix attached.
The matrix outranks any generated visual. Do not ask a model to fill a semantic
gap with plausible product behavior.

## Prompt 1 — Screen family exploration

> Using `AC-WF-LEARNER-SF-V0.1A`, `screen-inventory.md`, and the full state
> matrix, explore exactly three independent desktop/mobile visual directions
> for the learner screen family. Keep behavior identical across directions.
> Show the shell, Dashboard/home, My Learning, Discover, program/module path,
> activity, Progress/insight, Profile/Settings, and one recovery state. Do not
> invent paid access, scores, mastery, provider details, plans/deadlines,
> notifications, or data values. Preserve explicit loading/empty/error/offline/
> locked/processing distinctions and non-color status. Return direction IDs,
> frame IDs, and a comparison table; do not select a direction.

## Prompt 2 — State-family expansion

> For screen ID `<SCREEN_ID>`, implement only the states listed in
> `state-transition-matrix.csv`. Retain shell chrome, preserve safe input,
> name the canonical source and recovery owner, and distinguish missing from
> zero. Use the same route and actor semantics. Do not add a state because it
> looks polished; add only a state that changes action, data safety, or
> recovery. Flag any missing API, provider, policy, or approved asset as a
> gate instead of fabricating a result.

## Prompt 3 — Accessibility and responsive review

> Review the selected/reference state family against WCAG 2.2 AA intent,
> Focus Not Obscured, Target Size Minimum, keyboard order, accessible names,
> error association, status announcements, 200% zoom/reflow, 390px mobile,
> safe areas, reduced motion, captions/transcript status, and non-color
> communication. Verify Light/Dark/System and forced/high-contrast behavior
> without changing access, progress, consent, notification, or session state.
> Report evidence and gaps; do not claim compliance without observed test
> results.

## Prompt 4 — Implementation handoff

> Treat the state matrix as the source of implementable behavior. Build shared
> components for shell, cards, activity rows, status banners, forms, focus
> management, plan horizon containers, progress summaries, avatar crop, and
> certificate status. Keep route IDs and state names unchanged. All mutations
> are server-authorized and idempotent where the controlled contract says so;
> local caches/drafts are allowlisted, owner-scoped, stale-labeled, and never
> canonical. Leave a test/evidence reference for every changed state. Stop and
> record a gap when a provider, access, scoring, schedule, or policy detail is
> not present in the attached controlled sources.
