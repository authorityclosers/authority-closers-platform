# Pulse ↔ Sales X-Ray: identity, org link and profile sync (contract)

Status: draft for agreement, 25 Oct 2026. Sales X-Ray side: the AC sign-in
session. Pulse side: the EA Pulse card for this contract.
Product design: `docs/product/roles-owner-profile-pulse.md`, section 3.

Both apps are the owner's. Code patterns may be shared, but data and secrets stay
with each company, and nothing is set up by hand per customer.

## 0. Words

- **Pulse issuer:** one Pulse install's base URL, e.g.
  `https://pulse.authorityclosers.com`. Under the federation plan each org may
  run its own; Sales X-Ray keeps a list of trusted issuers per environment.
- **sub:** the stable Pulse person id, unique within an issuer, never reused.
- **Pulse org id:** stable within an issuer.

## 1. Pulse as an OpenID Connect provider (sign-in)

Pulse serves these documents and endpoints:

| What | Where |
|---|---|
| Discovery | `GET /.well-known/openid-configuration` (OIDC Discovery 1.0) |
| Authorize | `GET /oauth/authorize`: code flow; PKCE S256 required; `state` and `nonce` honoured |
| Token | `POST /oauth/token`: `authorization_code` and `refresh_token`; client auth `client_secret_basic` |
| User info | `GET /oauth/userinfo` (bearer access token) |
| Keys | `GET /oauth/jwks`; ID tokens are signed RS256 or ES256 with a `kid`, rotated with overlap |
| Revoke | `POST /oauth/revoke` (RFC 7009) |
| Registration | Pulse registers Sales X-Ray once per environment: dev, staging and production redirect URIs from the sign-in session. The secret goes into each side's secret store, never into chat or git |

**Scopes:**

| Scope | Gives |
|---|---|
| `openid` | `sub` |
| `profile` | `name`, `given_name`, `family_name`, `picture`, `updated_at`, `preferred_username` |
| `email` | `email`, `email_verified`. Sales X-Ray links accounts only on a verified email |
| `pulse.orgs` | `pulse_orgs`: `[{ "id", "name", "role" }]`, the person's active Pulse orgs |

**ID token:**
- Contains `iss`, `aud` (Sales X-Ray's client id), `exp` (at most 10 minutes),
  `iat`, `nonce`, `sub`, and the profile and email claims granted.

**`picture`:**
- An HTTPS URL that Sales X-Ray may fetch without a token for 24 hours.
- It **changes whenever the photo changes**, for example
  `.../people/{sub}/photo?v={sha256-prefix}`.
- JPEG, PNG or WebP, at most 2 MB.

## 2. Org link

A Sales X-Ray Owner or Admin connects their organisation to a Pulse org:

1. Sales X-Ray starts an authorize request with scopes
   `openid pulse.org.read pulse.org.webhooks` (plus `pulse.signals.write` if
   they turn signals on later). It also sends `pulse_org_hint` when known.
2. Pulse shows a consent screen to a **Pulse org admin** of that org: "Sales
   X-Ray (Authority Closers) wants to read your members' names, photos, titles
   and teams, and to be told when they change."
3. The token response adds `pulse_org_id`. The refresh token belongs to the
   **link**, not the person. Pulse keeps it valid while the link lives, even if
   the approving admin leaves.

**API**, bearer = the link's access token; JSON; cursor paging:

| Method and path | Answer |
|---|---|
| `GET /api/v1/orgs/{org_id}/members?updated_since=&cursor=` | `{ "members": [Member], "next_cursor": … }` |
| `GET /api/v1/orgs/{org_id}/members/{sub}` | `Member` |
| `POST /api/v1/orgs/{org_id}/webhooks` `{ "url", "events": [...] }` | `{ "id", "secret" }`; the secret is shown once |
| `DELETE /api/v1/orgs/{org_id}/webhooks/{id}` | 204 |
| `DELETE /api/v1/orgs/{org_id}/link` | 204: either side ends the link |

```json
Member = {
  "sub": "…", "email": "…", "email_verified": true,
  "name": "…", "title": "Sales manager", "team": "Inside sales",
  "picture": "https://…/photo?v=3f9c…", "role": "member",
  "status": "active", "updated_at": "2026-10-25T12:00:00Z"
}
```

## 3. Webhooks (Pulse → Sales X-Ray)

- **Where:** `POST https://<sales-xray>/v1/integrations/pulse/webhook`.
- **Headers:** `X-Pulse-Event-Id` (UUID), `X-Pulse-Event` (type) and
  `X-Pulse-Signature: t=<unix>,v1=<hex HMAC-SHA256 of "t.body">`. Pulse signs
  with the webhook secret.
- **Sales X-Ray refuses** anything older than 5 minutes or with a bad signature.
- **Events:**
  - `person.updated` (fields changed);
  - `person.photo_updated`;
  - `membership.added`, `membership.removed`, `membership.role_changed`;
  - `link.revoked`.
- **Body:** `{ "event_id", "type", "org_id", "sub", "occurred_at", "changed": ["name", "picture", ...] }`.
  No profile values are sent.
- **Sales X-Ray answers** 2xx within 5 seconds and then **fetches the member**
  from the API. A payload never writes data by itself.
- **Pulse retries** with backoff for 24 hours. Events may arrive twice or out of
  order; `updated_at` decides.

## 4. Work signals (Sales X-Ray → Pulse)

Only with `pulse.signals.write` and only the kinds the Sales X-Ray org switched
on (all off by default):

- `POST /api/v1/orgs/{org_id}/signals`
  `{ "items": [{ "sub", "kind", "day", "value" }] }`.
- **Kinds:** `calls_analysed`, `leads_worked`, `follow_ups_done`, `talk_minutes`.
  Counts per person per day.
- **Idempotent** on (`sub`, `kind`, `day`): the latest value wins.
- **Never sent:** call content, transcripts, reports, scores, lead names or
  contact details.

## 5. Security and audit

- PKCE and `state` on every authorize; exact redirect URI match;
  `nonce` checked.
- No Sales X-Ray data goes to Pulse without the org switch, and no Pulse
  profile comes to Sales X-Ray without the org link.
- Either side can end the link at once. Both sides audit link, unlink, webhook
  changes and signal switches (who, when; never values).
- Tokens and webhook secrets are stored sealed: in Sales X-Ray,
  `integration_secrets` with AES-GCM.

## 6. What Sales X-Ray builds against this

1. A "Sign in with Pulse" button through a generic OIDC provider module
   (discovery, PKCE, ID token checks). It uses the same identity path as
   Google: a verified email links, a new person consents.
2. Organisation → Integrations → "Connect your Pulse org": the link, the first
   member sync, and matching by `sub` or verified email.
3. The webhook receiver, with pull-on-push sync of photo, name, title and team.
   A photo uploaded in Sales X-Ray wins over Pulse.
4. The signal switches and a daily sender.
