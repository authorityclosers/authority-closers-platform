# Messenger and Instagram on "Sales Xray Messaging": what Meta's dashboard needs

Phase C of the Meta integration (orchestrator, 19 Oct 2026): Messenger and Instagram
conversations in the Sales Xray CRM, on the same Meta app as WhatsApp ("Sales Xray
Messaging", see `whatsapp-app.md`). Each customer organisation connects **its own**
Facebook Pages and the Instagram professional accounts linked to them in Settings →
Integrations → Messenger & Instagram. Nothing here is named after a customer.

The Lead Desk session does **not** create or change Meta apps; the orchestrator does it
with the owner's OK and records each ID here. Secrets go only into Infisical.

Sources (Meta developer docs, read 19 Oct 2026): Instagram Messaging get started,
webhooks, send a message, private replies, App Review for apps that serve other
businesses; Messenger Platform send messages, webhooks, policy (24-hour window, Human
Agent tag); Page and Instagram webhook references. Items marked **check** must be read
off the dashboard while setting up.

## What Sales Xray does

- **Connect:** an owner or admin presses Connect Messenger & Instagram → Facebook Login
  for Business (the Messenger and Instagram configuration below) → picks Pages → Sales
  Xray keeps each Page's token sealed to the Page, notes the Page's linked Instagram
  account, and subscribes the Page to the app (`POST /{page-id}/subscribed_apps`,
  fields `messages, messaging_postbacks, message_echoes, message_deliveries,
  message_reads, feed`). From the Sales Xray phone app the login opens in the phone's
  browser and comes back to the app (`app_return`, provider `messaging`).
- **Messages:** someone writes to the Page on Messenger or to its Instagram account →
  webhook → a lead (the organisation's assignment rules pick the seller) with their
  name from Meta's profile API → the lead's owner or a manager answers in the lead's
  conversation (`POST /{page-id}/messages`, `messaging_type: RESPONSE`).
- **Windows:** answers only within 24 hours of the person's last message. After that a
  person (never an automation) may answer up to 7 days later with the `HUMAN_AGENT`
  tag, once Meta grants the Human Agent feature and the organisation turns it on.
- **Comment to message:** a comment on the Page's posts (Page `feed` webhook) or the
  Instagram account's media (Instagram `comments` webhook) with one of a rule's keywords
  → one private reply (`recipient: {comment_id}`, within 7 days) and, if the rule says
  so, a short public answer (Facebook `POST /{comment-id}/comments`, Instagram
  `POST /{comment-id}/replies`); the commenter becomes a lead. Comments no rule matches
  are not kept.
- **Auto replies per Page:** an instant first reply to someone writing for the first
  time (within about 10 seconds), and a reply to messages that arrive outside work
  hours (once in 12 hours).
- **First response:** a person's answer stops the lead's first-response clock; auto
  replies don't. Breaches alert the seller like WhatsApp.
- **Privacy:** message words are the customer's own data, kept only in
  `lead_desk_social_messages`; a message the person takes back (unsent) loses its words
  at once; a lead that leaves Lead Desk takes its words with it.

## 1. App and use cases

Same Business app as WhatsApp: **Sales Xray Messaging**, app ID **856472050863115** (parent for production, with
"- staging" and "- dev" test apps). Add, per app:

- Use case **Engage with customers on Messenger from Meta** (Messenger Platform).
- Use case **Manage messaging and content on Instagram** (Instagram API with Facebook
  Login; the account must be an Instagram professional account linked to a Page).

## 2. Facebook Login for Business configuration (Messenger and Instagram)

A second configuration per app, next to the WhatsApp Embedded Signup one:

- Login variation: **General** (user access token).
- Assets: **Pages** and **Instagram accounts**.
- Permissions:
  - `pages_show_list` (list the Pages the person shares)
  - `pages_manage_metadata` (subscribe the Page to the app's webhook)
  - `pages_messaging` (receive and answer Messenger, private replies)
  - `pages_read_engagement` (read the Page's posts and comments that the feed webhook
    names)
  - `pages_manage_engagement` (the optional public answer under a Facebook comment)
  - `instagram_basic` (the Instagram account's id and username)
  - `instagram_manage_messages` (receive and answer Instagram messages)
  - `instagram_manage_comments` (Instagram comments webhook, private and public replies)
  - `business_management` (Pages and Instagram accounts held in a business portfolio)
- Record the **configuration ID** for each environment as
  `AC_MESSAGING_LOGIN_CONFIG_ID`.
- Valid OAuth redirect URI: `https://<Sales Xray host>/v1/lead-desk/messaging/callback`
  (salesxray, salesxray-staging, salesxray-dev, each on its own app). The person's
  browser makes this request, so it needs no Cloudflare Access bypass.

## 3. Webhooks

App Dashboard → Webhooks, per app, with the same callback for both objects:

- Callback URL: `https://<host>/v1/lead-desk/messaging/webhook`
- Verify token: the app's `AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN` (one value per app).
- Object **Page**, fields: `messages`, `messaging_postbacks`, `message_echoes`,
  `message_deliveries`, `message_reads`, `feed`.
- Object **Instagram**, fields: `messages`, `messaging_postbacks`, `messaging_seen`,
  `comments`.
- Each customer's Page is subscribed by Sales Xray after Connect; nothing per customer
  in the dashboard. **Check** that Instagram notifications for a Page-linked account
  arrive once the Page is subscribed (Meta's docs say the Page token needs
  `instagram_manage_messages` and the Instagram topic subscribed at app level).
- Dev and staging sit behind Cloudflare Access: `/v1/lead-desk/messaging/webhook` needs
  the same Access bypass as `/v1/lead-desk/whatsapp/webhook` (Align 3, Root card
  AUT-2152).

## 4. Settings (Infisical, per environment)

| Name | What |
| --- | --- |
| `AC_WHATSAPP_APP_ID`, `AC_WHATSAPP_APP_SECRET` | the Messaging app (same as WhatsApp) |
| `AC_WHATSAPP_WEBHOOK_VERIFY_TOKEN` | the same verify token |
| `AC_MESSAGING_LOGIN_CONFIG_ID` | **new:** the Messenger and Instagram login configuration |
| `AC_WHATSAPP_GRAPH_VERSION` | optional, as WhatsApp |

Messenger and Instagram switch on when the four exist (WhatsApp's Embedded Signup
configuration isn't needed for them). Page tokens are sealed with the existing
`AC_LEAD_DESK_TOKEN_KEY`. Dev: `<value> | ac-secret-drop AC_MESSAGING_LOGIN_CONFIG_ID dev
--restart`.

## 5. In each customer's accounts

- The Instagram account must be **professional** (business or creator) and linked to
  the Page.
- Instagram → Settings → Messages and story replies → Message controls → Connected
  tools → **Allow access to messages** must be on (Meta's rule for any inbox app).
  Settings → Integrations says so next to the Instagram switch.

## 6. App Review (production)

Advanced Access for every permission in section 2, plus the optional **Human Agent**
feature; `business_management` as a dependency. The use texts and the screencast plan
are in `meta-app-review.md`. Until approved, only people with a role on the app can
connect a Page.

## 7. Testing

- Dev: the AC test Page "Sales Xray Test Leads" and a test Instagram professional
  account linked to it; testers with a role on the dev app write from their own
  accounts. No real customer conversations on dev.
