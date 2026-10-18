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
