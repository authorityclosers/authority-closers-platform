# ADR 0034: Admin release control through an engine inbox

Date: 2026-09-28. Status: proposed; owner approval is pending in AUT-21.

## Context

The release engine runs as root, while the Admin API runs as an unprivileged
container user. Admin must not gain a shell, Docker socket, engine state, or
release-store access in order to request a production release. The current
engine already refuses production deploys unless the production enablement file
exists and the commit passed staging. This ADR records the proposed request
channel and additional release controls; the Admin routes and inbox consumer
are not yet implemented.

## Decision

Admin sends intent through a narrow host-file inbox. The engine, under its
existing lock, validates each request and runs its own release logic. Admin
never supplies a command, path, option, token, or other executable input.

### Inbox and outbox

- The production API alone receives the host inbox
  `/var/lib/ac-release/admin/production/inbox` at `/run/ac-release/inbox`,
  mounted read/write. It is owned by `root:acrelreq` with mode `1730`; the API
  user (uid `10001`, through `group_add`) can create request files but cannot
  list the inbox. Once the engine moves a request into the root-only
  `processed/` directory, the API can no longer reach it.
- The host outbox is `/var/lib/ac-release/admin/outbox`. The engine writes
  `status.json` and `requests/<id>.json` atomically as root. Staging and
  production APIs mount the outbox read-only.
- `ac-release-inbox.path` triggers `ac-release inbox`; a two-minute engine tick
  is the backup trigger. The inbox consumer uses the engine lock.

Requests use a strict schema; unknown keys are refused. The planned fields
are `v`, `id`, `action` (`promote` or `rollback`), `bump`, `sha`, `web_sha`,
`expected_production_sha`, `expected_version`, `requested_by`,
`audit_event_id`, and `requested_at`.

The engine moves each inbox request into the root-only `processed/` directory
before handling it, so a request runs at most once. It reads the moved file
once: the opened file must be regular, not a symlink, no larger than 4 KB, and
owned by uid `10001`. The engine validates only the bytes read from that open
file and never re-reads the inbox path.

The planned API routes are:

- `GET /v1/platform/releases` for the snapshot.
- `POST /v1/platform/releases/requests` to submit a request.
- `GET /v1/platform/releases/requests/{id}` for its outcome.

Before writing a request, the production API checks the new owner-only
`platform_release_manage` capability, `require_safe_origin`, and the typed
resulting version, then appends an `audit_events` entry. It writes the request
and returns `202` with its request id. The APIs read results from the outbox;
the web app does not access engine state directly.

### Engine guards

The engine rechecks the release and request-file guards it can enforce; Admin
UI state is never authority. It refuses requests older than 15 minutes or when
another request is running. It also compares the expected production commit
and version before acting, preventing stale requests and double submissions.

Production actions require all of the following:

1. `/etc/ac-release/production.enabled` exists. It is created only after the
off-host backup restore check passes.
2. The core commit and paired web build are on `main` and passed staging.
3. The expected production commit and version still match, and the engine lock
allows only one action at a time.
4. Rollback targets only the immediately previous release and only when its
migration head matches the current one.
5. Foundation support for any new migration is installed first, and the Sales
Xray approval has at least one day remaining.
6. The production API checks `platform_release_manage`, `require_safe_origin`
and the typed resulting version, and appends the `audit_events` entry, before
it writes the request. The engine accepts requests only from the production
inbox, which no other API mounts, and each one must carry its `audit_event_id`.
Staging Admin is read-only for production actions.

### Recorded decisions from AUT-21

- **D1 — baseline version:** no `vX.Y.Z` tags exist yet. Count current
  production as `v0.2.0`; the first minor promote therefore produces `v0.3.0`.
- **D3 — request surface:** production actions come only from production
  Admin. Staging Admin is read-only. The CLI is the fallback when Admin is
  unavailable.
- **D4 — authorization:** add the owner-only `platform_release_manage`
  capability. Do not reuse `platform_access_manage`; per ADR 0031, one
  capability does not imply another.

The production API requires the owner to type the displayed resulting
version to confirm. The engine derives the next version from the highest
`vX.Y.Z` among tags and release records. Rollback remains limited to the
previous release; database rollback is out of scope.

### CLI fallback

The planned fallback commands are `sudo ac-release promote --bump minor` and
`sudo ac-release rollback production`. They become usable only after the
corresponding engine CLI work is implemented and released. On the current
engine, neither command is available; use only the commands listed in the
current [runbook](../runbooks/RELEASE_ENGINE.md).

## Alternatives

- Letting the API run release commands would give an unprivileged web process
  access to root operations and is rejected.
- Giving the API read access to the inbox, or mounting it in staging, would
  violate the write-only request boundary and staging read-only decision.
- Reusing `platform_access_manage` would couple unrelated authority and is
  rejected by ADR 0031.

## Consequences

The web tier has a bounded file-write capability and reads status only. The
engine remains the authority for validation and execution. The host paths,
container mounts, trigger unit, API routes, CLI commands, and outbox format
must land together across the AUT-21 implementation tasks before this design
is operational.

## Reversal cost

Changing the channel later requires coordinated changes to the API, container
mounts, engine consumer, installer, trigger unit, and operational monitoring.
Audit event IDs, request IDs, and compare-and-swap semantics must remain
compatible or be migrated explicitly.

## Evidence

- AUT-21 plan, revision `aaaf22ec-9c34-42fd-a036-cc5c78f5b32a`, sections 5,
  6, and 8 (inbox/outbox, guards, D1/D3/D4).
- Current behavior: [Release engine runbook](../runbooks/RELEASE_ENGINE.md)
  and `infra/release/ac_release.py` (`production.enabled`, staging check).
- Capability separation: [ADR 0031](0031-explicit-platform-and-studio-capabilities.md).

## Owner

Owner approval is pending in AUT-21. Platform implementation follows its
R1–R9 task sequence.

## Supersedes

None. This is additive to the existing staging release engine runbook.

## Trigger to revisit

Revisit if owner approval changes D1, D3, or D4; if the API/engine boundary
cannot enforce the stated file permissions and guards; or if the implementation
changes the request or outbox contract.
