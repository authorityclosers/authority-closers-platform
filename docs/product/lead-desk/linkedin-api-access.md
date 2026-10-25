# LinkedIn API access for Sales Xray: developer app, Lead Sync and Advertising API answers, owner steps

Owner, 25 Oct 2026: start every approval now. One LinkedIn developer app serves both features:
- **Lead Gen Forms → Sales Xray leads** (Lead Sync API; the connector `connectors/linkedin.py` is to be built, one api-lane task);
- **lead stages → LinkedIn** (Conversions API; already built in `journey/providers/linkedin.py`, scopes `rw_conversions r_ads`).

Nothing works until LinkedIn grants each product.

## 1. Developer app (linkedin.com/developers/apps/new)

| Field | Value |
|---|---|
| App name | Sales Xray |
| LinkedIn Page | Authority Closers' Company Page. The owner names it; a **Page admin must verify** the app (step 3) |
| Privacy policy URL | https://salesxray.authorityclosers.com/privacy |
| App logo | `brand-20261023/icon/sales-xray-icon-1024.png` (square PNG; LinkedIn asks for at least 100×100) |
| Legal agreement | the owner ticks LinkedIn's API Terms (his account) |
| Description (Settings tab) | Sales Xray is a sales CRM and call-coaching app for small and mid-sized businesses in India. A business connects its own LinkedIn ad account so its Lead Gen Form leads reach its sales team within minutes, and so it can tell LinkedIn which leads became customers. |
| Website | https://salesxray.authorityclosers.com |
| Business email | admin@authorityclosers.com |
| Authorized redirect URLs (Auth tab) | `https://salesxray.authorityclosers.com/v1/lead-desk/linkedin/callback`, plus `https://salesxray-staging.authorityclosers.com/v1/lead-desk/linkedin/callback` and `https://salesxray-dev.authorityclosers.com/v1/lead-desk/linkedin/callback` |

## 2. Product requests (Products tab), with the answers

### Lead Sync API

A separate program from the Advertising API, requested on its own. Scopes:
`r_marketing_leadgen_automation`, `r_ads`, `r_organization_admin`. The person connecting needs
Account Manager, Campaign Manager or Lead Gen Forms Manager on the ad account.

| Question (wording varies) | Answer |
|---|---|
| Company and product | Authority Closers (India). Sales Xray, a sales CRM with call coaching, used by SMB sales teams in India: https://salesxray.authorityclosers.com |
| Use case | CRM lead sync. A business connects its own LinkedIn ad account in Sales Xray (Settings → Connected apps). New Lead Gen Form responses arrive in that business's Sales Xray lead list so its sellers call back within minutes. |
| How do you use the API? | OAuth 2.0 (3-legged) per business. We list the ad accounts the person can manage and their lead forms (`/rest/leadForms`). We subscribe to `/rest/leadNotifications` for real-time delivery, verifying LinkedIn's challenge with our client secret. We read each response (`/rest/leadFormResponses`), and we pull every 10 minutes as a safety net. |
| Who are your customers? | Businesses using Sales Xray. Each connects only ad accounts it manages. |
| Expected volume | Up to 100 businesses in the first 6 months, a few hundred leads a day in total |
| Data use | Lead answers are stored only in that business's organisation, encrypted at rest and in transit. Nothing is sold or used for advertising, and nothing goes to AI models. Deletion on request: https://salesxray.authorityclosers.com/data-deletion |
| Do you share data with third parties? | No. Hosting (Hostinger, Mumbai), network (Cloudflare) and backups (Google Drive, encrypted) are our processors. |
| Screenshots or video | Settings → Connected apps, Leads → Lead sources, a lead from LinkedIn. Recorded once the connector is on dev, like the Meta and Google demos |

### Advertising API (for Conversions API, `rw_conversions`, `r_ads`)

LinkedIn first grants a **Development** tier, then **Standard** after a review with a demo.

| Question | Answer |
|---|---|
| Use case category | Conversions / measurement (offline conversions from a CRM) |
| Describe your application | When a business's lead reaches a stage it confirmed in Sales Xray (for example "Qualified lead" or "Won"), Sales Xray sends that event to LinkedIn's Conversions API (`/rest/conversionEvents`) for a conversion rule we create in the business's own ad account. The event carries a SHA-256 email and, for website leads, LinkedIn's click id `li_fat_id`. This tells LinkedIn which ads bring real customers. |
| Do you create or manage campaigns? | No. We only read the ad accounts the person can access (to pick one) and create conversion rules named "Sales Xray · …" in that account. |
| Number of advertisers | Up to 100 in the first 6 months |
| Data protection | As above. Only hashed emails and click ids leave Sales Xray. |
| Demo (for Standard) | Connect LinkedIn → pick an ad account → confirm "Qualified lead" in Leads → Lead stages → move a lead → the event shows as delivered in Sales Xray and in Campaign Manager → Conversions |

## 3. Owner steps

1. Create the app at linkedin.com/developers/apps/new while signed in to LinkedIn as a Page admin of Authority Closers. Use the section 1 values and tick the legal agreement.
2. **Verify** the app: Settings → Verify → copy the link → a Page super admin opens it and approves. Without verification, product requests stay locked.
3. Products → request **Lead Sync API** and **Advertising API**. The orchestrator fills the forms in his Chrome with section 2's answers.
4. When LinkedIn grants them:
   - Auth tab → reveal the client secret (his sign-in);
   - `ac-secret.ps1 AC_LINKEDIN_CLIENT_ID|AC_LINKEDIN_CLIENT_SECRET <env>`;
   - the compose/SECRETS wiring (Align).

**Expected time:**
- Development tier: often the same day.
- Lead Sync access: LinkedIn publishes no figure. Developers report about 2–6 weeks.
- Advertising API Standard tier: a review after the demo.

**Meanwhile with no review:** a business's own Zapier or Make "LinkedIn Lead Gen Forms" trigger posts to a Sales Xray Website-form source.

## 4. Build after access (api lane, one task): `connectors/linkedin.py`

This mirrors `connectors/meta.py`:
- OAuth with the extra scopes;
- ad accounts and lead forms;
- a source per account (kind `linkedin`, refresh token sealed with `AC_LEAD_DESK_TOKEN_KEY`);
- `/v1/lead-desk/linkedin/webhook` (challenge plus signature check, then fetch the response, then `LeadDesk.ingest` with the response id as reference);
- a 10-minute pull and a 90-day backfill;
- a Connected-apps card with its blockers (waiting for LinkedIn; role on the ad account; the form isn't a Lead Gen Form);
- tests shaped like `tests/unit/lead_desk_connectors/test_meta*.py`.

Sources: [Lead Sync access](https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/getting-access-leadsync?view=li-lms-2024-07),
[Lead Sync use case and webhooks](https://learn.microsoft.com/en-us/linkedin/marketing/lead-sync/lead-sync-usecase).
