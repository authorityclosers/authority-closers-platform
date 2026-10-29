# Usage metrics store (one Admin for every environment)

Owner order, 19 Oct 2026: there is only one Admin, the production Admin. It shows real cost and usage for production, staging and dev, each tagged by environment.

## Shape

```
each environment's postgres ──(read-only export, every 15 min)──▶ /srv/authority-closers/metrics/<env>/usage.json
                                                                        │ (read-only mount)
                                                         Admin API ◀────┘  GET /v1/admin/conversation/metrics
```

- **`ac-metrics-collect`** (root timer on the ac host) runs `usage-metrics-export.sql` inside each environment's own postgres container.
  - The session is read-only (`default_transaction_read_only=on`) with a 60 s statement timeout.
  - The JSON is written atomically.
  - The collector never writes to an application database, never connects one environment to another, and moves no secret: the login stays inside the container.
- **The document holds numbers only:**
  - opaque call and company ids, dates, stage, provider, model and version labels, and token, audio, time and attempt counters;
  - hold totals and payment totals;
  - company names.

  It never holds call titles, transcripts, reports, prompts, audio, people, emails or phone numbers. `tests/unit/conversation_intelligence/test_cost_metrics.py` guards the SQL.
- **The Admin API** (`ac_platform.conversation_intelligence.cost_metrics`) reads whatever environment folders are mounted for it, then:
  - prices the counters from the repo price sheet (`admin_pricing.py`, list price at ₹100/USD; not an invoice);
  - counts rows that were copied between databases once, in the most upstream environment (production, then staging, then dev).
- **What each Admin is given:**
  - the dev Admin mounts dev and staging only;
  - the production Admin mounts all three.

  Production numbers never flow down.

## AI budget alerts (19 Oct 2026)

After each export, `ac-budget-alerts --apply` reads the store (production only unless
`AC_BUDGET_ALERT_ENVIRONMENTS` says otherwise) and does three things:

- **Owner task.** It keeps one AC Pulse task for the owner while a budget is at least 80% used or any call is waiting for budget. The task holds the one-click raise link, and it closes itself once usage is back under 80% with nothing waiting. Pulse is written only through `pulse.task_save` and `pulse.task_move`.
- **Telegram.** It sends the owner one Telegram line when an alert opens or gets worse.
- **Ceiling changes.** It sends the owner one Telegram line (through `ac-notify-owner`) for each change of the AI budget ceiling or period in Admin. Cap raises send nothing.

State lives in `/var/lib/ac-budget-alerts/state.json` and the log in `/var/log/ac-budget-alerts.log`.

## Agent work and server time (30 Oct 2026)

`ac-agent-burn` is a root timer. It runs nightly at 23:40 UTC, at nice 19 and with at most 25% of a CPU, and writes `/srv/authority-closers/metrics/agent-burn.json`. Admin → Economics uses that file to split the agents' subscriptions and the ac server by product (`ac_platform/economics/burn.py` and `costs.py`).

- **Agent work.** It reads the Claude and Codex session logs changed in the last 30 days and weighs them at list-price ratios. It places each session by the files it touched: Sales X-Ray, the learner app, or platform and ops. Pulse, EA and Naya work is placed by the session's working folder. Anything else is unattributed.
- **A laptop's own logs.** `ac-agent-burn --summary --source laptop --tool claude <folder>` prints the same counts for a laptop's logs. Save the output as `/srv/authority-closers/metrics/agent-burn.d/laptop.json`. Counts younger than 8 days are added.
- **Server time.** It reads CPU use since the last run from cgroup v2:
  - apps: `system.slice` (every environment's containers and services);
  - agents: `ac.slice` and `user.slice`.

  The previous reading is kept in `/var/lib/ac-agent-burn/cpu.json`.
- **Counts only.** The file holds no prompt, path, file name, person or session id.

## New costs found in email (30 Oct 2026)

`ac-cost-detect` runs as a root timer daily at 02:30 UTC. It searches AC's mailboxes, read only, for receipts, invoices, renewals and payment notices from the last 3 days.

- **Proposal.** Each charge it finds gets a proposed vendor, amount (rupees and the original currency), cadence, category, cost centre and split. The proposal comes from the sender's domain and the text, and carries a confidence.
- **Filing.** It files one AC Pulse task per charge under "AC costs: confirm new costs from email" through `ac-pulse-tasks ensure`, with the marker `cost:<hash>`, so each email is filed once. Finance confirms the task into Pulse finance and the Admin cost register.
- **What a task holds.** The vendor, amount, date, subject and Gmail id. Never the email's body.
- **Gmail access.** A Google service account with domain-wide delegation for `gmail.readonly` only. Its key is `/etc/ac-cost-detect/service-account.json` (root 600, from Infisical), and the mailboxes are listed in `/etc/ac-cost-detect/env` as `AC_COST_DETECT_MAILBOXES`.
- **Before the key exists.** The unit does nothing (`ConditionPathExists`).
- **One-off back-scan.** `ac-cost-detect --days 60` (add `--dry-run` to print instead of filing).
- **State.** `/var/lib/ac-cost-detect/seen.json` holds message hashes only.

## Install (dev, done 19 Oct 2026)

```bash
sudo infra/metrics/install.sh --dev-api
```

It installs the collector to `/usr/local/sbin`, the SQL and the canary fixture hashes to `/usr/local/lib/ac-metrics`, and the timer. It also adds the dev-live API's read-only binding and `AC_METRICS_STORE_ROOT` (restart `ac-dev-live-api` afterwards).

## Production (Root, with the release that carries this)

1. Install from the released commit: `install.sh` without `--dev-api`.
2. Add `production` to `AC_METRICS_ENVIRONMENTS` in `ac-metrics-collect.service`.
3. Mount `/srv/authority-closers/metrics` read-only into the production API container.
4. Set `AC_METRICS_STORE_ROOT=/srv/authority-closers/metrics` there.
5. Check that Admin → Usage & cost lists all three environments, with fresh times.
