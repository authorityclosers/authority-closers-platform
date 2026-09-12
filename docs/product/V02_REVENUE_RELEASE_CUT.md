# v0.2 Alpha — revenue-first release cut

Current user direction, 2026-09-10: prioritize complete usable apps and a route to revenue over further broad visual exploration. Keep usability, accessibility, security, and the approved visual system. This sequencing supersedes older v0.1/embedded-Studio scope descriptions; it does not invent commercial policies or mark features complete.

## Current free-first release motion

Latest explicit user correction: Dipak's free course, real video delivery, normal identity and persisted username claiming come first. There is currently no public paid offer; salespeople handle sales. Dipak's controlled documents are the basis for offer research, not authorization to invent price, access periods, promises or refund terms. A separate research task drafts clean policy language and flags required legal disclosures for owner/counsel review; drafts are not activated policies. No revenue forecast is asserted.

If an already approved external payment/sales process exists, assess a sales-assisted pilot using normal audited enrollment operations. Do not interpret a payment screenshot, browser success page or analytics event as course access. Hosted checkout can follow without building a custom billing suite, but verified payment records and application-owned enrollment remain separate.

## Implementation order

| Priority | Required outcome | Acceptance boundary |
| --- | --- | --- |
| P0 | Three reachable apps and normal identity | Learner, Coach and Platform Admin; separate staging/production, correct callback/session behavior and scoped permissions; WordPress unchanged |
| P0 | One complete course that can actually be delivered | Dipak creates/edits a draft, uploads video, sees honest processing/retry state, previews and publishes; enrolled learner watches, seeks, resumes and progresses |
| P0 | Free-course admission and identity | Explicit free enrollment, recoverable sign-in, persisted unique username claim and profile; no paid-access dependency or email-based public identity |
| P0 | Support can resolve a blocked learner | Working scoped lookup/diagnosis, audited authorized enrollment correction and account recovery; not decorative People screens |
| P1 | Activation and return visits | Simple onboarding, continue learning, understandable progress, working profile photo, useful notifications; existing practice/rewards remain truthful |
| P1 | Learner competition and meaningful feedback | Opt-in tenant-scoped leaderboard using canonical earned practice XP, explicit period/tie rules, no fake scores or email exposure; colorful shared-token Arcade controls, visible actions and accessible optional motion/sound |
| P1 | Dipak can operate the course without a developer | Course outline/order, image/content editing, supported lesson/practice formats, preview/publication, scoped review queue and settings |
| P1 | Learn where the sales/learning journey fails | Descriptive visit/sign-in/enrollment/first-lesson/return signals; confirmed revenue/access/progress comes only from its canonical source |
| P1 | UI quality supports completion | Mobile access to all core features, visible primary actions, no internal error codes, no broken controls, shared tokens, keyboard/reduced-motion support, understandable recovery |
| Later | Payment and product expansion | Interchangeable Razorpay/Cashfree/PayU adapter boundary; live checkout after an approved offer and provider setup. More individually designed Arcade games, advanced characters/3D, social leagues, broad marketplace/B2B, native packaging, full finance/ERP, autonomous AI evaluation only after its gates |

The video requirement still includes authorized VPS delivery, genuine attributed 4K technical fixtures, adaptive quality, captions, seeking and recovery. A prepared 720p long test film is not proof of 4K or a published Dipak lecture.

Initial leaderboard implementation choice, explained to the user: academy-scoped, explicit opt-in, all-time confirmed earned practice XP. Equal totals receive equal competition ranks; username is a stable secondary display/pagination order only. No prizes, email exposure, public private-course activity, new XP rules or official assessment implications. Leagues/seasons remain separate future work. This records the chosen implementation behavior, not a claim of completion.

## Release rule

Ship small reviewed changes to staging regularly. Promote the exact accepted artifact to production after the core journey, configuration, authorization, migration and rollback checks pass. A source change, unit-test pass, login HTTP200, or Cloudflare redirect alone is not acceptance. Do not wait for every future animation/game; do not omit an essential step in the course-delivery journey.

## Delegation and ownership

- Root: integrated source ownership, video/storage/processing, cross-cutting backend decisions and final acceptance.
- Sol revenue-journey task (`01a0879b-1037-7533-ba49-ac79ea06e105`): username claim and opt-in leaderboard implementation plus focused acceptance tests in isolated `25ac`; exact patches integrated into current source by root. One Luna Max helper for bounded independent tests. Earlier attempted assignment to the old UI Development task was cancelled before edits; no duplicate identity writer.
- Sol offer/policy research (`01a087b1-0d14-74a1-b58d-ac7390ee9264`): verified Dipak source review and primary-source legal checklist; no paid-offer activation, publication or invented refund promise.
- Sol release-readiness task: verified artifact/configuration/rollback readiness; one Luna Max helper for read-only environment checks. Remote writes require a named accepted artifact and explicit handoff from root.
- Gemini 3.8 Flash High via `agy`: bounded sanitized UI component/prototype work; Luna reviews, Sol/root integrate only accepted changes. No permission bypass, secrets, customer data, autonomous deployments or unreviewed generated feature claims.
- Each task owns disjoint files. New worktrees do not automatically contain current uncommitted implementation. No competing production writers or unlimited recursive agent trees.

## Verified starting state

2026-09-10 public read-only checks: learner-staging200; Coach staging redirects to login; Admin staging redirects to Cloudflare Access. Production learner/Coach503 release hold; Admin Access redirect does not prove production origin health. WordPress apex/www200. Staging is the last exact release `7bdd069d4bf00561edcab90b1679666205708185`, not the latest uncommitted local implementation.

Production configuration remains the known release blocker: required runtime values in Infisical prod `/application` were absent, and production Google OAuth ownership/client/callback setup remains unresolved. No secrets should be pasted into chats. Existing free enrollment and manual-grant foundations are not an implemented paid checkout.

## Latest verified increment

2026-09-10: staging advanced through the canonical controller to Coach/session release `783da9838179ee32f0481d9bae9a8b1b30a95ec4` after successful immutable packaging run `34406701015`. Public Learner/Coach/API checks, protected Admin routing, OAuth-start and WordPress-preservation checks passed; an independent SSH read confirmed the exact staging release link. Production was not changed. A fresh names/presence-only check of Infisical prod `/application` injected zero application settings: all thirteen required database, identity, OAuth and tenant-reference names were absent. No values were printed. The local username/leaderboard and Arcade increment is browser-tested and is being isolated as the next dependency-complete candidate, not claimed to be in the deployed Coach increment.

The initial isolated community candidate `99fdc62bf43ce1206871502cb58176cf1eb2214e` is not accepted for deployment: independent review required mutation/retry isolation and explicit transaction ownership. Sol is correcting those within the existing allowlist, plus three bounded input/accessibility hardening findings. After final clean review and verification, Sol may push only the candidate branch and dispatch immutable packaging once; root remains the only foundation/application deployer. The replacement SHA and workflow result must be recorded before claiming it packaged or staged.

Separately, root implemented and independently reviewed the inactive authenticated video-byte transport, real filesystem streaming and default-disabled exact-route body-limit exception. Combined backend/security/storage/ASGI/PostgreSQL verification passed244; final Origin hardening passed31 ASGI cases. Actual paused-stream PostgreSQL revocation prevents file publication without holding database locks during upload. This is verified backend implementation, not an enabled browser uploader or production4K playback. Detailed scope, corrections and remaining composition gates are in `docs/evidence/20260910_STUDIO_VIDEO_UPLOAD_PIPELINE.md`.

### Superseding staging status

Exact candidate `74631e0dd94a1d54a2e2b88bc925e47e0e0c7029` passed immutable workflow34414740852 and was deployed to staging through the canonical controller, with exit0 and a committed migration0027 receipt at2026-09-09T23:22:38Z. The corresponding foundation parity helpers were upgraded first. The VPS release link, healthy app services, public routes, sign-in callback constraints and WordPress preservation were independently checked. Username claims, private-by-default public profiles, opt-in canonical-XP leaderboard and allowlisted Arcade changes are now in staging; this supersedes the pending-candidate notes above. Normal localhost browser acceptance is recorded separately from remote unauthenticated admission probes.

Production remains on release hold: owner-controlled Infisical/Google OAuth configuration is missing and an accepted off-site restore drill is still required. A read-only follow-up confirmed the canonical logical-backup invocation from 2026-09-09T23:20:07.915787Z completed with systemd success at 23:24:01.228226Z, superseding the earlier ongoing-failure status for that invocation only. Historical upload failures remain recorded; one successful job is not a restore proof. No production promotion or broad UI/course-upload completeness is claimed. The normal Coach upload→processing→ready→publication→learner playback path remains an essential unfinished course-delivery item; payment gateways and policy publication do not precede that free-course priority.

### Superseding activation and recovery check

At 2026-09-10 03:15 UTC, the canonical isolated off-site restore proof passed for exact staging746 and migration0027, including parity, held workers, zero provider calls and verified cleanup. See `docs/evidence/20260910_STAGING_OFFSITE_RESTORE_ACCEPTANCE.md`. The production configuration gate is unchanged.

The earlier statement that Arcade changes are “in staging” describes packaged code, not activation. Fresh checks found its immutable staging policy explicitly disabled and its practice routes unavailable. A reviewed staging-only release-contract correction is being implemented; no host flag bypass or production activation is authorized by that work. Usernames and opt-in leaderboard routes are mounted, with authenticated remote acceptance still separate from the completed localhost evidence.

The current user-requested Sol offer/policy research task is `01a08940-fa74-77b1-ab65-a607ddec4bfd`. It is research-only, supersedes the earlier task assignment above, and does not publish policies, approve business terms or activate a payment provider.

### Staging pilot activated — 2026-09-10 04:03 UTC

Canonical deployment of exact `4e8d413b828ab750d7c5e20d1a9320d0f427c823` completed with exit0 and a committed migration0027 receipt. This supersedes the disabled-pilot staging status above: `/practice/availability` now returns enabled=true, `/practice` loads, and private practice/community endpoints still return401/no-store without authentication. The controlled browser shows the normal Practice sign-in state. Normal authenticated VPS participation/reward acceptance is not claimed. See `docs/evidence/20260910_STAGING_ARCADE_ACTIVATION_ACCEPTANCE.md` for the artifact, tests and exact boundaries.

Production still has no selected release and was not changed; required production configuration and Google provider setup remain unresolved. WordPress remains unchanged. New Coach video upload and the subsequent username-shortcut focus correction remain local, not in this staging artifact. Policy research is complete as an advisory draft; free-course/video/identity still precede payment activation, and no paid offer or refund promise was invented.
