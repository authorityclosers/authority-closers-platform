# AUT-1676 / AUT-1681: customer minutes follow report delivery

**Sensitive change: CTO and CEO review required; excluded from evening automatic merge.**
Owner AUT-1701 authorizes one strike PR, including minimal necessary charging changes.
Source pin: 81ca252. Exact-ID controlled intake and relevant UXA/GOV-AUD receipt
are retained in strike-c-provider-failure-evidence-20261010.md.

Migration 0080 adds an append-only customer report-minute journal. It preserves
all acquisition usage/settlement rows and provider reservations/observations.
One usage-row lock serializes release, retry reservation and report delivery.
A unique partial index permits exactly one delivery charge for the source.
An immutable trigger rejects journal updates/deletion. Account projections use
the latest journal outcome, falling back to the original receipts for old calls.

Terminal failed/cancelled plans append a zero-minute release independently of
provider cost certainty. No provider no-work receipt is manufactured. A worker
cannot deliver against a released reservation; a future explicit retry must
reserve available capacity first. Delivery is bound to the source, processing
owner and saved C6 report in the report-persistence transaction. Repeated valid
report delivery retains the first receipt. A later failure cannot release a
completed delivery or a newer plan's reservation. Processing admission refuses
released sources, fencing late workers; private retained reads remain separate.

The coordinator settles pre-existing terminal plans one at a time after restart.
Expiry and ordinary terminal transitions settle during their own transaction.
The retry reservation primitive checks capacity, preserves the original source
receipt and coalesces repeats. Public retry wiring and pre-plan/local-run timeout
coverage remain in progress; this commit does not claim the whole strike done.

Verification: 9 focused disposable PostgreSQL cases passed in 19.36s, covering
migration/model drift, release/re-reserve/delivery, exact-once repeats, restart,
release-vs-delivery races in both orders, journal immutability, rollback before
commit, insufficient retry capacity, and bounded coordinator recovery. Ledger
fixtures use minimal synthetic drafts and do not claim provider/report quality.
Three legacy acquisition regression cases passed (13 deselected, 8.96s): settlement
immutability, concurrent allowance admission and historical trial preservation.
58 processing-plan/private-progress unit cases passed. Targeted mypy and Ruff
passed. No provider, staging or production mutation occurred.

Dev: https://salesxray-dev.authorityclosers.com. After authorized release, fail an
internal test analysis and compare its account allowance before/after recovery;
minutes return while provider failure evidence remains. A delivered report must
charge the measured source once. This branch is not deployed dev evidence.
Rollback requires a reviewed forward code change; journal history is retained.
