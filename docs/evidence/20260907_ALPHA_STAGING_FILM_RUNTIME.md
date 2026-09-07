# Alpha staging public-film delivery composition

Date: 2026-09-07. Status: implemented and independently reviewed locally;
**not deployed playback or final Alpha acceptance**.

## Scope

`AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED` is a separate, default-off
switch. The older diagnostic cache flag alone does not mount delivery. The new
switch requires staging/isolated test, the configured learner tenant, the exact
staging learner HTTPS origin, the fixed package and no general media provider.
Production, development/local activation, runtime injection and S3/webhook
activation remain closed.

The application loads only the package-owned manifest
`d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222`,
verifies all local bytes/probes/HLS inventory and binds the capability to the
running baked release and configured tenant. Missing/changed media fails startup
instead of creating an empty playable surface. This explicit activation should
occur only after the immutable file mount has been installed and verified.

## Authorization and behavior

- Only the two deterministic public-film VIDEO activities in technical v2 can
  acquire this delivery port. Catalog version/digest/source, global ownership,
  module, kind, title and visible license/credit prompt must match the package.
- The learner binding must reference the matching deterministic film asset and
  version, not merely any approved media. Other courses keep inert media metadata.
- Every byte request retains the persisted identity session, tenant membership,
  entitlement/enrollment, pinned catalog, prerequisites and grant checks from
  the canonical authorization adapter. A copied URL is not independent access.
- URLs use a distinct derived signing key, a five-minute window, same-origin
  cookies, exact CORS and bounded single-range reads. The media grant signer
  remains separate. The inventory is read-only and contains only public test
  films, not real sales calls or instructional video.
- The default catalog-to-learning resolver was moved verbatim into a shared
  learning module; HTTP and delivery use the same catalog fact projection.
- No VideoEvidencePolicy was enabled. Viewing a film does not fabricate Watch
  evidence, progress, an achievement or a certificate. That capability retains
  its own controlled requirements.

## Verification

Root run: `uv run pytest tests/unit/media/test_staging_fixture_runtime.py
tests/unit/media/test_delivery_runtime.py tests/unit/media/test_file_storage.py -q`
passed **98/98 in 5.39 seconds**. Ruff passed all scoped changes; mypy passed the
two new implementation modules. Initial failures were two test expectation/setup
errors (production canonical origin and typed storage-unavailable exception),
corrected without changing production guards.

Independent review found no actionable Critical/Important findings and repeated
the same 98 checks successfully, alongside 49 import checks. Independently
validated the actual ignored pack: **30 artifacts / 54,274,209 bytes**, BBB
3840×2160 and Caminandes 1920×1080, each 12.032 seconds including bounded AAC
padding. The 12-second video samples and synthetic caption labeling are recorded
in the source/import evidence.

## Remaining release proof

Real PostgreSQL async transaction/advisory-lock concurrency and rollback,
reviewed immutable VPS mount/configuration, ordinary authorized learner
enrollment, actual same-origin proxy/cookie delivery, playback/seek/captions/
rendition switching, logout/expiry/revocation and browser recovery remain
required. These checks are not replaced by local SQLite, composition tests or
passing source hashes. General production instructional media is not activated
by this staging-only exception.
