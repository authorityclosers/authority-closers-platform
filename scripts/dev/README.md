# Sales Xray sandbox loader

`load-sales-xray-sandbox.py` loads the owner's fictional dataset into normal
conversation records in the exact active AC Sandbox organisation. It requires
the current approving owner's UUID and a recorded approval reference.

The current live dev database is `172.27.0.12:5432/ac_platform` in the dedicated
`acdev-live-postgres` container. Root moved it there on 11 Oct 2026; the earlier
loopback database named `ac_dev_live` is no longer served. The script requires
`AC_ENVIRONMENT=development` and refuses any other database, host, port or URL
query options. Credentials are injected at runtime through the existing dev
environment; never pass them as arguments or copy them into a receipt.

With that environment already injected:

```sh
python scripts/dev/load-sales-xray-sandbox.py \
  --dataset /home/acdev/strikes/1676/sandbox-source-20261011-0537 \
  --approver-person-id "$AC_SANDBOX_APPROVER_PERSON_ID" \
  --approval-reference "Owner AUT-1701 DEV-FIRST sandbox load 2026-10-11"
```

The default is dry-run. After inspecting its JSON receipt, repeat with `--apply`.
It validates all 3,360 bundles and 60 representatives, then writes members,
normal owned calls and completed reports in one transaction with an audit event.
Every source and label says synthetic. The exact authored report, coaching,
transcript and answer key remain preserved in sandbox records; the normal report
adapter copies only authored findings and their quoted transcript evidence.

Synthetic usage is released immediately and has a zero-second no-work settlement.
Completed local jobs cannot enter the provider queue. Member identities have no
password, provider identity or verified-email assertion. Replays skip identical
calls and refuse changes to preserved content or existing membership state.

Once the full calls are loaded, repeat dry-run and apply with `--include-history`
to preserve the 177,615 dated call summaries for history readers. These summaries
do not acquire invented transcripts or reports. The loader calls the normal
company Insights refresh adapter so charts can read them immediately. Keep the identifier/count-only
JSON receipts in the strike notes; full source files stay outside Git.

Verify with a normal dev owner session: select AC Sandbox, open Calls and a
populated report, then organisation members and team Coaching. The normal API
library must show `report_ready` calls, `done` analysis and their representative owners.
Hosted acceptance is complete only after these reads succeed on dev.
