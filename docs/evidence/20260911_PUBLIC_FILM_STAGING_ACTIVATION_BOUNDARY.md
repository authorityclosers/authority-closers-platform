# Staging public-film activation boundary — 2026-09-11

Status: candidate policy-on release only. This record supersedes the earlier
policy-disabled status for the next reviewed staging slice; it does not claim
that PR48 or this stacked change has merged, that a release has been deployed,
that a pack has been installed, or that catalog/media state has been imported.

## Candidate scope

The candidate is stacked on PR48’s repaired head (`e27ad7f`), which must merge before this PR
can be retargeted to `main` or considered for merge. The only capability change
is `infra/application/capabilities/public-films.json`:

```json
"enabled": {
  "staging": true,
  "production": false
}
```

The fixed manifest digest remains
`dc8f635df33432aee83c461535823881286ded1577a8f8a72dc5b10f0ad86b42`; the
staging origin remains exactly
`https://learner-staging.authorityclosers.com`; the production origin and
production-disabled value are unchanged. The legacy
`staging-public-films.json` policy remains disabled. The legacy overlay is not
selected alongside `compose.public-films.yaml`; the new overlay is API-only,
read-only, and keeps provider, stress-fixture, and legacy media flags false for
all other services.

The package is a technical playback demonstration, not course instruction or
full films: exactly 30 files / 54,274,209 bytes, two 12.032-second excerpts,
with registry digest
`fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290` and source
inventory digest
`d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222`.
The canonical provenance table and archive/extracted hashes remain in
`MEDIA_STRESS_FIXTURES_IMPLEMENTATION_EVIDENCE.md`; no media bytes are added
to this PR and no source URL is fetched.

## Gates before merge or deployment

- PR48 must be merged; then this stack must be rebased or retargeted to the
  resulting `origin/main` commit and revalidated as one immutable release.
- The exact release archive must pass commit-marker, archive SHA, image-digest,
  file-inventory, and migration-head verification. The candidate and rollback
  releases must pass public-film preflight before writers stop.
- An owner-approved, already-verified licensed pack must be supplied without
  downloading media in the activation step. `public-films.py install` must
  verify every path, length, hash, regular-file/link invariant, root ownership,
  `0444` files, `0555` directories, atomic placement, and fixed manifest-root
  destination on Linux.
- A fresh verified PostgreSQL backup, writer fencing, release migration, and
  restore/rollback evidence are required. Pre-exposure failure may restore the
  verified backup and prior release; post-exposure failure requires maintenance,
  fencing, and forward reconciliation rather than database downgrade.
- Catalog publication, media import, and approved activity bindings must use the
  canonical audited importer with a real staging session and tenant-scoped
  `catalog_write`/`catalog_publish`; no direct SQL or guessed catalog version.
- Actual authenticated staging proof must cover exact descriptor/binding
  identity, HLS master/variants/subtitles and all pinned bytes, progressive
  GET/HEAD and forward ranges, private no-store/CORS, expiry, session/tenant/
  grant/membership revocation, logout invalidation, and the absence of Watch or
  learning-progress side effects. Current isolated ASGI tests are not deployed
  staging evidence and currently use the production learner-origin constant.

Production remains an explicit no-go: do not enable the production policy, use
`--allow-production`, import into production, deploy to production, or treat
this candidate file as runtime authorization until all separate governance and
release gates pass.

## Candidate validation

This branch has only the source policy flip, one focused policy/legacy-overlay
test, and this additive boundary record beyond PR48. Local validation must be
repeated after PR48 merge and before any deployment decision.
