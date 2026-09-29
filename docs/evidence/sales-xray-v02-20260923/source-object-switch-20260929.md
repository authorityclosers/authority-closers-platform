# AUT-43 shared-source switch — 29 September 2026

Base: `922756813de5d0f1f3e6d60f8ea481cd259e29de`; branch `task/sales-xray/81-source-object-switch`.
Authority: AUT-43 amended CTO spec and ADR 0033. Fictional data only; no providers activated.

Implementation:

- New uploads publish `SourceAudioKey(tenant, sha256)` and attach permanent reference rows after full input verification.
- Object acquisition always inserts with conflict-ignore, then selects the live row for update. HTTP upload and erasure callers retain the existing storage-root fence through commit.
- Shared publication and collision each stat the final object after disposing of the temporary link. Neither opens stored content; reads still verify its digest before yielding bytes.
- Erasure releases the recording's reference, unlinks only after the last live reference, and tombstones last. Finalization rejects an unreleased reference.
- Existing ready recordings without reference history retain their legacy key and strict inventory erasure. No migration or history deletion.

Verification on the dev host with disposable PostgreSQL schemas:

- Storage/application/resolver unit tests plus worker, retention and guest ownership DB suites: **90 passed**.
- Full submission HTTP/PostgreSQL suite: **18 passed** (one existing httpx per-request-cookie deprecation warning).
- Source-object DB suite: **2 passed**. After adding the NOWAIT row-lock assertion, the affected source-object and shared-storage checks: **9 passed**.
- HTTP proof compares both owners' status, complete headers, normalized body and ordered SQL statements, forbids stored-content reads, and rejects foreign identifiers.
- Lifecycle proof covers A erasure followed by B playback/native analysis, final owner/retention erasure, fresh object identity after re-upload, tenant separation, legacy cleanup, and rollback after unlink.
- Race proof holds erasure inside the root fence, proves the object row rejects another NOWAIT lock, and proves upload waits until deletion commits before creating a fresh object.
- Ruff format/check and mypy: passed; `git diff --check`: passed. No schema changes.

D5 timing evidence (milliseconds; **acceptance remains failed**):

| Protocol             |      Bytes | First median / p90 | Collision median / p90 | Median gap | Limit | Result |
| -------------------- | ---------: | -----------------: | ---------------------: | ---------: | ----: | ------ |
| Initial              |     86,016 |   89.585 / 100.710 |       87.338 / 102.376 |      2.248 | 5.000 | pass   |
| Initial              | 33,554,432 |  204.837 / 303.241 |      274.713 / 327.380 |     69.876 | 5.000 | fail   |
| Pre-seeded, profiled |     86,016 |    27.254 / 33.510 |        27.352 / 32.633 |      0.098 | 5.000 | pass   |
| Pre-seeded, profiled | 33,554,432 |  109.689 / 215.300 |       98.956 / 268.703 |     10.733 | 5.000 | fail   |

Each run used 30 first and 30 collision uploads per size, shuffled with seed `4300929`, two fictional owners in one tenant, full seeded byte streams, and two excluded warmups. Timed `store_source` only; transaction commit, fixture registration and fence acquisition are outside the interval. The first run prepared each collision immediately before its measurement and overlapped other tests. The diagnostic run prepared every recording and collision object before measuring the shuffled uploads, with phase instrumentation and no remaining local test processes. Scratch scripts are not committed.

The profiled 32 MiB median `put` times were 81.361 / 73.122 ms (first/collision); unlink was 0.015 / 7.451 ms. The median gap reversed direction, and p90 remained high. This does not establish a passing timing contract or identify a single cause. No timing padding or acceptance threshold change was added. CTO follow-up is required before activation.

Live dev verification:

- `http://127.0.0.1:8100/health/ready`, with the dev application Host: HTTP 200, `ready`, `local-unreleased`.
- The public dev URL could not be exercised from this client (edge response 403).
- One login attempt for the documented fictional sandbox learner returned HTTP 401. Sign-in checks stopped; credentials and infrastructure were not changed. A Board action needed comment requests authorized fixture access through the CEO.
- The authenticated live two-owner journey remains unverified. After access is restored: visit `https://salesxray-dev.authorityclosers.com`, upload one fictional clip in each of two accounts, analyse both, delete A and confirm B still plays/analyses, then delete B and confirm erasure.

This is implementation and diagnostic evidence, not a passing D5 timing or live-dev acceptance receipt. The PR must remain unmerged until both are resolved.
