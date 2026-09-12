# Sales Xray 0031 recovery compatibility

This bounded recovery follow-up starts from integrated source `01ef58a` and
extends the three independently packaged PostgreSQL parity controllers to the
frozen `20260913_0031` migration. The `ac-postgres-parity-v11` contract retains
the 71-table `20260913_0030` inventory and adds exactly one table:

```text
conversation_inference_tasks
```

The historical `20260910_0027` to `20260910_0029` and `20260910_0029` to
`20260913_0030` rehearsal contracts remain explicit and unchanged. A third
explicit pair now covers `20260913_0030` to `20260913_0031`; it preserves every
populated source row and requires the new table to start empty. The controller
rejects unreviewed migration pairs and does not infer compatibility from
revision ordering.

## Verification

The controller parity suite covers the synchronized v11 table catalogue,
71-to-72 table-count transition, exact metadata identity, and rejection of
incomplete or unknown heads. The restore-drill suite covers the populated
0030-to-0031 transition, preserved source counts, and the empty new-table
contract. The combined controller suite passed **576 tests**, with two
expected Docker/opt-in integration skips. Ruff check and format validation
passed.

The opt-in PostgreSQL regression uses the dedicated local test runtime at
`127.0.0.1:55432`, a fresh `ac_migration_rehearsal_` database and an isolated
generated schema. It applies the existing populated 0027 fixture through 0030,
then upgrades to 0031 and compares every existing row before and after the
transition. The disposable schema is removed after the run.
The dedicated rehearsal passed **3 tests**; its temporary database was dropped
afterward.

No VPS deployment, application selector change, provider call, production
database mutation or operational SQL recovery occurred. This evidence does
not attest a live backup, restore or release; the installed foundation helpers
must receive the reviewed controller commit through the normal immutable
deployment path first.
