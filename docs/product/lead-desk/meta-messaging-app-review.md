# Meta App Review: Sales Xray Messaging (production app 856472050863115)

WhatsApp, Messenger and Instagram for Sales Xray run on this app (see `meta-apps.md`,
`whatsapp-app.md`, `instagram-messenger-app.md`). Until Meta grants Advanced Access,
only people with a role on the app can connect, and only their messages arrive; the
Connected apps cards say so (`connected_apps.messaging_blockers`, `MESSAGING_APPROVED`).

Method: the same as the Leads app on 19 Oct 2026 (`meta-app-review.md`). One captioned
screencast per area, recorded from the browser-pane region with ffmpeg; texts filled in
Meta's form with `form_input`; the owner uploads the videos, pastes the reviewer
password and confirms the declarations; Submit only on the owner's clear yes.

## 0. Before we can submit (read live 25 Oct)

| Gate | State | Action |
|---|---|---|
| Another submission in review | `can_submit: false`, "Cannot submit to App Review while a previous submission is in review." This app has no history of its own, so the block is the Leads app's review 29297824896491997 (or the business's access verification) | Wait for it to close. Everything below is ready the same day |
| Business verification, privacy policy | pass | none |
| Tech Provider | accepted 20 Oct. Access verification for the AC business was "In review" | Owner checks Business Suite → Security center |
| API calls per permission (`api_precheck`) | not complete for 9 permissions. Parent app: 0 calls in 30 days; dev test app 1116775534070252: also 0, although the 20 Oct dev test made calls inside the 30-day window (the counter may not count every call type; make fresh calls anyway) | One real call per permission within 30 days before submitting. Run the dev checklist in §4 the day before |
| `test_page` step for pages_messaging | not complete | Meta wants a Page used for the test. Pick "Sales Xray Test Leads" 1326368220570095 in the form |
| Prod webhooks | none on the parent; prod verify token held back on purpose | Owner's yes, then subscribe prod `whatsapp_business_account`, `page` (messages, messaging_postbacks, message_deliveries, message_reads, message_echoes, feed) and `instagram` (messages, messaging_postbacks, messaging_seen, comments) to salesxray.authorityclosers.com, and set the prod verify token in Infisical. Reviewers test against production |
| App icon | not uploaded (`app_icon_url: null`) | Upload with the file-input trick (the console's Choose file opens a native picker: patch `HTMLInputElement.prototype.click` to append the input, then upload to it) |
| Contact email | `contact_email_verified: false` | Owner clicks Meta's verify mail |
| Instagram test account | none linked to the test Page (20 Oct note §4) | Owner links an Instagram professional test account to the Page and turns on "Allow access to messages" |

## 1. App use summary (paste into "Tell us how your app works")

Sales Xray is a sales CRM and call-coaching product for businesses in India. A business
owner or admin connects their own WhatsApp Business number (Embedded Signup), Facebook
Page (Messenger) and the Page's Instagram professional account from **Settings →
Connected apps**. When a customer writes to them, the conversation appears in **Chats**
and on that customer's lead record. Their sales team answers from Sales Xray within
Meta's messaging windows.
- Only people in that business's Sales Xray organisation see its conversations.
- Tokens are stored encrypted.
- Disconnecting removes our webhook subscription.
- Message text is deleted with the lead or on request (/data-deletion).
- We don't send marketing broadcasts. Outside 24 hours, WhatsApp uses approved templates only.
- No message content is sent to any AI provider unless the business turns on AI reply suggestions. That's off by default, and it never includes lead-ads data.

## 2. Permission texts (one per "Tell us how you'll use this permission")

**whatsapp_business_messaging:** To receive messages sent to the business's own WhatsApp number (webhook `messages`), and to send the sales team's replies, from the lead's conversation in Sales Xray (`POST /{phone-number-id}/messages`). That covers text within 24 hours of the customer's last message, and the business's approved templates after that. We also read delivery and read statuses to show ticks.

**whatsapp_business_management:** After Embedded Signup we read the business's WhatsApp Business Account and its phone numbers (`GET /{waba-id}/phone_numbers`), subscribe our app to it (`POST /{waba-id}/subscribed_apps`) and register the number. We list, create and delete the business's own message templates (`/{waba-id}/message_templates`) from Settings → Connected apps → WhatsApp → Templates, and show their review status.

**pages_messaging:** To receive Messenger messages sent to the business's connected Facebook Page and to send the sales team's replies (`POST /{page-id}/messages`, messaging_type RESPONSE, within 24 hours). We also send one private reply to a comment that contains a keyword the business chose (`recipient: {comment_id}`).

**pages_show_list:** After Facebook Login for Business we list the Pages the admin manages (GET /me/accounts) so they choose which Page's messages come into their CRM. We keep only the chosen Page's ID, name and Page token (encrypted).

**pages_manage_metadata:** To subscribe our app to the connected Page's messaging webhooks (`POST /{page-id}/subscribed_apps` with messages, messaging_postbacks, message_deliveries, message_reads, message_echoes, feed). On disconnect we remove the subscription.

**pages_read_engagement:** With the Page token, to read the connected Page's name and its linked Instagram account. We also read the text of new comments the `feed` webhook tells us about, so a keyword rule the business set can answer the commenter privately. We don't read follower or engagement data.

**business_management:** Facebook Login for Business lets the admin give access to Pages and WhatsApp accounts owned by their business portfolio, not only Pages they own personally. This permission lets those business-owned assets appear and be connected. We don't change any business settings.

**instagram_basic:** To read the connected Instagram professional account's id and username, so its messages and comments land under the right business.

**instagram_manage_messages:** To receive direct messages sent to the business's Instagram professional account and send the sales team's replies from Sales Xray within 24 hours. We also read the sender's name and username to label the lead.

**instagram_manage_comments:** To receive comments on the business's own Instagram media (webhook `comments`), and, for a keyword the business chose, to send one private reply and an optional short public reply (`POST /{comment-id}/replies`).

**Human Agent:** A person on the business's sales team (never an automation) may answer a customer's Messenger or Instagram question up to 7 days after their last message, with the HUMAN_AGENT tag. The business turns this on in Settings, and our automatic replies never use it.

**Business Asset User Profile Access (add it to the request):** our Messenger code reads the sender's `first_name,last_name` to name the lead (`social/graph.py`). Text: "To show the name of a person who messages the business's Page on their lead record, so the sales team knows who they're talking to."

**public_profile:** Facebook Login for Business needs it; we read nothing from it.

## 3. Screencasts (captions in English, one video per area, about 2–3 min each)

The common start, on production with the reviewer test account (the QA account in the
"Meta Review" organisation, AUT-2151):
sign in → Settings → Connected apps.

1. **WhatsApp** (whatsapp_business_management, whatsapp_business_messaging):
   1. Connect WhatsApp → Embedded Signup → pick the business and number → Connected.
   2. Templates → new template (name, language, Utility, body with {{1}}) → Pending.
   3. A team phone writes "Hi" to the number → the lead appears in Chats → reply from Sales Xray → it arrives on the phone (side by side) → ticks go delivered, then read.
   4. Send the approved template to a lead outside 24 hours.
   5. Disconnect.
2. **Messenger** (pages_show_list, business_management, pages_manage_metadata, pages_messaging, pages_read_engagement, Human Agent, BAUPA):
   1. Connect Messenger & Instagram → Facebook Login for Business dialog shows permissions and the Page picker → pick the test Page → Connected (show the subscription in the Test step).
   2. A tester's personal profile messages the Page → the lead appears with their name → reply → received.
   3. Comment the rule's keyword on a Page post → the private reply arrives.
   4. Show the "Let sellers answer personally up to 7 days later" switch (Human Agent) and its explanation.
3. **Instagram** (instagram_basic, instagram_manage_messages, instagram_manage_comments):
   1. The same connect shows the linked Instagram account.
   2. A tester's Instagram account sends a DM → the lead appears in Chats → reply → seen.
   3. Comment the keyword on a post → private reply.

Blur Telegram pop-ups, cut other windows, and use no real customer data (as for the Leads app).

## 4. Reviewer instructions (draft)

1. Go to https://salesxray.authorityclosers.com and sign in with the test account below (email and password).
2. Open **Settings → Connected apps**.
3. **WhatsApp:** press Connect and finish Meta's Embedded Signup with a WhatsApp Business account you control. Then open Chats, send a WhatsApp message to that number from any phone, and reply from Sales Xray.
4. **Messenger and Instagram:** press Connect on "Messenger", sign in with a Facebook account that manages a Page (and its linked Instagram professional account), grant the permissions, and pick the Page. Message the Page from another account: the conversation appears under Chats; reply from there.
5. **Comment to message:** Connected apps → Messenger → Manage → "Comments that send a message" → add a keyword and save. Comment it on one of the Page's posts; a private message arrives.

Test account: the owner pastes the email and password into Meta's form himself.

**Dev checklist the day before** (fills `api_precheck`): on the dev test app, connect,
receive one message, send one reply, list numbers, list templates and create one, and
subscribe a Page and an IG account. One call each. Ping the orchestrator before any
send (they watch the test phone).

## 5. Data handling (same answers as the Leads app, approved 19 Oct "as drafted")

| Question | Answer |
|---|---|
| Processors | Hostinger International Limited (India), production hosting in Mumbai; Cloudflare, Inc. (India, US), network proxy; Google LLC (US), Drive backups |
| Also listed | Google (Gemini), **only if** a business turns on AI reply suggestions. It's off by default, and its privacy page names it. **Owner confirms this line, because it differs from the Leads app** |
| Responsible entity | Authority Closers, India |
| National-security requests | none |
| Policies | legality review and data minimisation |

## 6. Owner-only steps
- Upload the 3 videos (the pane can't open a file chooser).
- Paste the reviewer password.
- Confirm the data-handling answers, including the Gemini line.
- Verify the contact email.
- Link the test Instagram account.
- Say yes to production webhooks and the verify token.
- Say "submit" (or press it).

## 7. Order of play, the day the Leads review closes

1. Check `can_submit` (Meta DevTools `devtools_app_review requirements` for 856472050863115).
2. Owner's yes for the production webhooks and verify token (section 0); subscribe and
   verify (`hub.challenge` answered, a wrong token refused).
3. Dev checklist (section 4) so every permission has a fresh API call.
4. Record the three screencasts on production with the reviewer account; cut, caption,
   blur notifications.
5. Fill the form: app use, permission texts, data handling, reviewer instructions;
   Business Asset User Profile Access added to the Messenger use case first.
6. Owner: uploads, password, declarations, Submit.

## 8. WhatsApp coexistence: the business keeps its WhatsApp Business app (owner, 25 Oct 2026)

Owner, 25 Oct 2026, verbatim: "Keep the WhatsApp Business app on the Redmi 13 and add the
same number to the API with coexistence once Meta approves our Messaging app; use the test
number for test messages until then."

What it is: Meta's "Onboard WhatsApp Business app users" feature of Embedded Signup. The
business connects the number it already uses in the WhatsApp Business app; it keeps using
the app one-to-one, Sales Xray sends and receives through Cloud API, and messages stay in
sync both ways. No new number, no re-registration.

Requirements (Meta's docs, read 25 Oct 2026):
| Requirement | Us |
|---|---|
| We are a Solution Partner or Tech Provider | Tech Provider accepted 20 Oct; access verification still in review |
| Embedded Signup with session logging, `extras.featureType = "whatsapp_business_app_onboarding"`, `sessionInfoVersion: "3"`; Embedded Signup v2 is retired on 15 Oct 2026, use v4 | `whatsapp/cloud.py` opens the dialog by redirect with `extras={"setup":{}}`: add the feature type (and check the redirect flow carries it; otherwise the connect page uses the JS SDK popup) |
| WhatsApp Business app 2.24.17 or newer on the business's phone | the Redmi 13 runs 2.26.41.77 |
| Webhooks: also `history`, `smb_app_state_sync` and `smb_message_echoes` (and `account_offboarded`) | add them to the app's WhatsApp webhook fields and the inbox handler |
| Within 24 hours of onboarding, start the contacts and history sync (SMB App Data API), or the business must offboard and start again | a job right after connect; the WhatsApp card shows "Syncing your WhatsApp history" until done |
| Skip phone-number registration (the number is already registered) | `connect_number` must not call `/register` for these |
| Countries: not Cuba, Iran, North Korea, Syria or the sanctioned regions of Ukraine | India is fine |

What changes for the business on its phone: 1:1 chats, contacts and history sync; group
chats don't sync; disappearing, view-once and live-location messages are turned off in 1:1
chats; broadcast lists become read-only; linked companion devices are unlinked once and can
be re-linked (not WhatsApp for Windows or WearOS); calls, catalogue, status, labels and quick
replies are unchanged. Throughput is fixed at 20 messages a second. Messages sent from the
app stay free; messages sent through the API are charged at Meta's rates (paid by the
business, as for any number).

For App Review: no extra permission; the WhatsApp screencast shows the "Connect your
existing WhatsApp Business account" choice in Embedded Signup alongside a new number, and
the review notes say Sales Xray supports both. Build before recording: the feature type, the
three webhook fields, the sync job and the skipped registration (one api task, one web task
for the card's sync state).

Until approval: Meta's test number +1 555 656 0179 (WABA 1000985176354249) for test
messages; steps in the side notes `meta-suite-20261025/whatsapp-test-number-steps.md`.

## Escalation without resubmitting

Resubmitting or cancelling puts a submission at the back of the queue. Meta's App
Review FAQ says reviews "may take up to several weeks" while volume is high. To ask
about a submission that seems stuck: developers.facebook.com/support → AI Developer
Assistant → if it can't help, its prefilled support request (an app admin submits it),
naming the app ID, the submission ID, business verification (16 Oct 2026) and Tech
Provider status. Check the app's Required actions and the business's Alerts first.
