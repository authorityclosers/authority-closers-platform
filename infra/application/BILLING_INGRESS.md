# Billing ingress and rollout packet v1 — AUT-579 / R0

Prepared 2026-10-03 against `14c5311d8489c96c22d0ce098c45d930125432ba`.
This is a proposal for R1 review, not an applied configuration. The controlling
[AUT-560 plan](/AUT/issues/AUT-560#document-plan), revision
`d3daabe0-54f7-4052-bd30-83bb129ef7b7`, and [ADR 0052](../../docs/adr/0052-billing-ledger-subscriptions-and-top-ups.md) retain S7's activation boundary.

## Existing forwarding

| Exact callback URL | Release-owned handler | Upstream |
| --- | --- | --- |
| `https://api-staging.authorityclosers.com/v1/payments/webhooks/razorpay` | [staging.caddy](edge-routes/staging.caddy), `@staging_api` | `ac-staging-api:8000` |
| `https://api.authorityclosers.com/v1/payments/webhooks/razorpay` | [production.caddy](edge-routes/production.caddy), `@api` | `ac-production-api:8000` |

The foundation [Caddyfile](../vps-foundation/compose/foundation/Caddyfile)
imports `/etc/caddy/application-routes/{staging,production}.caddy` inside `:8080`.
The host mount is `/srv/authority-closers/application/edge-routes`; the installer
selects immutable `edge-route-releases/<sha>/<environment>.caddy` files.
The generic API handlers preserve path, method, raw body and signature/event-id
headers; they do not redirect or invoke the conversation write-eligibility gate.
Sales Xray `/v1/*` aliases also reach these upstreams, but are not proposed provider URLs.
The [webhook router](../../packages/python/ac_platform/http/billing.py) installs
only with billing commands, needs no session, and rejects query parameters.
Forwarding alone does not prove that billing is enabled or its route installed.

## Proposed Cloudflare packet (disabled; CEO routes any settings change)

For each host separately, substitute `HOST` with the exact API host above in
the following JSON bodies; expand `ENV` to `staging` or `prod` in each `ref`.
`W` means `(http.host eq "HOST" and
http.request.uri.path eq "/v1/payments/webhooks/razorpay")`; expand it literally
in `expression`. No wildcard, trailing slash, Cashfree, PayU or Stripe exemption.
Discover and record real zone/account IDs, ruleset IDs/versions, rule IDs/order,
Access application/policy IDs and tunnel ingress first; none are invented here.
Read `GET /client/v4/zones/{zone_id}/rulesets/phases/{phase}/entrypoint` for
`http_request_firewall_custom` and `http_ratelimit`; proposed additions use
`POST /client/v4/zones/{zone_id}/rulesets/{ruleset_id}/rules`, never replace a whole ruleset.

First custom rule (only where the existing plan supports body-size inspection):

```json
{"ref":"ac_r0_razorpay_body_ENV","enabled":false,"description":"Razorpay exact-path body cap","expression":"W and http.request.body.size gt 1000000","action":"block","action_parameters":{"response":{"status_code":413,"content_type":"text/plain","content":"Webhook body too large."}}}
```

Then the exact-path challenge exemption; custom challenge rules also require
their expressions to exclude `W`. Keep existing custom blocking rules intact:

```json
{"ref":"ac_r0_razorpay_no_challenge_ENV","enabled":false,"description":"Razorpay exact-path machine callback","expression":"W","action":"skip","action_parameters":{"phases":["http_request_sbfm","http_request_firewall_managed"],"products":["bic","securityLevel"]},"logging":{"enabled":true}}
```

Keep `http_ratelimit` active. Add this rule at the end of its phase's rules:

```json
{"ref":"ac_r0_razorpay_rate_ENV","enabled":false,"description":"Razorpay 120 requests per minute per source IP and exact path","expression":"W","action":"block","action_parameters":{"response":{"status_code":429,"content_type":"text/plain","content":"Webhook rate exceeded."}},"ratelimit":{"characteristics":["cf.colo.id","ip.src"],"period":60,"requests_per_period":120,"mitigation_timeout":60}}
```

Each host gets its own rule/counter; the single fixed path supplies path isolation.
Cloudflare requires `cf.colo.id`, so this is a per-data-centre counter, not a
strict global quota. Validate period/duration/custom-response entitlements with
the existing subscription; do not buy an upgrade. Overflow is a 60-second 429
block, with no challenge. [API shape](https://developers.cloudflare.com/waf/rate-limiting-rules/create-api/),
[parameters](https://developers.cloudflare.com/waf/rate-limiting-rules/parameters/) and
[skip options](https://developers.cloudflare.com/waf/custom-rules/skip/options/).

`http.request.body.size` [requires Enterprise](https://developers.cloudflare.com/ruleset-engine/rules-language/fields/reference/http.request.body.size/).
R1 must always add a preceding exact host/path Caddy handler with
`request_body { max_size 1000000 }` and the same API upstream/headers; preserve
the raw body for HMAC. [Caddy returns 413 on excess reads](https://caddyserver.com/docs/caddyfile/directives/request_body).
Without the edge entitlement, record the origin cap as the enforcement point;
do not claim edge enforcement or trust only `Content-Length` (chunked bodies).

Known repository conflicts: generic API routes lack a webhook-specific cap;
Admin/Coach API routes allow 2,000,000,000 bytes and must keep their upload limits.
The challenge applies to guest acquisition, not this unauthenticated router.
Live Cloudflare rules/Access/plan facts were not read. Before R1, inspect early
custom challenges, managed rules, broad `/v1/*` limits/skips, Access login,
cache/redirect rules, Worker/Transform body changes and tunnel host routing.
Bot Fight Mode [cannot be skipped by a custom rule](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/).
If it or Access blocks this path, record the exact Board action needed for CEO;
no global disable, guessed exemption, origin exposure or change in R0.
The proposed managed-rule skip is limited to `W` and needs CTO security review.

## Trial and S6 release preparation

[Names contract](SECRETS.md#billing-r0-names-reservation-aut-579): proposed
`AC_TRIAL_POLICY=v2` maps to `AC_SALES_XRAY_TRIAL_POLICY=v2` in dev/staging;
fixed proposed `AC_SALES_XRAY_TRIAL_POLICY_SWITCH_AT=2026-10-05T00:00:00Z`.
Apply only after S1c-P and reviewed runtime injection ship. If R1 misses this
instant, supersede the proposal with a new reviewed future UTC instant before
application; never apply a past instant or silently move the trial clock.
Production remains v1 with switch time unset until S7; this packet applies nothing.
The implemented trial selects v1 before the instant, v2 at it, and clamps the
existing person's trial start to `max(first_use, switch_at)` (ADR 0052).

R1 consumes reviewed S6a-2 service/timer, maintenance enqueue CLI and S6b
reconciliation, with their exact source SHA and tests. At this source pin those
assets are absent; there is no reviewed timer schedule or executable CLI to invent.
Have the versioned release installer wire `ac-billing-maintenance.service` and
`.timer` before rollout. Use `ac-release deploy staging <merged-sha> --component core
--dry-run`, then the authorised engine deployment; promote the same CI build
through the existing release train, respecting every production hold.
Record installed unit digests, service result, UTC `NextElapseUSecRealtime`,
the timezone/`OnCalendar`/`Persistent` values and an isolated dev double-enqueue
receipt: one durable expiry/reconciliation job, no duplicate closings or guessed
credit on mismatch. Annual future lots need no activation timer. No live expiry
before S6 ships; no manual `systemctl enable`, service restart or host edits here.

## R1 checks and rollback

Before: record nonsecret route selectors/hashes, build SHA, names presence,
trial version/time, timer state and Cloudflare rule snapshots/versions/order.
After: fictional invalid-signature callback reaches the installed application
without login/challenge; acceptance expects 400 `invalid_signature` (verify the
merged endpoint's actual error contract, do not count 404/HTML as a pass).
The provider parser already bounds bodies to 1,000,000 bytes, but reads follow
`request.body()`, so an origin streaming cap is still needed.
At 1,000,000 bytes the request reaches signature validation; 1,000,001 bytes,
including a chunked request, yields 413; a bounded overflow probe yields 429;
adjacent/non-Razorpay paths retain their protections. Check v1 immediately before
the proposed instant and v2 at it using an injected dev clock; prod stays v1.
Rollback only this packet's recorded rule IDs via `enabled:false`, restore any
edited challenge expression/order from its snapshot after checking no concurrent
change, and restore the prior immutable application/route through `ac-release`.
Disable the billing timer only through a reviewed rollback release. Trial rollback
needs CTO review of admission impact; never rewrite ledger, use or audit history.
