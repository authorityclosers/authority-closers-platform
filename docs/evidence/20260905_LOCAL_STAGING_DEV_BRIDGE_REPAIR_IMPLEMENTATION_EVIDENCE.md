# Local Staging Development Bridge Repair Implementation Evidence

- Evidence date: 2026-09-05
- Worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`
- Branch: `codex/local-staging-dev-bridge`
- Repair scope: Local development staging bridge origin validation and health startup
- Affected packages: `@ac/learner-web`, `@ac/admin-web`
- Database/migration effect: None (no DB or VPS state changed)
- Production/deployment effect: None (local development bridge only)

## Root Cause Analysis

Running `pwsh -NoProfile -File scripts/Start-LocalStagingBridge.ps1 -NoBrowser` launched Next.js 16.2.11 for both `@ac/learner-web` (port 3000) and `@ac/admin-web` (port 3001). However, the initial probe to `http://learner.localhost:3000/v1/programs?limit=1` consistently failed with HTTP 403 Forbidden.

Investigation revealed:

1. **Remote Upstream**: `https://staging.authorityclosers.com` and `https://api-staging.authorityclosers.com` do not require Cloudflare Access. Direct curl to `https://staging.authorityclosers.com/v1/programs?limit=1` returned HTTP 200 OK. The 403 was not originating from Cloudflare Access or the remote staging gateway.
2. **Local Origin Validation**: In Next.js dev server mode (`next dev --webpack --hostname 127.0.0.1`), Next.js constructs the Web standard `Request` object for App Router route handlers with the local listen host (`http://localhost:3000` / `http://localhost:3001`), rather than the virtual host used by the client.
3. **Strict Origin Equality Check**: Both `isAllowedBridgeOrigin` in `apps/learner-web/app/lib/dev-api-proxy.ts` and `hasAllowedOrigin` in `apps/admin-web/app/lib/dev-api-proxy.ts` strictly evaluated `new URL(request.url).origin === expectedOrigin`. Because the launcher configures `http://learner.localhost:3000` and `http://admin.localhost:3001` for host-only cookie isolation, `http://localhost:3000 !== http://learner.localhost:3000`, causing the local proxy to reject legitimate requests with HTTP 403 (`{"title":"Development API proxy unavailable","detail":"The authenticated staging bridge accepts requests only from its exact configured localhost origin."}`).

## Repair Implementation

The origin validation in both applications was updated with strict defense-in-depth guardrails adhering to security review requirements:

1. **Loopback Enclosure**:
   Verifies that `request.url` hostname is an exact loopback host via `isLoopbackHost(new URL(request.url).hostname)` (`127.0.0.1`, `localhost`, `*.localhost`, `::1`). Non-loopback URLs are immediately rejected.
2. **Direct Host Header Requirement**:
   Requires the direct HTTP `Host` header to resolve to the exact configured localhost origin (`expectedOrigin` / `browserOrigin`). If `Host` is absent (such as in synthetic test environments), falls back strictly to `rawUrl.origin === expectedOrigin`.
3. **Forwarded Header Agreement (No Sole Trust)**:
   Does not solely trust `x-forwarded-host`. If `x-forwarded-host` or `x-forwarded-proto` is present, it must strictly agree with the expected origin and protocol as an additional check. Conflicting or spoofed forwarded headers are rejected with 403.
   Host authorities containing credentials, paths, queries, fragments, whitespace, comma-joined values, or empty forwarded values are also rejected.
4. **State-Changing Origin Enforcement**:
   Preserves strict `Origin` header validation: safe GET/HEAD requests may omit `Origin`, but unsafe methods (POST, PUT, DELETE) must provide an exact matching `Origin` header.
5. **No Secret Exposure & Contract Preservation**:
   No Cloudflare Access tokens or credentials are logged or persisted. The `X-AC-Dev-Data-Mode: staging-public-catalog` contract is preserved.

## Verification and Quality Gates

1. **Unit and Regression Tests**:
   - `@ac/learner-web`: 39 tests passing (`pnpm --filter @ac/learner-web test app/lib/dev-api-proxy.test.ts`), including regression tests for direct Host matching, agreeing forwarded headers, rejection of missing Host when forwarded headers are present, rejection of conflicting forwarded hosts/protocols, malformed authority values, exact IPv6/HTTPS authorities, and hostile non-loopback URLs.
   - `@ac/admin-web`: 57 tests passing (`pnpm --filter @ac/admin-web test app/lib/dev-api-proxy.test.ts`), covering identical security guardrails.
2. **Typecheck**:
   - Both packages cleanly passed `tsc --noEmit` with zero errors.
3. **Lint**:
   - ESLint cleanly passed with zero warnings across modified files in both packages.
4. **Infra Launcher Tests**:
   - `pytest tests/infra/test_local_staging_bridge.py`: 9 passed.
5. **Real Bridge Health Proof**:
   - `Start-LocalStagingBridge.ps1 -NoBrowser` executed and passed both health checks with exit code 0:
     - `http://learner.localhost:3000/v1/programs?limit=1` -> HTTP 200 OK (`X-AC-Dev-Data-Mode: staging-public-catalog`).
     - `http://admin.localhost:3001/v1/dev-bridge/health` -> HTTP 200 OK (`status: ok`, `transport: connected`).
6. **Initial Process Disposition**:
   - The original default-port bridge processes were stopped before the later collision revalidation. They are not claimed as current runtime state.

## Port Collision Follow-up

Revalidation after the main-branch reconciliation found that port `3000` was
owned by an unrelated local workspace. That process was not terminated. The
launcher now accepts validated, distinct `-LearnerPort` and `-AdminPort`
overrides while keeping both servers bound to `127.0.0.1` and preserving the
separate `learner.localhost` / `admin.localhost` cookie boundaries. The default
ports remain `3000` and `3001` for backward compatibility.

Fresh proof after that follow-up:

- `pytest tests/infra/test_local_staging_bridge.py -q`: `9 passed`.
- `Start-LocalStagingBridge.ps1 -NoBrowser -LearnerPort 3100 -AdminPort 3101`:
  completed successfully.
- `http://learner.localhost:3100/v1/programs?limit=1`: HTTP `200` with
  `X-AC-Dev-Data-Mode: staging-public-catalog`.
- `http://admin.localhost:3101/v1/dev-bridge/health`: `status=ok` and
  `transport=connected`.
- The unrelated process already using port `3000` was left untouched.
- A second launch on free ports `3200`/`3201` was refused while the tracked
  `3100`/`3101` bridge remained healthy; its PID record hash was unchanged.
- Start and stop now acquire the same workspace-scoped exclusive lifecycle
  lock before reading or changing `processes.json`, preventing a concurrent
  shutdown from racing startup or observing a partial process record.
- The `3100`/`3101` bridge is the sole tracked active bridge at evidence handoff.
