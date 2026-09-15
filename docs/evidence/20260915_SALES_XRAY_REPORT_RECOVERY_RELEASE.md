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
