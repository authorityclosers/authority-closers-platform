# Sales Xray live staging verification

Date: 2026-09-22. This is a checkpoint, not a production acceptance certificate.

## Exact deployed candidate

Staging API, native worker, and Sales Xray web run commit
`9986cf2ee9ab421aa16c16ae3ccccedf1f1adf1f`. The canonical application installer
completed successfully, including its database, backup, migration, release hold,
and health checks. Public staging API readiness and Sales Xray web health returned
HTTP 200 with this release ID. Production API readiness remained HTTP 200 on its
previous release; this checkpoint did not deploy production.

Exact application workflow `35748002411`, native workflow `35748006730`, and web
workflow `35748010705` succeeded. PR application workflow `35747976990` also
succeeded after rerunning an unchanged job whose PowerShell TCP listener fixture
timed out. The required compiled browser artifact records 15 assertions, no API
interception, and synthetic provider/challenge/native adapters. It does not prove
live provider acceptance.

## Retained call recovery

The source-owned retained C5 CLI appended recovered version 1 with state
`revalidated`, using the exact historical request and response binding. It made
zero provider calls. Original task/job and provider receipts remain historical
records; no operational SQL edits were used. The result remains an advisory draft,
with `human_approved=false` and `official_score=false`.

The guest report endpoint returned HTTP 200 with that recovered report. Browser
display failed because the frontend's strict envelope parser did not recognize
the supported `recovery` field. After excluding that field only in an offline
diagnostic, the strict overview parser rejected the supported `business_impact`
field. Excluding both fields in that diagnostic admitted all remaining bindings,
evidence, and overview fields. No deployed response was modified.

With the frontend correction in this follow-up, the exact private projection
passes the normal parser with neither diagnostic exclusion. The proof prints
only pass/fail, guest status, overview presence, and zero provider/database writes.
Raw call content and the private test input remain outside Git.

## Fresh synthetic guest canary

The owner approved accepting Terms and running this staging test within the
existing approved test budget. Through Chrome, the guest uploaded the locally
generated fictional `discovery-next-step.wav` (72.898 seconds; SHA-256
`df617e9387e1fc83b5cd52f3254765bd944fc11a7bfc7a62d174a5716d29fe46`).

Submission: `a2a5766b-49e9-4eca-a29f-1a4b84e1873e`.
Recording: `b5c109dc-ce4e-46db-8fb2-7a80aea3effe`.
Run: `745f4c87-e8f4-4904-b232-fadfdbf33ac2`.

At 16:20 UTC, browser-observed API responses showed HTTP 200 for progress,
transcript, and report. Progress reported `state=report_ready`,
`local_state=completed`, `has_report=true`, `failure_code=null`, and completed
C2, C4, and C5 stages. This exercised the activated real-provider pipeline.
The canonical report has a detailed overview and a non-null `business_impact`;
it has no recovery metadata. The deployed frontend still rejects that overview,
so this is pipeline success, not yet a successful end-to-end browser journey.

The existing AC account then signed in through the normal Google OAuth flow.
The browser's explicit `Save to my account` action completed. The Saved calls
page listed the 1:13 synthetic call as `Report ready`, alongside the earlier
3:46 recovered call. Opening the claimed report is still blocked by the same
frontend contract mismatch at this checkpoint.

## Remaining acceptance

Deploy the corrected frontend from a tested exact candidate, then display and
reload both saved reports without requesting a fresh paid plan. Verify playback,
account sign-in/claim and saved-call access, a fresh authenticated upload, and
appropriate denied-access behavior. Promote the accepted immutable candidate
only after staging checks and current activation prerequisites pass. Human
coaching quality review and a measured soak remain separate evidence.
