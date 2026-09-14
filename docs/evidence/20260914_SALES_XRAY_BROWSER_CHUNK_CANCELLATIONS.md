# Standalone browser proof: cancelled navigation scripts

Root release base: `5a393eb65cec0105cafb564209150b865b0531f5`.
The owned leaf starts at `96a0a7bff89c87a69ceb487c148dec0725234240`;
the starting standalone test bytes are identical to the root release base
(`f40b5819c10dfb074ebafc1236c6a0c35995783d371724d79db66b1652fa1f0e`).

CI [34850165984](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34850165984)
finished with 5,612 passed, 1 failed and 1,253 skipped. All 15 standalone workflow
checks passed before the final network assertion rejected one JavaScript request:
`GET /_next/static/chunks/1ovm88hcg4mdk.js: net::ERR_ABORTED`.
That historical receipt lacks request lifecycle timing, so its exact cause is
not independently established. The same cancellation class was reproduced locally
during password login by delaying real emitted route scripts.

## Changed evidence boundary

The test records main-frame navigations and completed, destination-checked windows
around sign-in navigation, password login and anonymous reload. A script cancellation
can qualify only when all original workflow assertions pass and:

- It is a same-origin main-frame script GET with exactly `net::ERR_ABORTED`.
- Its path is a safe emitted Next chunk filename, without query or fragment.
- The cancellation falls inside a successful navigation window with an actual
  main-frame navigation event to the verified destination.
- The exact file exists under the static export and independently returns HTTP 200
  without redirects, with JavaScript MIME type and bytes matching the local SHA-256.

Every cancellation stays in the receipt, including its resource/frame context,
timing, successful navigation and independently fetched asset hash. Other network
failures and page errors remain failures. Completed static responses are now also
recorded and rejected unless 200 or 304. Existing API success, cookie, tenant denial,
logout and availability assertions remain intact. No production source, retries,
timeouts, API response mocks, provider calls or deployment settings changed.

## Actual local receipts

| Execution | Result | JUnit time |
|---|---|---:|
| Five-second delay of real route chunks requested from `/login/` | 1 passed; all 15 workflow checks; 2 navigation cancellations independently fetched and byte-verified | 28.675 s |
| Normal scheduling | 1 passed; all 15 workflow checks; no script cancellations | 36.274 s |
| Cheap boundary controls using a loopback static HTTP server | 16 passed | 5.696 s |

The negative controls reject missing export files, actual HTTP 404/503 responses,
redirects, wrong MIME types, differing bytes, API paths, foreign origins, subframes,
non-script resources, other network errors, non-GET requests, unsafe paths and
cancellations outside a completed navigation. Both full workflow runs have zero
external requests, page errors, static response errors and unexpected failures.
They use real Chromium, loopback AC HTTP, disposable PostgreSQL and synthetic data.
Ruff lint/format and `git diff --check` pass.

External evidence packet:
`D:/AC-authority-closers-release-audit/peer-sales-xray-ci-chunk-repair-20260914.json`
SHA-256: `1d9d35500418642882763f5dedcdef9f801fc2b5bd8cb5dddf180990c5197733`.
It indexes the test source, JUnit, logs, browser receipts, timing-only middleware and
actual delayed-request trace with hashes. The middleware changes latency only;
existing application/static handlers and their response bytes remain in use.

The reused local static export has no relevant source delta from its verified build
base; its generated chunk filenames differ from the CI artifact. Exact release CI,
staging/production tests and actual new-model report quality remain separate proofs.
