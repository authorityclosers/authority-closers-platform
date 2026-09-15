# Social boundary and localized practice content

Date: 2026-09-13 (Asia/Kolkata). Source and test evidence only; no environment
activation, database migration or external write was performed.

Historical note: this records the initial boundary decision made before the
bounded community contract was authored. The implemented follow-on is recorded
in `20260913_COMMUNITY_DISCOVERY_CONNECTIONS.md`; its migration is now reserved
as `20260913_0033` after the Sales Xray `20260913_0032` parent.

## Source authority and base

This worktree is based exactly on release-candidate commit
`41d3c5726a1b5d217259c034bf058d9107135b1f` (`41d3c57`), as requested. The
controlled local source register is `docs/traceability/CONTROLLED_SOURCE_REGISTER.md`.

The practice content follows the controlled v0.2 intake at
`docs/workflows/v0.1-alpha-experience/00-start-here/v0.2-alpha-coach-practice-update-intake-2026-09-10.md`:

- English, Hinglish and Marathi-English are named language outcomes.
- The exact regional label is **Marathi-English (Marlish)**.
- Content is natural spoken language awaiting editorial review, with separate
  global and Indian/Maharashtrian scenario registers.
- Practice remains formative and must not change course progress, rewards,
  rankings, certificates or formal assessment semantics.

The existing practice engine in
`packages/python/ac_platform/practice/arcade.py` keeps the inventory in an
editorial preview boundary and removes answers and feedback from public
projections. The new content remains under that same boundary.

## Implemented practice content

`packages/python/ac_platform/practice/exercise-library.draft.json` now includes
three catalog-selectable sets, each with three India-based discovery prompts:

| Set | Display label | Prompts |
|---|---|---:|
| `india-daily-english` | India daily practice · English | 3 |
| `india-daily-hinglish` | India daily practice · Hinglish | 3 |
| `india-daily-marlish` | India daily practice · Marathi-English (Marlish) | 3 |

The scenarios use varied Pune, Mumbai and Nagpur decision contexts. Existing
stable option shuffling provides deterministic variation per prompt. All nine
prompts are marked `editorial_draft`; all three sets retain
`needs_Dipak_review`, `competition_eligible: false` and
`assessment_eligible: false`. No new reward or scoring path was added.

## Initial social capability decision

No safe friend/student search, profile viewer or friend-connection backend
contract exists in the current candidate. The current community API exposes
only self identity, username claim, academy opt-in and academy leaderboard.
The controlled release sequence (`docs/workflows/v0.1-alpha-experience/00-start-here/alpha-to-arcade-release-sequence-2026-09-07.md`, row 6)
requires invitation, privacy, report, block, moderation and roster rules before
a cooperative social pilot. The v0.2 intake authorizes permitted username
profiles and academy-scoped diagnostics, but does not define search, profile
visibility, invitations or connection state.

Accordingly this slice intentionally adds no social tables, routes, migrations,
frontend fake state or group surface. The following remain deferred until those
controlled contracts are promoted:

- opt-in academy-scoped student search using usernames only;
- a profile viewer with an explicit permitted-field and visibility contract;
- reversible friend invitations/connections with block, report, moderation and
  roster enforcement;
- groups or cooperative squads and any related ranking semantics.

This preserves tenant boundaries, avoids email exposure and avoids inferring
private-profile or protected-visibility semantics from the username or
leaderboard implementation.

## Verification

- `uv run pytest tests/unit/test_practice_arcade.py -q` — **56 passed**.
- `uv run pytest tests/unit/test_practice_arcade.py tests/unit/test_practice_engine.py tests/unit/test_practice_focus.py tests/unit/test_practice_pilot.py -q` — **161 passed**.
- `uv run pytest tests/database/test_practice_engine_postgresql.py -q` — **20 skipped** because no disposable PostgreSQL URL is configured; no database operations ran.
- `uv run ruff check packages/python/ac_platform/practice/arcade.py tests/unit/test_practice_arcade.py` — passed.
- `git diff --check` — passed.

No browser, staging, production, provider, account, tenant or database state
was changed by this work.
