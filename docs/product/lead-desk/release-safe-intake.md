# Release-safe lead intake

The owner asked on 27 Oct 2026: "when a routine update runs, services might stop midway… how are we handling this?"

This note covers how each inbound lead path behaves during a release, what production shows, and the fix that means no lead is ever lost. The orchestrator approved it on 27 Oct 2026, and it is built as described under "What was built".

## What happens today

Every production release puts every host behind the edge hold (`infra/application/edge-routes/production-hold.caddy`), `salesxray.` and `api.` included. The hold answers any request with a plain-text `503` and `Retry-After: 30`.

During the hold the release:

- stops the API and workers;
- switches the database to the migrator only;
- migrates;
- starts the new release.

Nothing in the app can store a lead until the hold lifts.

There were six holds on 26 Oct 2026, about two minutes each (UTC, from `deployments/production/*.env`):

| #   | Hold              | Release  |
| --- | ----------------- | -------- |
| 1   | 01:47:13–01:49:07 | 7b76772f |
| 2   | 06:45:09–06:47:10 | a2e71abb |
| 3   | 08:30:12–08:32:18 | 1bb8df63 |
| 4   | 12:21:53–12:23:51 | 405eebd8 |
| 5   | 14:21:02–14:23:03 | d5b1ec84 |
| 6   | 17:34:23–17:36:24 | 6160b08a |

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

## What was built: a store-and-forward spool for the capture route during the hold

**Why not just answer with something senders retry?** The hold already answers `503` with `Retry-After`, which Meta, WhatsApp, Google and Make retry. A website form never retries, and Zapier retries only on paid plans with Autoreplay on. No status code changes that.

The code is `packages/python/ac_platform/lead_desk/spool.py`.

**1. `intake-spool`: a small receiver that a hold never stops.**

- It is a service in `infra/application/compose.yaml` on the API image, running standard-library code only: `python -m ac_platform.lead_desk.spool serve`.
- It has no database network and no secrets. Its environment is `AC_ENVIRONMENT` and `AC_INTAKE_SPOOL_ROOT` only, its root filesystem is read-only, and it has 96 MiB of memory. Started, it holds about 25 MiB (measured 27 Oct 2026 on Python 3.12: its imports are the standard library and the two package `__init__` files).
- The edge reaches it as `ac-<env>-api-intake:8080`.
- It accepts only `POST /v1/lead-desk/capture/{uuid}` and `POST /v1/lead-desk/capture/{uuid}/google-ads`, with a body of at most 64 KiB (the API's own limit). It reads the body as the API does: JSON, or a form.
- For each lead it writes one file to `/srv/authority-closers/application/intake-spool/<env>/new/` (a temporary file, then `fsync`, then rename; mode 0600, owned by the app user 10001). The file holds:
  - the source;
  - the arrival time;
  - the lead;
  - the source key's SHA-256, never the key itself. The key comes from the header, the bearer token, `?key=` or Google's `google_key`; the last is removed from the stored body.
- It answers `202 {"received": true, "outcome": "queued", "lead_id": null}`, the API's 202 shape. It answers 401, 404, 413 or 422 where the API would.
- It can't check the key, because it has no database. It bounds a flood instead:
  - at most 10,000 waiting files, then 503;
  - 60 posts a minute from one address, then 429. The address is read as the API's own
    limiter reads it (`http/rate_limits.py` `client_identity`): `CF-Connecting-IP` only when
    the edge router (`AC_TRUSTED_PROXY_ADDRESSES`) delivered exactly one, else the peer, and
    an IPv6 sender by its /64. `X-Forwarded-For` is the sender's to write, so it is never
    read. Caddy's `{client_ip}` wouldn't do: the edge listens only on 127.0.0.1 behind the
    Cloudflare tunnel and has no trusted proxies, so it is the tunnel's one address.
- A sender has 15 s to send its body, as at the API, and every read waits at most 15 s,
  so a stalled sender, or one that says its body is longer than it is, frees its thread.
  A chunked body is read too (Caddy passes one on as sent), up to the same 64 KiB.
- Anything else gets the hold's 503 and `Retry-After: 30`.

**2. The release starts it, then the hold sends capture posts to it.**

- `install-application-release.sh` prepares the spool folder (10001:10001, 0700) and starts the candidate's spool **before** the hold, before any mutation.
- A spool that won't start leaves those posts with today's 503. It doesn't stop the release.
- A release stops only the API and the workers, never the spool.
- `production-hold.caddy` and `staging-hold.caddy` each add a named matcher (the Sales X-Ray host, `POST`, the two capture paths) with its own `handle`, ahead of the 503 hold. Outside a hold nothing changes.

**3. The API files what the spool kept, every minute.**

- The API runs `spool.run_replay` for its lifetime (`spool.attach`, beside the Lead Desk push loops), so there's no timer and no extra release step. The API mounts the same folder.
- Each file goes through the same `Intake.capture`:
  - the key is checked by its hash (`key_sha256`);
  - the arrival time becomes the lead's `received_at`;
  - the capture's content reference dedupes, so a file replayed after a crash is filed once.
- Then:
  - filed or already known: the file is deleted, since the lead is in the database now;
  - a wrong key, an unknown source or a lead with no answers goes to `rejected/`;
  - anything else stays in `new/` for the next minute, for up to 24 hours. A file still
    failing after that moves to `rejected/` with one error log, so `new/` can't fill
    with files that never file.
- `rejected/` is deleted after 7 days. Spool files hold personal data, so they stay out of
  git and logs, and out of backups: restic excludes the spool folder
  (`ac-restic-backup-inner`), and the Drive backup reads only `/srv/authority-closers/backups`.
- A file lock keeps two API processes from replaying at once.

The compose file, the hold files and the release script are shared infrastructure, so this needs CTO review before it rides a release.

### Tests

Built as `tests/unit/lead_desk/test_spool.py`, `tests/database/test_intake_spool_postgresql.py` and `tests/infra/test_intake_spool_infra.py`. The hold files were also adapted by the edge's own Caddy image with the foundation Caddyfile, and the intake route is evaluated before each 503.

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
  - both hold files adapt with the foundation Caddyfile;
  - only a capture POST on the Sales X-Ray host goes to the spool, and everything else, `/health/ready` included, keeps the `503 release-hold-<env>`.
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
