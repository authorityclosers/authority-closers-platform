# Microsoft Advertising for Sales Xray: what it can do, our pack, owner steps

Owner, 25 Oct 2026: LinkedIn, Microsoft Ads "and so on", with accounts and sign-in all set up.

## What Microsoft offers (checked 25 Oct 2026)

- **Lead forms by API: not confirmed.**
  - A Microsoft Q&A answer (undated) says Microsoft Advertising has no lead forms "like Facebook or Google Ads".
  - Nothing in the Bing Ads API v13 reference turned up a lead-form download or webhook.
  - **Owner check (2 minutes):** in ads.microsoft.com, open an Indian campaign → Assets. If "Lead form" is offered, tell us and we'll find its export route. Until then, Microsoft is for **lead stages back** (offline conversions), not lead capture.
- **Offline conversions: built.**
  - `journey/providers/microsoft_ads.py` creates "Sales Xray · …" offline conversion goals in the business's account.
  - It sends MSCLKID and/or SHA-256 email and phone (enhanced conversions) through Campaign Management v13 REST (`OfflineConversions/Apply`).
  - It stays off until `AC_MICROSOFT_ADS_CLIENT_ID`, `_CLIENT_SECRET` and `_DEVELOPER_TOKEN` exist. `AC_MICROSOFT_ADS_SANDBOX=1` uses Microsoft's sandbox.
- **Sign-in:**
  - delegated user OAuth only (no app-only flow);
  - endpoint `https://login.microsoftonline.com/common/oauth2/v2.0`;
  - scope `https://ads.microsoft.com/msads.manage offline_access`.
- **Note:** Microsoft is freezing its SOAP API (reported dates: feature freeze 1 Oct 2026, shutdown 31 Jan 2027). Our code already uses REST.

## Our pack

**Entra app registration** (portal.azure.com → Microsoft Entra ID → App registrations → New):

| Field | Value |
|---|---|
| Name | Sales Xray |
| Supported account types | Accounts in any organizational directory **and personal Microsoft accounts** (multitenant + personal). Advertisers sign in with either |
| Redirect URIs (Web) | `https://salesxray.authorityclosers.com/v1/lead-desk/microsoft/callback`, plus the `salesxray-staging` and `salesxray-dev` equivalents |
| API permissions | Microsoft Advertising API → delegated `msads.manage`, plus `offline_access`. The API appears only after the account has signed in to ads.microsoft.com once |
| Branding | logo `brand-20261023/icon/sales-xray-icon-1024.png`; home page, terms and privacy URLs as for Meta and Google |
| Publisher verification | link the Microsoft Partner Network ID of Authority Closers. Without it, consent shows "unverified" |
| Client secret | 24-month expiry; reveal → `ac-secret.ps1 AC_MICROSOFT_ADS_CLIENT_SECRET <env>` |

**Developer token** (ads.microsoft.com → Tools → Developer settings, signed in as the account's Super Admin):
- the purpose answer: "Sales Xray is a CRM. Businesses connect their own Microsoft Advertising accounts to send offline conversions for leads that became customers. We don't manage campaigns."
- Microsoft says a token for your own accounts is often issued at once. A token used for other advertisers' accounts can take up to about 5 business days.

## Owner steps
1. Create or confirm a Microsoft Advertising account for Authority Closers at ads.microsoft.com. Sign in once with the work account that will own the Entra app.
2. Entra app registration with the values above (his Azure sign-in). The orchestrator can fill the form in his Chrome.
3. Developer settings → request the developer token with the purpose answer above.
4. Optional, for "verified publisher": a Microsoft Partner Network account for Authority Closers.
5. Secrets:
   - `ac-secret.ps1 AC_MICROSOFT_ADS_CLIENT_ID|AC_MICROSOFT_ADS_CLIENT_SECRET|AC_MICROSOFT_ADS_DEVELOPER_TOKEN <env>`;
   - then the compose/SECRETS wiring (Align).

**Expected time:**
- app registration: immediate;
- developer token: immediate to about 5 business days;
- publisher verification: days.

Sources: [Microsoft Q&A on lead forms](https://learn.microsoft.com/en-us/answers/questions/2288903/does-bingads-offer-lead-forms-like-on-facebook-or),
[Cyclr Microsoft Ads setup](https://community.cyclr.com/connector-guides/microsoft/microsoft-ads-setup),
[unified.to: Microsoft Advertising API key](https://unified.to/blog/how_to_get_your_microsoft_advertising_api_key).
