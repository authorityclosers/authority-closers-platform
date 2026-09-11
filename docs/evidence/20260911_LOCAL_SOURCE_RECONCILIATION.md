# Local source reconciliation evidence — 2026-09-11

Worktree: `C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform`

Branch: `codex/v02-alpha-latest-ui-20260911`

Source reconciliation was applied from `HEAD` `cb8df7b44fc79144a6697a77966f4a4c6088932f` to the reviewed corrected tree `688989d483484fbb6113909a9d84a71571c6f6b3`. The seven initial requested working-tree files hashed byte-for-byte to the reviewed tree:

- `apps/learner-web/app/lib/dev-api-proxy.transport.test.ts` — `8537e05e311f3066b2460416405bcbcc16734a43`
- `apps/learner-web/app/lib/dev-api-proxy.ts` — `effbf4d59ba78ec44a9e1f6452688755094df735`
- `apps/learner-web/app/lib/dev-local-api-upstream.test.ts` — `4f27b8d5314f02df47b5580acfbe19ff3c050523`
- `apps/learner-web/app/lib/dev-local-api-upstream.ts` — `161818b4d9d1a9507dd069ae67b0bfb70d460e03`
- `infra/application/scripts/install-application-release.sh` — `58ecd0611fda1f08f5f5b37f814cdd254c36f61c`
- `tests/infra/test-release-install.sh` — `aba4a2c43d67e936311eb6d6c88ca1a5f27af3ac`
- `tests/infra/test_local_staging_bridge.py` — `71abd765be237607cb8fcf4bacbb09684d021ab4`

An independent reviewer then approved a scoped hardening follow-up in `apps/learner-web/app/lib/dev-api-proxy.test.ts` and the already-owned local-upstream helper/test paths: preserve the intentional native non-sandbox route, enforce the existing native-network diagnostics privacy guard, force `Accept-Encoding: identity`, and fail closed if an upstream returns a non-identity content encoding.

## Validation

- Managed Node `v24.19.0`, direct installed Vitest `v4.1.11`: proxy/helper/transport suites passed, 3 files / 67 tests.
- Direct installed ESLint passed for the changed learner proxy/helper files and tests.
- Direct installed learner TypeScript `tsc --noEmit` passed.
- `.venv` Python `pytest -q tests/infra/test_local_staging_bridge.py`: 10 passed.
- `tests/infra/test-release-install.sh`: reaches the fixture permission assertion, then fails under Windows Git Bash because `chmod 2750` reports mode `755`; no source assertion failure was observed.
- The legacy local-transport assertion was updated in the approved follow-up to document the intentional native route; the focused proxy/helper/transport run is now fully green.

## Local UI restart probe

The managed PowerShell 7 launcher was invoked sequentially for learner, admin, and coach. API `:8000` and PostgreSQL `:55432` were already live and were reused; no production/staging service was touched.

- Learner `:3100`: launcher succeeded; independent probe `/login` `200`, `/v1/me` `401`, `cache-control: no-store, private`, no `Set-Cookie`.
- Admin `:3101`: launcher readiness timed out while Next.js 16.3.3 compiled `proxy`; no listener remained. Its managed log records an `UNKNOWN` open error while resolving the hardlinked `zod@4.5.4` module.
- Coach `:3102`: same managed readiness failure; no listener remained. Its log records the same `zod@4.5.4` module open error.

The failed admin/coach launches stopped only their newly started UI processes. This is local readiness evidence only; it is not a production-live claim.

The Next-generated `root-params.d.ts` imports in all three `next-env.d.ts` files were restored to their exact `HEAD` text after UI checks and are excluded from release scope.
