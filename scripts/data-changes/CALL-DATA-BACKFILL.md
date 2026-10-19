# Call data engine backfill (staging, production)

Every stored call is read once by the fast pipeline and then by the deep
pipeline. Calls already read are skipped, and our canary and QA calls are never
read. Both runs stay within the Admin daily caps; if a cap is reached, the
remaining calls wait.

## Approval

The owner approved this on 19 Oct 2026; the orchestrator relayed it, and it is
recorded on the v0.65 release card.

| Pipeline | Staging | Production |
|---|---|---|
| Fast | ~₹42 | ~₹2.5 |
| Deep ("yes deep") | ~₹147 | ~₹9 |

The estimates use the rates measured on the dev backfill: fast ₹0.087 and deep
₹0.30 per audio minute.

## When

Run it after v0.65 is live and healthy, in a window agreed with Align 3, and
never during a promote. The script takes `/run/ac-release.lock` and refuses to
start while a release holds it. Releases wait for the backfill to finish
(staging takes about 30 minutes).

## How (on ac, as root)

```bash
sudo scripts/data-changes/call-data-backfill.sh staging            # dry run: what would be read
sudo scripts/data-changes/call-data-backfill.sh staging --apply    # snapshot, pause runner, backfill, restart, summary
sudo scripts/data-changes/call-data-backfill.sh production         # dry run
sudo scripts/data-changes/call-data-backfill.sh production --apply
```

`--apply` does four things in order:
1. Takes a verified `ac-db-snapshot <env> call-data-backfill`.
2. Stops `ac-call-data@<env>`. Only one runner may hold the database lock.
3. Runs the runner with `--backfill --pipeline both --apply`.
4. Always restarts the runner, then prints content-free counts: runs by
   pipeline and state with their spend, and objects made, retracted and
   superseding.

## Afterwards

Post the following on the release card: the snapshot path, the spend per
pipeline, and the object counts. Each backfill run is recorded in
`call_data_runs` with trigger `backfill` and created_by
`operator:call-data-backfill`. Every object it made points at its run.
