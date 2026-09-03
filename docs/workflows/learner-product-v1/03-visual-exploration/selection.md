# Visual selection

Status: **selected implementation direction; individual screens still require
paired desktop/mobile state designs and visual QA**

Founder selection update (2026-09-02): the four packaged
`founder-selected-dashboard-*-v1.png` references are the visual contract for
the responsive Dashboard. Their shared composition—premium white/navy/cobalt
shell, prominent continue-learning media, compact course/discovery rows,
desktop side rail, and mobile bottom navigation—overrides earlier lower-density
Dashboard explorations. `public-entry-command-center-v1.png` is selected for
the public entry route so the signed-out and signed-in experiences feel like
one product.

## Selected system

Use a disciplined hybrid with one authoritative visual language:

- **Direction A — Learning Command Center:** global light app shell, desktop
  sidebar/header, compact navigation, Dashboard composition, Profile/Settings/
  Notifications inheritance, and planning hierarchy.
- **Direction B — Skill Journey:** My Learning, course/module progression,
  `Your next move`, and deterministic low-typing practice patterns.
- **Direction C — Content Studio:** dedicated player, captions/transcript/resume
  composition, Discover artwork, and media/library density after the provider-
  neutral media contract exists.

Direction A's warm-white/navy/cobalt visual grammar remains authoritative. B
and C contribute bounded component and content patterns; they do not introduce
competing navigation, typography, radius, color, or icon systems.

## Why this was selected

Independent reviewers consistently found:

- A has the clearest scalable product IA and strongest global dashboard shell.
- B best answers the core learning problem and most safely reuses the existing
  five-step activity topology.
- C has the strongest media presentation but carries the highest API,
  performance, and unsupported-data risk if used as the whole product.

One accessibility review ranked B first because it makes the next action and
prerequisites clearest. One design review ranked A first because it scales best
across non-course routes. The selection resolves that difference by assigning
A to the global application and B to the learning subsystem.

## Accepted elements

- A: persistent wide rail; compact utility header; five-item mobile bottom bar;
  retained shell during loading; continue-learning priority; balanced density.
- B: authored journey stages; explicit complete/current/locked states; choice,
  ordering, matching, branching, evidence-chip, and confidence interactions.
- C: 16:9 player; resume; captions; transcript; up-next only in the player;
  restrained visual discovery cards.

## Rejected or gated elements

- Unsupported calendars, live coaching, role-play sessions, weekly schedules,
  course counts, time-spent charts, or lesson metrics.
- Fake percentages, ratings, enrollment counts, mastery, scores, ranks, points,
  badges, streaks, reward currency, or leaderboards.
- Player controls, captions, transcripts, saved resources, or resume claims
  before their APIs and assets exist.
- Paid-course access, purchase prompts, or notification mutations before their
  controlled entitlement/commerce/notification contracts exist.
- Carousels without keyboard controls, reflow alternatives, and explicit scroll
  affordances.

## First bounded implementation slice

1. Implement the shared light shell: wide rail/header, compact bottom nav,
   avatar/account menu, active states, skip link, focus behavior, safe areas.
2. Add real routes for `/learning`, `/discover`, `/notifications`, and
   `/profile` without copying unsupported data into them.
3. Keep current canonical data and actions; use honest empty/informational states
   for capabilities whose APIs are not yet present.
4. Replace generic full-page loading with shell-retaining, route-shaped
   skeletons and in-flight request deduplication/cancellation where safe.
5. Add a bounded, encrypted, owner-scoped IndexedDB read cache for explicitly
   allowlisted learner display projections. It is a stale/offline fallback,
   never canonical authority, and is purged on sign-out or identity loss.
6. Localhost may read the exact staging published catalog anonymously;
   protected data and mutations remain staging-origin-only and never reuse
   staging cookies on localhost. Visual acceptance uses the real app routes,
   not a separate fixture preview.
7. Do not implement the media player, avatar upload mutation, new activity
   schemas, durable notifications, analytics, or commerce in this slice.

## Required QA

- 1440x1024 and 390x844 reference/implementation composite comparisons.
- 320px, 375px, 768px, 1024px, 1280px, 200% zoom, long copy, Windows scaling,
  and iOS safe-area checks.
- WCAG 2.2 AA intent, visible focus, non-obscured focus, non-color state labels,
  keyboard operation, reduced motion, and 44px preferred mobile targets.
- Page and section default/loading/empty/retry/offline/permission/locked/partial/
  success states as relevant.
- Offline cache allowlist/denylist, AES-GCM ciphertext, owner isolation,
  retention, tamper/expiry cleanup, fail-closed 401/403/404/409, and logout purge.
- Local VPS preview blocks every mutation and private endpoint, strips browser
  credentials, and accepts only the exact staging API origin.
