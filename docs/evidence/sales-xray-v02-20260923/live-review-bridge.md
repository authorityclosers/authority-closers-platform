# Local production bridge: optional review-only mode

This note documents the opt-in `analysis_read_only` mode added to the existing loopback Sales Xray production bridge. It is a server-side API allowlist for reviewing current state through the existing UI; it is not an authentication mechanism or an Admin surface.

## Behavior

The default remains `analysis_read_only: false`, preserving current live bridge behavior. The CLI accepts the paired boolean option `--analysis-read-only true` or `--analysis-read-only false`; omitted means `false`, and any other value fails validation. `/health` returns the active boolean so a reviewer can verify the mode on the process they are using.

When enabled, the API route policy permits only routes already accepted by the bridge's exact route resolver with method `GET`, plus these exact `POST` exceptions:

- `/v1/auth/password/login`
- `/v1/auth/logout`
- `/v1/context`

The exceptions let an owner authenticate normally, end the session, and select workspace context. Authentication and workspace authorization remain canonical upstream checks; the bridge does not mint or bypass an account identity. OAuth redirect routes, Admin routes, unknown routes, and query variants of these POST exceptions are denied.

All other POST, PUT, PATCH, and DELETE API actions are refused before request-body reading and before the upstream fetcher is invoked. This includes quote creation, plan creation/acceptance, source upload/replacement, submission deletion, guest-session creation, account claim, intake quote, and run creation. Non-API page and asset requests continue to use the existing local UI proxy, which permits only GET/HEAD. The bridge does not cache upstream responses.

## Verification

The bridge tests use a synthetic fetcher and random loopback test ports; they do not contact the production service. The added tests assert that blocked operations do not invoke the fetcher, allowed exact GET and auth/context exceptions still reach it, default mode continues forwarding a plan quote, and the CLI option is strictly boolean.

Executed with Node.js `v24.19.0`:

```powershell
node --test scripts/sales-xray-production-bridge.test.mjs
```

Result: **8 passed, 0 failed**. `git diff --check` also passed for the changed bridge and test files.

No launcher was changed and no bridge process was restarted. The currently running bridge on port 3016 remains as it was started; this source change does not retroactively switch that process into review-only mode. A new process must be launched with the validated flag, and its `/health` response must report `analysis_read_only: true`, before relying on the restriction.
