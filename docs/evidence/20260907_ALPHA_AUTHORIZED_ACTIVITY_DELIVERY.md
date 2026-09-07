# Alpha authorized activity delivery

Date: 2026-09-07. Base checkpoint: `28b0c06bb7dea5aa8c5d71435b6e015bd253587f`.

## Implemented boundary

The learner activity descriptor can now issue an approved binding's signed HLS
manifest, progressive fallback and caption URLs when both the delivery port and
the canonical `delivery_activity_resolver` are explicitly composed. The default
remains unavailable. A missing rendition remains blocked and writes no grant.

The existing `MediaPlaybackGrant` records the revocable delivery window. Its
request fingerprint pins tenant, person, browser session, activity, activity
version, asset, media version, enrollment and approved binding. Signed URLs also
carry the durable grant ID. The original opaque grant token is reconstructed
only to verify its stored digest; it is not returned by this descriptor.
Repeated descriptor reads reuse a currently valid scoped grant; expiration
appends a new grant. Existing grant history is not rewritten.

`DatabaseMediaDeliveryAuthorizer` is constructed per authenticated request. It
checks actual request actor/session equality, persisted active identity session
and person, selected tenant, grant digest/fingerprint/revocation/expiry, exact
signed issue/expiry times, current approved binding and ready media version.
It reuses `SqlAlchemyLearningRepository` and `ActivityService.current_state` for
current tenant/membership/enrollment/entitlement/published-or-superseded version
and authoritative prerequisite checks. Media does not create new access rules.

`install_media_delivery_http` has an explicit authenticated mode accepting
`RequireActor` and `authenticated_handler_factory(Session, ActorContext)`.
Anonymous GET/HEAD is rejected; copied URLs cannot cross browser session,
person or tenant. OPTIONS only returns the exact-origin CORS policy and never
opens media or creates a grant. The dependency uses FastAPI `scope="function"`,
verified against the installed API, so the SQL transaction is closed before a
lazy streaming body is consumed. The static handler installation is retained
only as the existing isolated contract-test seam; runtime composition is not
activated by this change.

HLS child URLs carry the same grant scope and original expiry. Existing strict
rendition namespace, recursive inventory validation, checksums, byte caps,
single-range handling, no-store headers and no external playlist URLs remain.
Delivery requires the real current authenticated browser session on each new
GET/HEAD; revocation does not retract bytes already delivered or interrupt an
already-authorized in-flight response.

## Controlled references

Consulted exact manifest IDs, not filename guesses:

- AC-DATA-01: `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`.
- AC-API-01: `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`.
- AC-QA-01: `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`.
- AC-GOV-AUD-001: `17Gs86tkRo4jr8XcqgMPyO-UojXeTANnY`.

These preserve canonical enrollment/version authority, short-lived scoped
playback, tenant/person isolation and expiry/revocation testing. Governance's
protected production video/provider gate is not activated by a staging-only
public-film demonstration. Neither film is represented as Dipak instruction.

## Verification

`uv run pytest -q tests/unit/media tests/unit/http/test_learning_routes.py`:
**272 passed**, one existing Starlette/httpx deprecation warning. Includes 37
focused activity-delivery cases, the existing media regression suites and the
concurrently added file-storage tests.

`uv run ruff check` on the five changed implementation files plus the focused
test file: passed. `uv run mypy` on the five changed implementation files:
passed. Scoped `git diff --check`: passed.

Focused tests exercise real SQLite media grants/catalog/access queries and
actual HTTP byte-range delivery using isolated in-memory media bytes. They
cover every signed scope field, grant digest/fingerprint, identity/grant expiry
boundaries, tenant/person/session/membership/enrollment/entitlement/binding and
media lifecycle denial, configured prerequisites, no composition/no rendition,
HLS child propagation and revocation, anonymous/copied GET/HEAD, OPTIONS and
transaction release before body consumption. No canonical learning playback
session is created by descriptor issuance.

## Remaining release gates

This is not evidence of VPS delivery, real browser playback, PostgreSQL
integration, production provider approval or canonical completion. Root owns
the authenticated runtime composition, same-origin `/v1/media` proxy and
cookie/range forwarding, release-bound staging import, read-only fixture mount,
deployed checks and player QA. Import must use a reviewed application command,
not manually written READY rows. The existing technical catalog has one VIDEO;
two simultaneous fixtures require a newly published, explicitly labeled
technical-validation version preserving existing versions and enrollments.

Independent security review found no Critical/Important issue. The reviewer
independently ran all 37 focused delivery and 59 file-storage cases: 96 passed.
Runtime composition remains a separate acceptance gate.
