# Google Picker under the Sales X-Ray edge CSP (27 Oct 2026)

Sheets and Drive, slice 1 opens Google's file picker on the Sales X-Ray sites. The
builder found that the edge CSP blocked it. This folder shows what the picker needs,
measured by opening it.

## How it was measured

- `probe.cjs` runs headless Chromium on ac (Playwright from `apps/sales-xray-web`).
- It serves a page with the exact `Content-Security-Policy` read from the production
  Sales X-Ray route.
- The page loads Google's real `https://apis.google.com/js/api.js`, loads the
  `picker` module and opens a picker.
- The key, token and project number are fictional: Google's own frame shows an error,
  but everything the page itself loads, frames or is refused gets recorded.

## Results

| Policy              | `current.json` (main today) | `new.json` (this change)                 |
| ------------------- | --------------------------- | ---------------------------------------- |
| `api.js`            | refused (`script-src-elem`) | loaded                                   |
| Picker module       | never loads                 | loaded, picker shown                     |
| Frames              | none                        | `https://docs.google.com`                |
| Page's own requests | the refused script          | 3 scripts from `https://apis.google.com` |
| Violations          | 1                           | 0                                        |

The page fetched, styled and drew nothing from Google, so `connect-src`, `style-src`
and `img-src` stay as they were.

`https://content.googleapis.com` is allowed as a frame as well. It is the Google API
client's proxy frame, which this probe did not reach with a fictional token.

## What changed

The Sales X-Ray route in `infra/application/edge-routes/{staging,production}.caddy` now
allows:

- `script-src` adds `https://apis.google.com`;
- `frame-src` adds `https://docs.google.com https://content.googleapis.com`.

No other route changes. Dev's loopback Caddy sets no CSP, so dev needs nothing.

## Checks

- `tests/infra/test_sales_xray_edge_csp_google.py` pins the directives for both
  environments, and that Google appears nowhere else.
- `tests/e2e/test_sales_xray_google_picker_csp_browser.py` has Chromium enforce the exact
  policy with synthetic Google bodies and no egress.
  - The loader, its module and both frames load.
  - A fetch and an image from Google are refused.
  - Run against today's routes, all six of the new cases fail.
- Caddy `adapt` and `validate` pass in the pinned foundation image (offline, read-only),
  with the foundation Caddyfile and both new routes. Each Google origin appears twice in
  the adapted config.

## Still to check with the real key

Once the browser key and the project number are set on dev, run a real pick there.

The Sales X-Ray route sends `Referrer-Policy: no-referrer`. If the browser key is
restricted by HTTP referrer, Google may refuse it. Restrict the key to the Picker API
instead, or prove that a referrer-restricted key works.
