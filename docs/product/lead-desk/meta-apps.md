# Meta apps for Sales Xray: dev, staging and production

Owner order, 16 Oct 2026: lead ingestion, lead data back to Meta, WhatsApp and
Meta login must all work on dev, staging and production. This is the plan.

## Three apps, each with a dev and a staging copy

| App | Type | What it does | Permissions (use case) |
| --- | --- | --- | --- |
| **Sales Xray Leads** | Business | Leads from Facebook and Instagram Instant Forms arrive in the CRM (Page `leadgen` webhook). Lead stages go back to Meta (Conversions API for CRM) so ads find more good leads. Later: ad reporting. | Capture & manage ad leads: `leads_retrieval`, `pages_manage_ads`, `pages_read_engagement`, `pages_show_list`, `pages_manage_metadata`, `business_management`, `ads_read` (dataset for lead stages). Facebook Login for Business configuration. Webhooks: Page → `leadgen`. |
| **Sales Xray Messaging** (Meta allows no "WhatsApp" in app names) | Business | A customer connects their WhatsApp number to the CRM (Embedded Signup) and talks to leads there; AC's own number too. Also the Page's Messenger and Instagram conversations and comment replies (Phase C, `instagram-messenger-app.md`). | WhatsApp use case: `whatsapp_business_management`, `whatsapp_business_messaging`. Login for Business configuration for Embedded Signup. Webhook: `whatsapp_business_account`. Messenger and Instagram: see `instagram-messenger-app.md`. Details: `whatsapp-app.md`. |
| **Sales Xray Sign-in** | Consumer | "Continue with Facebook" sign-in to Sales Xray. | Facebook Login: `public_profile`, `email`. |

Why three:

- Meta has two app types; consumer sign-in and business tools can't share one
  app, and an app's type can never change.
- WhatsApp needs its own Tech Provider review, message rules and quality rating.
  Kept apart, a WhatsApp restriction can't switch off lead capture.

Why a copy per environment: a webhook has one callback address per app, so dev,
staging and production each need their own App ID. Meta's **test apps** fit:
made from the parent in one click, they copy its settings, have their own ID
and secret, always stay in development mode (only people with a role on the
app can use them), and a parent can have up to 50.

| | dev | staging | production |
| --- | --- | --- | --- |
| App | test app "… (dev)" | test app "… (staging)" | the parent app |
| Return address | `https://salesxray-dev.authorityclosers.com/v1/lead-desk/meta/callback` | `https://salesxray-staging.authorityclosers.com/v1/lead-desk/meta/callback` | `https://salesxray.authorityclosers.com/v1/lead-desk/meta/callback` |
| Lead webhook | same host, `/v1/lead-desk/meta/webhook` | same | same |
| Who can connect | people with a role on the app | same | any business, after Advanced Access |
| Infisical | `dev` `/sales-xray-dev` | `staging` `/application` | `prod` `/application` |

## Created 16 Oct 2026 (Authority Closers portfolio 1027309697060163)

| | App | App ID | Login configuration |
| --- | --- | --- | --- |
| production | Sales Xray Leads (parent, unpublished) | 29252912124316608 | not yet (needs the owner's go-ahead) |
| staging | Sales Xray Leads - staging (test app) | 1864458368324359 | 1132781386071692 |
| dev | Sales Xray Leads - dev (test app) | 1092841566696886 | 1098608695872724 |

Use case: Capture & manage ad leads, plus `pages_manage_metadata`. Each
configuration is a user access token with eight permissions: `ads_management`,
`ads_read`, `business_management`, `leads_retrieval`, `pages_manage_ads`,
`pages_manage_metadata`, `pages_read_engagement`, `pages_show_list`. Return
addresses are saved for dev and staging. Test Page "Sales Xray Test Leads"
(1326368220570095) has the Instant Form "Sales Xray test - enquiry" (email,
full name, phone).

## Settings the CRM reads (Leads app)

`AC_META_APP_ID`, `AC_META_APP_SECRET`, `AC_META_LOGIN_CONFIG_ID`,
`AC_META_WEBHOOK_VERIFY_TOKEN`, `AC_LEAD_DESK_TOKEN_KEY` (seals Page tokens),
optional `AC_META_GRAPH_VERSION` (default v23.0). The connector stays off until
all five exist.

Dev, 16 Oct: `AC_META_WEBHOOK_VERIFY_TOKEN` (sha256 214d92c9cc4c) and
`AC_LEAD_DESK_TOKEN_KEY` (sha256 1d189bf4bf23) are in Infisical and dev-live.
App ID, login configuration ID and App Secret follow once the app exists.

Before staging/production: `infra/application/compose.yaml` lists every API
variable explicitly, so these five must be added there (and to
`infra/application/SECRETS.md`) and shipped through `ac-ship` on the owner's word.

## Secrets without anyone seeing them

- Laptop: `~/.ac/bin/ac-secret.ps1 NAME dev|staging|prod`. It takes the value
  from the clipboard (the provider's Copy button) or generates one
  (`-Generate token|key`). It writes Infisical through the laptop's Infisical
  login using a file only this Windows user can read, deleted at once. For dev
  it also pipes the value to the server, and `-Restart` reloads the dev API.
  It prints only a 12-character fingerprint and clears the clipboard.
- Server: `/usr/local/sbin/ac-secret-drop NAME dev` takes the value on stdin
  and writes the dev-live API env (backed up). It logs only the name and
  fingerprint to `/var/log/ac-secret-drop.log`. The server's Infisical identity
  is read-only (HTTP 403), so the Infisical record is written from the laptop.
  A write-scoped identity would let server agents do the whole job.
- Meta asks for the account password before it shows an App Secret. That one
  step stays with the owner: reveal → Copy → run the command.

## Test assets (Authority Closers portfolio)

- Facebook Page "Sales Xray Test Leads", unpublished, plus a second Page for
  multi-Page tests.
- Instant Forms on it, e.g. a Hindi/English enquiry with name, phone, email,
  city and two custom questions.
- Test leads from Meta's Lead Ads Testing Tool or `POST /{form-id}/test_leads`.
- WhatsApp: Meta's free test number in the WhatsApp app (up to 5 recipients).
- A test dataset (pixel) for lead stages going back to Meta.

## Owner-only steps

1. Sign in to Meta once in the browser the agent uses.
2. Reveal each App Secret (Meta asks for the password), press Copy and run the
   `ac-secret.ps1` command.
3. Business Verification of Authority Closers: company documents, website
   domain and phone. It is needed before Advanced Access (other companies'
   Pages) and the WhatsApp Tech Provider review.
4. Privacy policy, terms and data-deletion pages on authorityclosers.com
   (required for review and for Sign-in going live).
5. Cloudflare Access: salesxray-dev (and staging) sit behind Access, so Meta
   cannot reach the webhook. Add an Access bypass for
   `/v1/lead-desk/meta/webhook` (and `/v1/lead-desk/capture/*` for Google Ads
   and website forms). The Meta return address needs no bypass: the signed-in
   person's browser makes that request. Until then, connecting a Page still
   files its last week of leads at once and the rest Meta keeps (90 days) in
   the background, and the 10-minute pull reads new ones.

## Order

1. Leads app → dev test app → Continue with Meta on /leads, a test lead arrives.
2. Staging test app, after the compose change ships.
3. Business Verification, then App Review for the Leads parent app (production).
4. WhatsApp app (Embedded Signup, test number), then the Sign-in app.

## AI connectors from Meta

- **Meta Ads MCP** (official, `https://mcp.facebook.com/ads`): reporting,
  campaigns, audiences and dataset signal health. Add it in Claude → Settings →
  Connectors → Add custom connector, then sign in with Facebook. It cannot
  create apps, Pages or forms.
- **WhatsApp Business Tools MCP** (Meta, released 15 Sep 2026): business
  account, numbers, templates, webhooks. Its address still has to be read from
  Meta's WhatsApp docs.
