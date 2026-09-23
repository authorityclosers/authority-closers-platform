# Sales Xray staging 819a checkpoint

Observed on 2026-09-22, after the earlier 9986 checkpoint. This is staging
evidence, not a production or universal-user acceptance claim.

## Exact candidate and checks

The product candidate is `819a3b1016b833908d25cf2a0c58a6e52d54fd74`.
Exact application workflow `35754764681`, web workflow `35754759908`, and
native workflow `35754854400` passed. The compiled browser artifact records
15 assertions, 76 HTTP observations, zero API interceptions, and zero errors.
Its provider adapters are synthetic; real provider acceptance is recorded
separately in the earlier live guest canary.

The only changes from product candidate 819a through
`6ed3f057d64ee7f7309a3a194ec10ec202bd2c67` are a test readiness wait and its
evidence. PR workflow `35757875911` passed every validation job, including
the required compiled browser journey. Production images remain pinned to
the separately verified product candidate.

## Staging deployment

The canonical application installer committed 819a at 17:13:44 UTC. Staging
API and Sales Xray web readiness both return HTTP 200 with the exact 819a
release ID. The API and web Docker health checks pass. Both application
workers are running with zero restarts; they do not define Docker health
checks. The native helper is active on the verified 819a image.

| Component | Runtime image |
| --- | --- |
| API and workers | `sha256:a8af2dcbb13f3b3bcdf0f46f22f55561988bf69f77c43c9170ed65ae69a5bab6` |
| Sales Xray web | `sha256:9be2470103f7eb7a8be6719edd9dcd6181cd28c7fc7b367975e432e1f4f05398` |
| Native helper | `sha256:71525e09b5575633159bed3fc6426c47d716bb32142d090d4ff7d4145f0ee141` |

An initial installer attempt encountered an Infisical 504. The subsequent
attempt rejected writable generated activation inputs. Sealing the exact
generated environment and worker manifest preserved their SHA-256 values
and the existing staging approval. The worker manifest was set through the
source-owned metadata helper. The standard installer then passed, including
its release hold, backup, migration, routing, and startup checks. No
operational SQL repair or provider-policy modification was used.

Future activation preparation must verify trusted file metadata and candidate
schema before draining the old services. Rollback artifacts, old approval
files, and the failed-attempt evidence remain preserved.

## Browser evidence on the complete release

The fresh fictional guest call previously completed live C2/C4/C5 processing,
Google sign-in, explicit account claim, and Saved calls listing. On 819a its
saved report renders, audio advances to 14.319946 seconds of 72.897823 seconds
without a media error, and a reload renders the report again.

The original retained call also renders on 819a. Its audio advances to
12.271398 seconds of 225.558333 seconds without a media error. Reloading
renders the recovered report again. Recovery used zero additional provider
calls and preserved the original failed task/job/response history.

For both reports, observed report, transcript, and waveform responses return
HTTP 200; audio returns HTTP 206. Separate bounded network observations
around reload contain zero mutating API requests and were not truncated.
The browser's four report tabs are present. The previous frontend-only phase
also exercised the individual tabs and rejected unauthenticated access to
history, report, and source with HTTP 401.

Private evidence is retained outside Git. SHA-256 values:

- Complete browser receipt: `b7dceee9343581fc4cfff90b45d89f11a17f76a357c1557313d0f8a2f4211f1e`.
- Complete deployment receipt: `253da931f2f3dc0183f842fabfda142d29ccf895b6649ac734c1816d20b69b43`.
- Public readiness receipt: `02e7199bcbc4d7e7a7d820e82fd08426a0b1a69a7cc15a6b5b97217a11c3a80b`.

## Remaining acceptance

A fresh authenticated MP3 is selected, but accepting its Terms and submitting
it still awaits the separate owner confirmation. The live guest call was
claimed before the corrected browser was deployed; a fresh unclaimed guest
display on the complete release is not established by the saved-report check.
The compiled browser gate covers that path with synthetic server adapters.

Production remains on its prior release and its API readiness returns HTTP
200. Its provider approval had expired. The owner subsequently approved the
specific 819a renewal through 2026-09-29 16:45 UTC with existing controls
unchanged. Issuing and validating those inactive inputs is separate from
deploying them. Production deployment and a live production synthetic canary
remain contingent on staging acceptance. Human coaching-quality review,
broader user/device coverage, and measured soak remain separate evidence.
