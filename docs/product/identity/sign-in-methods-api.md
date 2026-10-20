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
  "available": [
    {"kind": "google", "label": "Google", "connected": true},
    {"kind": "facebook", "label": "Facebook", "connected": false}
  ],
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
- `available` is the Connect list: only the providers configured here, in sign-in
  order (Google, Apple, Facebook), with their label and whether this account has
  one. A provider that is not configured is left out.
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

## Connect: `POST /v1/me/sign-in-methods/{google|apple|facebook}/connect`

Same-origin `fetch` (the browser sends `Origin`), then a full-page redirect to the
provider. Never a pop-up.

```ts
const answer = await fetch(`/v1/me/sign-in-methods/${provider}/connect`, {
  method: "POST",
  credentials: "same-origin",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ return_to: "/#settings/security" }),
});
if (answer.ok) {
  const { redirect_url } = await answer.json();
  window.location.assign(redirect_url); // the answer also set the sign-in cookie
} else {
  const { code } = await answer.json(); // see the table
}
```

`return_to` is where the provider sends the person back: a Sales Xray page path
(`/` or up to six segments of letters, digits, `-` and `_`; not `/v1/…` or
`/auth/…`; no query), optionally with the Settings dialog's hash, `#settings` or
`#settings/<section>`. So both `/#settings/security` and `/settings/security` work.

| Answer | Meaning |
| --- | --- |
| `200 {"redirect_url": "https://…"}` | go there with `window.location.assign` |
| `401 {"detail", "code": "sign_in"}` | not signed in |
| `403 {"detail", "code": "fresh_sign_in"}` | the session is older than `fresh_minutes`; ask the person to sign out and in again, then connect |
| `403 {"detail", "code": "origin"}` | not sent from a Sales Xray page |
| `403 {"detail", "code": "staff_key"}` | staff keys can't connect |
| `404 {"detail", "code": "not_configured"}` | that provider isn't offered here |
| `409 {"detail", "code": "already_connected"}` | this account already has it |
| `409 {"detail", "code": "app_not_supported"}` | from inside the phone app (see below) |
| `422 {"detail", "code": "return_to"}` | `return_to` is not an allowed page |

`detail` is a sentence to show as it is. Nothing is started when the answer is not 200.

### Coming back

The provider returns to the server, which links and then sends the page back to
`return_to` with one query value, placed before the hash:

| Back at | Meaning | Suggested corner card |
| --- | --- | --- |
| `/?connected=facebook#settings/security` | connected | "Facebook is connected. You can now sign in with Facebook." |
| `/?connect_error=in_use#settings/security` | that provider account belongs to another Sales Xray account | "That Facebook account is already used by another Sales Xray account." |
| `/?connect_error=cancelled#settings/security` | the person stopped at the provider | "Facebook wasn't connected." |
| `/?connect_error=failed#settings/security` | anything else (signed out meanwhile, provider error) | "Couldn't connect Facebook. Try again." |

On mount, read `connected` or `connect_error` from `location.search`, show the card,
reload the list, then remove the query with `history.replaceState` so a reload does
not show it again.

Rules the server keeps:

- The provider's email may differ from the account's; Facebook is allowed. No email
  match is involved because the person is already signed in.
- A provider account already on another Sales Xray account is never moved
  (`connect_error=in_use`); nothing is written.
- Each new connection writes `identity.provider_connected.v1` (provider, account,
  time, client address) and emails the account. Connecting the same provider again
  changes nothing and sends nothing.
- The session stays the same; no new session is issued.

**Not inside the phone app.** The app opens provider pages in the phone's browser,
which holds no Sales Xray session, so the server answers `409 app_not_supported`. In
the app (`inPhoneApp()` from `app/leads/native-phone.ts`), hide Connect or say
"Connect from a computer or your phone's browser".

The older client helper `connectProvider()` in `app/account-auth-client.ts`
(`GET /v1/auth/{provider}/start?action=link`, back through `/auth/complete`) still
works but is not needed with the POST above.
