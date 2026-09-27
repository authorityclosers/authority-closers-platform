# Hosted avatar upload transport

Base source: `a9196c11063bf13b87bb4411a099c60275b24b70`.

The hosted filesystem avatar intent now uses the exact configured learner or
Sales Xray origin of the authenticated request. The media route accepts only a
matching configured `Origin` and raw request `Host` authority. It supplies that
origin to a request-scoped copy of the avatar service and storage adapter;
shared runtime state is not changed. The short-lived filesystem upload token
signs the chosen origin together with its existing object key, byte length,
MIME type, and SHA-256 checksum. The PUT route checks the origin against the
configured list and token before writing bytes. A token issued for one app host
cannot be replayed at the other host.

The authenticated avatar read route now mints the signed delivery URL on the
same configured learner or Sales Xray host serving the profile request. GETs
often omit `Origin`, so reads select the surface from the exact raw `Host`
authority and the scheme of the matching configured app URL. If a GET includes
`Origin`, it must match that same surface. The Python API runs with Uvicorn
`--no-proxy-headers` (`infra/application/Dockerfile.python`); this route does not
use `Forwarded` or `X-Forwarded-*` values as authority. A request-scoped copy of
the signed delivery port changes only the generated URL host. Read tokens stay
origin-independent and retain the existing tenant/person/session, current
avatar version, and private object-key authorization checks. On a Sales Xray
host, the request must therefore carry that host's own authenticated session;
a token from a different canonical session is denied. No provider URL is
returned.

Scanner behavior, canonical actor/tenant ownership, upload completion, and
external object-store transport are unchanged.

The browser accepts a filesystem avatar URL only when it is same-origin, uses
the exact filesystem upload path/object key, contains one well-formed media
token, and has the expected MIME, length, and checksum headers. It sends the
PUT with same-origin credentials and mode, no referrer, no cache, and redirects
disabled. The browser supplies `Content-Length` and `Origin`; the client does
not set them. External object-store uploads continue to omit credentials and
also omit browser-owned `Content-Length`, `Origin`, `Cookie`, and `Host`
headers.

Legacy filesystem upload tokens created before this change do not include a
signed origin and fail closed at PUT. A retry must obtain a newly issued upload
intent. Local sandbox avatar tokens remain on their existing separate contract.

Focused verification on the source worktree:

- `tests/unit/media/test_local_avatar_runtime.py` and
  `tests/unit/http/test_media_upload_telemetry.py`: 68 passed.
- `apps/learner-web/app/lib/avatar-upload.test.ts`: 20 passed.
- Learner web typecheck and focused ESLint: passed.
- Python Ruff on the three implementation modules and two focused tests:
  passed.
- Python mypy on the three implementation modules: passed.

These are unit and route-contract checks. No production or staging writes,
provider calls, actual browser upload/read, scanner integration, or deployed
verification were performed by this change.
