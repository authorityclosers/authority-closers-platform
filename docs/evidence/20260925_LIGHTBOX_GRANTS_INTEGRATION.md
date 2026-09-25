# Lightbox and Admin integration candidate

Candidate integration parent: `3a1777bf` on
`codex/sales-xray-v02-release-20260925`.

## Included reviewed changes

- Inline report evidence and section navigation (`2867febb`), with 14 overview
  points, full quotations, direct playback and both report views preserved.
- Upload continuity and quiet first use (`07a4876e`): root-owned in-memory upload
  survives client navigation; read-before-retry, matching source identity,
  current consent and account-change abort guards protect the source transfer.
- Admin coaching-v5 contract repair (`8d487c5d`), including mixed revision history.
- Audited finite account minute grants (`e679b99b`) and the cross-target
  idempotency serialization fix (`0abcc0a3`). The full Admin grant screen and
  learner notifications are separate unfinished slices.

The individual implementation evidence records their bounded test results.
The earlier `2867febb` PR validation was green (Application 36082046358 and
Control plane 36082046265); that does not validate this later combined candidate.

## Combined local check and limitation

Admin settings/history: 10 tests passed. Admin and Sales Xray TypeScript checks
passed. Targeted Admin lint passed with zero warnings.

A combined upload/acquisition/Moments run did not pass: 37 failed, 46 passed,
and two workers could not load installed happy-dom modules. The first failures
were five-second timeouts, followed by overlapping React act calls and cascading
empty-render assertions. A concurrent Windows CIM check showed 13 MiB free
physical memory out of 7540 MiB; Git also reported a transient inability to read
its existing ignore file. The own-task preview was stopped. No timeout, assertion,
dependency version or required release gate was weakened to conceal the failure.

The per-slice upload run had passed 94 tests before integration; clean exact-source
CI is still required to distinguish resource interference from integration
regressions. The combined visual browser check was not completed. A clean CI
result must precede deployment, and live acceptance is a separate requirement.

## Release requirements

Build the application bundle, Sales Xray web image and native image from one
frozen source revision. The application bundle must include the updated Admin
web image to repair v5 settings; updating only Sales Xray web is insufficient.
Preserve active provider holds, credentials, tenant/consent boundaries and
canonical release activation. No production provider benchmark, credential
activation, successful real report or complete v0.2 claim is established here.
