# Community discovery and learner connections evidence — 2026-09-13

## Authority and base

This slice is based on release candidate `41d3c5726a1b5d217259c034bf058d9107135b1f` (`codex/release-followon-20260913`) and follows the controlled community identity contract in `docs/evidence/20260910_ACADEMY_COMMUNITY_IDENTITY_CANDIDATE.md`, the onboarding profile boundary, and the community release sequence in `docs/workflows/v0.1-alpha-experience/00-start-here/alpha-to-arcade-release-sequence-2026-09-07.md`.

## Contract implemented

- A learner is private and unsearchable by default. A row in `community_discovery_preferences` is created only by the authenticated learner's explicit change.
- Discovery is scoped to the authenticated learner's selected academy and requires an existing immutable username, active learner membership, active verified account, and explicit discovery opt-in.
- Search and profile projection accept a username or username prefix only. Responses contain the username, the learner's explicitly chosen display name, an explicitly selected avatar asset reference, and practice XP only when the learner already opted into the existing academy leaderboard metric.
- Responses contain no email, first name, inferred real name, course progress, enrollment, org roster, role, or automatic membership details. Existing users are never backfilled into discovery.
- Connection requests are mutual: the recipient alone can accept or decline an incoming request; either participant can remove an accepted connection. An append-only connection event row preserves request/response/removal/block actions.
- A learner can block a discoverable peer (removing any current connection) or report one of four bounded reasons. Reports are append-only; moderation workflow and group membership remain deferred.
- All reads and writes use the existing authenticated actor and selected learner academy admission. State-changing routes require the existing safe-origin and transaction boundary. Route limits are bounded by the existing in-process rate limiter.

## Routes

`GET/PUT /v1/community/discovery`, `GET /v1/community/search`, `GET /v1/community/public/{username}`, `POST /v1/community/connections/{username}`, `POST /accept|decline`, `DELETE /v1/community/connections/{username}`, `POST /v1/community/blocks/{username}`, and `POST /v1/community/reports/{username}`.

## Deferred gaps

The current media delivery contract mints avatar URLs only for the authenticated owner's private profile. This slice stores and returns the learner-selected avatar asset reference but does not create a new cross-learner media delivery path. Groups, rosters, messaging, automated suggestions, and moderation administration remain outside this migration and must follow the controlled release sequence before activation.

## Validation evidence

- `uv run pytest tests/unit/community/test_discovery_connections.py -q` — 4 passed.
- `uv run ruff check` passed for all changed Python community, HTTP, limiter, migration, and focused test files.
- `python -m compileall -q packages/python/ac_platform/community` passed.
- Frontend component/API tests were added under `apps/learner-web/app/components/community-discovery.test.tsx`; this isolated worktree has no installed Node workspace dependencies, so Vitest/typecheck require the normal workspace install/CI environment.
