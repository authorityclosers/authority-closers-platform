# QA and release checklist

Status: **reference-ready for behavioral handoff; not production-approved**.

## Structural package gate

- [ ] All JSON parses with a strict parser.
- [ ] State matrix parses with 17 required columns and no malformed rows.
- [ ] Every flow and screen ID is unique and cross-referenced by inventory,
      matrix, AI context, and diagram.
- [ ] Every matrix row has an actor, trigger, visible structure, primary
      action, system response, recovery, source of truth, and QA status.
- [ ] Every primary action has a success or failure/recovery behavior.
- [ ] No matrix row claims a provider, payment, access, scoring, schedule, or
      certificate result without a named controlled source.
- [ ] Asset manifest reflects zero generated visuals and no unverified links.

## Behavioral/state gate

- [ ] Shell retains context during route-shaped loading.
- [ ] Empty, unavailable, partial, stale, locked, permission-denied,
      processing, and terminal states are distinct where applicable.
- [ ] Auth and recovery are existence-neutral and preserve safe return intent.
- [ ] Onboarding uses bounded fields and revision-aware save/retry/conflict.
- [ ] Session expiry returns to the exact route/step and preserves supported
      drafts; sign-out purges owner-scoped local state.
- [ ] Catalog preview is read-only; explicit free enrollment remains server
      authorized and payment-independent.
- [ ] Activity loop uses configured prerequisites and canonical evidence; no
      client-only completion, mastery, rewards, ranks, or autonomous scoring.
- [ ] Progress distinguishes missing from zero and analytics from canonical
      facts.
- [ ] Plan horizons do not invent dates, reminders, deadlines, or appointments.
- [ ] Notification read state is idempotent and separate from delivery
      preferences/consent.
- [ ] Avatar processing retains the current avatar until success and
      supersedes history safely.
- [ ] Certificate wording distinguishes course completion from competency.

## Accessibility and responsive gate

- [ ] WCAG 2.2 AA intent is tested at component and journey level.
- [ ] Controls have accessible names, labels, error association, keyboard
      operation, visible/non-obscured focus, and sensible focus return.
- [ ] Statuses use text/icon/semantics in addition to color; charts have text
      equivalents; unknown is distinct from zero.
- [ ] Comfortable learner touch targets are approximately 44 CSS px where
      practical, while the exact WCAG target-size criterion and exceptions are
      tested.
- [ ] 320/375/390/768/1024/1280 widths, 200% zoom, long copy, safe areas, and
      reduced motion are checked.
- [ ] Media controls, captions, transcript, orientation, and control occlusion
      are tested before media capability is activated.
- [ ] Light/Dark/System theme mode, named presets, accent, density, motion, and
      storage failure are tested; System follows the device signal without
      server mutation or first-paint flash. All appearance values remain
      browser-local and cannot affect account, tenant, or authority state.

## Resilience/security gate

- [ ] Slow network, duplicate action, provider failure, offline, stale cache,
      interrupted draft, revision conflict, and expiry are injected.
- [ ] Offline data is allowlisted, stale-labeled, owner-scoped, bounded, and
      never used for protected mutation or authority.
- [ ] Authorization checks actor + tenant + resource + action server-side;
      locked/denied states do not expose protected payloads.
- [ ] Sensitive actions require recent auth/confirmation where controlled;
      no direct DB recovery is used.
- [ ] No secrets, tokens, raw provider errors, or unnecessary personal data
      appear in docs, events, logs, or visual prompts.

## Release evidence gate

- [ ] Exact commit SHA and environment are recorded.
- [ ] Unit/domain, API/contract, authorization/tenant, state-transition,
      accessibility, performance, and mobile/PWA evidence is attached.
- [ ] Exact-current browser/device screenshots are compared only after visual
      generation and a direction selection.
- [ ] Media, avatar, certificate, notification, plan, and any future commerce
      activation gates are each closed by their owning controlled evidence.
- [ ] Review status says `reference-ready` until the above evidence is complete;
      never call this package deployed or final from documentation alone.
