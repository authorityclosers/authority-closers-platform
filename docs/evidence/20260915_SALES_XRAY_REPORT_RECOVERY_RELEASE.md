# Sales Xray report recovery and internal testing

This release candidate starts from `a4f936c5d9bdd551747614003dbc4fc765acca9b`.
It is not a production-completion receipt. Deployment and actual report readback
must be recorded separately after the immutable release is installed.

## Report references

C5 may cite an exact native segment or a bounded range of Unicode code points
within that segment. The application derives the literal quote and native
timestamps. Strict legacy references remain supported; invented quotes, wrong
times, mixed reference shapes and unknown fields are rejected. C4 validation is
unchanged. Optional report-level business impact retains its typed uncertainty
state, and the prompt preserves proposed-versus-completed outcomes and does not
present generated wording as Dipak's own review.

## Internal testing

Release-bound approvals can exempt explicitly named, verified active accounts
from account-minute, analysis-count and session-issuance limits. An ordinary
account sharing the same IP stays limited. Each new run rechecks the approval;
revocation applies even to a previously quoted run. Historical reservations are
preserved when an unlimited account returns to a smaller finite allowance.
Provider budgets, recording ownership and retention remain independently checked.

## Local verification

The Saved calls selection now travels as an opaque, validated URL selector.
Opening it uses the current account's server-checked ownership, even when an
unrelated unclaimed guest cookie remains in the browser. The selected call does
not claim that guest recording. An ordinary login return still offers explicit
claim, and another account's or an unclaimed guest's call remains unreadable.
Starting another call clears the selector while keeping the saved library entry.
The focused component tests and two disposable PostgreSQL ownership/lease cases
passed; the latter also prove that new-upload guest-claim admission is unchanged.

Admin's strict report reader now accepts the actual recovered-report envelope,
including its version and nullable failure code. Previously the backend could
return HTTP 200 while the frontend rejected those two fields. The regression
uses that complete envelope and continues to reject false human approval.

- Integrated Python report, prompt, entitlement, tester and runtime checks:
  199 tests passed. Four initial failures were caused by the Windows default
  temporary directory being beneath an unrelated Git root; all 25 hosted-runtime
  checks passed with an explicit temporary directory outside repositories.
- Sales Xray frontend: 178 tests passed on the required Node 24.19.0 runtime.
- Admin and Sales Xray TypeScript checks passed.
- Python Ruff checks passed; mypy passed across 295 source files.
- The isolated PostgreSQL tester regression passed, including revocation,
  an ordinary account on the same IP, and a finite allowance smaller than the
  already reserved history. Its random proof schema was removed by the harness.
- A private retained-call correction was independently checked against the
  integrated report contract. Seven positive and negative checks passed,
  including exact source quotations and rejection of false human attribution.
  No private recording text is included in this repository.
- The integrated conversation unit suite passed 965 tests with one
  POSIX-ownership test skipped on Windows. The initial local decoding failure
  was resolved by installing the already built, source-and-binary-hash-verified
  AudioAtlas executable in the ignored native build directory. No decoder or
  measurement contract was changed to obtain this result.
- Startup recovery and release-archive checks passed 108 tests. The source-owned
  systemd installer still requires a separate verified activation after release.
- The Sales Xray production build passed, including route generation and
  TypeScript. Python type checking passed across 298 source files.
- The Admin production build and retained-report API contract tests passed.

Private local receipts retain exact commands, source hashes and outcomes. None
of these checks made an inference-provider request or settled a provider bill.
# Final retained HTTP integration

At candidate `b77e1fb`, the two disposable PostgreSQL cases pass, including actual Admin revalidate/correct/report requests and owner report, transcript, progress and source requests. Unauthorized guest and anonymous Admin reads are rejected. Recovery responses include the metadata accepted by the Admin frontend. Receipt: `D:/AC-authority-closers-release-audit/integrated-retained-http-final-pg-20260915-v2.xml`. The first root invocation used a temp directory under a parent Git checkout and failed the storage-root fixture guard; the corrected invocation uses an isolated `D:/Temp` directory. No provider call or production write occurred.

This is candidate verification, not production deployment evidence. Report and processing visual work continues on isolated branches with normal Pro design handoffs.

## Release notes and CI repairs

The new Sales Xray note is prepared in the artifact catalogue as a draft. It must
only become visible with the matching verified UI release. Existing stable note
IDs and account-scoped read receipts are unchanged. Notification copy and body
type are clearer. The existing learner notification tests passed 21 cases; the
app-update application and HTTP tests passed 32 cases.

Candidate `aef50b8` includes the async Admin route-save test repair and the
reviewed row-count parity entry for migration `20260915_0043`. The isolated
provider-control tests passed 17 cases; model registry and restore-drill checks
passed 92 cases with two Docker/explicit-integration skips. Full final-candidate
CI remains necessary.

The first processing visual check established horizontal fit and reduced
motion, but the user's screenshot exposed vertical overflow and poor hierarchy.
That check is not accepted as one-viewport UX proof. The revised mounted route
must show its status and main action without default page scrolling at the
declared desktop/mobile sizes, while remaining reachable at enlarged text.

## Image-led visual revision

The user rejected the HTML-derived report and processing direction. The new
references were generated as actual raster images in normal ChatGPT Pro chats:
processing desktop/mobile revision 3 and report desktop/mobile revision 4.
Private asset receipts record their provenance and SHA-256 values. These are
design references; sample findings and decorative graphics are not evidence
from a recording and do not replace the canonical report contract.

The initial processing implementation at `a7ed00d` was checked in the mounted
standalone route at 1536×674. Document height equals 674px and the saved-calls
action ends at y=605px. Visual review caught the old canvas background and the
need to retain mobile navigation. Those findings remain open until the follow-up
is verified. The report implementation is still being revised to match its
image reference. None of these local checks establishes deployed behavior.

The integrated image-led revisions include upload and selected-file consent,
the processing waveform and stage rail, and the report overview with on-demand
review points. The report uses its saved one-line diagnosis as the heading;
the final assessment stays in point 14. No generated reference copy, invented
scores, model name, price, waveform measurement or new upload limit is adopted.

On the actual AcquisitionStudio route, the synthetic processing fixture at
390×844 has document height 844px and width 390px. Its saved-calls action occupies
y=590.45–634.45px and the bottom navigation remains visible. The desktop first
change action and source entry are checked at 1536×674. The report's mobile
toolbar collapses native playback controls, preserves the same source element,
and presents the first change before the strengths. Longer report content
remains readable through sections and normal accessible reflow.

Manual browser checks confirmed that opening point 02 moves focus to that point,
returning restores the review navigation, selecting the source moment updates
the saved audio to 00:01.000–00:02.200, and starting another call clears only the
current selector. The local API uses a synthetic tone and authored fixture,
accepts no POST and makes no provider calls. The Chrome extension file chooser
was unavailable in the final root pass; earlier selected-file desktop/mobile
checks from the upload implementation and the component regressions remain
separate evidence, not a fresh production-upload claim.

The matching catalogue notification is included as shipped in this candidate
artifact. It becomes visible only when this artifact is deployed. Existing
notification IDs and account-scoped read receipts are preserved. Final CI and
production guest/learner/Admin verification are still required.

Final local UI verification on Node 24.19.0: 187 tests across 18 files passed,
ESLint passed with no warnings, and the optimized Sales Xray production build
passed, including TypeScript and all six static pages. The playback regression
proves expanding/collapsing its controls preserves the same saved source and
does not resubmit or restart analysis. All 32 app-update application/HTTP tests
passed after the matching notification was enabled in the candidate catalogue.

## Release CI repair

The first frozen candidate `f0a29b2` failed CI: a legacy report browser assertion
matched two summary paragraphs, the retention-denial fixture assigned its
retention deadline before its creation timestamp, and an existing frontend test
needed formatting. The expired-permission fixture now creates a valid historical
interval before checking denial; it does not depend on the runner being slow.
The report proof now scopes the saved summary and explicitly opens the on-demand
strength review point before checking its detailed feedback.

The companion web image built and passed its baked-release and HTTP health
checks, but artifact admission rejected the old-plus-new bundle size. The
repository artifact pool is now configurable through
`AC_RELEASE_ARTIFACT_POOL_BYTES`, defaulting to 1 GB with numeric bounds of
450 MB to 4 GB. Each artifact retains its 450 MB ceiling; old release cleanup
still follows verification of the newly uploaded artifact. The focused infra
checks passed 102 cases with five platform/opt-in skips. All four workflow YAML
files passed formatting and duplicate-key validation.

The resumed Windows environment had no running Docker PostgreSQL service;
local database/browser reruns were not completed. A fresh normal CI run with
disposable PostgreSQL remains required. The static Sales Xray build, complete
frontend formatting check, and changed-file Python lint/format checks passed.
These repairs and local results do not establish production deployment.

At `3607fd1`, the independent web-image workflow passed and all 187 Sales Xray
frontend tests plus the saved-report browser proof passed in normal CI. Three
Python shards and the static/gate jobs passed. The remaining failures were the
Learner journey's previous upload-button label and the expired-permission
fixture using an injected clock while the Admin reader intentionally uses the
database clock. The fixture now places expiry before both clocks while keeping
a valid historical interval. The Learner journey uses the visible "Analyse my
call" label; all six focused Learner journey cases passed locally.
