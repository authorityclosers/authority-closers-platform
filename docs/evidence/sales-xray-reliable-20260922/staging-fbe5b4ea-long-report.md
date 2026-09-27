# Hour-long waveform and revised coaching acceptance

Staging checkpoint: `fbe5b4eaa909f060f91671b7169068d52b76591c`.
Production remains `f61f15f7fed81ef59cd57f4dd955eb7b2e624427` with an expired
processing approval. This is staging evidence, not production acceptance.

## Release and controls

All five exact-source CI/build runs passed: application `35797325394`, native
`35797328742`, web `35797331958`, PR application `35797318175`, and control
`35797318161`. The compiled synthetic browser gate passed 15 assertions and
explicitly does not claim provider acceptance.

The canonical staging deployment committed on September 22 at 23:51:50 UTC.
Exact API/worker, web and native images were verified, healthy where a health
check exists, with zero container restarts. The source-owned native installer
verified installed units and its runtime. The restored staging approval
`468d14b28572f3fd3e0d5c2b815a5511622d9360e89db29dc51d63088c2e0afa`
remains unchanged: the temporary C2 retry limit is back to one, and the total
owner testing ceiling remains INR1,000.

## Actual long-call result

The same fictional 59:57.994 stereo MP3 used at the preceding checkpoint was
reopened. Its waveform now returns HTTP 200 with 1,200 display points, from
0 to 3,597,000 ms, for the measured duration of 3,597,994 ms. The report and
transcript return HTTP 200 and audio returns HTTP 206. Citation playback and
the last spoken segment work; playback advanced from 3,589.14 to 3,597.491875
seconds with no media error.

A new normal acquisition plan was quoted and explicitly accepted for the same
fictional source and unchanged provider/privacy/retention controls. Its whole
plan ceiling was INR418, within the remaining owner testing ceiling. Acceptance
immediately reached C5. The new plan completed, and independent SELECT-only
comparison proved exactly one new provider task: `coaching-v2`. Every earlier
task, provider receipt and checkpoint remained unchanged. The completed C2 and
all five successful `facts-v2` chunks were reused.

The new C5 input SHA-256 matches the offline projection exactly:
`f9861caaecf0edb8ae35d849d6bb7dfc8df2d944a4a4466437b457bcbfbb046f`.
Canonical report validation passed for report SHA-256
`da9d3521faacd474f0a39a6bf69e0883d3acb8e3e90d642e34bf30048584cdbd`.
Saved-library reopening, full reload after completion, all 161 transcript
segments and the earlier short-call report reload passed in the deployed browser.

The new task ceiling was INR22, bringing this recovery's dispatched ceilings to
INR331. The shared historical budget contains INR557 in unreconciled holds,
including work outside this recovery. Neither number is an actual provider
invoice. The provider receipt requires reconciliation and has no actual-cost
value; zero settled cost must not be described as free usage.

## Independent semantic review

All 55 evidence objects match normalized transcript text and start/end times
exactly, covering 27 unique segments in the first, middle and final thirds.
The report preserves no purchase, unaccepted pricing, and no booked follow-up,
implementation, payment or order. The earlier unsupported claim of declining
a pilot is absent. The generated outcome omits an explicit pilot-status sentence
without falsely claiming a pilot occurred or was rejected.

One causal hypothesis uses stronger wording than the fixture establishes, but
the schema and UI explicitly label it as a possible effect and inference.
Independent review classified it as non-blocking. Proper-name variants and
imperfect speaker separation remain transcription limitations. This fixture
does not establish accuracy for every language, format, recording quality or
concurrent load. Public uploads remain bounded to 60 minutes and 32 MiB.

## Follow-up found during acceptance

An immediate reload during active C5 timed out at the authenticated acquisition
session read. The displayed retry succeeded after completion, and later full
reloads passed. Investigation confirmed that this task uses the separate
non-login processing principal, so the provider transaction does not hold the
human account's identity lock.

Source review instead found that authenticated audio streaming retains the
`current_owner` request-scoped transaction. Identity resolution locks the human
Person and Session rows until the response completes or cancellation unwinds.
A paused or slow audio response can block another session read. This needs a
bounded stream/identity fix and a concurrent-stream PostgreSQL/HTTP regression
before final promotion acceptance. Do not treat a successful completed-report
reload as proof that this processing-time path is fixed.

## Private receipts

Raw fictional payloads stay outside Git. Immutable acceptance receipts include:

- Browser acceptance SHA-256:
  `25c267bef5dfc0592c55b0826ea29eee8f683d65b3ae9072a52e764d91ca10cd`.
- Source-owned report export SHA-256:
  `78a9f32b9410a4742137099e4d49edee779e43bdcd6154ba63070f4173fbb289`.
- Exact task/receipt/checkpoint comparison export SHA-256:
  `b66309355aaed0c43e9241ce8be580a62c7a54b3397c2f873e834b7b148b2be8`.
- Cost/reuse read SHA-256:
  `4d6955b3996d5c13772a33e6c84d1ec4f415a2b70c3c96e0fb5b34e7f5bbe34e`.
- Independent semantic review SHA-256:
  `8788251054db27c4d1cdede3fe8c3549f1eb21edbaf8f4af5c1d6131608a0452`.

Production-derived approval drafts, provider configuration and actual native
fallback units were prepared and validated without issuance or activation.
The audio-stream follow-up will require a newly pinned candidate before an
exact production approval is requested. The f61 fallback remains valid only
before candidate write exposure; versioned candidate plans require forward
recovery after exposure.
