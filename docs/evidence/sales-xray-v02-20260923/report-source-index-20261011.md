# AUT-1677 — bounded Report source lookup

Baseline: `351b217`. Owner priority: finished saved Reports should open quickly
and keep older formats readable. The Report codec previously scanned every
transcript segment for each finding, summary/verdict reference, dimension
reference and detailed Overview reference. Long calls repeated that work.

The codec now builds a segment index once per Report read and uses it for those
references. It retains the previous first-match behavior; the transcript parser
still rejects duplicate IDs. The index stays within this invocation, so a later
privacy-withheld source is checked again. It changes no wire fields, stored
reports, source/quote/timing validators, skill states or human outcome rules.

## Verification

- 91 focused Report contract, saved preload and Story cases pass. The new cases
  preserve a populated legacy Report with its references at the end of a
  20,000-segment source and reject old quotes on a later withheld read using the
  same segment IDs.
- Incremental app typecheck, cached changed-file ESLint, Prettier and diff checks
  pass. No dependency, shared component, migration or worker change.
- A private offline comparison reads all 13 retained C5s against their original
  C2. Baseline and candidate outputs serialize identically for every report;
  three C5s are absent and no providers run.
- The existing actual Python account/guest projection, six-pillar/eight-skill,
  Word and per-call Coaching corpus proof passes on the candidate. Customer
  contents remain outside Git and logs.

The synthetic benchmark uses a populated fictional fixture, including eight
source references per dimension, and alternating baseline/candidate batches in
one process. Median codec times on this shared host:

| Segments | Baseline  | Candidate |
| -------- | --------- | --------- |
| 500      | 0.844 ms  | 0.289 ms  |
| 5,000    | 7.387 ms  | 0.770 ms  |
| 20,000   | 60.508 ms | 4.247 ms  |

These are offline synthetic codec measurements, not end-to-end or production
latency. The timing test is not part of CI; functional cases have no time-based
assertions. Source pins, count-only receipts and the benchmark are retained in
`/home/acdev/strikes/1677/report-source-lookup-receipt.json` and adjacent files.

## Deployed acceptance

The shared-dev populated nullable Report fixture is
`http://127.0.0.1:3026/review-fixture/report/legacy`. After the committed refresh,
verify its six pillars, eight skills, literal source selection and retained
Reading/Document views at 390/1440 in light/dark. The strike notes record the
source-bound screenshot receipt. No local build or preview server is needed.

Strike A still owns actual saved-call route/studio preload adoption. H/QA owns
authenticated production acceptance. Company/outcome persistence still waits
for the shared migration slot and canonical authority. No production/staging
write, provider activation, deployment or manual merge occurs here.
