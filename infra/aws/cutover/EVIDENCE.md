# Fictional AWS cutover evidence — 29 Oct 2026

No real cutover, staging/production change, DNS change, S3 upload or backup timer activation.

- Accepted run: `/home/acdev/scratch/aws-cutover-20261029/run-03/`; full report `/home/acdev/scratch/aws-cutover-20261029/REPORT.md`.
- 24 files / 12,582,912 bytes presynced in 26.149 s; forward simulated write freeze **82.870 s**. Full reverse and reopen **99.063 s**.
- 256 tables and sequence/catalog checks matched; 26 final files / 12,582,979 bytes matched. AWS-window row/file survived; 10,002 source rows after return.
- Populated rollback at default lean lock capacity failed safely (transaction rolled back). Separate 192 MiB PG17 fixture at 512 locks/20 connections passed. Production requires its own exact settings/schema proof before holding writes.
- AWS backup capture 4.281 s, encrypted fictional archive 3.841 s, decrypt/restore/verify 23.948 s; all 256 tables matched. Real S3/IAM/lifecycle remains untested/unactivated.
- Actual SSH read-only DB tunnel and Caddy syntax validation passed. Own PG exited 0, no OOM/restarts; private ports closed and shared API ready 200. Existing rehearsal stack preserved.
- 26 local safety/encryption/rsync tests, ruff, HTTP import and systemd verification pass. Hosted control-plane/lint pass; wb-ci 40781561147 is blocked by prerequisite bundle storage admission and Python was skipped. Do not report overall CI green.
- Initial 21:49:50–21:55:30 overlap is disclosed in both reports; run-01 not accepted. Subsequent scheduled capacity phases ended 22:12:15; resource exclusivity was explicitly released. Capacity report remains NO-GO for t3.small at the requested load.

See [runbook](../../../docs/ops/aws-cutover.md) for exact owner/operator steps, source pins, current ops connections and remaining admission gates. No production readiness is implied.
