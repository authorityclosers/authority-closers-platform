# AUT-1355: measured release CI after the duration-table refresh

Observed 2026-10-11T22:41:59.767874+00:00 at workbench `67e74ea29720b25d6b218635aa4720a972681fb9`.

This continues the earlier [implementation evidence](20261011_AUT1355_TEST_SPEED.md).
The existing checker, template database and refreshed scheduling table are unchanged.
No application tests were rerun locally for this receipt analysis.

## Exact source and coverage

The main run tested `fa846dc1264130e295eccc13daf6164c673c8a8a`.
The release PR API reports head `133af617e7f115c18898f101a133dc9c13185edb`;
its four artifacts identify tested merge `7f6fd297ac8026c3a2d4e6c138057148ae2ce3d4`.
These identities are retained separately.

All eight setup and scheduling inputs match the observed workbench bytes:
the application workflow, shard runner, duration reader, duration table,
exclusions, `tests/conftest.py`, and both database fixture infrastructure files.
The PR comparison uses the exact tested source tree; the main comparison uses
the local release commit. Each shard attests duration-table SHA-256
`6ddd63623b7b35f27da8f59cbe485e261bcaa899c404da9fde26278088d1a4f1`
and measurement source `a775389cd07e554fa3b6c979e45f8454f49e7d3d`.
The unchanged duration reader accepts all eight manifests and JUnit receipts,
including complete unique test-file scheduling and zero required-runtime
environment skips. Every required application validation job passes.

## Observed timing

| Run                                                                                                               | Shard job seconds (0 / 1 / 2 / 3) | Pytest seconds (0 / 1 / 2 / 3)        | Job max/mean | Pytest max/mean |
| ----------------------------------------------------------------------------------------------------------------- | --------------------------------- | ------------------------------------- | -----------: | --------------: |
| [Main 38176600054](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38176600054)       | 613 / 654 / 646 / 709             | 514.481 / 554.887 / 514.440 / 583.312 |        1.082 |           1.077 |
| [Release PR 38180369767](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38180369767) | 482 / 604 / 704 / 680             | 382.737 / 490.603 / 598.085 / 584.826 |        1.140 |           1.163 |

The main run meets the <=1.15 bound for both job and pytest wall times.
The release PR meets it for jobs; its pytest ratio is 1.163 and remains above
the target. The target therefore is not consistently met across these runs.
These observations do not establish a controlled overall speedup.

Each run reports 19,018 cases, with 4,333 skips on main and 4,329 on the PR;
both have zero failures and errors. This is not an all-cases-executed claim.
The median across the same ten application validation jobs is 378 seconds on
main and 411.5 seconds on the PR. Packaging and other workflows are excluded.
The duration table is retained: one higher pytest ratio alone does not establish
a scheduling regression or justify another refresh.

## Receipts and remaining handoff

Durable local evidence under `/home/acdev/strikes/1355/`:

- `refreshed-release-ci-timing-20261011.json`: sanitized counts, timings, source
  attestations and hashes of every raw shard receipt.
- `measure_refreshed_release_ci.py`: receipt validation and timing calculation.
- `release-ci-38176600054-{run.json,shards/}`: exact main metadata and receipts.
- `release-ci-38180369767-{run.json,shards/,input-tree.json}`: exact PR metadata,
  receipts and source-tree identities.

At the last observation, newer main run
[38181177711](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38181177711)
for `70000783a9bbe7f9b21523f978f04a7d3084a83e` was still running.
Its result is not inferred from the successful PR. The coordinator owns release
execution and production verification; these CI receipts do not certify
current workbench HEAD or a production version.
