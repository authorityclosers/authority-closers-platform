# Sign-in inside the Android app (Google and Facebook)

Owner, 23 Oct 2026: sign-in in the Sales X-Ray app must happen inside the app, not by
jumping out to Chrome.

- **Google:** Android's own account sheet (Credential Manager, "Sign in with Google").
  Nothing opens in a browser.
- **Facebook:** the Facebook SDK. With the Facebook app installed it switches to that
  app and back. Without it, Facebook's own sign-in sheet opens over Sales X-Ray and
  closes by itself. Meta allows no sign-in inside a web view, so that sheet is the
  only alternative.
- **Apple:** Apple has no Android sign-in, so it stays in the phone's browser.
- Email code and password are unchanged. The website keeps its usual flow.

An older app, or an environment whose settings below are missing, keeps signing in
through the phone's browser as before.

## How it works

1. The sign-in page sees the app (the `SXPhone` channel says `nativeSignIn`) and calls
   `POST /v1/auth/{google|facebook}/native/start` with the same fields as the
   browser start: action, completion flow, consent and age acknowledgement. The
   server issues the same sign-in transaction and cookie, and answers:
   - Google: `{state, nonce, client_id}`, where `client_id` is this environment's web
     client ID.
   - Facebook: `{state, nonce, app_id, client_token}`.
2. The page asks the app (`nativeSignIn`):
   - Google: the account sheet, for an ID token with that `client_id` as the server
     client ID and that nonce.
   - Facebook: Facebook's sign-in, for a user access token with `public_profile` and
     `email`.
3. The page posts `state` and the token to `POST /v1/auth/{provider}/native/finish`
   as a normal form, from the same origin. The server checks the token, then
   finishes exactly like the browser callback. It answers with a redirect to
   `/auth/complete`, the same results and the same session cookie.

What the server checks:

- **Google:** Google's signature, issuer, the audience (our web client ID), the
  transaction's nonce and a verified email. These are the same checks as the
  browser flow's ID token.
- **Facebook:** first `debug_token` with the app token. The token must be valid, a
  person's token, and issued to this environment's app. Then `/me` with
  `appsecret_proof`, which must be that same person.
- **Account rules:** unchanged from 19 Oct. Google links to an existing account by
  verified email. Facebook never links or joins by email. Platform staff are never
  linked.
- **No token is stored.** The app signs out of the Facebook SDK right after
  handing the token over.
- Settings → Connect stays a browser page. In the app it is refused, as before.

## Console entries (once per environment)

Fingerprints come from Play Console → Test and release → App integrity:

- "App signing key certificate": SHA-1, used by the Play app.
- "Upload key certificate": SHA-1. This is the durable key, which also signs the
  download-link app and the signed dev build.

Neither fingerprint is a secret.

### Google Cloud (OAuth clients → Create client → Android)

| Project                                          | Package                              | SHA-1                |
| ------------------------------------------------ | ------------------------------------ | -------------------- |
| 539905311435 (production and staging web client) | `com.authorityclosers.salesxray`     | Play app-signing key |
| 539905311435                                     | `com.authorityclosers.salesxray`     | upload (durable) key |
| 136376378344 (dev web client)                    | `com.authorityclosers.salesxray.dev` | upload (durable) key |

Each Android client holds one SHA-1, so production needs two. Nothing goes into
Infisical: the server keeps using the web client ID it already has, and Android
finds the Android client by package and signature.

### Meta for Developers

For the production app 1448624290545887 and the dev test app 1514054053884522:

1. **Settings → Basic → Add platform → Android.**
   - Package name: `com.authorityclosers.salesxray` for production,
     `com.authorityclosers.salesxray.dev` for dev.
   - Class name: `com.authorityclosers.salesxray.MainActivity`.
   - Key hashes: the base64 of each SHA-1 above. For production, both the Play
     app-signing key and the upload key; for dev, the upload key.
   - Turn on Single Sign On.
2. **Client token:** Settings → Advanced → Security → Client token. Store it in
   Infisical as `AC_FACEBOOK_LOGIN_CLIENT_TOKEN`: production `/application`, dev
   `/sales-xray-dev`, and dev-live's environment. It is made to be embedded in
   apps, but keep it in Infisical like every other setting.

Staging has no Android build, so the staging test app needs nothing.

Key hash from a SHA-1 (the colons are fine):

```bash
python -c "import base64,sys;print(base64.b64encode(bytes.fromhex(sys.argv[1].replace(':',''))).decode())" AA:BB:...
```

## Checking it

On a phone with the dev app (`com.authorityclosers.salesxray.dev`, signed with the
durable key):

- **Google:** tap Continue with Google. The account sheet slides up over Sales X-Ray;
  pick an account and you land signed in. No browser opens.
- **Facebook:** tap Continue with Facebook. The Facebook app opens (or Facebook's
  sheet) and comes back signed in.

Code: back end `http/auth.py` (native start and finish),
`identity_provider.py` and `identity_provider_facebook.py` (`verify_native_token`).
Web: `account-auth.tsx`. App: `NativeSignIn.java` in `authorityclosers/sales-xray-apps`.
