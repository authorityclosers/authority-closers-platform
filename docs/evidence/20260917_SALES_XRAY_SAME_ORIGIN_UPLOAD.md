# Sales Xray same-origin upload recovery

## Finding

On 2026-09-17, a fresh public guest upload reached the Sales Xray source upload endpoint but received HTTP 403 before a canonical recording was created. The browser request was a same-origin `PUT` through `salesxray.authorityclosers.com`; browsers omit the `Origin` header for this request. The API's safe-origin guard required an `Origin` value even when the request host was the configured Sales Xray host, so the user saw an access error and could not reach processing.

## Change

`require_safe_origin` now accepts a missing `Origin` only when the request hostname exactly matches the configured Sales Xray application host. Requests with a foreign origin, and requests on every other surface, continue through the exact configured-origin checks. This keeps the host boundary while allowing the browser's same-origin upload transport.

## Verification

- Added a unit regression for a same-origin Sales Xray `PUT` without `Origin` and a foreign-origin rejection on the same host.
- Targeted auth tests pass.
- Production verification must be performed after the signed release is deployed: upload a fresh consented guest recording, confirm the source `PUT` is no longer 403, then confirm the recording appears in Admin and advances through the server-owned stages.

No production database rows or provider state are edited by this change.
