# Learner product v1 brief

## Outcome

Build a fast, premium, light-default learner application rather than a
free-course microsite. Desktop and mobile share product semantics but use
purpose-built navigation and composition.

## Product surfaces

- Dashboard
- My Learning
- Discover
- Progress and Analytics
- Notifications
- Profile
- Settings
- Course and module overview
- Activity workspace
- Premium media player
- Click-first practice activities
- Authentication, onboarding, recovery, policy, and offline states

## Experience rules

- Dashboard and My Learning are distinct routes and jobs.
- Desktop uses a persistent app sidebar and compact utility header.
- Mobile bottom navigation is `Home`, `Learning`, `Discover`, `Progress`,
  `More`; Profile, Settings, Notifications, and Help are available through the
  avatar/More experience.
- Light is the product default. Dark and System may remain later preferences.
- Loading uses route-shaped skeletons and retained shell chrome; a generic
  full-page “Loading your learning…” card is not an acceptable steady pattern.
- Progress reports deterministic completion evidence. Analytics is not
  canonical progress, payment, access, mastery, or scoring state.
- Post-video practice is click-first and low-typing. No autonomous scoring,
  fabricated mastery, or reward economy is authorized.
- Media delivery uses a provider-neutral port. The VPS is the first origin;
  later CDN/provider replacement must not change product routes or domain
  models.

## Delivery model

Each slice follows: source reconciliation -> three paired visual options ->
independent review -> selection -> contract update -> bounded implementation ->
tests and performance evidence -> exact-SHA CI/staging deployment -> smoke and
visual comparison. Work on the next visual slice can continue while the prior
slice is in CI, but no unverified build is described as live or final.

## Guardrails

All repository `AGENTS.md` guardrails apply. In particular: no inferred
protected business semantics; no production DB/VPS authority; no analytics as
canonical state; no autonomous AI scoring before AC-SVAL; no unsupported
provider/data activation before governance gates; and every code change leaves
tests and implementation evidence.
