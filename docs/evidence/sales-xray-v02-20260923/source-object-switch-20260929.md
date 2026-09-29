# AUT-43 shared-source switch — 29 September 2026

Base: `922756813de5d0f1f3e6d60f8ea481cd259e29de`; branch `task/sales-xray/81-source-object-switch`.
Authority: AUT-43 amended CTO spec and ADR 0033. Fictional data only; no providers activated.

Implementation:

- New uploads publish `SourceAudioKey(tenant, sha256)` and attach permanent reference rows after full input verification.
- Object acquisition always inserts with conflict-ignore, then selects the live row for update. HTTP upload and erasure callers retain the existing storage-root fence through commit.
- Shared publication and collision each stat the final object after disposing of the temporary link. POSIX keeps the spool descriptor open until hand-off to one background closer; Windows keeps close-before-unlink. Neither opens stored content; reads still verify its digest before yielding bytes.
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
- Follow-up: **45 storage/intake tests and four HTTP/reference checks passed**; Ruff format/check and mypy passed. The closer test proves one descriptor per path, no temporary names, open descriptors until hand-off, background close, and no descriptors after drain.

Original D5 timing evidence (milliseconds; **the CTO withdrew this threshold on 29 September**):

| Protocol             |      Bytes | First median / p90 | Collision median / p90 | Median gap | Limit | Result |
| -------------------- | ---------: | -----------------: | ---------------------: | ---------: | ----: | ------ |
| Initial              |     86,016 |   89.585 / 100.710 |       87.338 / 102.376 |      2.248 | 5.000 | pass   |
| Initial              | 33,554,432 |  204.837 / 303.241 |      274.713 / 327.380 |     69.876 | 5.000 | fail   |
| Pre-seeded, profiled |     86,016 |    27.254 / 33.510 |        27.352 / 32.633 |      0.098 | 5.000 | pass   |
| Pre-seeded, profiled | 33,554,432 |  109.689 / 215.300 |       98.956 / 268.703 |     10.733 | 5.000 | fail   |

Each run used 30 first and 30 collision uploads per size, shuffled with seed `4300929`, two fictional owners in one tenant, full seeded byte streams, and two excluded warmups. Timed `store_source` only; transaction commit, fixture registration and fence acquisition are outside the interval. The first run prepared each collision immediately before its measurement and overlapped other tests. The diagnostic run prepared every recording and collision object before measuring the shuffled uploads, with phase instrumentation and no remaining local test processes. Scratch scripts are not committed.

The profiled 32 MiB median `put` times were 81.361 / 73.122 ms (first/collision); unlink was 0.015 / 7.451 ms. The median gap reversed direction, and p90 remained high. The CTO prescribed deferred spool close and a replacement ABBA full-HTTP protocol. No timing padding was added.

Replacement protocol: **86 KB passes; 32 MiB fails Pass 1**. Each size uses 100 first and 100 collision HTTP requests in ABBA order, fixtures/collision uploads prepared first, and two excluded warm-ups. Seed `4300929`; 0.5-second fictional PCM WAVs contain seeded RIFF JUNK data to reach exactly 86,016 or 33,554,432 bytes. Real native preflight, request fencing, all SQL and commits are included. No other local test process was active at launch. Each round's byte cleanup and closer drain occur outside timing. SQL/phase instrumentation adds overhead; bootstrap uses 10,000 seeded independent resamples. Full-request resolution is broad, so this does not prove precise timing equality.

|      Bytes | Phase                  |  First median / p90 | Collision median / p90 |   Difference 95% CI | Half-width |
| ---------: | ---------------------- | ------------------: | ---------------------: | ------------------: | ---------: |
|     86,016 | spool write hash fsync |       1.741 / 4.178 |          1.931 / 4.084 |     [-0.044, 0.423] |      0.233 |
|     86,016 | commit                 |       1.514 / 3.663 |          1.500 / 3.850 |     [-0.149, 0.194] |      0.172 |
|     86,016 | request                |  981.365 / 1892.815 |    1158.161 / 1822.535 | [-356.519, 485.192] |    420.855 |
| 33,554,432 | spool write hash fsync |    99.002 / 207.000 |      109.195 / 186.728 |   [-44.565, 38.202] |     41.383 |
| 33,554,432 | commit                 |       1.618 / 2.887 |          1.521 / 2.569 |     [-0.215, 0.052] |      0.134 |
| 33,554,432 | request                | 1468.751 / 2592.265 |    1444.642 / 2430.156 | [-563.426, 634.416] |    598.921 |

All values are milliseconds; differences are collision minus first. Link/unlink/stat/hand-off median gaps are at most 0.020 ms at both sizes. The 287 SQL statements have identical order; their maximum median gap is 0.354 ms at 86 KB. At 32 MiB, statement 259 (`UPDATE conversation_minute_accounts SET snapshot=…, revision=…`) fails: first median/p90 **16.034/56.330**, collision **15.001/54.157**, absolute gap **1.033 ms > 1 ms**. All other SQL phases pass. Work stopped under the CTO's Pass 1 stop rule; no limit change, padding or repeat-to-pass run.

Live dev verification:

- `http://127.0.0.1:8100/health/ready`, with the dev application Host: HTTP 200, `ready`, `local-unreleased`.
- The public dev URL could not be exercised from this client (edge response 403).
- One fictional sandbox login returned HTTP 401 and checks stopped. CEO/CTO subsequently confirmed this does not block AUT-43: the pre-merge evidence is the PostgreSQL HTTP tests. No account provisioning is required.
- AUT-257 owns the unverified live journey once the merged build reaches the working dev upload/analysis stack: at `https://salesxray-dev.authorityclosers.com`, two fictional accounts upload/analyse the same clip; delete A and confirm B still plays/analyses, then delete B and confirm erasure.

The PR remains draft until the replacement D5 protocol and CI pass. Live dev verification is deferred by the CEO/CTO decision.
