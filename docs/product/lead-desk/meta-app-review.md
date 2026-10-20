# Meta App Review: how Sales Xray uses each permission, and what to record

For the orchestrator, who submits the reviews (orchestrator, 19 Oct 2026). One entry
per permission or feature: the text for "How will your app use this permission?",
then the screencast plan. Sign-in ("Sales Xray Sign-in") is a separate chat and not
here.

All recordings: on staging or dev with Meta's test assets (the test Page "Sales Xray
Test Leads", a test Instagram professional account linked to it, Meta's WhatsApp test
number), in English, starting signed out, with the browser's address bar visible, no
real customer data. Meta wants to see the login, the permission grant, and the feature
working end to end. Record the same app that is submitted.

Apps: **Sales Xray Leads** (lead capture, lead stages, ad spend) and **Sales Xray
Messaging** (856472050863115: WhatsApp, Messenger, Instagram).

---

## Sales Xray Leads

### leads_retrieval

**Use.** Sales Xray is a sales CRM for businesses that advertise on Facebook and
Instagram. When a business connects its Page in Sales Xray (Leads → Sources →
Facebook & Instagram → Connect), Sales Xray reads the leads its Instant Forms collect,
as each one arrives (the Page's leadgen webhook) and for the last 90 days, so its
sellers can call each lead within minutes. Sales Xray reads only the forms of Pages the
business chose and keeps each lead in that business's own workspace.

**Record.** Sign in to Sales Xray → Leads → Sources → Facebook & Instagram → Connect →
Facebook Login for Business: pick the test Page, grant → back in Sales Xray, turn the
Page on → in Meta's Lead Ads Testing Tool, submit a test lead → it appears in Sales
Xray Leads within seconds with its answers → open it.

### pages_show_list, pages_read_engagement, pages_manage_metadata, pages_manage_ads

**Use.** To list the Pages the person manages so they can pick which ones bring leads
in (`pages_show_list`); to read the Page's lead forms and their names
(`pages_read_engagement`, `pages_manage_ads`); and to subscribe the Page to Sales Xray's
webhook so new leads arrive in seconds (`pages_manage_metadata`).

**Record.** The same recording as leads_retrieval: the Page list after login, the
forms covered on the Page card, and a lead arriving by webhook.

### ads_read

**Use.** Two features for the business's managers. (1) Lead stages back to Meta: the
business picks its own dataset from its ad accounts. (2) Ad spend: Sales Xray reads
what each of the business's campaigns spent per day, to show the cost per lead and per
customer next to the leads that arrived (Leads → Team → "Ads: what each lead cost", and
a line on the Facebook & Instagram source). Read only; Sales Xray never changes ads.

**Record.** Connected business → Leads → Team → "Ads: what each lead cost" → Check now
→ the campaigns with spend, leads here, per lead → Sources → the spend line under the
Page. Then Lead stages back to Meta → choose the dataset.

### business_management

**Use.** Dependency: Pages, ad accounts and datasets owned by a business portfolio are
only visible with it. Sales Xray uses it only to list those assets after the person
grants them in Facebook Login for Business.

**Record.** The login step showing the business portfolio's assets being granted.

### Conversions API for CRM (no extra permission; dataset access)

**Use.** When a seller moves a Meta lead to a new stage (contacted, interested,
customer), Sales Xray sends that stage to the business's own dataset with Meta's lead
id and hashed contact details only, so the business's ads find more leads like its
customers.

**Record.** Open a test lead → mark it Interested → Lead stages back to Meta shows the
event delivered → Events Manager → the dataset's test events show it.

---

## Sales Xray Messaging

### whatsapp_business_management

**Use.** A business connects its own WhatsApp Business number to Sales Xray with
Embedded Signup (Settings → Integrations → WhatsApp → Connect WhatsApp). Sales Xray
subscribes its app to the business's WhatsApp account, registers the number, and lets
the business manage its message templates (create, see Meta's review result, delete).
The business pays Meta directly for its messages.

**Record (screencast 2, "create a template").** Settings → Integrations → WhatsApp →
New template → name, language, Utility, a body with {{1}} and an example → it shows
Pending → (after Meta approves) Approved → it is sent to a lead outside the 24-hour
window from the lead's conversation.

### whatsapp_business_messaging

**Use.** Leads who write to the business's WhatsApp number appear in Sales Xray as
leads, assigned to a seller by the business's own rules. The seller answers in the
lead's conversation inside the 24-hour window and only with an approved template
after it, and only to people who agreed. The business can turn on automated replies:
an instant first reply, an after-hours reply, and AI replies that answer only from
the business's own information (its profile, services, FAQs and hours), in the lead's
language. In "suggest" mode a seller reviews each AI draft and taps send; in "auto"
mode it is sent within those guardrails. The AI never acts as a general assistant: it
hands the conversation to a person (and alerts the seller) on complaints, price or
discount talk, anything it can't answer from the business's information, or when the
lead asks for a person, and it stops automatic messages when the lead says STOP.

**Data handling (AI replies).** The processor is Google LLC (the Gemini API), which is
named on the privacy page (/privacy, "AI replies to messages"). For each draft it gets
only the business's own profile, the words of up to the last 10 messages of that one
conversation, and the lead's first name, but only when the lead did not come from lead
ads. Nothing from Meta lead ads (`leads_retrieval`) is ever sent: no form answers, and
no phone number or email saved with a lead. AI replies run only while Sales Xray's Admin
has them switched on for that environment, and within its spending cap.

**Record (screencast 1, "send a message").** A test phone writes "Is a site visit
possible on Sunday?" to the test number → the lead appears in Leads with the message →
the AI draft appears in the conversation → the seller taps Send → the reply arrives on
the phone (side by side) → delivered and read ticks. Then the phone writes "I want to
talk to someone" → no AI reply; the conversation shows "A person should answer" and
the seller replies by hand. Then "STOP" → no further automatic messages.

### pages_messaging

**Use.** A business connects its Facebook Page (Settings → Integrations → Messenger &
Instagram). People who message the Page become leads in Sales Xray; the business's
sellers answer them in the lead's conversation within Meta's 24-hour window (and, if
Meta grants the Human Agent feature, a person may answer up to 7 days later). The
business can turn on automated replies: an instant first reply, an after-hours reply,
and AI replies that answer only from the business's own information and hand over to
a person on complaints, price talk, uncertainty or a request for a person. Comment to
message: a comment with a keyword the business chose gets one private reply.

**Record.** Connect the test Page → a tester messages the Page → the lead appears with
the message → the seller replies (or approves the AI draft) → it arrives in Messenger →
the tester writes "can I talk to a person?" → the AI hands over and the seller answers →
a comment "price" on the Page's post → the private reply arrives in Messenger and a
public answer appears under the comment.

### instagram_basic, instagram_manage_messages

**Use.** For a business's Instagram professional account linked to its Page: Sales
Xray shows the account's username (`instagram_basic`) and brings its direct messages
into Sales Xray as leads; sellers answer inside the 24-hour window. Automated replies
work as on Messenger: a first reply (within seconds), an after-hours reply, and AI
replies limited to the business's own information, with hand-off to a person on
complaints, price talk, uncertainty or a request for a person. Messages a person
unsends are removed from Sales Xray at once. Custom inbox: agents read and answer
conversations; nothing is deleted at Meta.

**Record.** Connect the Page with its Instagram account → a tester sends an Instagram DM
→ within 30 seconds the automated first reply arrives → the lead appears in Sales Xray
→ the seller answers → the tester unsends a message → it disappears from Sales Xray →
"talk to a human" → hand-off.

### instagram_manage_comments

**Use.** Comment to message on Instagram: when someone comments with a keyword the
business chose (for example "price") on the business's post or reel, Sales Xray sends
them one private reply and, if the business wants, a short public answer under the
comment, and makes them a lead. Comments without a keyword are not stored.

**Record.** Settings → Integrations → Messenger & Instagram → add a comment rule
("details" → private message) → the tester comments "details" on a test post → the
private reply arrives in the tester's Instagram inbox and the public answer appears →
the lead appears in Sales Xray.

### pages_manage_engagement

**Use.** Only for the optional public answer under a Facebook comment that matched a
comment rule ("We've sent you a message"). Sales Xray never posts anything else.

**Record.** Part of the pages_messaging recording (the public answer under the comment).

### Human Agent feature (optional)

**Use.** Sales Xray's inbox lets a seller answer personally up to 7 days after the
lead's last message when the business turns it on, for weekends and questions that
need more time. Automated and AI replies never use the tag.

**Record.** A conversation older than 24 hours → the composer says a person can still
answer within 7 days → the seller sends → the message arrives.

### business_management (Messaging)

**Use.** Dependency for `pages_messaging`, `pages_show_list` and
`instagram_manage_messages`: Pages and Instagram accounts in a business portfolio are
listed only with it, after the Page admin grants them in Facebook Login for Business.

**Record.** The login step granting the portfolio's Page and Instagram account.
