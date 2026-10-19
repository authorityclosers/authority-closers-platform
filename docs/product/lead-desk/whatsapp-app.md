# Sales Xray Messaging (WhatsApp): what Meta's dashboard needs

Phase B of the Meta integration (orchestrator brief, 19 Oct 2026): a WhatsApp channel
in the Sales Xray CRM. The app is **"Sales Xray Messaging"**: Meta does not allow
"WhatsApp" in an app's name (orchestrator, 19 Oct). The same app also carries
Instagram and Messenger conversations (Phase C, `instagram-messenger-app.md`). Each customer organisation connects **its own** WhatsApp number
in Settings → Integrations with Meta's Embedded Signup, and pays Meta directly for its
messages. Nothing here is named after a customer.

This page lists exactly what has to be set up in Meta's App Dashboard. The Lead Desk
session does **not** create or change Meta apps; the orchestrator does it with the
owner's OK and records each ID here. Secrets go only into Infisical (never chat or git).

Sources (Meta developer docs, read 19 Oct 2026): Embedded Signup overview and
implementation, Tech Provider onboarding, webhooks overview, messages and status
webhook references, template management, pricing. Items marked **check** could not be
confirmed from the docs and must be read off the dashboard while setting up.

## 1. A separate Business app

Why separate from "Sales Xray Leads": WhatsApp has its own Tech Provider review,
message rules and quality rating; kept apart, a WhatsApp restriction can't switch off
lead capture (see `meta-apps.md`).

| | App | Type | Where |
| --- | --- | --- | --- |
| production | **Sales Xray Messaging** (parent), app ID **856472050863115** | Business | Authority Closers portfolio 1027309697060163 |
| staging | Sales Xray Messaging - staging (test app), app ID **1991172831554212** | from the parent | same |
| dev | Sales Xray Messaging - dev (test app), app ID **1116775534070252** | from the parent | same |

The settings keep their `AC_WHATSAPP_*` names (section 5): they are this app's.

Created by the orchestrator on 19 Oct 2026 with three use cases (WhatsApp, Messenger,
Instagram), in development mode; basic settings filled (privacy, terms and data-deletion
URLs, domain salesxray.authorityclosers.com, category Business, contact admin@). Still
to do there: the icon, the dev and staging test apps, the Embedded Signup and the
Messenger and Instagram login configurations, the app secret into Infisical, the
verify token and the webhooks.

Business verification of Authority Closers is done (16 Oct), which the Tech Provider
steps need.

## 2. Use case and products

- Use case: **Connect with customers through WhatsApp** (WhatsApp Business Platform,
  Cloud API).
- App settings → Basic: privacy policy, terms and data-deletion URLs on
  authorityclosers.com (the same pages as the Leads app), app icon, category
  "Business and pages", contact email admin@authorityclosers.com.

## 3. Facebook Login for Business configuration (Embedded Signup)

One configuration per app (parent, staging, dev):

- Login variation: **WhatsApp Embedded Signup** (the dashboard template "WhatsApp
  Embedded Signup Configuration With 60 Expiration Token" or the system-user one;
  **check** which token types the dashboard offers, and prefer a **system user**
  access token that never expires).
- Products: WhatsApp Cloud API (Embedded Signup v4 picks products in the
  configuration).
- Assets: WhatsApp accounts (and the phone numbers in them).
- Permissions: `whatsapp_business_management`, `whatsapp_business_messaging`.
  `business_management` only if the dashboard requires it.
- Configuration IDs (orchestrator, 19 Oct; the "60-day expiry token" template with a
  system-user token, `whatsapp_business_management` + `whatsapp_business_messaging`):
  dev **1681184823523717**, staging **1646520163493469**, production
  **1423452606610966** (`AC_WHATSAPP_CONFIG_ID`).

Sales Xray opens Embedded Signup **by redirect**, the same way as Continue with Meta for
leads: no Meta JavaScript SDK on our pages, so the site's content-security policy stays
as it is. After signup, Sales Xray swaps the code with the same return address, reads
the shared WhatsApp accounts from the token (`debug_token` granular scopes) and
connects each number in them.

Facebook Login for Business → Settings, per app:

- Valid OAuth redirect URI:
  `https://salesxray.authorityclosers.com/v1/lead-desk/whatsapp/callback`
  (staging: `salesxray-staging…`, dev: `salesxray-dev…`, each on its own app). The
  person's browser makes this request, so it needs no Cloudflare Access bypass.
- **Check** whether Embedded Signup v4 in this account allows the redirect flow; if the
  dashboard insists on the JavaScript SDK, the site's CSP needs
  `script-src https://connect.facebook.net` and `frame-src https://www.facebook.com`
  (an edge change through Align 3), and the page path `POST /v1/lead-desk/whatsapp/connect`
  (code + account + number ids) is already built for it.

## 4. Webhook

Products → WhatsApp → Configuration → Webhook, per app:

- Callback URL: `https://<host>/v1/lead-desk/whatsapp/webhook` on staging and production.
  **Dev uses the alias `https://salesxray-dev.authorityclosers.com/v1/lead-desk/meta/webhook/whatsapp`**
  (the same handler and checks): it sits under the Leads webhook's Cloudflare Access
  bypass, so it works without a new bypass.
- Verify token: a new random value, `AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN` in Infisical.
- Object `whatsapp_business_account`, fields:
  - `messages` (incoming messages and delivery statuses)
  - `message_template_status_update`, `message_template_quality_update`,
    `template_category_update` (template review and quality)
  - `phone_number_quality_update`, `account_update` (number rating, account bans)
- Each customer's account is subscribed by Sales Xray itself after Embedded Signup
  (`POST /{waba_id}/subscribed_apps`); nothing per customer in the dashboard.
- Dev and staging sit behind Cloudflare Access: add an Access bypass for
  `/v1/lead-desk/whatsapp/webhook`, like the Leads webhook.

## 5. Settings the CRM will read (Infisical, per environment)

| Name | What |
| --- | --- |
| `AC_WHATSAPP_APP_ID` | the app's ID (parent for production, test app for dev/staging) |
| `AC_WHATSAPP_APP_SECRET` | the app secret (owner reveals it; `ac-secret.ps1`) |
| `AC_WHATSAPP_CONFIG_ID` | the Embedded Signup configuration ID |
| `AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN` | generated (`ac-secret.ps1 -Generate token`) |
| `AC_WHATSAPP_GRAPH_VERSION` | optional, default the same as the Leads app |

Customer tokens are sealed in the database with the existing
`AC_LEAD_DESK_TOKEN_KEY`; no secret per customer anywhere else. The channel stays
off until all four exist. For staging and production the names must also be added to
`infra/application/compose.yaml` and `infra/application/SECRETS.md` (a release change
through Align 3).

## 6. Tech Provider and App Review (production only)

1. Become a Tech Provider for the app (WhatsApp → Quickstart in the dashboard).
2. App Review, Advanced Access for `whatsapp_business_messaging` and
   `whatsapp_business_management`, with the two screencasts Meta asks for:
   sending a message from Sales Xray, and creating a message template from Sales
   Xray. Recorded on staging once Phase B is there.
3. Access verification, after which onboarding grows from 10 new customers a week to
   200.

Until then only people with a role on the app can connect a number (same as Leads).

## 7. Testing

- Dev and staging use Meta's free **test number** in each test app (up to 5
  recipient numbers, added in the dashboard). Recipients: only our own team phones.
- No real customer conversations on dev.

## 8. Dev: ready for the values (checked 19 Oct, 15:50Z)

The code is on dev (`ac-dev-live-api` serves 0de9566d). The channel switches on the
moment the four settings exist; nothing else in Sales Xray changes.

1. On `ac` (root), each value from stdin, never on screen:
   `<value> | ac-secret-drop AC_WHATSAPP_APP_ID dev`, then `AC_WHATSAPP_CONFIG_ID`,
   `AC_WHATSAPP_APP_SECRET`, and last `AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN dev --restart`
   (the restart makes the dev API read them). `AC_LEAD_DESK_TOKEN_KEY` is already there.
2. Check, signed in to dev as an owner: Settings → Integrations shows WhatsApp with
   **Connect WhatsApp**. On the server:
   `curl -s 'http://127.0.0.1:8101/v1/lead-desk/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=42'`
   answers `42` (a wrong token answers 403).
3. **Webhook on dev:** Meta posts to the alias
   `/v1/lead-desk/meta/webhook/whatsapp`, which sits under the Leads webhook's
   Cloudflare Access bypass (the canonical `/v1/lead-desk/whatsapp/webhook` still goes
   to the Access sign-in on dev). Staging and production use the canonical path.
4. In the dev test app (Meta dashboard): redirect URI
   `https://salesxray-dev.authorityclosers.com/v1/lead-desk/whatsapp/callback`, the
   webhook above with the verify token and the fields in section 4, and our team
   phones as test recipients.
5. Connect: Settings → Integrations → Connect WhatsApp → Embedded Signup. **Check**
   that Embedded Signup lists the test app's own test account and number; if it
   doesn't, the number is connected once with the dashboard's temporary token instead
   (a dev-only step, asked for then).

Then the two review screencasts, on dev with the test number:

- **Send a message** (`whatsapp_business_messaging`): a test phone writes to the
  test number → the lead appears in Leads with the conversation → the seller replies
  in the lead's conversation → the reply arrives on the phone (shown side by side) →
  the status ticks to delivered and read.
- **Create a template** (`whatsapp_business_management`): Settings → Integrations →
  WhatsApp → Templates → new template (name, language, category, body with a
  variable) → it shows Pending → after Meta approves, Approved → it is sent to a lead
  outside the 24-hour window.

## 9. Money

Each customer's WhatsApp account has its own billing with Meta: the customer adds a
payment method in WhatsApp Manager during or after Embedded Signup. Authority Closers
never pays for customers' messages and Sales Xray never shows a price.
