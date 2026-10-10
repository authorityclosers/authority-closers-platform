# AUT-1344: parallel saved-report reads

Source: `main` at `4c76de1c69e7edc77f36486dbf347d2bdfc0b862`.
Specification: `/home/acdev/scratch/ea-study/reports/r1-performance.md`,
section 3, card 7. Work is confined to the established sx-shell checkout.
The gate reported main green and admitted `1344-parallel-report-fetch`.

After canonical progress confirms `has_report`, the actual observer starts
transcript and report reads with `Promise.all`. It parses the transcript first,
then validates the report against that transcript and the selected submission
and recording. Both reads retain the same caller cancellation signal and the
existing reader's 30-second per-request timeout. The studio's existing effect
cleanup aborts that caller signal on navigation/unmount.

## Before/after browser measurement

The study's original `browser-study.cjs` visits dashboard and Calls-list routes;
its synthetic responses do not include a saved transcript/report. Running it
unchanged cannot measure card 7. The checked-in
`apps/sales-xray-web/tests/saved-report-performance.mjs` extends its Playwright
request timestamps, synthetic route fulfillment and 150 ms delay to this exact
observer, and also checks the study's upper 300 ms delay estimate.

The same harness and synthetic acquisition canary ran before the observer edit
and afterwards, three times per delay, on the same host/browser. Vite loads the
actual observer and its existing parsers before the timed observation. Every
sample returns a verified report through exactly three GETs. No audio upload,
provider call, backend write or real customer data is involved.

| API delay | Before median (range) | After median (range) | Median gain |
| --- | --- | --- | --- |
| 150 ms | 598.5 ms (595.5–686.9) | 399.1 ms (391.0–493.6) | 199.4 ms |
| 300 ms | 995.5 ms (919.3–1009.6) | 616.9 ms (611.5–697.5) | 378.6 ms |

Transcript/report start gaps were 200–218 ms before at the 150 ms delay,
305 ms before at the 300 ms delay, and **0–1 ms after** in all six samples.
This proves three request waves became two without reducing the GET count.
Raw samples, source/script digests and summaries are in
[saved-report-timings.json](aut-1344/saved-report-timings.json).

Replay from the repository root with the existing browser installation:

```bash
node apps/sales-xray-web/tests/saved-report-performance.mjs "$PAPERCLIP_RUN_SCRATCH_DIR/saved-report-timings.json"
```

The harness requires a run-owned scratch directory and stops its browser/server
in `finally`. It allows requests only to its loopback origin and mocks all API
reads. This is an observer measurement through Vite, not a production-build page
paint measurement. Shared-host scheduling adds noise; the 300 ms median gain
includes that noise and is not a guaranteed production saving.

## Validation

- The two new overlap assertions failed against the original observer: only
  the transcript request had started. They pass after the implementation.
- The five-file run passed 178 of 179 tests, including all 14 observer tests,
  report contracts, analysis start and owner surfaces. One existing acquisition
  playback test exceeded its default five-second limit.
- That exact playback test passed alone with `--testTimeout=15000`; its
  assertions completed in 6.21 seconds. No test timeout or playback code changed.
- ESLint passed on the observer, new tests and measurement script, with zero
  warnings. All changed web files were formatted with the repository Prettier.

```bash
pnpm --filter @ac/sales-xray-web exec vitest run app/observe-submission.test.ts app/report-contract.test.ts app/owner-surfaces.test.tsx app/acquisition-studio.test.tsx app/analysis-start.test.ts --maxWorkers=1
pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-studio.test.tsx -t 'toggles every visible clip control against the one shared player' --maxWorkers=1 --testTimeout=15000
pnpm --filter @ac/sales-xray-web exec eslint app/observe-submission.ts app/observe-submission.test.ts tests/saved-report-performance.mjs --max-warnings 0
```

Observer tests cover both completion orders, progress gating, transcript-first
validation, report schema and submission/recording/hash/revision mismatches,
malformed report content, cancellation of both pending requests, and the exact
timeout boundary when one or both requests stall. Owner-approved surfaces are
unchanged.

## Dev/release boundary

Before editing, the existing shared preview at
`http://127.0.0.1:3016/analysis/calls` returned HTTP 200 and its loading shell was
inspected with Playwright, with all API calls intercepted as synthetic signed-out
responses. That server belongs to the UI checkout, so it was preserved. No
dedicated live sx-shell preview was found. Mounted studio tests and the browser
observer harness verify this branch locally; authenticated deployed dev,
staging and production verification remain with the normal release path.

To check after normal dev delivery, open a fictional saved canary with a report
and inspect the Network panel: progress completes first, then transcript and
report start together. Navigate away while both are pending and confirm both
are cancelled. No host/systemd/Caddy/env-file, data, provider, scoring or access
activation is included in this PR. Lead Engineer reviews the exact PR SHA and
CI. Production version and What's new remain release-engine responsibilities.
