# AUT-154: the UI studio on salesxray-dev uses staging's Sales Xray back end

Date: 29 Sep 2026. Lane: sales-xray.

## Why

The owner designs Sales Xray screens live on salesxray-dev (the ui lane's `next dev`, behind Cloudflare
Access) and needs to see real calls and reports there. Dev can't run its own analysis yet:

- the native helper accepts only uid 10001, and the dev API runs as `acdev`;
- the stored native build (390b4285) knows only staging and production;
- main's installer can't install that build, because its renderer pin and its release-bound renderer path disagree.

That dev-native work is a separate platform task.

## Change

- `Settings.sales_xray_studio_origin` names one exact origin, `https://salesxray-dev.authorityclosers.com`, on
  **staging only**, and only when the Sales Xray host is configured. Production has none.
- `require_safe_origin` accepts that origin only for requests to the Sales Xray host. Every other host still
  refuses it.
- CORS `allowed_origins` is unchanged: the studio reaches staging through its own same-origin proxy (the dev
  Caddy sends `/v1/*` to salesxray-staging with the Host rewritten).

## Tests

`tests/unit/http/test_sales_xray_auth.py` gains 7 cases:

- staging's Sales Xray host accepts the studio origin;
- the public, admin and API hosts refuse it;
- production trusts no studio origin;
- CORS is unchanged;
- staging with no Sales Xray host trusts no studio origin.

Locally: `test_sales_xray_auth.py`, `test_auth_routes.py` and `test_settings.py` all pass (304 tests), and ruff
check and format pass.

## Check on dev after the staging deploy

Sign in on https://salesxray-dev.authorityclosers.com with a staging account. The Calls library lists the
account's staging calls, and a finished report opens in the studio's screens.
