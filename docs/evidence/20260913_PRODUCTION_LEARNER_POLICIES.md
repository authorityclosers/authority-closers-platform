# Published learner policies and registration consent binding

## Authority and scope

The user explicitly delegated authoring the Terms and Privacy notice and CTO release decisions on 13 September 2026 IST, without further questions. This slice replaces the staging-only policy pages and signup declaration with published, versioned copy for the actual Authority Closers learner service. It does not activate payments, WhatsApp automation, call recording, external AI processing or official autonomous scoring.

Controlled-source context follows the existing UI source register and required intake order. Relevant requirements include AC-IMP-04 account/consent and explicit enrollment, AC-UXA-01 understandable consent/recovery/accessibility, and existing identity, security, data, telemetry and provider activation boundaries. No missing hostile-audit text or legal entity details were invented.

## Published version and deployment configuration

- Exact `AC_LEARNER_CONSENT_VERSION`: `ac-learner-terms-privacy-2026-09-13-v1`.
- Effective date: 13 September 2026.
- Authoritative copy: `apps/learner-web/app/lib/learner-policy.ts` exports, rendered by `/terms`, `/privacy` and the registration declaration.
- Contact: the existing `admin@authorityclosers.com` address.
- Release API configuration must match this exact frontend version in staging and production. Deploy frontend and API/config together. A stale browser must reload and review the current copy.
- Password JSON and the consent-gated Google GET include the displayed version. The API compares it with its configured version before opening a database session, creating an OAuth transaction or requesting provider authorization. A supplied mismatch is refused in every environment. Production also refuses an absent version. Existing nonproduction fixtures without the field retain compatibility; an explicitly stale field never receives that exception.
- A matching request records the configured server version. Existing callback version checks remain in place. This release performs no consent-history migration or overwrite; existing Google consent conflicts retain their reviewed refusal behavior.

The recovery packet contains `ac-learner-terms-privacy-2026-09-13-v1.json`: 13,103 UTF-8 bytes with SHA-256 `77bb2963164d82eb0c71d1a0251441ed4c2e11264cb48383c67b519b2cef005f`. It serializes the version, date, contact, complete joined checkbox text, and both ordered policy section arrays with two-space JSON indentation and a final newline. The final committed-blob manifest/test binding identifies the implementation. Changing copy requires a new published version.

## Verified facts and policy choices

The factual review checked password registration fields and salted hashes; Google identity/profile scope; session/security metadata; onboarding, enrollment, drafts, responses and completion records; optional academy leaderboard visibility; essential email; browser preferences, recovery and offline cache; and privacy-request/account-closure boundaries. Analytics language is conditional on required consent and retention controls. Browser recovery expiry is seven days since local save and checked on read, not a promise of scheduled physical deletion. Server, audit and backup retention are not misrepresented as seven days.

The learner leaderboard is off by default for participation. An opted-in entry can be seen by other authorized learners in the academy. No self-service export/deletion endpoint, immediate complete erasure, certified legal compliance, guaranteed learning result, or unverified hosting country is promised. The no-sale/no-advertising-profile language is an adopted policy commitment under the user's authoring authority, not a conclusion that software tests can establish.

No verified legal entity address or named grievance officer was available in the controlled facts reviewed for this slice. The existing brand and support address are used; neither an address nor a person's appointment is fabricated. Mailbox monitoring and provider contract adequacy were not independently verified by this implementation. These are material operational/legal limitations, recorded for the release owner rather than concealed by a compliance claim.

## Primary legal context

The [official final Digital Personal Data Protection Rules 2025 Gazette](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf) specifies phased commencement: core notice and related rules begin eighteen months after publication in November 2025. The copy uses clear descriptions of data, purpose, choices and contact without claiming all core DPDP rules were already in force in September 2026 or that this release establishes comprehensive compliance.

The [2011 SPDI Rules Gazette reproduced by WIPO](https://www.wipo.int/wipolex/en/legislation/details/15063) covers privacy practices, necessary collection, purpose-limited retention, review/correction, withdrawal and grievance contact. It also identifies agency-address and named-officer requirements; the factual gaps above remain explicit. Policy text is original service-specific drafting, not a copied statutory template or legal certification.

## Validation and independent review

The checks cover current/missing/stale/bounded consent, side effects on refusal, Google authentication compatibility, API payloads, no-JavaScript and hydration consent gating, existing learner regressions, and public policy/signup layout at 320 and 1440 pixels. Browser tests intercept Google start or perform same-origin reads only; they do not contact Google or register an actual account.

Independent factual review corrected leaderboard viewer wording and removed an unverified contractual-safeguard assertion before freeze. Independent implementation review found no P0/P1/P2 defects; it confirmed refusal before database/provider effects and the existing callback check before Google code exchange.

### Final validation checkpoint

Evidence root: `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.

- `production-policy-static-20260912T190933Z`: 125 focused learner tests; all 1,578 learner tests across 87 files; 124 Python auth tests, including 47 new consent-version cases. All passed. Node 24.19.0 was used. TypeScript, full learner ESLint, Prettier, Ruff format/check and mypy passed.
- `production-policy-browser-20260912T191352Z`: all nine browser cases passed. Three cover consent-gated Google GET and inert registration without JavaScript. Six cover `/terms`, `/privacy` and `/register` at 320 and 1440 pixels. Policy version, date, contact, section count, links, initial consent state and absence of horizontal/text-container overflow were verified.
- Six full-page screenshots in that browser evidence directory were visually inspected. The version panel, policy headings/paragraphs, support contact and signup controls remain readable in the intended layout at both widths. No CSS change was necessary.
- Each run records the exact raw worktree SHA-256 of all 13 implementation/test files before execution. The final Git-object inventory and binding distinguish those worktree bytes from normalized committed blobs.

Limits: mocked route services establish request ordering and contracts, not a production database transaction or a live Google journey. The local browser run establishes rendered behavior with intercepted Google start, not deployed activation. The release owner must validate the final combined image/configuration and actual staging/production deployment. The policy slice does not certify the broader learner/Studio/Coach/admin backlog as complete.
