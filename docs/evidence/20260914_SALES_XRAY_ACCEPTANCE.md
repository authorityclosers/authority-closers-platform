# Sales Xray production acceptance

The founder's full request, repeated in the attachment on this turn, is the
current release objective. The existing Codex goal remains active, but its
objective text cannot be edited with the available goal tools. This record and
`20260913_SALES_XRAY_PRODUCTION_PRIORITY.md` govern execution and completion.
The prior AC v0.2 integration is retained. Production is the required outcome.

Each row requires actual staging and production evidence. Local implementation
or synthetic fixtures never count as production acceptance. No row is waived
because another feature works.

| Required journey | Implementation / next proof | Production status |
| --- | --- | --- |
| Dedicated Sales Xray URL, HTTPS, working app shell | Source-owned ingress, DNS controller and standalone image exist; activate and test exact artifact. | Pending |
| Ad/lead link opens focused upload before login | Add guest entry to the existing CallStudio, with accessible drag/drop, supported formats and immediate selection feedback. | Pending |
| Clear recording rights, provider and retention consent | Consent must match the actual source, recipients, approved policy and retention period before external processing. | Pending |
| Upload/analysis/recovery/progress | Reuse durable stages and source validation; implement guest ownership through the same engine. Show actual stage state, retry without duplicate charge, and truthful failure recovery. | Pending |
| Useful guest report, roughly 70% open | Server projection now selects summary, strengths, missed opportunities, eight observations and one immediate action. Transcript and call moments are guest-visible once owner-bound endpoints exist. | Pending |
| Deeper 30% unlocked after signup | Complete action plan, objection/closing detail and final coaching guidance absent from guest JSON. Claim-aware route and UI still need integration. This is a section partition, not a measured byte ratio. | Pending |
| Shared canonical Academy identity | Consent-aware Sales Google entry now registers a new canonical person or reuses the same provider identity and selects the public Academy. Actual HTTP/PostgreSQL proof passes; hosted proof remains. A visitor is not a second account or verified person. | Pending |
| No mailbox round-trip interrupts report viewing | Google verified assertion supports immediate canonical claim. Password registration must preserve the visitor's own report and give a report-scoped continuation; do not grant unrelated account access or falsify email verification. | Pending |
| Name, phone, email and available Cohorva username | Progressive form, canonical availability lookup and race-safe final username claim; retain input on conflicts and return to the same report. | Pending |
| 100 minutes and no signup reset | New PostgreSQL admission ledger passes concurrent reservation and immutable claim tests. Integrate with the existing worker and existing account allowance without double charging or parallel grants. | Pending |
| Abuse controls | Server-verified challenge, request/concurrency/storage limits, bounded IP/device risk signals, shared provider spend cutoff. IP/device is not report ownership or proof of a unique human. | Pending |
| Plain-language Dipak-specific coaching | Existing controlled eight-factor qualitative report; benchmark evidence-specific explanations and next actions, not generic summaries. Human-approved scoring remains subject to SVAL. | Pending |
| Visual report navigation and playback | Overview, call moments, transcript and coaching plan; exact seek, source clips, measurable physical channels with units, small-screen layout, keyboard and reduced motion. | Pending |
| Fast response | Measure short-clip and full-context latency on deployed services; under one minute is a target. Report failures and timing distribution, not only the fastest run. | Pending |
| Reviewer queue and permissions | Dipak/Suyash/admin and explicitly invited reviewers see only authorized calls; choose sales/developer/UX lenses and save multiple immutable submissions. Dedicated reviewer admission still needs integration. | Pending |
| Review notifications | Configure authorized recipients; enqueue once per ready report, verify real delivery and avoid duplicate sends on retries. | Pending |
| Review data accessible for iteration | Persist source/report/config/reviewer/lens/revision associations in PostgreSQL, with bounded audited reads available for Codex. | Pending |
| Transcription and analysis provider selectors | Validated real model catalog, independent selectors, secret manager integration; Gemini/ElevenLabs and supported alternatives. No fabricated model versions. | Pending |
| Prompt and parameter studio | Versioned drafts, supported parameter ranges, system/custom prompts, test run, activation and rollback with exact run configuration. Prompt configuration is not weight training. | Pending |
| Per-run/user/model/provider cost analytics | Actual usage and provider reconciliation separated from estimates; totals, remaining caps, failures, duration and latency. No guessed account balance. | Pending |
| Coach/Academy analytics and app access | Dipak Coach/reviewer, Suyash/admin full authorized operations; show actual scoped learner/login/course/Sales usage aggregates. Preserve staging/production separation. | Pending |
| Initial benchmark under INR 1,000 | Intended INR 500 Gemini plus INR 500 ElevenLabs, funding not observed. Hard per-provider cap, reuse artifacts, small consented multilingual/noisy/overlap examples, full-context case when required. | Pending |
| Complete production release | Exact immutable images, migrations, reversible activation, real Google/password/funnel/review/model/budget/audio/mobile tests, then promote/document main/v0.2. | Pending |

## Foundation evidence on this branch

- Twenty-four unit tests pass: seven report projections and seventeen server
  challenge checks. Locked coaching sentinel text is absent from guest payloads;
  a request-style string cannot select account access. Challenge tests cover
  exact host/action, success type, five-minute expiry, HTTP errors and bounded
  response size using a local transport, with no real Cloudflare request.
- Ten actual PostgreSQL cases pass: forward migration/metadata parity, no
  guest-created Person, source replay/foreign-session denial, expiry/revocation,
  unverified and foreign identity denial, two-tab allowance race, two-account
  claim race, claim-preserved cumulative usage, exact settlement, database
  append-only history, real identity-cookie HTTP claim, and two deliberately
  interleaved identity/claim/reservation races. The latter prove consistent lock
  ordering when an HTTP request already holds the canonical identity lock.
  Receipt: external `sales-acquisition-postgres.log`, ten passed in 13.46s.
- The HTTP case installs the real identity and acquisition routers against an
  isolated PostgreSQL database. It checks private/no-store responses, exact host
  and origin, duplicate-cookie rejection, bounded input, secure host-only cookie
  attributes and 61 seconds of usage retained after a canonical claim. ASGI uses
  an HTTPS request URL and a synthetic challenge verifier; this is not live TLS
  or external challenge acceptance.
- Ruff passes; mypy passes all five new source modules. These are backend
  foundations. The HTTP installer exists but is **not mounted in application
  composition**; guest recording ownership, worker admission, existing allowance
  reconciliation and the report route still need integration. No provider call,
  production migration or production capability is activated by this branch.
- Earlier proof attempts exposed test harness errors (an async transaction used
  as a synchronous context manager, missing test settings and a seed identity
  without an email). Those were corrected in isolated fixtures. Failed attempts
  are not counted as successful evidence.

## Frozen frontend contract, version 1

The response envelope is `ac.sales-xray.report-envelope/1`, created by
`project_bound_report`. It contains `recording_id`, `run_id`, `source_sha256`,
`transcript_revision`, `source_label` and the explicit access projection as
`report`. The route must obtain `ReportSourceBinding` from the authorized run and
recording rows before invoking it. The projector rejects a source hash or
transcript revision that differs from the report. The frontend must bind this
envelope to its owner-authorized playback/transcript responses, never infer the
source from whichever recording happens to be selected. This resolves the Sales
lane's source-association integration finding. Ownership endpoint proof remains
separate. Four added envelope tests pass, bringing projection/challenge tests to28.

The new server projector is `conversation_intelligence/report_access.py` and
returns `schema: ac.sales-xray.report-access/1`. Ownership must be resolved by the
future report endpoint; a body/query flag never selects access. Existing report
routes and consumers remain unchanged until integration.

Both views contain `access`, `review_status`, `numeric_publication: false`,
`content`, `sections` and `unlock`. Guest `content` contains only `summary`,
`strengths`, `missed_opportunities`, `dimensions` and `next_action`. Their field
types reuse `ReportDraft` observations and improvement objects. `next_action`
is its first improvement or null. Account `content` additionally contains
`improvements`, `objection_analysis`, `closing_analysis` and `verdict`.

Sections `overview`, `moments` and `transcript` are available to the private
guest owner. `coaching` is `sign_in` for guests and `available` for accounts.
Guest `unlock` supplies title, description and action copy; account `unlock` is
null. Transcript, playback and physical channels need independently owner-bound
endpoints; declaring a tab available does not expose those resources by itself.

The session installer contract is `POST /v1/conversation/acquisition/session`
with only a bounded `challenge_token` JSON field, `GET` of the same route, and
canonical-identity `POST /v1/conversation/acquisition/claim`. Responses include
`state` and `allowance` with integer `allowance_seconds`, `committed_seconds` and
`available_seconds`. A claim also returns the immutable `visitor_id`. The bearer
is only a Secure, HttpOnly, host-only cookie, never JSON or browser storage.
Claim deletes that cookie and keeps the same used minutes on the existing person.
These endpoint definitions are ready for integration, **not live endpoints**.

## Shared Google entry implementation

Sales now accepts canonical Google registration on its own configured host.
`GET /v1/auth/google/start?action=authenticate&surface=sales_xray&consent=true`
with the current `consent_version` and safe same-host `return_path` binds a
REGISTER transaction before redirecting. The existing canonical registration
command handles new people and existing linked Google people; email matching
does not silently attach an identity. Explicit `action=register` works too.
Existing-account authenticate without consent retains its previous behavior.
Provider linking stays on Academy account settings.

Both start and callback require the current registration consent. The callback
creates or preserves the public Academy learner context and returns to the same
report. It does not auto-claim an arbitrary report ID in the return URL; the
separate guest-cookie plus canonical-session claim still establishes ownership.

Actual PostgreSQL suite now passes **12 cases in 19.15s**. The new real identity
and HTTP case creates a previously absent canonical Google learner, returns to
the original report path, claims 124 used seconds, then signs in again with the
same provider key and proves there is exactly one additional Person. A separate
case rejects an unverified provider assertion without creating a person/session.
Only the provider exchange is synthetic; no real Google network call occurred.
Earlier test assertions expected generic422 for denied consent/assertion rather
than the existing400/401 domain responses; corrected to the actual contracts.
Production source activation and real Google browser acceptance remain pending.
The two auth route suites pass117 tests in11.26s, including exact-host/cookie
boundaries, consent-aware entry, missing/stale consent and callback revalidation.
Changed Python lint, formatting and strict auth types pass.

## Combined release verification, 14 September

Combined candidate `8396728` integrates the accepted Sales navigation packet
`39dcb36` and acquisition foundation `e1060c7`. It has not been deployed. The
preceding CI run `34775463451` failed four browser/routing assertions and skipped
image packaging. The Sales packet corrects the three browser assertions. The
routing failure was a platform-dependent PowerShell line wrap; its failure now
uses the stable `AC_TUNNEL_READBACK_MISMATCH` marker, retaining the same refusal
before any DNS write.

Verification on the combined source plus that marker correction passed:

- Full Ruff, formatting (580 files), mypy (264 source files) and Prettier.
- 161 focused routing, identity, challenge and report-access unit tests.
- 12 actual PostgreSQL acquisition/claim/identity cases; disposable database
  removed after the run.
- Optimized Sales static build and three actual HTTP/password identity,
  PostgreSQL, native-audio and browser tests in 132.49 seconds. Source playback,
  upload processing and logout are exercised; report inference remains synthetic
  and no external provider is contacted. Receipts are in
  `D:/AC-authority-closers-release-audit/combined-sales-20260914-r1/`.

SSH access was confirmed restored. Both core environment pointers still select
`69db2257b2671baa3aefc7902e69078f381a649d`; the standalone staging companion is
healthy at the older `99cdee5e19e298173e4bb8e8619087ef70cf9ccf`. The local edge
returns its health marker and rejects anonymous recording access. This proves
the existing runtime only, not the new acquisition funnel.

Cloudflare readback found tunnel configuration version 15, fourteen existing
entries and neither standalone hostname. The source-owned staging dry run
preserved all existing entries and proposed only the staging hostname plus its
proxied tunnel CNAME. The connected API credential's write failed with Cloudflare
`1001: Not authorized`; a subsequent readback confirmed no change. The authorized
signed-in dashboard is being used for the same prepared change. Production
activation and real hosted onboarding remain pending.

The original Sales root is preparing the latest user correction: simple English
app controls with original mixed-script report/transcript content. That packet
must accompany the next combined CI run; the previous global language switch is
not the selected release behavior.

## Focused product research

Gong's [scorecard documentation](https://help.gong.io/docs/all-about-scorecards)
supports structured human feedback alongside unstructured comments. Avoma's
[coaching product](https://www.avoma.com/conversation-intelligence/ai-sales-coaching-software)
describes timestamped examples and custom coaching frameworks. Our design
inference is to put the source clip and a short improvement action beside each
review dimension, with reviewer lenses in Admin. Their marketing does not
validate AC's model accuracy or authorize AC numeric scoring.

Cloudflare's [Turnstile validation contract](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)
requires server-side verification and makes challenge tokens single-use with a
five-minute lifetime. This informs the guest admission control; it does not make
IP/device fingerprints canonical identities.
