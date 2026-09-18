# Sales Xray 0032 and community 0033 recovery compatibility

This bounded follow-up starts from frozen Sales Xray source `8c907778` and
extends the three independently packaged PostgreSQL parity controllers through
the reviewed Sales `20260913_0032` parent and community `20260913_0033`
migration. The `ac-postgres-parity-v12` contract retains the
`20260913_0031` parity inventory and adds the two Sales plan tables. The
`ac-postgres-parity-v13` contract then adds exactly these community tables:

```text
conversation_processing_plans
conversation_plan_stage_authorizations
```

```text
community_discovery_preferences
community_connections
community_connection_events
community_blocks
community_reports
```

The historical `20260910_0027` to `20260910_0029`,
`20260910_0029` to `20260913_0030`, direct `20260910_0029` to
`20260913_0031`, and `20260913_0030` to `20260913_0031` rehearsal contracts
remain explicit and unchanged. Exact pairs cover populated
`20260913_0031` to `20260913_0032` and populated `20260913_0032` to
`20260913_0033`; each preserves every source row and requires its new tables to
start empty. Unknown heads and unreviewed pairs remain rejected; compatibility
is never inferred from revision ordering.

## Verification

The synchronized parity and restore-drill controller suite passed **699 tests**
with two expected Docker/opt-in skips. Ruff check and diff validation passed.
The model registry contract includes both Sales 0032 tables and all five
community 0033 tables.

The opt-in PostgreSQL regression used the dedicated local endpoint at
`127.0.0.1:55432`, a unique `ac_migration_rehearsal_` database and an isolated
generated schema. It populated the reviewed 0031 state, upgraded through 0032,
inserted valid processing-plan and stage-authorization rows, upgraded to 0033,
compared every existing row, and verified all five community tables were empty.
The targeted populated `0032 → 0033` regression passed **1 test** with five
related cases deselected. The temporary database is dedicated and disposable;
it was dropped after the run. `ac_local_sandbox` remained intact.

No VPS deployment, application selector change, provider call, production
database mutation or operational SQL recovery occurred. This evidence does
not attest a live backup, restore or release; the reviewed helpers must receive
this controller change through the normal immutable deployment path.
