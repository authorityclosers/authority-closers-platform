# Sales Xray v0.2 live bridge compatibility

Date: 2026-09-23

The bridge route-policy test now covers the three plan requests used by the v0.2 frontend:

- `GET /v1/conversation/acquisition/submissions/{id}/plan` for the owner-scoped saved plan.
- `POST /v1/conversation/acquisition/submissions/{id}/plan/quote` for an explicit quote request.
- `POST /v1/conversation/acquisition/submissions/{id}/plan` for explicit acceptance.

Each request must resolve to a session-authenticated route. The test also confirms that wrong methods, extra path segments, query strings, and `GET`/`POST /v1/admin/conversation/analysis-settings/history` remain blocked. The bridge allowlist implementation was not changed.

The backend source has matching quote, owner-read, and accept handlers in `packages/python/ac_platform/http/conversation_submissions.py` at lines 582, 609, and 626. These local source and bridge unit checks do not establish that a live remote service has deployed those handlers.

Validation used Node `v24.19.0`:

```text
node --test scripts/sales-xray-production-bridge.test.mjs
tests 6
pass 6
fail 0
```

The suite exercises the local bridge with a stub upstream. No production API request was made, and no bridge runtime was started, stopped, or changed for this check.
