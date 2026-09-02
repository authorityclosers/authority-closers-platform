# Component and interaction contract

This is a semantic contract for implementation. It does not prescribe final
brand hex values, typography, icon family, or imagery; those remain subject to
the controlled UI system and the future three-direction visual gate.

## Shared primitives

| Component | Stable behavior | Required states / a11y |
| --- | --- | --- |
| `AppShell` | persistent desktop rail; mobile bottom nav; account/More surface; retained chrome during loading | active route text + icon; skip link; focus order; safe areas; keyboard; reduced motion |
| `RouteHeader` | page context, heading, optional back/help action | one `h1`; breadcrumb/back label where needed; focus not obscured |
| `NextActionCard` | one dominant resume/start/continue action sourced from canonical projection | disabled/loading/error text; no fake percent; action destination named |
| `ProgramCard` | published or owned program summary with explicit source | loading/empty/locked/partial; no access inference; full-card keyboard action |
| `ModuleCard` | module title, progress/lock status, prerequisite reason | icon + text; no protected payload for locked state |
| `ActivityRow` | authored order, activity kind, status, next action | current/completed/locked/loading/error; no hover-only affordance |
| `PlanHorizon` | Today/Week/Month container for canonical/authored plan items | empty/unavailable/stale; no invented date/deadline/cadence |
| `StatusBanner` | domain-specific status with safe action and optional trace reference | `role=status`/`alert` as appropriate; non-color icon/text; no raw provider error |
| `FormField` | label, hint, input, error, preserved value | explicit accessible name; error association; password manager/paste support |
| `AsyncAction` | idempotent command state and duplicate-submit guard | idle/processing/success/retryable/terminal; announce without focus theft |
| `ActivityWorkspace` | common context, renderer slot, save/submit area, recovery footer | dirty/saving/saved/offline/expired/conflict; safe leave warning |
| `MediaPlayerRegion` | activity-owned controls and transcript/caption/resume affordances | keyboard, captions, focus, full-screen, orientation, provider failure; gated until assets/policy |
| `ProgressSummary` | canonical completion counts and text equivalents | unknown distinct from zero; no mastery/rank/streak/reward |
| `InsightPanel` | descriptive analytics/read model with source/time label | stale/partial/unavailable; chart text equivalent; no canonical mutation |
| `NotificationRow` | safe title, read state, owned target, optional timestamp | target announced; read mutation separate/idempotent |
| `AvatarCropDialog` | local preview/crop then explicit submit; current avatar retained until success | focus trap only while open; Escape/cancel; keyboard crop alternative; file errors |
| `ThemeControl` | Light/Dark/System local preference with immediate preview | radio semantics; fallback on storage failure; no server call or authority effect |
| `CertificateStatus` | incomplete/processing/issued/denied/not-found state | course-completion wording; no competency/mastery claim |

## Responsive modes

| Mode | Composition | Acceptance intent |
| --- | --- | --- |
| Desktop (≥1024px candidate) | persistent rail + compact utility header + constrained reading column | no horizontal overflow; 200% zoom and keyboard usable |
| Tablet (768–1023px candidate) | collapsible/condensed rail or shell variant as approved | same IDs/actions; reflow without hidden state |
| Compact mobile (≤767px candidate) | bottom nav + full-width primary action + single-column activity | comfortable targets (~44 CSS px where practical); 390px and safe-area checks |
| Installed PWA / browser | same semantics with install-mode chrome differences | offline boundary, resume after background/termination, no native-store claims |

## State rendering rules

1. Route-shaped skeletons retain shell context; they never render fake zero or
   empty data while waiting.
2. Every primary action maps to a canonical response and named recovery in the
   matrix. Duplicate taps are disabled/debounced and server idempotency remains
   authoritative.
3. `partial`, `offline_or_stale`, `permission_denied`, and `locked` are not
   synonyms. The copy and allowed action must differ.
4. Inputs preserve safe local text across validation, retry, expiry, and
   supported offline states. Conflicts ask the learner to review; they never
   silently overwrite history.
5. Status is conveyed through text/icon/semantics, not color alone. Charts and
   progress controls have text alternatives.
6. Motion respects reduced-motion preferences. Theme application must not
   flash or move focus unexpectedly.

## Content/data rules

- Use real canonical content only after its source and version are attached.
- Use neutral placeholders labeled as placeholders when an approved asset is
  missing; never imply a provider, coach, score, plan, or certificate exists.
- Keep personal data private and self-scoped. Do not include emails, tokens,
  secrets, or raw provider details in event examples or visual prompts.
