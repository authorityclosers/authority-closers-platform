# Release recovery checkpoint — 2026-09-11

Status: active recovery; this is not a production or cohort acceptance record.

Work item: [issue 52](https://github.com/authorityclosers/authority-closers-platform/issues/52).

## Verified identities

- Release workspace: `C:/Users/Suyash/.codex/worktrees/9191/authority-closers-platform`, branch `codex/release-recovery-20260911`, base `1c20a80280e83c6d20e835dd96538f2f8c1f0e0b`.
- GitHub main is that same base. Saved local main remains clean at `65b1f36c2507fba706eecee4e565158cc7492baa`; it was not updated or used for implementation.
- PR [47](https://github.com/authorityclosers/authority-closers-platform/pull/47) is open at `cb8df7b44fc79144a6697a77966f4a4c6088932f`, conflicting, with no status-check results attached at this observation.
- Staging current link and `/health/ready` report `1c20a80280e83c6d20e835dd96538f2f8c1f0e0b`.
- Application validation [34563384317](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34563384317) succeeded, including validate, capacity simulation, and release-image packaging. Control-plane validation [34563348247](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34563348247) succeeded. The earlier application run was cancelled and is not used as passing evidence.
- Artifact `10185451417`, `ac-application-1c20a80280e83c6d20e835dd96538f2f8c1f0e0b`, is unexpired, 192,097,974 bytes, digest `sha256:3f16bb7aa9c7f6a79e647667b3b630da8c585188cd0253b11009f089e13a1fbd`, bound to that exact successful run and commit.

The trusted `Deploy-Staging.ps1` controller detected the already-active release and took its read-only path. It exited 0 after route, static asset, health, disabled public API documentation, Admin Access, Coach login, legacy route, exact runtime/checksum and WordPress boundary verification. This operation did not deploy, reapply configuration, run migrations, or issue a new OAuth transaction.

## Runtime receipt and availability

The committed receipt is `/srv/authority-closers/application/deployments/staging/20260911T062241Z-1c20a80280e83c6d20e835dd96538f2f8c1f0e0b-wuZDPG.env`. It references prepared evidence `20260911T062215Z-1c20a80280e83c6d20e835dd96538f2f8c1f0e0b-prepared-ylqyPh.env`, predecessor `8474c9824fdfdbc41730df52c3e7a1119473d2a1`, and migration head `20260910_0027`.

| Component | Immutable runtime image |
| --- | --- |
| API / worker | `sha256:218c432e4615ef1af5811c20969d1460a7d4621ab0dbdac19f7a2148574521bb` |
| Learner | `sha256:d8c99020cad1f26e44834c5611d1020304e2319f0d2ef10be0a2b65181ca0cb2` |
| Admin | `sha256:e6cf5819e1494fb4ca8ed9ce740c67415839df36524e7e33f8acd3761b9a0545` |
| Coach | `sha256:f859e4aad154ca67a32ffa9bfe50fdf2d4863e888497e76236529a7a9f045919` |

The installer backup reference is `/srv/authority-closers/backups/application/staging/20260911T062142Z-pre-1c20a80280e83c6d20e835dd96538f2f8c1f0e0b.VbDVV4.dump`. This reference alone does not prove paired logical-backup metadata or satisfy the 0027-to-0029 rehearsal. The controller's recovery policy preserves post-exposure writes: forward recovery after exposure, with no downgrade or operational direct SQL edits.

Staging Learner/Coach login return 200 and API readiness returns 200. Admin redirects to `restless-cherry-c46f.cloudflareaccess.com`. Production API, Learner and Coach return 503; the API states the production application release is not active. Production Admin remains behind the same reviewed Access tenant. No production activation was performed.

Scanner container `ac-media-safety-scanner` is running but unhealthy at release `3eb24da05caced66f15dcfe58ffc086014da8b0d`, pinned image `clamav/clamav@sha256:5a7c486fc98339860373284f48a670b74b1f25f15812b327fbe5b684061cf42f`. Its retained archive SHA-256 is `f4ed561104193502ee01a62b48109dcc5b1eb2850ed23bb55d5fc96c63eb143f`; Docker still uses `CMD clamdcheck.sh`. No new scanner readiness is claimed.

## Preservation and ownership

Read-only inventory found 21 registered worktrees, six dirty and 15 clean. Both security candidates have the same ten dirty file contents; nine match d2de. The differing runbook line says Next 16.3.3 in the security candidates but 16.2.11 in d2de. Both next-action backend files match telemetry-restart exactly; the full next-action source has additional learner/tests/evidence paths. The 25ac predecessor is not byte-redundant and remains preserved.

UI task `01a08f28-507b-75c1-a57c-ec0487096913` remains the single product/UI writer in d2de and owns the first heavy workload slot. Release task `01a08f28-00cf-7811-9aa0-414b5a0d530a` owns only the explicitly frozen release paths. The ten-file transfer is recorded in `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/release-path-freeze-20260911.json`; source and destination SHA-256 were verified for every copied file. No original dirty file, user asset, old worktree, or saved main was changed.

The dirty-only transfer exposed a committed dependency gap: the new scanner controller needs the IPv4 Compose healthcheck from the UI history. That dependency requires an additional explicit hash handoff. Rehearsal similarly needs the exact candidate's 0029 migration/schema and immutable image before execution. Neither gap is treated as successful acceptance.

Subsequent verification: `scanner-dependency-freeze-20260911.json` explicitly
transferred Compose and both scanner configuration files; source/destination
hashes match. The IPv4 healthcheck dependency is now included. Independent
review's rollback precondition defect was fixed and the focused scanner suite
passed 56 tests; Ruff lint/format checks pass. A managed names-only production
configuration check at 06:46 UTC found zero of the 13 required application
names present. No values were printed or copied. The newest retained paired
logical-backup metadata filename observed is dated 2026-09-10 07:15:40 UTC;
fresh backup operation evidence still needs reconciliation.

## Controlled requirements and next gates

Read in required order by manifest IDs: Master Index, BRD, AC-IMP-00/01/03/04/05, followed by PRD, IA, UX Research/States/UI, SRS, Data/Tenancy, API/MCP, Security, DevOps, QA, Admin, Telemetry and ADR/Risk. AC-UXA-01 was fetched for recovery acceptance. Controlled Drive documents remain authoritative; this file is implementation evidence only.

- [AC-IMP-03](https://docs.google.com/document/d/1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo/edit): P0-03 recovery side effects, P0-07 restore proof, ENG-G07/G08 migration and immutable artifacts.
- [AC-IMP-05](https://docs.google.com/document/d/1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw/edit): WRK-G0-010/021/022/023/024 artifact identity, readiness, backup, isolated restore and side-effect hold.
- [DevOps](https://docs.google.com/document/d/1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs/edit): CI, traceable OCI images, migration rehearsal, health, rollback and measured recovery evidence.
- [QA](https://docs.google.com/document/d/1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg/edit): failure/retry, security, recovery and exact journey evidence.

Next: finish scanner dependency reconciliation and independent review; run the bounded scanner and recovery tests after UI releases capacity; package the reviewed immutable scanner transition; obtain paired 0027 backup metadata and independently attested 0027/0029 images; execute the disposable held-side-effect rehearsal. Authenticate and capture exact-release Learner/Coach/Admin evidence and file it in Drive. Resolve production configuration and release gates before eligible promotion. Continue the controlled learner/Studio/admin backlog; one scanner or UI slice does not complete the program.
