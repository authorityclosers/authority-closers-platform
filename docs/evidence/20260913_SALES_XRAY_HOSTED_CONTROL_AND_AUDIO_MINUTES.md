# Hosted provider control and audio-minute accounting

The dedicated worker and API now bind provider configuration to the managed
operations tenant. A PUBLIC learner keeps learner permissions and owns their
recording, minute ledger and report. They do not need provider-admin access.
The hash-pinned approval bundle and worker configuration must name the same
operations tenant as the deployed API. Current verified control-account email,
active owner/admin membership and active operations tenant are rechecked before
provider execution; a saved registry revision cannot bypass later revocation.

C1 charges measured audio duration. Hosted C2/C4/C5 request quotes and the report
plan require zero additional audio minutes. An account whose audio allowance is
exhausted after C1 can complete its already-approved report. Provider request,
token, privacy and paid-budget controls remain separate. Provider response
success remains distinct from invoice reconciliation. Legacy non-hosted C2
quotes retain their duration check. The UI explains the additional-minute rule.

Evidence is under
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`:

| Receipt | Actual result |
| --- | --- |
| `0035-conversation-unit-03.xml` | 507 passed; one POSIX ownership test skipped on Windows |
| `0035-cross-control-postgresql-02.xml` | 5 passed against disposable schemas on actual loopback PostgreSQL |
| `0035-control-scope-postgresql-01.xml` | 11 passed, one test failed on its hardcoded fixture balance |
| `0035-meter-boundary-postgresql-02.xml` | Existing failed authority case passed after asserting before/after balance; new boundary test exposed an incorrect settled-invoice assertion |
| `0035-meter-boundary-postgresql-03.xml` | New zero-balance full C2-to-C6 case passed, preserving the provider reconciliation hold |
| `0035-meter-ui.xml` | 19 call-studio tests passed |

The current PostgreSQL outcomes cover 18 distinct cases after the targeted
reruns. Earlier failed receipts are preserved. The cross-scope fixture needed
explicit membership flush before creating its session to satisfy the real
foreign key. The boundary fixture now preserves existing grant/debit history
and debits its observed remaining balance through typed ledger transitions.
No production SQL or provider transport was used.

Ruff passed for the changed backend/test files; mypy passed for six changed
runtime modules. Existing core report-import tests also require fresh fixture
and schema per case so a control-email mutation and prior draft cannot leak to
the next case; the release coordinator owns that separate exact-core rerun.

These are local implementation receipts, not hosted activation evidence. The
release installer lifecycle, managed operator artifacts, immutable images,
authenticated staging flow and subsequent production canary remain separately
verified deployment work. No real recording was sent externally by these tests.
