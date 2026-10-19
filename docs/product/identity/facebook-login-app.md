# Continue with Facebook: the "Sales Xray Sign-in" Meta app

Owner order, 19 Oct 2026: Sales Xray offers every common sign-in (Google, Apple,
Facebook, email code, password), generic for every user. This page is what the
Meta dashboard needs for **Continue with Facebook**. The code is in
`packages/python/ac_platform/http/identity_provider_facebook.py`; the routes are
`/v1/auth/facebook/start` and `/v1/auth/facebook/callback` in `http/auth.py`.

## How it works (for the dashboard and the reviewer)

- A plain redirect, no Facebook JavaScript SDK in the page, so the Content
  Security Policy is unchanged. The browser goes to Facebook's login dialog and
  comes back to Sales Xray's callback with a one-time code.
- The server exchanges the code with the app secret and the sign-in's PKCE
  verifier (S256), then reads `id,name,first_name,last_name,email` from
  `/me` with `appsecret_proof`. No Facebook token is stored or sent to the
  browser.
- Permissions: `public_profile` and `email`, nothing else.
- Account rules:
  - Facebook's person id (app-scoped) is the identity key.
  - A first Facebook sign-in whose email already belongs to a Sales Xray account
    is **not** linked to it: Meta gives no "email verified" flag, so the person
    is told to sign in the way they did before. New emails get a new account.
  - Facebook sign-in never joins an organisation by email domain or invite on
    its own.
  - No email from Facebook (phone-only account, or email declined): sign-in stops
    with "Facebook didn't share your email address".
- Inside the Sales Xray phone app, the sign-in opens in the phone's browser
  (Custom Tab, never the Facebook app) and returns to the app by its deep link.

## Apps (Authority Closers portfolio)

| | App | App ID | Mode |
| --- | --- | --- | --- |
| production | **Sales Xray Sign-in** (consumer, Facebook Login use case) | 1448624290545887 | development until App Review passes |
| staging | test app "Sales Xray Sign-in - staging" | (make from the parent) | always development |
| dev | test app "Sales Xray Sign-in - dev" | (make from the parent) | always development |

Test apps copy the parent's settings and have their own ID and secret; only
people with a role on the app can sign in with them.

## Facebook Login settings, per app

Facebook Login → Settings:

| Setting | Value |
| --- | --- |
| Client OAuth login | Yes |
| Web OAuth login | Yes |
| Enforce HTTPS | Yes |
| Use Strict Mode for redirect URIs | Yes |
| Embedded browser OAuth login | No |
| Login with the JavaScript SDK | No |
| Login from devices | No |

Valid OAuth Redirect URIs (exactly one per app):

| App | Valid OAuth Redirect URI |
| --- | --- |
| production | `https://salesxray.authorityclosers.com/v1/auth/facebook/callback` |
| staging | `https://salesxray-staging.authorityclosers.com/v1/auth/facebook/callback` |
| dev | `https://salesxray-dev.authorityclosers.com/v1/auth/facebook/callback` |

Basic settings (filled on the parent, 19 Oct): App domain
`salesxray.authorityclosers.com`, privacy, terms and data-deletion URLs. Each
test app needs its own host as App domain (`salesxray-staging…`,
`salesxray-dev…`).

### Data deletion

Use the **Data deletion instructions URL**
`https://salesxray.authorityclosers.com/data-deletion`; no callback is needed.
Sales Xray keeps only the Facebook person id, the email and the name it used to
make the account, and deletes them with the account on request.

Proposed paragraph for the data-deletion page (owner to approve the wording; not
yet on the page):

> **If you signed in with Facebook.** We keep only your Facebook person id and the
> name and email Facebook shared, to sign you in. Ask for your account to be
> deleted as above and they go with it. To remove Sales Xray at Facebook too,
> open Facebook Settings, then Apps and websites, and remove Sales Xray Sign-in.

A Data Deletion Request **callback** (Meta posts a `signed_request`, we answer
with a status link and confirmation code) is not built. It is only needed if
Meta's review asks for it instead of the instructions page.

## Settings Sales Xray reads (Infisical, per environment)

| Name | Value |
| --- | --- |
| `AC_FACEBOOK_LOGIN_APP_ID` | that environment's App ID (numeric) |
| `AC_FACEBOOK_LOGIN_APP_SECRET` | that app's App Secret |
| `AC_FACEBOOK_LOGIN_GRAPH_VERSION` | optional, default `v23.0` |

Continue with Facebook shows on the sign-in screen only when the first two exist
and are valid; anything missing or malformed keeps it off and never stops the
API. Staging and production keep separate secrets; a production secret never
goes into dev. Folders: dev `/sales-xray-dev`, staging and production
`/application` (as for the Leads app, `docs/product/lead-desk/meta-apps.md`).

## App Review

`public_profile` and `email` need Advanced Access before people without a role
on the app can sign in.

**How we use it** (for each permission):

- `public_profile`: "Sales Xray uses the person's Facebook id to sign them in to
  their Sales Xray account, and their name to fill in the name on a new
  account's profile. We don't post, read friends or read anything else."
- `email`: "The email address is the address of the person's Sales Xray account:
  we send their sign-in and account emails there, and it shows in their
  profile. It is never shared with other users or businesses, and a Facebook
  email is never used to sign in to an account someone made another way."

**Screencast plan** (about 90 seconds, production app, a reviewer test user):

1. Open `https://salesxray.authorityclosers.com/login` in a desktop browser.
2. Show the Terms and Privacy links, tick the box, click **Continue with
   Facebook**.
3. Facebook's dialog lists `public_profile` and `email`; continue.
4. Back in Sales Xray: the new account's dashboard; open the profile and show the
   name and email that came from Facebook.
5. Log out; open the data-deletion page and show the Facebook paragraph.
6. Optional: the same on a phone in the Sales Xray app (opens the phone's
   browser, comes back to the app).

Reviewer access: the reviewer signs in with their own Facebook test user; no
Sales Xray password is needed. Steps for the reviewer note: "Open
https://salesxray.authorityclosers.com/login, tick the Terms box, press Continue
with Facebook."

## Dev check (needs a person with a role on the dev test app)

1. Set `AC_FACEBOOK_LOGIN_APP_ID` and `AC_FACEBOOK_LOGIN_APP_SECRET` for dev
   (Infisical `/sales-xray-dev`, then the dev-live API environment).
2. `https://salesxray-dev.authorityclosers.com/login`: the order is Google,
   Apple (when configured), Facebook, then email.
3. Continue with Facebook with a new email: a new account, back on the page you
   started from.
4. Again with an email that already has an account: the corner card says that
   email already has an account, and nothing is linked.
