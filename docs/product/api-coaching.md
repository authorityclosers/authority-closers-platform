# Coaching by API, MCP and CLI

Gap 11 of `docs/product/api-mcp-cli-gaps-20261115.md`, built on 15 Nov 2026 at the
orchestrator's request.

Apps can read the Coaching the app shows. It needs `reports:read`, the same scope as call
reports (see `docs/product/api-call-reports.md`); there is no new scope. The code is in
`packages/python/ac_platform/integrations/coaching_api.py`.

This is not Ask Dipak's Next-call missions. Those are `coaching:read` and `coaching:write`, and
`docs/product/ask-dipak.md` describes them.

## The app's rules stand

| Read                    | Who                                                                      |
| ----------------------- | ------------------------------------------------------------------------ |
| My Coaching             | A person (connected app), from their own calls only, whatever their role |
| One call's coaching     | A person, for their own calls only: no owner or admin bypass             |
| The team's Coaching     | Owners, admins and organisation keys                                     |
| Names of reps who share | Only while the reader is a current owner or admin                        |

The team's Coaching is anonymous counts of how often each recommendation came up, plus the reps
who chose to share their Coaching.

For an organisation key, the reader is the person who made the key. An organisation key is no
person, so it has no Coaching of its own.

## Routes, tools and commands

| API (`/v1/api`)            | MCP             | CLI                     |
| -------------------------- | --------------- | ----------------------- |
| `GET /coaching`            | `my_coaching`   | `sx coaching`           |
| `GET /coaching/calls/{id}` | `call_coaching` | `sx coaching --call ID` |
| `GET /coaching/team`       | `team_coaching` | `sx coaching --team`    |

Each answer is the app's own view model (`CoachingView`, `CallCoachingView`, `TeamCoachingView`)
without the browser session id.

Refusals:

| Code                | When                                             |
| ------------------- | ------------------------------------------------ |
| 403 `scope_missing` | The key lacks `reports:read`                     |
| 403 `person_only`   | An organisation key asks for a person's Coaching |
| 403 `team_only`     | Anyone else asks for the team's                  |
| 404 `call_missing`  | Not one of the person's calls                    |

## How it reads

A key has no browser session, and the app's Coaching re-admits one. So the reports are read the
way the call-report API reads them:

1. The calls are found through the library query.
2. Their recordings are locked for share.
3. The app's post-authorization report projection reads them, never with the previous call's
   context.

The Coaching itself is built by the app's own code:

- `CoachingLibrary.read_authorized`, a small public entry added to `coaching/library.py`, for my
  Coaching;
- `CallCoachingCache.read` for one call;
- `from_report` and `summarize_team` for the team.

These are suggestions from AI reports, never official scores. AC-SVAL gates any official
scoring.

## Tests

- `tests/database/test_integrations_coaching_postgresql.py`:
  - each rule above, for people and an organisation key, directly and over the API;
  - a key without `reports:read` is refused.
- `tests/unit/integrations/test_coaching_api.py`: the scope on each tool, each refusal, the
  `sx coaching` commands, and that tool names stay unique.
