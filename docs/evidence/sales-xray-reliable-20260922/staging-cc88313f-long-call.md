# Hour-long staging acceptance checkpoint

Candidate: `cc88313fb27d0ab89023f747ca0c00634c09bc9c`.
This is an intermediate checkpoint, not completed long-call acceptance or a production release.

## Exact release and verification

All five exact-candidate application, native, web, PR application, and control CI runs passed:
`35781166817`, `35781170345`, `35781174325`, `35781151623`, and `35781151621`.
The manual-source compiled browser artifact `10717194121` verifies 15 synthetic
journey assertions for the exact source. It does not establish provider acceptance.
The separate PR browser artifact uses the PR merge tree and is not substituted for this proof.

The canonical staging installer committed the candidate at
`20260922T205503Z-cc88313fb27d0ab89023f747ca0c00634c09bc9c-Lycj5F.env`.
Verified runtime images:

| Component | Image SHA-256 |
| --- | --- |
| API and workers | `efa61b5039709efbfc247f739a7e4ee392925c2a19b3a0d4f389f2fcba93aa26` |
| Web | `b312f657b20e16330a772c6ef69497d3c1705e7732583db709e591a1463f3e3d` |
| Native | `3a4ac37266a15128e4272940129c1e3a712469530162a2a6ed2fb81add754177` |

Local validation passed 1,142 conversation unit tests (one POSIX-only skip),
272 web tests, 16 acquisition PostgreSQL tests, and 15 inference PostgreSQL tests.
Python lint/format/type checks and web type checks passed. Independent review
found no P1/P2 defects in the bounded provider-storage change. A process kill
between receipt commit and raw persistence was not exercised; the reviewed
recovery path rejects redispatch and requires retained bytes for reuse.

## Approved retry and preserved history

The source fixture is fictional: 3 voices, 168 turns, 9,359 script words,
3,597.994104 seconds, 28,784,684-byte stereo MP3.
Source SHA-256: `d7d7f203fd96875bf3c95768d8c48202ea2c5c8b2d19f693833073a7609965f3`.
It contains no loop or silence padding.

Normal browser upload created recording `1d077fb8-5fe3-43cc-bc30-18491eb91e1f`
and completed native processing. Initial plan acceptance returned 403 because
the earlier failed recording had consumed the source's one transcription attempt.
This was the intended cross-upload provider allowance fence, not a new provider call.

The owner explicitly approved a temporary staging profile-wide change from one
to two C2 attempts per source, with restoration to one after the test. It is not
an exact-source-only exemption. The issued approval
`151e803bb229a33941e28e9a0e1d732aac9f8ac0ab594c25acad9ed70ed35ff5`
changes only that field and the issuance timestamp. It retains the policy ID,
configuration digest, prior uncertain reservation, expiry, tester scope, privacy,
retention, and INR 1,000 total testing ceiling. The earlier approval and descriptor
remain preserved. No source identity alteration or direct SQL recovery occurred.

Canonical same-source activation committed at
`20260922T211436Z-cc88313fb27d0ab89023f747ca0c00634c09bc9c-uHXckd.env`.
All services were healthy/running with zero restarts at 21:14:59 UTC.
The fresh plan `b22e25c2-b587-45d9-a6a8-8ffc17c42674` quoted INR 418.
The proposal's INR 440 estimate was conservative: the actual plan requests one
C2 call while the release approval allows two across the source's history.

## Live result and remaining failure

C2 run `0ea23a9d-d2c2-4ce7-9bfa-c357aa8d850e` completed successfully.
The retained provider response is **2,210,229 bytes**, exceeding the previous
single-chunk storage boundary, and its digest was rechecked through the private
storage adapter:
`1513a4a5069a7f0e61d052efe859a76ef8ae7a7c97af57b63056df346f987b9c`.
Canonical transcript checkpoint `f072dd4a-d792-491b-bf05-486f00b588d7` exists.

C4's first chunk completed with 607 output tokens. The second chunk
`7d10ab10-a4b9-431e-be39-7a2c573fb2fd` returned `MAX_TOKENS`, using 1,393
output tokens against the approved 1,400-token limit. Its retained response
attempts observations for nearly every turn and ends mid-fact. The strict
validator rejected it; no partial facts checkpoint or C5 report was published.
The failed job is uncertain/dead-lettered with its receipt, raw bytes, and cost
hold preserved. Raw SHA-256:
`0f9cca86dd72e1704550dbe1977655c773f90fbbd6533822eb95f52c1965dcfa`.

Current recovery dispatched ceilings total INR 177, including uncertain and
successful requests; these are not invoices or proof of zero cost. Full provider
billing reconciliation remains separate. The new transcript and first fact
checkpoint must be reused where compatible; the failed task must not be reset.

Remaining acceptance: bounded C4 output repair and exact-version recovery,
all chunks and final report, independent transcript/report review, cited audio
playback and saved-call reload, temporary-policy restoration, then production
approval and deployment. Production remains on the prior f61 release.
The production approval is expired, so promotion preparation also requires a
compatible renewed rollback baseline; preserving images alone is insufficient.

A synthetic hour-long canary does not establish reliability for every accent,
language, noisy recording, overlap, bitrate, or sustained load. The public upload
limit is 32 MiB as well as 60 minutes.
