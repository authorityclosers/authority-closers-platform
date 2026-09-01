# QA and release checklist

Status values:

- `[x]` package artifact check completed in this documentation task.
- `[ ]` implementation/runtime evidence required.
- `[~]` implementation candidate or accepted contract is present; exact-live
  runtime evidence remains pending.
- `[!]` blocked by a named gap.

This checklist separates **reference-ready** from **production-approved**. The
package can pass structural QA while every runtime checkbox remains open.

## A. Package integrity

- [x] All required package artifacts exist under the permitted root.
- [x] Every JSON artifact parses as strict JSON.
- [x] The transition CSV parses with one fixed header and no malformed rows.
- [x] `transition_id` values are unique and match `TR-{DOMAIN}-{NNN}`.
- [x] Every CSV `screen_id` exists in `ai-design-context.json`.
- [x] Every AI-context flow/screen ID appears in the behavioral spec.
- [x] Every journey ID used by the CSV exists in `journeys.md`.
- [x] Every local path in `asset-manifest.json` resolves inside this package.
- [x] No file was written outside `docs/workflows/v0.1-alpha-experience/**` by
      this documentation task.
- [x] No raw email, password, reset/verification token, OAuth code, cookie,
      provider payload, or secret appears in the package.

## B. Source and decision traceability

- [x] Master Index, BRD, AC-IMP-00/01/03/04/05 are registered with exact IDs.
- [x] PRD, IA, UX Research, UX States, UI System, SRS, Data/Tenancy, API,
      Security, Admin, Telemetry, Mobile/PWA, DevOps, QA, and ADR/Risk are registered.
- [x] AC-UXA-01 is registered for learner/admin/recovery/accessibility behavior.
- [x] Clarity Grid and every used screen reference have exact Drive IDs.
- [x] Facts, observations, current user decisions, and design inferences are
      visibly distinguished.
- [x] ADR 0028, the environment contract, self-attestation implementation, and
      current learner routes are registered as repository authority.
- [x] `/settings` and `/progress` are labeled implementation candidates/runtime
      pending rather than live.
- [x] Theme authority is limited to the current device-local implementation;
      account/cross-app synchronization is not invented.
- [x] Visual references are never described as runtime proof.
- [x] Supersession policy is append-safe in `decision-log.md`.

## C. Behavioral fidelity

- [x] Every primary action in the transition matrix has a system response.
- [x] Every mutation state names duplicate-safety/idempotency where applicable.
- [x] Every form state states what input is preserved.
- [x] Authentication responses are existence-neutral where required.
- [x] Consent is explicit, unchecked, exact-version-bound, and separate from
      marketing consent.
- [x] Free enrollment requires the explicit start action, exact recorded
      current consent, and an active learner membership in the distinct active
      public learner tenant.
- [x] Self-attestation is limited to the exact published global free-course
      slug and policy `AC-FREE-SELF-ATTESTATION-v1`; negative/conflicting facts
      fail closed and positive history is not overwritten.
- [x] Google registration and existing-person login remain distinct.
- [x] Onboarding uses only the bounded current fields and revision contract.
- [x] Onboarding does not infer role, score, entitlement, persona, or course.
- [x] Home distinguishes no enrollment from unavailable projection.
- [x] Module 1 ordering is exactly Watch, Reflect, Implement, Review, Improve.
- [x] Modules 2-4 remain topology-only; no activities, completion, or unlock
      semantics are invented.
- [x] Video completion is server-authoritative participation evidence, not
      page-open, player position, or mastery.
- [x] Reflection states include restored, dirty, saving, saved, failed,
      offline-unsaved, conflict, and completed behavior.
- [x] Implementation evidence does not fabricate real-world verification.
- [x] Review/Improve do not fabricate a reviewer, AI feedback, or score.
- [x] Progress shows canonical facts and missing-vs-zero accurately.
- [x] Admin commands require server permission, tenant, purpose/reason,
      idempotency, confirmation as appropriate, and append-safe audit.

## D. Universal state-family gate

For each applicable screen family verify:

- [ ] Entry/ready.
- [ ] Loading/submitting/processing.
- [ ] Empty/first use.
- [ ] Field validation and missing consent.
- [ ] Retryable provider/network failure.
- [ ] Terminal failure/support path.
- [ ] Offline/stale data.
- [ ] Permission denied/session expired.
- [ ] Locked/prerequisite state.
- [ ] Success confirmation and next action.
- [ ] Back/change/cancel/recovery path.
- [ ] Domain state, presentation state, and service-recovery state remain
      distinguishable.

## E. Visual and theme QA

- [ ] Every visual task attaches the exact approved source asset.
- [ ] Reference and implementation are compared at the same viewport and state.
- [ ] Clarity Grid is the only active direction; reserves are not mixed in.
- [ ] Final color/type values come from approved assets/tokens, not prompts.
- [ ] Real icons/assets are used; no emoji, ASCII, CSS art, fake SVG, or
      placeholder boxes are approved.
- [ ] Light, Dark, and System preserve the same hierarchy and meaning.
- [ ] Browser controls, form controls, overlays, skeletons, progress, focus,
      locked/offline/error states, and media controls are checked in both themes.
- [ ] Theme change avoids first-paint flash and preserves keyboard focus.
- [ ] Theme cannot alter permissions, progress, content, or completion.
- [ ] A selected reference is not called approved until behavioral, visual,
      accessibility, and runtime checks pass.

## F. Accessibility

- [ ] WCAG 2.2 AA automated and manual checks pass for included journeys.
- [ ] Logical keyboard order and visible, non-obscured focus pass.
- [ ] Icon-only controls have accessible names.
- [ ] Field errors are programmatically associated and focusable.
- [ ] Authentication permits password managers, paste, and accessible recovery.
- [ ] Status announcements are restrained and meaningful.
- [ ] Status never relies on color alone.
- [ ] AC 44px mobile target intent and WCAG 2.5.8 minimum/spacing are checked.
- [ ] 200% zoom/reflow retains essential content and actions.
- [ ] Reduced motion is respected.
- [ ] Captions/transcript/player controls pass when real media is approved.
- [ ] Screen-reader runs cover registration, recovery, onboarding, reflection,
      locked state, settings/theme, and admin reason-confirmation.

## G. Responsive and browser/PWA runtime

- [ ] 320px, 375px, 390px, 600px, 768px, 1024px, 1280px, and 1440px checks.
- [ ] No horizontal overflow at 390px except intrinsic approved data surfaces.
- [ ] Windows Edge browser journey passes on the exact release.
- [ ] Windows Edge installed-PWA journey passes independently.
- [ ] iOS Safari browser journey passes on a real supported device/version.
- [ ] iOS Home Screen/standalone journey passes independently.
- [ ] Safe-area insets do not hide navigation, errors, save state, captions, or
      primary actions.
- [ ] Manifest, icons, theme metadata, deep links, update flow, and offline shell
      are verified.
- [ ] A service-worker update never reloads over dirty learner work.
- [ ] Protected responses are not made broadly cacheable.
- [ ] Unsupported offline mutations are blocked and explained.

## H. Functional and data gates

- [ ] Fresh password registration -> real verification -> login -> onboarding
      complete/skip -> course entry works on exact staging release.
- [ ] Existing-person Google login works for an explicitly selected test
      identity without automation selecting/transmitting an account.
- [ ] Missing/current-consent OAuth recovery works without raw JSON/token leak.
- [~] `GAP-ENR-001` is superseded by ADR 0028/`DEC-014`; consent-backed
  self-attestation and enrollment code exists, but exact-release runtime,
  transaction, idempotency, provenance, and audit evidence remains pending.
- [ ] Learner home shows the actual enrollment and authoritative Module 1 0..5
      projection.
- [!] `GAP-MEDIA-001`: approved media/transcript/captions and real playback
  evidence pass.
- [ ] Reflection save/resume/conflict/session-expiry behavior passes against the
      real database.
- [ ] Implementation/Review/Improve evidence and Module 1 completion pass.
- [~] `/progress` route/component is an implementation candidate; canonical
  projection, empty/error/session, and topology-only states await runtime proof.
- [~] `/settings` route/component is an implementation candidate; exact current
  cards, identity boundaries, and recovery paths await runtime proof.
- [~] Device-local Light/Dark/System is implemented; first paint, focus,
  storage failure, browser, and theme parity checks remain pending. No
  account/cross-device/cross-app sync is claimed.
- [x] No deletion workflow, MFA, SSO, native app, or provider semantics are
      introduced by this package.
- [ ] Wrong-user, wrong-tenant, no-membership, inactive-person, and wrong-role
      negatives pass for every protected route.
- [ ] Admin Access plus AC session, tenant, permission negatives, correction,
      grant, idempotency, and audit evidence pass.

## I. Quality, security, failure, and performance gates

- [ ] Unit tests pass for identity, onboarding, enrollment, activities,
      evidence, progress, settings/theme, and admin permissions.
- [ ] Integration/API-contract/database tests pass on fresh PostgreSQL.
- [ ] End-to-end learner and admin journeys pass on the exact release.
- [ ] Accessibility and responsive suites pass with manual evidence.
- [ ] Session fixation/revocation, CSRF/Origin, rate-limit, OAuth-state,
      challenge-token, tenant-isolation, and permission tests pass.
- [ ] Upload/media tests run only for approved media capability.
- [ ] Concurrency/retry/idempotency tests pass for onboarding revisions, drafts,
      enrollment, evidence, admin commands, and outbox delivery.
- [ ] Failure-recovery tests cover worker restart, provider outage, database
      transient failure, stale revision, offline/reconnect, and unknown command
      outcome.
- [ ] Authorized non-production security probing is documented and findings are
      fixed/retested.
- [ ] Authorized non-production load/stress tests meet agreed thresholds and
      preserve correctness under retry/concurrency.
- [ ] Observability proves request/correlation paths without secrets or learner
      free text.
- [ ] Backup/restore, rollback, exact-release identity, and recovery runbooks
      pass for the promoted environment.

## J. Release declaration

Reference-ready requires Sections A-C to pass and unresolved items to be named.
Implementation-ready additionally requires approved visuals/contracts for the
assigned screen family. Staging-ready requires Sections D-I for the exact
immutable release. Production-approved requires separate production DNS,
secrets, database/bootstrap, backup/restore, access, legal, observability,
rollback, security, load, browser/device, and action-time approval evidence.

Current declaration: **reference-ready package only; production NO-GO**.

Explicit non-claims: future LMS breadth, simulator/call-review engines, native
Windows/iOS, billing, SSO/SCIM, broad enterprise functionality, autonomous
official scoring, real-call processing, and production deployment.
