# Release-safe lead intake

The owner asked on 27 Oct 2026: "when a routine update runs, services might stop midway… how are we handling this?"

This note covers how each inbound lead path behaves during a release, what production shows, and the smallest fix that means no lead is ever lost. Nothing is built yet: it waits for the orchestrator's confirmation.

## What happens today

Every production release puts every host behind the edge hold (`infra/application/edge-routes/production-hold.caddy`), `salesxray.` and `api.` included. The hold answers any request with a plain-text `503` and `Retry-After: 30`.

During the hold the release:
- stops the API and workers;
- switches the database to the migrator only;
- migrates;
- starts the new release.

Nothing in the app can store a lead until the hold lifts.

There were six holds on 26 Oct 2026, about two minutes each (UTC, from `deployments/production/*.env`):

| # | Hold | Release |
|---|---|---|
| 1 | 01:47:13–01:49:07 | 7b76772f |
| 2 | 06:45:09–06:47:10 | a2e71abb |
| 3 | 08:30:12–08:32:18 | 1bb8df63 |
| 4 | 12:21:53–12:23:51 | 405eebd8 |
| 5 | 14:21:02–14:23:03 | d5b1ec84 |
| 6 | 17:34:23–17:36:24 | 6160b08a |

## Every inbound lead path, and what its sender does with a 503

**Meta lead ads webhook**
- Route: `POST /v1/lead-desk/meta/webhook`.
- The sender retries immediately, "then try a few more times with decreasing frequency over the next 36 hours". It drops a notice after 36 hours ([Meta webhooks][meta]).
- Our backstop: `meta_pull.py` reads each Page's recent leads every 10 minutes. The Meta lead id dedupes, so a lead that arrives both ways is filed once. "Bring in older leads" reads 90 days.
- **Safe.**

**WhatsApp Cloud API**
- Routes: `POST /v1/lead-desk/meta/webhook/whatsapp` and `POST /v1/lead-desk/whatsapp/webhook`.
- The sender "retries delivery with decreasing frequency until the request succeeds, for up to 7 days" ([WhatsApp webhooks][wa]).
- Our backstop: the unique `wamid` index files a retry once.
- **Safe.**

**Instagram and Messenger messages**
- Route: `POST /v1/lead-desk/messaging/webhook`.
- The general Graph rule (36 hours, [Meta webhooks][meta]) covers it. I didn't verify a separate Messenger rule.
- **Safe.** Re-check once that app is live.

**Google Ads lead forms**
- Route: `POST /v1/lead-desk/capture/{id}/google-ads`.
- Google marks a 5XX "retryable" ([Google Ads webhook][gads]). It publishes no schedule.
- Our backstop: `google_pull.py` reads every active account every 10 minutes. The click id dedupes.
- **Safe.**

**Website forms**
- Route: `POST /v1/lead-desk/capture/{id}`. Senders: Elementor, WPForms, a site's own code.
- No retry. A browser form shows our 503 text, and a plugin at most logs an error.
- No backstop.
- **Lost.**

**Zapier**
- Route: `POST /v1/lead-desk/capture/{id}`.
- The step errors. Autoreplay retries up to 5 times over about 10 h 35 min, but only on the Professional, Team and Enterprise plans, and only when it's turned on ([Zapier Autoreplay][zap]).
- No backstop.
- **Lost** on the Free plan, or with Autoreplay off.

**Make**
- Route: `POST /v1/lead-desk/capture/{id}`.
- Make treats a 503 as a `ConnectionError` ([Make connection errors][make-503]) and reruns it automatically. The first rerun is after 1 minute. With incomplete executions stored, there are up to 8 reruns over about 8 h ([Make backoff][make-retry]).
- No backstop.
- **Usually safe.** It depends on the scenario's settings.

**Pabbly Connect**
- Route: `POST /v1/lead-desk/capture/{id}`.
- Auto Re-Execute does 0–5 attempts, set per workflow. The interval and the default aren't documented ([Pabbly][pabbly]).
- No backstop.
- **Lost** unless someone turned it on.

So the gap is one route, `POST /v1/lead-desk/capture/{id}`. It is the "Website form" source, and the app also tells people to use it for Make, Pabbly and Zapier. A two-minute hold loses whatever a website form or an unconfigured automation sends in it.

## What production shows

All of these were read-only, counts-only reads, logged in `costq/QUERY-LOG.txt` (`holds.sql` and `inbound14.sql`).

- **The edge keeps no access log.** `ac-edge-router` logs only its configuration, so we can't count the 503s it served during the holds.
- **26 Oct had no inbound leads.** Production received 0 leads that weren't typed in or imported from a file, and 0 inbound WhatsApp messages, all day. Nothing arrived in or near the six holds, so nothing was lost. There is also nothing to compare against a sender's side.
- **14 days to 27 Oct:**
  - 7 Meta leads (24–25 Oct, test leads while the production Meta apps are in development mode);
  - 549 file imports;
  - 27 leads typed in.
- **Production sources:** two Meta Pages only (109 received, the last on 25 Oct at 18:56Z). There are no website-form, Google Ads, WhatsApp or social sources yet.

So the at-risk route has no production traffic today. It will as soon as a customer's website form goes live, or Wise Life's Make or Pabbly flow moves to production. Fix it before then.

## Proposal: a store-and-forward receiver for the capture route during the hold

**Why not just answer with something senders retry?** The hold already answers `503` with `Retry-After`, which Meta, WhatsApp, Google and Make retry. A website form never retries, and Zapier retries only on paid plans with Autoreplay on. No status code changes that.

### The pieces

**1. `intake-spool`: a small receiver that releases never stop.**
- About 120 lines of standard-library Python, with no app code. It has its own pinned `python:3.12-alpine` image, a read-only root filesystem and 64 MiB of memory.
- It runs in the foundation compose next to `ac-edge-router`, so an application release never stops or replaces it.
- It accepts only `POST /v1/lead-desk/capture/{uuid}` and `POST /v1/lead-desk/capture/{uuid}/google-ads`. The body must be at most 64 KiB, the same as the API's `_CAPTURE_MAX`.
- For each request it writes one file to `/srv/authority-closers/application/intake-spool/<env>/new/` (a temporary file, then `fsync`, then rename; mode 0600, root:acops). The file holds:
  - the path and the content type;
  - the arrival time;
  - the body;
  - the source key's SHA-256, never the key itself: from the header, the query or Google's `google_key`, which it replaces in the body with its hash.
- It answers `202 {"received": true, "outcome": "queued"}`, the same 202 shape the API gives.
- It can't check the key, because it has no database. It bounds a flood instead: at most 10,000 files or 200 MB, then 503, plus a per-address rate limit.
- Anything else gets the hold's 503, as today.

**2. The hold sends the capture route to the spool.**
- `production-hold.caddy` and `staging-hold.caddy` each get about 6 lines: on `api.` and `salesxray.`, `path /v1/lead-desk/capture/*` goes to `intake-spool`, before the 503 catch-all.
- Outside a hold nothing changes, and the API answers as now.

**3. Replay after the release.**
- `python -m ac_platform.lead_desk.spool_replay` runs inside the API container, with the spool directory mounted.
  - The release script runs it right after write exposure (`activate_edge_route` to the new release).
  - A 5-minute timer runs it as a safety net, so nothing is stranded if a release step fails.
- Each file goes through the same `Intake.capture`:
  - the key is checked by its hash;
  - the arrival time becomes the lead's `received_at`;
  - the capture's content reference dedupes, so a file replayed after a crash is filed once.
- Afterwards the file moves:
  - a filed lead goes to `done/`;
  - a 401 or 422 goes to `rejected/`, with a count in the log.
- Both folders are deleted after 7 days. They hold personal data, so they stay out of git, logs and backups.

### Size

About 400 lines with tests:
- the spool and its tests: ~200;
- the replay and its tests: ~150;
- the hold files: +12;
- the foundation compose: +25;
- the release script: +8;
- the timer: +15.

The hold files, the foundation compose and the release script are shared infrastructure. That means one pull request on its own lane, with CTO review.

### Tests

- **Spool (unit):**
  - only the two paths are accepted;
  - the 64 KiB cap holds, and the file cap answers 503;
  - writes are atomic: a crash leaves no partial file;
  - the 202 body matches the API's;
  - the key is never written in clear, Google's included;
  - a GET answers 503.
- **Replay (PostgreSQL):**
  - a spooled capture becomes one lead with `received_at` set to the spooled time;
  - replaying it twice still files one lead;
  - a wrong key goes to `rejected/` and is counted;
  - a Google Ads payload files like its webhook.
- **Edge:**
  - both hold files pass `caddy validate`;
  - during a hold, a capture POST gets 202 from the spool, while `/health/ready` keeps its `503 release-hold-<env>` (the existing `check_route` stays true).
- **Staging drill:** post a test lead every 5 seconds through a full staging release. Every one arrives once.

### Ruled out

- **Keep the old API up for capture during the hold.** No: the database takes only the migrator while the hold is on.
- **Caddy alone.** It can't store request bodies.
- **A queue service (Redis, SQS).** More moving parts than a directory of files for a two-minute window.
- **Spool Meta and WhatsApp too.** Not needed: their senders retry for 36 hours and 7 days, and Meta also has the 10-minute pull.

### Later, separately

An API crash outside a release has the same exposure for website forms. The spool could later sit in front of the capture route permanently: always write, then forward. That is a larger change, so it is not proposed here.

[meta]: https://developers.facebook.com/docs/graph-api/webhooks/getting-started
[wa]: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks
[gads]: https://developers.google.com/google-ads/webhook/docs/implementation
[zap]: https://help.zapier.com/hc/en-us/articles/19220226086797
[make-503]: https://help.make.com/fix-connection-errors
[make-retry]: https://help.make.com/exponential-backoff
[pabbly]: https://www.pabbly.com/how-to-use-auto-re-execute-and-skip-step-feature-inside-pabbly-connect/
