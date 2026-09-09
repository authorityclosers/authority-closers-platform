# Public-film runtime and PostgreSQL verification — 2026-09-08

Local working-tree evidence on `codex/local-staging-dev-bridge`, not a deployment.
The two licensed **12.032-second technical excerpts** remain separate from
Dipak's instructional courses. They are not full films or a general upload provider.

## Implemented

- Separate immutable package, tenant-owned optional VIDEO catalog, normal-session
  authorized/audited import, and production-capable delivery composition.
- Exact tenant/catalog/media binding, five-minute same-origin URLs, current
  identity/session/membership/enrollment/grant checks, and private/no-store bytes.
- Provider/upload activation and Watch completion remain off. Importing content
  never enrolls learners. The staging and production release policies remain off.
- API-only read-only digest mount and candidate/rollback package preflight are
  wired into the existing installer. Old staging authority is not broadened.

## Executed proof

Root ran both `test_public_film_import_postgresql.py` and
`test_public_film_delivery_postgresql.py`: **8 passed, 0 skipped, 27.58 seconds**.
An explicitly configured loopback PostgreSQL instance was used. The existing
harness migrated fresh random schemas and removed those schemas afterward;
the operational localhost schema and runtime configuration were not modified.

- Real opaque sessions: owner and explicitly granted learner publication;
  concurrent same-command locking/replay; immutable audit preservation;
  rollback after a final audit failure even when the caller catches it; revoked
  sessions denied before import/replay.
- Actual pinned 54,274,209-byte package, without manifest substitution: imported
  3840×2160 and 1920×1080 clips; delivered all five video rendition playlists,
  both subtitle playlists, and every referenced segment through the production
  composition's database-bound handler. Exact object sets and binary hashes match.
- Full progressive MP4 hashes, exact initial/tail forward ranges, HEAD, captions,
  expiry, cross-session/tenant denial, and revoked grant/entitlement/membership
  denial. Positive requests bracket every rolled-back revocation test.
- No canonical activity progress or Watch sessions were created; audit chains verify.

Earlier test assumptions about randomized URL equality, membership status and
suffix ranges were corrected before the accepted run. Existing suffix/multipart
range rejection is retained and tested; no new range capability is claimed.
Independent review findings on these assertions were fixed and re-reviewed.
Scoped Ruff passed. Separate package/import/runtime unit and release-wiring
results are recorded in their companion evidence files.

Root subsequently ran `test_public_film_http_postgresql.py`: **2 passed, 0 skipped,
19.66 seconds** on the same explicitly allowed local PostgreSQL service, again
using only fresh randomly named migrated schemas. The real ASGI application,
normal opaque session cookies and `/v1/context` selection issued both clips'
descriptors. Complete unique HLS playlist/fragment graphs and actual progressive
MP4/VTT GET, HEAD, ranges, hashes and MIME were verified. Anonymous, other-session,
other-tenant and foreign-origin access were denied. Normal second-session
descriptor delivery provided a positive control. Absent Watch routes/evidence
remain refused; learning rows stay empty and the audit chain verifies.
No authentication dependency overrides or substituted media runtime were used.
Independent review corrected the canonical `save_draft` expectation, mandatory
database-fixture ordering and exact graph assertions before the accepted run.

This proves actual bytes plus canonical services and HTTP on PostgreSQL, **not**
browser playback on the new deployment. Linux installation/permissions, effective Docker
Compose, exact-image execution, staging/production import, long-film performance,
and VPS/browser acceptance remain open. No deployment, DNS change, Git commit,
Drive upload, or production activation occurred in this slice.

Release readiness follow-up: local Ubuntu cannot start because its `ext4.vhdx`
is missing. `ssh ac` reached Cloudflare Access sign-in, then timed out; no current
VPS state was obtained and no Access bypass attempted. PR43 still points to
`2c56de938753a669265c4dda0d08ad9f3cb2ed0b`; its green checks do not cover these
uncommitted files. The latest verified packaged artifact remains the previous
`a5eef0df4b340070ac6e58f9912d73a3bf1d2f18` release, not this candidate.
