# Password reauthentication returns to the activity

Date: 2026-09-13 (Asia/Kolkata). Status: implementation and targeted validation
complete; separate local slice, not included in the current release candidate.
Full learner regression and canonical browser acceptance remain pending the
release owner's shared test-slot hold. No deployment or complete journey claim.

## Problem and behavior

A session that expired while loading an activity, refreshing its module path, or
saving a reflection offered a bare `/session-expired` link. Password sign-in then
returned a learner with completed/skipped onboarding to `/home`, losing the
activity destination. Existing account-scoped recovery storage could retain the
response, but this did not establish automatic return to the same activity.

Recovery links now carry only `activity=<UUID>`. The parser accepts a single
hyphenated UUID, normalizes hexadecimal case, and rejects ambiguous arrays,
whitespace, paths, URLs, query/fragment suffixes and non-UUID input. URL builders
revalidate the identifier and use fixed internal route constructors. Existing
course-only and default URLs retain their behavior.

The login and session-expired pages pass this navigation hint into the password
form. Only after password authentication and a canonical completed/skipped
onboarding response does the form reload the exact activity route. Incomplete or
unavailable onboarding retains the existing onboarding gate and carries the hint
forward. Onboarding recovery, retry and completion links preserve it; continuation
labels say "Resume activity" or "Back to activity" where appropriate. An explicit
settings return keeps precedence and discards activity/course hints.

## Boundaries preserved

The identifier is navigation context, not evidence of access or enrollment. The
activity page reloads current identity and activity data. Existing backend access,
enrollment and prerequisite checks, client allowed-actions gates, draft revision,
and tenant/person/enrollment/activity recovery scope remain unchanged. The patch
does not change a password request body, consent, canonical learning APIs,
progress, reviewer authority, submission behavior or provider activation.

This bounded slice covers password reauthentication. Google, registration,
verification email, password-reset and new-device activity continuity remain
separate unfinished work. The broader learner/Studio/Coach/admin goal is not
satisfied by this patch or its tests.

## Validation completed

Under supported Node `24.19.0`, five targeted unit/component files passed all
139 cases. They cover adversarial identifier parsing, compatibility with existing
course routes, real page-function query-to-prop wiring, successful and refused
password login, deferred-login ordering before onboarding reads, every canonical
onboarding state, skip/finish actions, settings precedence, both module-path
recovery links, initial-load 401, and a draft-save 401 retaining its response and
revision argument without evidence submission or a committed-mutation callback.

The page tests await actual server page functions and mount their returned React
trees with mocked API calls. They do not exercise Next's RSC transport, the browser
router, real authentication cookies or PostgreSQL. The actual browser probe is
still required to prove automatic activity return and persisted draft recovery.

Scoped Prettier, scoped ESLint with zero warnings, and the learner TypeScript
check passed. Independent review of the seven runtime wiring files found no
actionable P0/P1/P2 defects. The targeted checks did not start a browser, database,
runtime, build or full application test suite.

Retained receipt directory:
`D:\Projects\authority-closers-release-transfer\2026-09-11-recovery\activity-return-targeted-20260912T195605Z`.
It contains the exact 12-source allowlist, formatting/test/static output, exit
status receipts and a post-validation source snapshot/manifest.

After work resumed, eight additional default onboarding-page regressions passed
in a separate one-worker run. They mount the actual page and form together and
verify skip/finish destinations after the canonical profile read. Scoped format,
zero-warning ESLint and the learner TypeScript check also passed for that new
file. See `20260913_ONBOARDING_PAGE_COMPLETION_REGRESSION.md` for exact receipts
and the test source hash. The original 139-case run and its snapshot are retained;
they are not retroactively described as a combined 147-case execution.

The focused offline launcher file also passed all 13 tests under Python 3.12.0,
including published-policy compatibility, environment cleanup, explicit Studio
opt-in, process ownership guards and parser checks. Receipt:
`local-launcher-regression-20260912T205216Z` in the shared recovery packet. These
tests execute extracted configuration blocks and parsers, not runtime startup,
database operations or live registration.

## Pending canonical acceptance

The external `probe-canonical-draft-recovery.py` now asserts the exact recovery
href before clicking and a successful password-login HTTP response. Its source
binding includes the new helper, onboarding routing/form and affected pages. The
prior helper is preserved as `probe-canonical-draft-recovery.pre-activity-intent.py`.

An isolated syntax/AST check confirms that the request guard, API helper and
canonical completion comparison are unchanged. The helper still requires runtime
release equal to checkout HEAD, uses a fresh synthetic local account, permits only
the necessary canonical commands, checks same-account draft restoration, and
requires explicit saving before the next draft revision. Manual fallback
navigation remains labeled `draft-retention-passed-navigation-failed` and cannot
satisfy automatic-return acceptance. The helper has not been run in a browser for
this slice.

Preflight receipt: `canonical-draft-activity-return-harness-preflight-20260913.json`
in the shared recovery packet, SHA-256
`25b54701d9f452ead638df7f5be29105888d33ffd20f850d9e6d25351a4cafc7`.
Updated probe SHA-256:
`7922fd8bb14ba456a92f163902428d92504649f59bb02c7f4c82e37c497bc063`.

The separate local checkpoint preserves the targeted tests and static checks;
it is not a release candidate. After release gates permit local acceptance:
complete the full learner checks, archive old runtime logs, use the managed local
launcher, then run the canonical 390px draft/session probe and inspect its images.
Retain any failed receipts and repair the actual failing behavior before claiming
the automatic-return acceptance is complete.
