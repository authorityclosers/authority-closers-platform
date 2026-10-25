# Google Ads API access for Sales Xray: design document, OAuth verification, owner steps

Owner, 25 Oct 2026: get every platform's approval started today, so only the owner's own
account steps are left. The code already exists (`connectors/google_ads_api.py`,
`connectors/google_pull.py`, `journey/providers/google_ads.py`). It stays off until the
Google Cloud project has OAuth credentials and API access.

## What changed at Google (check before filling anything)

- **Since 9–10 Sep 2026, Google Ads API access belongs to the Google Cloud project.**
  - It's managed on the **Google Ads API overview page in Cloud Console**, no longer in a manager account's API Center.
  - Developer tokens were retired. A token sent in the header is ignored for now.
  - Basic applications that were queued at the switch were closed.
  - Sources: Google's access-level page; Relevant Audience and ppc.land, Sept 2026.
- **Levels:**

  | Level | Production accounts | Operations per day | Review |
  |---|---|---|---|
  | Test | no | — | none |
  | Explorer | yes | 2,880 | no formal review |
  | Basic | yes | 15,000 | a form; reviewed in minutes to hours once the Cloud project passes **brand verification** (the OAuth consent screen's verification) |
  | Standard | yes | unlimited | about 10 business days |

- **Known bug:** upgrades after 9 Sep sometimes weren't honoured (AUTHORIZATION_ERROR). Google's workaround is a new Cloud project.
- **Code follow-up:** `AC_GOOGLE_ADS_DEVELOPER_TOKEN` is still a required setting in `google_ads_api.config()`. Make it optional (one small api-lane task) before switching the connector on.

Cloud project: `ac-sales-xray-ads`.

---

## Part 1: API design document (Basic access application)

**Company:** Authority Closers, India. Website https://authorityclosers.com. Contact admin@authorityclosers.com.

**Product:** Sales Xray (https://salesxray.authorityclosers.com), a sales CRM and call-coaching
app for small and mid-sized businesses in India. It runs on the web, with an Android app on Google Play.

**What the tool does with the Google Ads API.** A business owner or admin connects **their own**
Google Ads account in Sales Xray (Settings → Connected apps → Google Ads lead forms → Connect).
From then on:
1. Leads from that account's **lead form assets** arrive in the business's Sales Xray lead
   list within seconds, so the sales team calls them back quickly.
2. Optionally, the business confirms which of its sales stages count as a qualified lead or a
   sale. Sales Xray then uploads those moments as **offline click conversions**, so Google
   Ads learns which leads turned into customers.

We are not an agency. We don't create, edit, bid on or report on campaigns, and we never
touch an account the business didn't connect.

**Users:** owners and admins of a Sales Xray organisation (each business is its own
organisation). Sellers never see the connection or its tokens.

**Authentication:** OAuth 2.0 web flow, scope `https://www.googleapis.com/auth/adwords`, with
`access_type=offline`, `prompt=consent` and a signed state bound to the organisation and the person.
- The refresh token is sealed with AES-256-GCM and stored with that organisation's lead source. It is never shown or logged.
- A person can disconnect at any time.

**API calls (REST, `googleads.googleapis.com`):**

| When | Service and method | Query or change |
|---|---|---|
| Connect | `CustomerService.ListAccessibleCustomers` | which accounts the person can reach |
| Connect | `GoogleAdsService.Search` | `customer_client` (level ≤ 1), to name the accounts, manager children included |
| Turn an account on | `GoogleAdsService.Search` | `asset` where type is LEAD_FORM (name, headline, delivery methods) |
| Turn an account on | `AssetService.MutateAssets` | adds Sales Xray's webhook to `lead_form_asset.delivery_methods`, only on forms with no other webhook |
| Every 10 minutes, per account | `GoogleAdsService.Search` | `lead_form_submission_data`, newest submissions: the safety net for a missed webhook |
| The business confirms its stages | `GoogleAdsService.Search` + `ConversionActionService.MutateConversionActions` | finds or creates UPLOAD_CLICKS actions named "Sales Xray · …" |
| A lead reaches a confirmed stage | `ConversionUploadService.UploadClickConversions` | gclid, conversion action and time; nothing else |

**Volume:**
- per connected account: about 150 searches a day (the 10-minute pull), plus one call per lead stage reached;
- 50 accounts: about 8,000 operations a day.
- Explorer covers our first ~15 customers; Basic covers growth to about 90.

**Architecture:**
```
Business admin (browser or Android) ── Sales Xray web ── Sales Xray API (FastAPI, Mumbai)
                                                         │  OAuth code → refresh token (sealed, PostgreSQL)
Google lead form ── webhook (per-source key) ─────────▶ │  /v1/lead-desk/capture/{source}/google-ads
                                                         │  runner: 10-minute pull, conversion uploads
                                                         └─▶ googleads.googleapis.com (REST)
```

**Data handling:**
- Lead answers are stored in that business's organisation only.
- They're kept until the business deletes them or asks us to: https://salesxray.authorityclosers.com/data-deletion.
- Lead data goes to no AI model, and isn't sold or shared.
- Hosting: Hostinger (Mumbai), Cloudflare (network), Google Drive (encrypted backups).
- Privacy: https://salesxray.authorityclosers.com/privacy. Terms: https://salesxray.authorityclosers.com/terms.

**Screens to attach:**
- Settings → Connected apps (the Google Ads lead forms card), from `/review-fixture/meta-connect` at 1440 px;
- Leads → Lead sources;
- a lead from Google Ads.

---

## Part 2: OAuth consent screen and verification (project `ac-sales-xray-ads`)

| Field | Value |
|---|---|
| User type | External, In production |
| App name | Sales Xray |
| User support email | admin@authorityclosers.com |
| App logo | `brand-20261023/icon/sales-xray-icon-1024.png`, exported at 120×120 PNG |
| Application home page | https://salesxray.authorityclosers.com |
| Privacy policy | https://salesxray.authorityclosers.com/privacy |
| Terms of service | https://salesxray.authorityclosers.com/terms |
| Authorised domains | authorityclosers.com (verified in Google Search Console by the owner) |
| Developer contact | admin@authorityclosers.com |
| Scopes | `openid`, `email` (non-sensitive) and `https://www.googleapis.com/auth/adwords` (**sensitive**) |
| Redirect URIs (Web client) | `https://salesxray.authorityclosers.com/v1/lead-desk/google/callback`, plus the `salesxray-staging` and `salesxray-dev` equivalents |

**Scope justification (adwords):**
> Sales Xray is a CRM. A business connects its own Google Ads account so that leads from its
> lead form assets arrive in its Sales Xray lead list, and so that it can send back which of
> those leads became customers (offline click conversions). We read the account's lead form
> assets and lead form submissions, add Sales Xray's webhook to the business's lead forms, and
> upload offline click conversions for the stages the business confirms. We don't create or
> change campaigns, budgets or bids. No narrower Google Ads scope exists for these calls.

**Privacy policy check before submitting:** Google wants the policy to say what Google user data is used and how.
- Add one paragraph (owner or legal):
  > When you connect Google Ads, Sales Xray reads your lead form assets and lead form submissions and uploads the conversions you choose. We use this data only to run these features for your organisation, we don't use it for advertising or sell it, and our use follows the Google API Services User Data Policy, including the Limited Use requirements.
- It's a declaration, so the owner approves the wording.

**Demo video script** (unlisted YouTube, about 2 minutes, English captions, production site, test account):
1. Title card: "Sales Xray · Google Ads lead forms · OAuth demo".
2. Sign in to salesxray.authorityclosers.com, then Settings → Connected apps → Google Ads lead forms → **Connect**.
3. Google's consent screen fills the frame. Hold 3 seconds on the **app name "Sales Xray"** and the **Google Ads scope**. Show the browser's address bar with the client ID visible. Press Allow.
4. Back in Sales Xray, the accessible accounts are listed. Turn one test account on, and a caption says "Sales Xray adds its webhook to this account's lead forms".
5. In Google Ads, a lead form preview sends a test lead, and it appears under Leads within seconds. Open it to show the form's answers.
6. Leads → Lead stages: confirm "Qualified lead" for Google Ads. Move the lead to that stage; the caption says "uploaded to Google Ads as an offline conversion".
7. Settings → Connected apps → Google Ads → Disconnect. End card with the privacy URL.

---

## Part 3: owner steps (only he can do these)

1. **Google Cloud console**, project `ac-sales-xray-ads`, signed in as admin@:
   1. **Google Search Console:** verify authorityclosers.com. Cloudflare DNS TXT: the owner adds it, or the orchestrator adds it with his yes.
   2. **OAuth consent screen:** enter Part 2's values, then **Publish app**, then **Prepare for verification**. Add the demo video link and the scope justification, then **Submit**.
2. **Google Ads API overview page** (Cloud Console → APIs & Services → Google Ads API):
   1. Enable the API.
   2. Apply for **Explorer** (no review).
   3. Then apply for **Basic** with Part 1's answers. The orchestrator fills this in his Chrome once he's signed in.
3. **A Google Ads test account:** an optional manager account with one test client account, for the dev proof and the demo video. This is his sign-in.
4. **Credentials:**
   - OAuth Web client ID and secret: the owner reveals them, then `ac-secret.ps1 AC_GOOGLE_ADS_CLIENT_ID|AC_GOOGLE_ADS_CLIENT_SECRET <env>`.
   - Then the compose/SECRETS wiring (Align) ships with a release.

Expected time:
- Explorer: same day.
- OAuth sensitive-scope verification: typically 3–5 business days. Google says it can be longer.
- Basic: minutes to hours after brand verification passes.
