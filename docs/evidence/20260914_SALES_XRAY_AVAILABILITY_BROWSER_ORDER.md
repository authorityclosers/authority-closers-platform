# Standalone browser proof: availability response ordering

Base: `d13204daf627532ccebf70670fda26e00caf93cf`.

CI run [34846345070](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34846345070)
finished with 5,612 passed, 1 failed and 1,253 skipped. The sole failure was the
standalone browser proof waiting for its first availability response.

## Cause and change

This fixture intentionally disables acquisition intake and exercises account-only
CallStudio. AcquisitionStudio initially mounts its availability widget; when the
real `/entry` response says `enabled: false`, the fallback removes the widget and
aborts its outstanding read. Requiring that transient read to complete before
the entry response made the test depend on request ordering.

The test now awaits and verifies the complete disabled-entry response, observes
the sign-in fallback, and explicitly fetches availability from the settled browser
page. HTTP 200, the exact `{"paused": false}` body and `no-store` remain required.
Every completed availability response must still be 200. Only this exact optional
GET's `ERR_ABORTED` is classified as component removal after those checks pass;
other request failures still fail. Navigation cancellations remain separately
recorded. No production source, guards, timeout or retry policy changed.

## Actual focused proof

Fresh worktree at the stated base; isolated Chromium, actual loopback TCP HTTP,
AC password/session/tenant routes, disposable PostgreSQL and verified AudioAtlas.
No provider calls or response-payload mocks.

| Run | Result | Elapsed |
|---|---|---:|
| Original test; one-second delay before the real availability handler | Same response timeout reproduced; sign-in fallback visible, availability aborted | 52.386 s |
| First changed test | Failed on an incomplete expected entry shape; corrected to include the four actual null fields | 19.262 s |
| Final test; same one-second handler delay | 1 passed; 15 checks; 3 expected widget cancellations; no unexpected failures | 25.811 s |
| Final test; normal response scheduling | 1 passed; 15 checks; 1 expected widget cancellation; no unexpected failures | 22.581 s |

Both final runs still verify password login, workspace selection, private saved
report, real audio playback/seek, C1 level/pitch values and chart, eight sales
factors, source transcript, host-only cookie, cross-tenant denial and source/
measurement/history denial after logout. Both have zero browser errors and zero
external requests. Ruff lint, Ruff formatting and `git diff --check` pass.

The existing static export was reused only after verifying no frontend/client/UI
or lockfile source delta between its earlier build base `82cbe661` and this base.
AudioAtlas source and binary hashes match its retained build metadata. This is a
local focused regression proof, not an exact deployed-image or live-call test.

## Retained evidence

External packet: `D:/AC-authority-closers-release-audit/sales-xray-ci-availability-order-repair-20260914.json`
SHA-256: `c7c6a35d5e2c0642cae4a6626b41183a403c25969f7e12a4869e5d06abde50c5`.
It indexes all four JUnit, log and browser receipts, including failures, with hashes.
The latency-only reproduction plugin is `slow_availability_probe.py` in that audit
directory; it delays the existing handler without replacing its response.
Final test source SHA-256: `f40b5819c10dfb074ebafc1236c6a0c35995783d371724d79db66b1652fa1f0e`.

The release owner must integrate this patch and run the new exact release checks.
Staging/production publication and real report quality are not claimed here.
