# Sales Xray 0031 recovery compatibility

This bounded recovery follow-up starts from integrated source `2358e3c` and
extends the three independently packaged PostgreSQL parity controllers to the
frozen `20260913_0031` migration. The `ac-postgres-parity-v11` contract retains
the 71-table `20260913_0030` inventory and adds exactly one table:

```text
conversation_inference_tasks
```

The historical `20260910_0027` to `20260910_0029` and `20260910_0029` to
`20260913_0030` rehearsal contracts remain explicit and unchanged. The
`20260913_0030` to `20260913_0031` pair preserves every populated source row
and requires the new table to start empty. Because live application databases
remain at `20260910_0029`, a separate direct `20260910_0029` to
`20260913_0031` pair is also explicit: its selective parity contract preserves
58 reviewed source tables and requires all 14 Sales Xray/inference tables to
start empty. The controller rejects unreviewed migration pairs and does not
infer compatibility from revision ordering.

## Verification

The controller parity suite covers the synchronized v11 table catalogue,
71-to-72 selective parity transition, exact metadata identity, and rejection
of incomplete or unknown heads. The restore-drill suite covers the populated
0030-to-0031 and direct 0029-to-0031 transitions, preserved source counts,
and empty new-table contracts. The PostgreSQL regression includes the direct
0029-to-0031 chain; it applies both reviewed migrations in one disposable
schema, compares every physical source row before and after, and confirms the
14 new physical tables are empty. The focused local run passed **66
restore-drill tests** and **512 parity/integration tests**; six expected Docker
or PostgreSQL opt-in cases were skipped. Ruff remains a CI gate for this
follow-up.

The opt-in PostgreSQL regression uses the dedicated local test runtime at
`127.0.0.1:55432`, a fresh `ac_migration_rehearsal_` database and an isolated
generated schema. It applies the existing populated 0027 fixture through 0030,
then upgrades to 0031 and compares every existing row before and after the
transition. The disposable schema is removed after the run.
The dedicated rehearsal passed **4 tests**; its temporary database was dropped
afterward. The physical schema was 79 tables before the direct migration and
93 afterward; the controller's selective parity projection remains 58 to 72.

No VPS deployment, application selector change, provider call, production
database mutation or operational SQL recovery occurred. This evidence does
not attest a live backup, restore or release; the installed foundation helpers
must receive the reviewed controller commit through the normal immutable
deployment path first.
