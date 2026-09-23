# SX-WS-01: bounded observed-view prototype

Public sanitized architecture and executable model source. No customer data, conversation transcript, private document extracts, credentials, operational receipts, or model prompts are included. Fictional tests are intentionally separate from actual response capture. This is not an installed workbench, browser demo, or deployment.

## Run without installing dependencies

From a repository checkout with its pinned toolchain already installed:

```sh
pnpm exec tsc -p docs/cloud-handoffs/sx-ws-01/tsconfig.json
node --test docs/cloud-handoffs/sx-ws-01/test/core.test.mjs
node docs/cloud-handoffs/sx-ws-01/test/fault-sim.mjs 20260923 10000
node docs/cloud-handoffs/sx-ws-01/verify-manifest.mjs
```

Alternatively, from this directory with TypeScript on PATH: `npm test`, then `npm run simulate`. There is no npm install step and no dependency or lockfile change. Compilation emits ignored `.build/` files. The prototype uses the standard Node test runner and WebCrypto SHA-256.

Integration target: Node 24, pnpm 11.19, TypeScript 5.9.3, Next 16.3.3, React 19.2.8, and the host repository's pinned Node Playwright 1.58.2 when browser checks are performed. The prototype itself needs no Playwright, React, or Next dependency. Compiler and runtime actually used for a test run must be reported independently; compatibility is not proof of running the target toolchain.

## Minimal interfaces

`FrameStore` accepts a trusted scope, clock, parser and reauthorization port. Its capture input contains bounded GET-response bytes and observed UI state. It calculates response fingerprints rather than accepting caller-supplied hashes. The parser derives workflow classification and verifies application contracts; controls do not set backend stages. `reauthorize(frameId)` requires fresh scope/binding and exact artifact grants. `read(selection)` returns live delegation, an authorized display frame, or an explicit unavailable reason.

`workspaceViewPort(liveModel)` is a production pass-through returning the identical model reference. It imports no local review runtime. `createDevViewPort(store, project, environment)` has the same rendering interface and selects display data only. There is no operational React state assignment. `parseCommand` and `parseReviewAddress` reject unknown keys, arbitrary destinations, invalid selectors, unsupported controls and oversized command text. The finite command queue has a maximum of 16 entries.

## Evidence honesty

All bundled test data and simulation results are fictional model evidence, not API, browser, provider or deployed-product evidence. The `actual-response` lane is a trusted collector assertion, not a cryptographic attestation. Only a separately verified fixed-origin bridge collector may construct it. A browser-supplied JSON object, body hash, state name or frame ID does not prove an actual response or access rights. The kernel has no network implementation.

`test/helpers.mjs` is a deliberately tiny fictional parser. It must never be imported into an actual-response adapter. The application adapter must reuse the real report/transcript/progress parsers, including their source binding, then return `ParsedView`. `Artifact` metadata is trusted only after those parsers pass. Partial/disagreeing bundles are rejected. A completed report never manufactures a past queued/running observation.

## Bounds and freshness

Default limits: 128 frames, 16 MiB retained UTF-8 serialization, 4 MiB per response, three response resources per frame, 30-minute capture TTL and 30-second authorization lease. Bounds may be lowered, not silently increased. Only one capture may allocate in flight; a concurrent capture returns `capture-busy` rather than creating an unbounded queue. Frame eviction is oldest-first and never falls back to the live API. Duplicate observations do not extend the original TTL. Older ordinals, reset races and mismatched scope/artifacts fail closed.

The byte counter is serialized retained content, not a precise V8 heap measurement; parsing, cloning and callers' copies have overhead. Expiry is enforced on access and pruning. The bridge integration needs an idle sweep and renderer expiry notification so idle buffers and already rendered private data are cleared without waiting for another action. JavaScript cannot guarantee immediate physical memory erasure or revoke copies already exported by a person.

The authorizer has a bounded deadline and receives AbortSignal. The trusted implementation must honor cancellation and obtain an authoritative check rather than label cached data fresh. Call access alone does not authorize an old report/transcript: grants include the retained artifact fingerprints. Failure to retrieve/authorize an old revision makes it unavailable. The injected clock is fictional only in tests; the live collector uses real time and no browser-wide fake clock.

## Not implemented here

The first kernel captures status/transcript/report only; media, plan and pre-submission capture remain unavailable until separately integrated. No bridge HTTP capture/RPC transport, CSRF middleware, actual application-parser wrapper, React integration, control-page UI, background expiry notification, Next alias/build exclusion, live authentication test, pixel capture, HMR browser proof, or deployment is delivered in this directory. The dev guard is tested as a function; it is not proof of the host application's module-graph exclusion. The optional real bridge read-only policy is an integration dependency, not replaced by `reviewRequestAllowed` (a limited standalone test model).

Detailed seam, boundary and release gates are in `INTEGRATION.md`. The sanitized architecture and complete proposed catalogue remain in `Decision-and-Handoff.md`, `contract.json` and `acceptance.json`. These documents are an architecture edition, not a private instruction transcript.

Decision: preserve one canonical call workspace with separate live/observed/presentation semantics. Confidence in direction: 0.90. Rejected: route-per-stage authority, replaying history as public API responses, duplicate screens, and a new framework. Stop at the bounded kernel and falsifiable integration gates. No processing spend, merge or deployment is authorized by this package.
