# Sign-in methods in Settings: the API for the Settings pages

For whoever builds Settings (owner, 20 Oct 2026: "add a connect google account, connect
facebook account … inside the settings"). The back end and a small client live in
the sign-in code; the Settings screens use only what is below. A plain version of
the screen already exists in `app/sign-in-methods.tsx` (Settings → Security) and may
be replaced.

## Read: `GET /v1/me/sign-in-methods`

Signed-in Sales Xray session (cookie), Sales Xray host only, `private, no-store`.

```json
{
  "methods": [
    {"kind": "email_code", "added_at": null, "last_used_at": null, "removable": false},
    {"kind": "password", "added_at": "2026-09-01T10:00:00+00:00", "last_used_at": null, "removable": false},
    {"kind": "google", "added_at": "2026-10-01T10:00:00+00:00", "last_used_at": "2026-10-18T09:00:00+00:00", "removable": true}
  ],
  "providers": {
    "google": {"linked": true, "can_connect": false},
    "apple": {"linked": false, "can_connect": false},
    "facebook": {"linked": false, "can_connect": true}
  },
  "fresh_sign_in": true,
  "fresh_minutes": 10
}
```

- `methods` lists only what this account has, in this order: email code, password,
  Google, Apple, Facebook.
- `email_code` appears only when codes are really sent to this account. Platform
  staff (owner, admin or support outside customer organisations) never get them.
- `removable` is true only for a provider, and only when another way in remains.
- `providers.*.can_connect` means the provider is configured in this environment
  and not yet on the account. Show a Connect button only when it is true.
- `fresh_sign_in`: this session started in the last `fresh_minutes`. Remove and
  Connect need it. Otherwise ask the person to sign out and in again first.

## Remove: `POST /v1/me/sign-in-methods/{google|apple|facebook}/remove`

Same-origin `fetch` (the browser sends `Origin`). Staff keys are refused.

| Answer | Meaning |
| --- | --- |
| `200 {"removed": "google"}` | removed; the account is emailed; reload the list |
| `409 {"detail": {"code": "fresh_sign_in", "message": …}}` | sign in again first |
| `409 {"detail": {"code": "last_method", "message": …}}` | it is the only way in |
| `404 {"detail": {"code": "not_found", …}}` | not on this account |

## Connect: a page redirect, not a fetch

Use the helper in `app/account-auth-client.ts`:

```ts
import {
  connectOutcome,
  connectProvider,
  forgetSignInResult,
  readSignInResult,
} from "../account-auth-client";

// On the button: the whole page goes to the provider and comes back here.
connectProvider("facebook");

// When the Settings page mounts (read first, forget once shown: dev runs effects twice):
const returned = readSignInResult();
if (returned) {
  forgetSignInResult();
  const { tone, message } = connectOutcome(returned.result, returned.provider);
  // show `message` as a corner card (tone "success" or "error"), then reload the list
}
```

What happens:

1. `connectProvider` keeps the current page, including a `#settings/…` hash, for
   this tab. It then goes to `/v1/auth/{provider}/start?action=link&surface=sales_xray&return_path=/auth/complete?flow=<uuid>`.
2. The server checks the session (fresh, not a staff key) and goes to the provider.
3. It comes back through `/auth/complete`, which returns to the kept page with one
   of these results:

| Result | `connectOutcome` says |
| --- | --- |
| `linked` | "Facebook is connected. You can now sign in with Facebook." |
| `already_linked` | "That Facebook account is already used by another Sales Xray account." |
| `fresh_sign_in` | "For your safety, sign out and sign in again, then connect Facebook within 10 minutes." |
| `unavailable` / `failed` | try-again wording |

Rules the server keeps:

- The provider's email may differ from the account's; Facebook is allowed. No email
  match is involved because the person is already signed in.
- Each new connection writes `identity.provider_connected.v1` (provider, account,
  time, client address) and emails the account. Connecting the same provider again
  changes nothing and sends nothing.
- The session stays the same; no new session is issued.

**Not inside the phone app.** The app opens provider pages in the phone's browser,
which holds no Sales Xray session. In the app (`inPhoneApp()` from
`app/leads/native-phone.ts`), hide Connect or say "Connect from a computer". The
server answers `failed` if it is tried from there.
