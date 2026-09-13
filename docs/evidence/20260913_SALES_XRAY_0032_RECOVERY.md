# Sales Xray 0032 recovery compatibility

This bounded follow-up starts from frozen Sales Xray source `8c907778` and
extends the three independently packaged PostgreSQL parity controllers to the
reviewed `20260913_0032` migration. The `ac-postgres-parity-v12` contract
retains the `20260913_0031` parity inventory and adds exactly these tables:

```text
conversation_processing_plans
conversation_plan_stage_authorizations
```

The historical `20260910_0027` to `20260910_0029`,
`20260910_0029` to `20260913_0030`, direct `20260910_0029` to
`20260913_0031`, and `20260913_0030` to `20260913_0031` rehearsal contracts
remain explicit and unchanged. A new exact pair covers populated
`20260913_0031` to `20260913_0032`; it preserves every source row and requires
both new tables to start empty. Unknown heads and unreviewed pairs remain
rejected; compatibility is never inferred from revision ordering.

## Verification

The synchronized parity and restore-drill controller suite passed **638 tests**
with two expected Docker/opt-in skips. Ruff format/check and diff validation
passed. The model registry contract now includes both 0032 tables.

The opt-in PostgreSQL regression used the dedicated local endpoint at
`127.0.0.1:55432`, a unique `ac_migration_rehearsal_` database and an isolated
generated schema. It populated the reviewed 0031 state, upgraded to 0032,
compared every existing row, and verified both new tables were empty. All
**5** migration rehearsal cases passed; the temporary database was dropped
afterward.

No VPS deployment, application selector change, provider call, production
database mutation or operational SQL recovery occurred. This evidence does
not attest a live backup, restore or release; the reviewed helpers must receive
this controller change through the normal immutable deployment path.
