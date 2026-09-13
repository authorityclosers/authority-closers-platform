# Sales Xray private submission HTTP adapter

This adapter consumes the root-owned guest processing contract. Its base is
`529c389cbb289fdaefbb5a4da04fb6b2480f7823`: the reviewed guest ownership, Gemini,
overview projection and report-claim fixes. It does not provision identities,
invent provider permission, configure DNS or activate a runtime.

## Explicit composition

`create_app` composes `install_acquisition_http` and `install_submission_http`
with the same exact Sales Xray host, public Academy tenant, session factory,
canonical account resolver and approved conversation intake runtime. Activation
requires these release-owned settings:

- `AC_SALES_XRAY_ACQUISITION_ENABLED=true`
- `AC_SALES_XRAY_ACQUISITION_POLICY_REVISION`
- `AC_SALES_XRAY_CHALLENGE_SECRET_FILE`: one narrow external file, never an env bundle
- `AC_SALES_XRAY_CHALLENGE_SITE_KEY`: public widget key
- `AC_SALES_XRAY_NATIVE_SOCKET_PATH`: private helper socket
- `AC_SALES_XRAY_NATIVE_IMAGE_REF`: pinned image digest

Missing or invalid acquisition configuration leaves the core API available and
the public entry reports `enabled=false`. No credential value is logged. Hosted
environments require the bounded socket helper and an existing private socket;
the API receives no Docker control or inference credentials. The helper shares
the reviewed private scratch mount. Release owns provisioning and the frontend
consumer; existing signed-in LMS/standalone clients remain separate.

The request limiter permits the larger body only for an exact submission UUID
PUT when acquisition is configured. Neighboring JSON routes retain their normal
one-MiB limit; streaming still enforces declared and actual bytes.

## User actions and routes

All paths start with `/v1/conversation/acquisition`. Requests use the guest
HttpOnly cookie or the actual claiming account session. A submission UUID is a
resource selector, never access authority. Tenant/account/provider selectors in
query strings are rejected. Mutations require the exact allowed origin; responses
are private/no-store and vary by Cookie.

| Route | Action |
| --- | --- |
| GET `/entry` | Discover availability and the public challenge action/site key; no secret or private submission data. |
| GET `/upload-policy` | Show the current private-upload terms, 128 MiB / 30-minute per-call limit, local ₹0 cost and retention. |
| PUT `/submissions/{uuid}/source` | Accept the selected original bytes with `X-Source-SHA256`, `X-Upload-Policy` and explicit `X-Upload-Consent: accepted`. |
| GET `/submissions/{uuid}` | Read stored processing status and report availability. |
| POST `/submissions/{uuid}/plan/quote` | Obtain the exact server-approved provider plan; no caller-selected provider/model. |
| POST `/submissions/{uuid}/plan` | Accept that plan's fingerprint, privacy revision and cost limit. |
| GET `/submissions/{uuid}/report` | Read the source-bound, fourteen-point guest/account report projection. |
| GET `/submissions/{uuid}/transcript` | Read the literal normalized transcript after a validated report is available. |
| GET `/submissions/{uuid}/source` | Replay the owned original recording with single byte-range support. |
| DELETE `/submissions/{uuid}` | Queue canonical erasure, including after execution/permission expiry. |

## Original audio and minutes

1. The user accepts the displayed local-upload policy for their selected file.
   This permits private upload/local measurement, not an external provider call.
2. The API admits the current owner before accepting bounded bytes. It holds no
   database transaction while uploading or waiting for isolated native decoding.
3. The private helper verifies the complete source, retaining its original hash.
   Admission checks its canonical receipt, complete feature artifact and actual
   decoded sample count. Browser duration and container nominal duration do not
   reserve minutes. Unsupported or inconsistent input leaves no acquisition usage.
4. One transaction reserves measured acquisition seconds, resolves the scoped
   processing actor, accepts local intake against the explicit upload policy,
   stores the verified original and queues the canonical local job. Stable
   submission/command keys prevent a retry from creating a second minute charge.
5. The canonical worker publishes C0/C1 under its lease. It checks measured
   duration against the reservation and charges zero additional user seconds.
6. The separate provider plan still requires current exact-source authority and
   explicit owner acceptance. Its worker publishes the report and atomically
   settles the original acquisition reservation using the C6 receipt, even when
   the browser has closed. Uncertain external execution is not refunded by a GET.

The first adapter reuses full native inspection for admission and repeats local
C1 under the durable worker. It does not repeat transcription. Removing that
duplicate local computation needs a separately validated preflight-to-worker
artifact handoff; it is not assumed here. The native helper's bounded runtime can
exceed an ordinary proxy response timeout. Hosted activation must verify the
effective upload/preflight timeout and capacity, or provide a durable admission
queue; these local tests do not establish VPS capacity.

## Retained evidence and access

Report and playback queries resolve immutable submission ownership, then select
the exact recording, person and source hash. They do not list the shared
processing principal's recordings. The root-owned per-visitor read fence spans
the streaming transaction; an unrelated visitor can still upload. Claim/revoke
and deletion fence the same owner, while recording locks coordinate erasure.

Reading does not admit or renew an execution lease. Expired processing/approval
does not erase retained reports; expired retention, revoked recording consent and
deletion still deny access. Claiming requires the real current account. The old
guest cookie alone cannot reopen a claimed report.

The returned report uses the explicit v2 projection and preserves the detailed
overview, literal source association and human-unreviewed status. Provider raw
responses and internal receipts are not included. Numeric publication remains
withheld; no approval of the 95/100 weighting discrepancy is inferred.
