# AUT-1676: integration with main 4d25e47

Main now includes #414 prospect fields, #419 screens and #422 organisation
reads. The strike preserves these changes. The new, undeployed report-minute
migration follows prospect fields as 20261010_0080 -> 20261009_0079. It has not
been applied to dev, staging or production by this session.

All three backup/restore consumers retain prospect fields at v50 and add the
minute journal at v51, deriving its full table list from v50. Historical contract
versions remain intact. Alembic/metadata PostgreSQL proof checks the single
linear upgraded schema, including both new tables and append-only triggers.

Focused merged-source verification: 22 PostgreSQL recovery/retry/charging cases,
22 registry checks and both exact backup parity checks (46 total), plus 77
frontend checks. Changed migration/parity Python passes Ruff and formatting.
The real component browser proof repeats all 20 state/viewport/theme combinations
through ac-heavy after the integration, with expanded approval terms fitting.

Application CI 38039746086 at the earlier b852c51 source passed every job,
including all four Python shards, static/gates, frontend and acquisition browser.
The final merged source needs its own CI receipt. The shared-file gate is still
blocked by #424 (AGENTS.md) as of the recorded local pr-check; it is not bypassed.
The expired unaccepted-quote page mount remains an explicit Strike A integration
item in strike-c-run-state-20261010.md.
