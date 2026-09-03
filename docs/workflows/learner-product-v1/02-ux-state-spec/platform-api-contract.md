# Learner product API and delivery contract

Status: **implementation proposal pending controlled-source promotion**

This contract supplies the seams needed by the selected product direction. It
does not activate a provider, create DNS, authorize paid commerce, or change
canonical progress/access semantics.

## Surface hosts

| Host intent | Initial responsibility | Provider seam |
| --- | --- | --- |
| `app.authorityclosers.com` | learner web/PWA | application hosting may change independently |
| `api.authorityclosers.com` | authenticated/public product APIs | stable product contract |
| `media.authorityclosers.com` | signed learner media delivery | VPS-backed now; CDN-backed later |
| `files.authorityclosers.com` | private user-file upload/download front door | VPS object store now; provider adapter later |

Staging uses the corresponding staging host convention. These are desired host
contracts, not a claim that DNS, TLS, routing, or runtime evidence exists.

## Learner bootstrap

`GET /v1/learner/bootstrap`

Purpose: remove the identity -> membership -> enrollment -> learning-path
client waterfall while retaining server-side authorization.

Response sections are independently optional and carry their own state:

- `identity`: person ID, display name, avatar presentation reference, account
  revision, verified status.
- `navigation_capabilities`: only routes/actions the current learner may see.
- `current_learning`: current program/module/activity projection and allowed
  actions, when present.
- `enrollments`: authorized summary projections.
- `progress_summary`: canonical counts only; unknown is not zero.
- `preferences`: presentation/accessibility preferences safe for bootstrap.

Rules:

- The server resolves tenant, identity, membership, entitlement, policy, and
  progression. The browser never reconstructs authorization from analytics.
- Support `ETag`/`If-None-Match` or an equivalent revision token for cheap
  revalidation. Authenticated responses remain private and must not enter a
  shared cache.
- The client may deduplicate identical in-flight requests and retain a previous
  successful shell projection during navigation. It must not persist sensitive
  responses in the service-worker cache.
- A failed optional section produces `PARTIAL` rather than blanking the shell.

## Profile and avatar

The canonical profile stores a private object reference and presentation
metadata, never an arbitrary public URL.

Proposed flow:

1. `POST /v1/me/avatar-upload-intents` with declared MIME, bytes, dimensions,
   and the current profile revision.
2. Server returns an expiring upload intent for `files.authorityclosers.com`.
3. Client uploads directly to the adapter front door.
4. `POST /v1/me/avatar-upload-intents/{intentId}/complete` requests validation
   and processing.
5. Server verifies ownership, MIME signature, byte/size/dimension limits,
   sanitization, orientation/metadata stripping, and configured security scan.
6. Successful processing creates a new avatar object version and supersedes the
   previous reference under retention/audit policy.
7. `GET /v1/me` and bootstrap expose presentation metadata or a short-lived
   private delivery URL.

Profile mutations require revision-aware `If-Match`. Delete means remove the
active presentation reference and supersede under policy; it is not an
unlogged destructive object overwrite.

## Media ports

```text
Activity service
  -> PlaybackPolicyResolver
  -> MediaDeliveryPort
       -> VpsMediaOriginAdapter (initial)
       -> CdnMediaDeliveryAdapter (later)
  -> Playback evidence service
  -> Canonical progress projection
```

Application code depends on `MediaDeliveryPort`, not VPS paths, Nginx paths,
bucket names, CDN vendors, or permanent public URLs.

Required port responsibilities:

- authorize a playback request against the activity and learner context;
- create a short-lived playback session;
- return an HLS manifest when processed media exists;
- return a range-capable progressive fallback only when policy allows;
- expose poster, caption tracks, transcript reference, duration, and rendition
  metadata only when approved and available;
- refresh or revoke delivery grants without changing the activity route;
- report safe typed errors: unavailable, processing, unsupported, expired,
  policy denied, range failure, and origin failure.

Proposed endpoint:

`POST /v1/learning/activities/{activityId}/playback-sessions`

Minimum response:

```json
{
  "playback_session_id": "opaque",
  "activity_revision": "opaque",
  "delivery": {
    "kind": "hls",
    "url": "https://media.authorityclosers.com/...signed...",
    "expires_at": "RFC3339"
  },
  "poster": {"url": "signed-or-public-approved", "width": 1600, "height": 900},
  "duration_seconds": 0,
  "captions": [],
  "transcript": null,
  "resume": {"position_seconds": 0, "revision": "opaque"},
  "allowed_actions": ["play", "seek"]
}
```

Zero/empty values above are schema examples, not runtime claims.

Playback resume is revision-aware and separate from completion. Viewing-time
analytics cannot mark an activity complete. Completion evidence remains under
the existing learning command/projection contract.

## VPS-first origin

The initial adapter may use the existing VPS for source storage, transcode
workers, and Nginx/static delivery, subject to governance and operational gates.
It must still provide:

- HLS master/media playlists and segmented renditions;
- byte-range support for permitted progressive fallback;
- correct MIME, CORS, cache, and content-disposition headers;
- short-lived signed delivery grants;
- private origin paths not exposed as application identifiers;
- health, latency, error-rate, disk-capacity, and egress telemetry;
- immutable media asset versions and supersession rather than in-place
  replacement;
- backup/restore and retention evidence.

Switching to a CDN changes only the delivery adapter and operational routing.
Activity IDs, playback-session API, evidence commands, player state machine,
and product routes remain stable.

## Versioned low-typing interactions

Catalog activities gain a versioned, server-authored `interaction_schema`.
Supported first families:

- `single_choice`: choose the strongest authored response;
- `ordered_steps`: place authored steps in order, with tap controls as an
  alternative to dragging;
- `pair_match`: match authored signal/action pairs, with select controls as an
  alternative to dragging;
- `branching_scenario`: choose through authored nodes and consequences;
- `evidence_chips`: select authored reasons/evidence;
- `confidence_check`: choose a range/chip with an optional note.

Submissions contain stable option/node IDs and the schema revision. Feedback is
authored and deterministic. The server may validate completeness and exact
authored rules; it does not infer ability, rank the learner, create mastery, or
perform autonomous AI scoring. Optional notes are secondary evidence, not the
primary interaction.

## Notifications and Discover

Routes may ship in an honest empty/informational state before mutations exist.
Durable unread/read state, delivery preferences, opt-in, commercial messaging,
and deep links require separate controlled contracts. `Coming soon` is status
copy, not entitlement or a purchase promise. No notification click or analytics
event grants access.

## Security and observability acceptance

- Host-only secure cookies; no bearer token in media URLs beyond an opaque,
  scoped, expiring delivery grant.
- Tenant/person/activity ownership checked before every profile, media, and
  learning mutation.
- Audit identity, object version, policy decision, and mutation result without
  logging secrets or signed URLs.
- Rate, byte, concurrency, and storage quotas for uploads and playback sessions.
- Structured traces across API -> policy -> adapter -> origin, with no analytics
  event treated as canonical business state.
- Contract tests prove that swapping a fake VPS adapter for a fake CDN adapter
  does not change API responses or learning semantics.
