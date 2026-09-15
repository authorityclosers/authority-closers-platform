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

Private local receipts retain exact commands, source hashes and outcomes. None
of these checks made an inference-provider request or settled a provider bill.
