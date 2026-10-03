# AUT-579 billing ingress preparation evidence — 2026-10-03

Source pin: `14c5311d8489c96c22d0ce098c45d930125432ba` (fresh gated main).
The interrupted 2 Oct draft was preserved and re-applied after the flow guard
removed its empty remote claim. This is docs-only R0 preparation, not R1 apply.

## Exact local and live resources

| Environment | Read-only live selector target | SHA-256 (also matches source file) |
| --- | --- | --- |
| staging | `/srv/authority-closers/application/edge-route-releases/14c5311d8489c96c22d0ce098c45d930125432ba/staging.caddy` | `d632b5022473059d7d8a8eba46230d62faa266f908797ee8c1d53e9cf10ea4da` |
| prod | `/srv/authority-closers/application/edge-route-releases/bfd392a86c55c6b4361f6dfc59a73f87d404ecde/production.caddy` | `a9cfd450e34757994781e9fc7f414a177753422aad85405751d6dc9b9bfff7cc` |

`ac-root check`, `ac-root run -- readlink -f` and `ac-root run -- sha256sum`
returned exit 0; the root wrapper records this run in its audit log.
The previous 2 Oct selectors are historical observations, superseded by these
read-backs; their route-content hashes have not changed.
No HTTP call was made to staging, production or a payment provider.

Cloudflare account, zone, ruleset, rule, Access and tunnel resource IDs remain
unobserved: R0 forbids provider/settings actions and reads no credentials.
No live-rule conflict or entitlement is asserted absent. R1 must record those
real IDs, full versioned before snapshots and exact targeted edits before apply;
this packet supplies the exact host/path bodies without inventing resource IDs.

## Expanded proposed rule bodies

Each entry below is a disabled single-rule POST body for the phase named in
its envelope. Review body-cap entitlement and challenge conflicts described in
[the packet](../../infra/application/BILLING_INGRESS.md). Keep the body rule
before the skip; do not skip `http_ratelimit`. No external write was performed.

```json
[
  {
    "environment": "staging",
    "phase": "http_request_firewall_custom",
    "body": {
      "ref": "ac_r0_razorpay_body_staging",
      "enabled": false,
      "description": "Razorpay exact-path body cap",
      "expression": "(http.host eq \"api-staging.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\") and http.request.body.size gt 1000000",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 413,
          "content_type": "text/plain",
          "content": "Webhook body too large."
        }
      }
    }
  },
  {
    "environment": "staging",
    "phase": "http_request_firewall_custom",
    "body": {
      "ref": "ac_r0_razorpay_no_challenge_staging",
      "enabled": false,
      "description": "Razorpay exact-path machine callback",
      "expression": "(http.host eq \"api-staging.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\")",
      "action": "skip",
      "action_parameters": {
        "phases": [
          "http_request_sbfm",
          "http_request_firewall_managed"
        ],
        "products": [
          "bic",
          "securityLevel"
        ]
      },
      "logging": {
        "enabled": true
      }
    }
  },
  {
    "environment": "staging",
    "phase": "http_ratelimit",
    "body": {
      "ref": "ac_r0_razorpay_rate_staging",
      "enabled": false,
      "description": "Razorpay 120 requests per minute per source IP and exact path",
      "expression": "(http.host eq \"api-staging.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\")",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 429,
          "content_type": "text/plain",
          "content": "Webhook rate exceeded."
        }
      },
      "ratelimit": {
        "characteristics": [
          "cf.colo.id",
          "ip.src"
        ],
        "period": 60,
        "requests_per_period": 120,
        "mitigation_timeout": 60
      }
    }
  },
  {
    "environment": "prod",
    "phase": "http_request_firewall_custom",
    "body": {
      "ref": "ac_r0_razorpay_body_prod",
      "enabled": false,
      "description": "Razorpay exact-path body cap",
      "expression": "(http.host eq \"api.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\") and http.request.body.size gt 1000000",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 413,
          "content_type": "text/plain",
          "content": "Webhook body too large."
        }
      }
    }
  },
  {
    "environment": "prod",
    "phase": "http_request_firewall_custom",
    "body": {
      "ref": "ac_r0_razorpay_no_challenge_prod",
      "enabled": false,
      "description": "Razorpay exact-path machine callback",
      "expression": "(http.host eq \"api.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\")",
      "action": "skip",
      "action_parameters": {
        "phases": [
          "http_request_sbfm",
          "http_request_firewall_managed"
        ],
        "products": [
          "bic",
          "securityLevel"
        ]
      },
      "logging": {
        "enabled": true
      }
    }
  },
  {
    "environment": "prod",
    "phase": "http_ratelimit",
    "body": {
      "ref": "ac_r0_razorpay_rate_prod",
      "enabled": false,
      "description": "Razorpay 120 requests per minute per source IP and exact path",
      "expression": "(http.host eq \"api.authorityclosers.com\" and http.request.uri.path eq \"/v1/payments/webhooks/razorpay\")",
      "action": "block",
      "action_parameters": {
        "response": {
          "status_code": 429,
          "content_type": "text/plain",
          "content": "Webhook rate exceeded."
        }
      },
      "ratelimit": {
        "characteristics": [
          "cf.colo.id",
          "ip.src"
        ],
        "period": 60,
        "requests_per_period": 120,
        "mitigation_timeout": 60
      }
    }
  }
]
```

## Environment mappings (names only)

| Infisical environment/path | Canonical runtime names | Rollout reservation |
| --- | --- | --- |
| `dev` / `/application` | `AC_RAZORPAY_KEY_ID`, `AC_RAZORPAY_KEY_SECRET`, `AC_RAZORPAY_WEBHOOK_SECRET` | independent TEST credentials only after explicit authorisation |
| `staging` / `/application` | `AC_RAZORPAY_KEY_ID`, `AC_RAZORPAY_KEY_SECRET`, `AC_RAZORPAY_WEBHOOK_SECRET` | independent TEST credentials only after explicit authorisation |
| `prod` / `/application` | `AC_RAZORPAY_KEY_ID`, `AC_RAZORPAY_KEY_SECRET`, `AC_RAZORPAY_WEBHOOK_SECRET` | independent credentials; S7 controls live mode |

`RAZORPAY_*` in the card maps to the prefixed store/runtime names; it is not an
alias. `CASHFREE_CLIENT_ID` / `CASHFREE_CLIENT_SECRET` reserve prefixed names
for S3, with no current Settings fields or injection. No names' availability,
credential values or modes were read from Infisical or any running process.
Compose currently forwards none of these billing/trial fields; reviewed R1
wiring must ship before any configuration is effective.

## Trial and timer boundary

Proposed dev/staging switch: `2026-10-05T00:00:00Z`, using
`AC_SALES_XRAY_TRIAL_POLICY=v2` and `AC_SALES_XRAY_TRIAL_POLICY_SWITCH_AT`.
This supersedes the unapplied draft's elapsed `2026-10-03T00:00:00Z` proposal.
`AC_TRIAL_POLICY=v2` is the plan shorthand only. Production remains v1/unset
until S7. A missed switch requires a new reviewed future instant, never silent
backdating. These are proposed settings, not readings of live configuration.

S6a-2's `infra/application/systemd/ac-billing-maintenance.service` and `.timer`,
`packages/python/ac_platform/payments/cli.py`, and S6b reconciliation are absent
at the source pin. R0 records release/next-run/double-enqueue checks; it does
not claim a reviewed installed schedule or fabricate a command for absent code.
R1 consumes their reviewed SHA and the versioned installer wiring. S6's outputs
are required for R1 execution, not for this independently reviewable R0 packet.

## Verification

- `uv run --frozen --offline pytest -q tests/unit/billing/test_trial.py tests/unit/http/test_billing_routes.py tests/infra/test_sales_xray_account_edge.py --basetemp "$PAPERCLIP_RUN_SCRATCH_DIR/pytest"`: exit 0, **132 passed**, 9.14 s. Existing FastAPI test-client deprecation warning only.
- Trial tests prove the boundary and first-use clamping using injected clocks;
  HTTP tests prove raw callback body/headers survive and routes require commands.
- Account-edge tests use local Caddy plus a fictional loopback API. They do not
  prove the proposed Cloudflare rules, future body handler or deployed billing.
- Local names/JSON/link checks validate this packet; no new tests or application
  code were added. See [R0 receipt](20261003_R0.md) for the handoff checks.

R1's bad-signature/413/429 and deployed timer checks remain future apply evidence.
The card expects 400 `invalid_signature`; the pinned route propagates
`PaymentEventRejected`. R1 must verify the merged application error mapping
before counting a bad signature as a pass; a 404 or HTML challenge is not proof.
