# Sign in with Apple for Sales Xray

Why: the iPhone app will offer Google and Facebook sign-in, and Apple's App
Store rules then require Sign in with Apple as well. The web sign-in screen
offers it too (Google, Apple, Facebook, then email code or password). The owner's
Apple Developer account is being set up; nothing below exists at Apple yet.

Code: `packages/python/ac_platform/http/identity_provider_apple.py`; routes
`/v1/auth/apple/start`, `POST` and `GET /v1/auth/apple/callback` in
`http/auth.py`.

## How it works

- The web flow ("Sign in with Apple REST API") with a **Services ID** as the
  client. `response_mode=form_post`, scope `name email`, a fresh `state` and
  `nonce` per sign-in.
- Apple posts the result to `/v1/auth/apple/callback` from appleid.apple.com.
  That cross-site POST carries no SameSite=Lax cookies, so the POST decides
  nothing: it seals Apple's code (and the first-time name) into a two-minute
  encrypted cookie and redirects to the same address as a GET, where the normal
  checks run (transaction cookie, state, provider binding, consent).
- The server exchanges the code with a client secret it signs itself (ES256 JWT,
  five minutes, from the key below), then verifies Apple's identity token
  against Apple's published keys: issuer `https://appleid.apple.com`, audience =
  the Services ID, expiry, and the sign-in's nonce.
- Email: the token's `email` with `email_verified` true. "Hide My Email"
  addresses (`…@privaterelay.appleid.com`) are ordinary verified emails here;
  the account's address is the relay address.
- Name: Apple sends it only on the very first authorization; it fills an empty
  Sales Xray profile name, and is never asked for again.
- Account rules (the same as Google): Apple's `sub` is the identity key; a first
  Apple sign-in whose verified email matches an existing account links to it,
  unless that account's own email is unverified or it belongs to platform staff
  (owner, admin or support outside customer organisations), who must sign in
  with their password or an already linked Google. Email codes still never go to
  those accounts.
- Inside the phone apps the sign-in opens in the system browser (Android Custom
  Tab now; iPhone `ASWebAuthenticationSession` later) and returns by the app's
  deep link, the same contract as Google.

## Apple Developer setup (owner's account, one team)

1. **App ID** for the iPhone app (bundle ID, e.g.
   `com.authorityclosers.salesxray`) with the *Sign in with Apple* capability,
   enabled as a primary App ID.
2. **Services ID** for the web, grouped with that App ID, e.g.
   `com.authorityclosers.salesxray.web`. Configure *Sign in with Apple*:

   | | Domain | Return URL |
   | --- | --- | --- |
   | production | `salesxray.authorityclosers.com` | `https://salesxray.authorityclosers.com/v1/auth/apple/callback` |
   | staging | `salesxray-staging.authorityclosers.com` | `https://salesxray-staging.authorityclosers.com/v1/auth/apple/callback` |
   | dev | `salesxray-dev.authorityclosers.com` | `https://salesxray-dev.authorityclosers.com/v1/auth/apple/callback` |

   One Services ID can hold all three, or make one per environment (cleaner if
   staging or dev must ever be switched off alone).
3. **Key** with *Sign in with Apple* enabled, for that primary App ID. Download
   the `.p8` once (Apple never shows it again) and note its **Key ID**.
4. **Team ID** (Membership details).
5. **Email relay** (Certificates, Identifiers & Profiles → Services → Sign in
   with Apple for Email Communication): register the domain and the From address
   Sales Xray sends mail from (the environment's `AC_RESEND_FROM`), with SPF and
   DKIM passing. Without this, mail to `@privaterelay.appleid.com` addresses
   (sign-in codes, notices) is refused.

## Settings Sales Xray reads (Infisical, per environment)

| Name | Value |
| --- | --- |
| `AC_APPLE_SIGN_IN_SERVICE_ID` | the Services ID (the web client id) |
| `AC_APPLE_SIGN_IN_TEAM_ID` | the 10-character Team ID |
| `AC_APPLE_SIGN_IN_KEY_ID` | the 10-character Key ID |
| `AC_APPLE_SIGN_IN_PRIVATE_KEY` | the `.p8` file: PEM, PEM with `\n`, or base64 of the file |

Sign in with Apple shows on the sign-in screen only when all four exist and are
valid; anything missing or malformed keeps it off and never stops the API. Put
the key into Infisical straight from the downloaded file (stdin or the
dashboard), never through chat, tickets or logs. Staging and production may share the Services ID and key, or use their
own; dev must not hold the production key if they are separate.

## Hosts behind Cloudflare Access (dev, staging)

Apple's form_post is a cross-site POST, so a SameSite=Lax Access cookie is not
sent with it and Access would answer with its own login page. On a host behind
Access, add a **Bypass** policy for `POST /v1/auth/apple/callback` (it only
bounces Apple's answer; every check runs on the following GET, which carries the
Access cookie). Production is not behind Access.

## Dev check (needs an Apple ID)

1. Set the four settings for dev and restart the dev-live API.
2. `https://salesxray-dev.authorityclosers.com/login`: Continue with Apple is
   second, after Google.
3. Sign in with "Hide My Email": a new account with the relay address, the name
   filled in, back on the page you started from.
4. Sign in again: the same account, no new link.
5. An Apple ID whose email already has a Sales Xray account: linked and signed
   in; for a staff account the corner card says to sign in another way.
