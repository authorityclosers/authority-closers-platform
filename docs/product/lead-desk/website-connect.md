# Website connect: one line, every form a lead

Owner, 30 Oct 2026: "connecting websites matters a lot to customers, the data is crucial, and today's way of adding
websites and landing pages is a frustrating experience." This is the design behind Leads → Sources → Websites and
landing pages, migration 0145 and `apps/sales-xray-web/public/sx.js`.

## What the customer does

1. Leads → Sources → **Add website**. The sheet shows one line with the organisation's key:

   ```html
   <script src="https://salesxray.authorityclosers.com/sx.js" data-key="sxw_…" async></script>
   ```

2. They copy it (or tap **Email it to your web person**) and paste it where their builder takes a head script. The sheet
   has two or three steps for WordPress (WPCode), Elementor, Webflow, Framer, Wix, Shopify and anything else.
3. They type their address and tap **Open site**. The site opens with `?sx_check=1`, which shows "Sales X-Ray is
   connected" on the page, and the sheet says **We saw yoursite.com at 10:42 · 2 lead forms found** by itself (it reads
   the card every 3 s while open).

From then on every lead form on every page with the line becomes a lead. New hosts that carry the line appear in the
list by themselves (landing pages on a subdomain, a second site). Each site opens a sheet with its pages: visits, lead
forms, new leads and how many visits filled a form over 30 days, plus **Send test lead**, **Pause** and **Remove**.

## Why one line (research)

The full note, with sources, is in the session notes (`website-connect-20261030/research.md`). In short:

- None of HubSpot, Zoho, LeadSquared or Pipedrive documents "one line, every form, click ids included". HubSpot is
  closest (tracking code plus "collect data from website forms") but skips JavaScript submits, single-page apps and
  forms added late. Zoho and Pipedrive make you build their form. LeadSquared's script tracks UTMs but not forms.
- Google's own recipe for offline conversions is the same pattern: one script on every page that reads `gclid` and
  sends it with the form. Meta documents `_fbc` as `fb.1.<ms>.<fbclid>`, built from the address bar when there is no
  pixel.
- Webhooks from Elementor, Typeform, WPForms or Google Forms carry no UTM or click ids unless hidden fields add them,
  and Zapier's catch hook is a paid plan. A hosted form is the right fallback for sites with no code box.

So the line is the primary path; the generic **Website form** source (address + secret key, for Make, Pabbly, Zapier,
Elementor Pro webhooks and developers) stays under Other ways to add leads.

## How it works

| Part | Where |
|---|---|
| The script | `public/sx.js`: hello once per page (address, title, lead forms, builder), and each lead form's answers on submit with the visit's UTM tags, click ids (`gclid`, `gbraid`, `wbraid`, `fbclid`, `msclkid`, `ttclid`, `li_fat_id`) and Meta's `_fbc` / `_fbp`. It catches the `submit` event in the capture phase, `form.submit()` from a site's own script, and `window.sx("lead", {...})` for forms that aren't `<form>`s. A lead waits in the browser until Sales X-Ray has it, so a send cut off by the page closing or a release goes again on the next page. |
| Public calls | `POST /v1/lead-desk/site/hello` and `/site/lead` (`lead_desk/websites_http.py`): no session; the key (looked up by SHA-256) and the page's own Origin are the authority. JSON as `text/plain`, so the browser needs no preflight; CORS without credentials. |
| Filing | `lead_desk/websites.py` → `LeadDesk.ingest(source="webhook", kind="website")`: deduped by phone, then email; the same person on the same site within 30 minutes is one lead ("known"); the lead rules give it an owner. |
| The record | The form's answers at the top (shown on the lead's sheet), `Page` and `Came from` in plain words ("Google Ads · Diwali offer"), and the raw tags under `attribution` (with `first_touch`) and the site under `website`. |
| Counters | `lead_desk_site_pages`: per page and day, views, lead forms, form fills, new leads and bot fills turned away. No visitor id, no IP address. |
| The key | A `webhook` source with `config.website`, hidden from the generic Sources list. It is public (it sits in the page), so the generic `/capture/{id}` route refuses it, and a new key stops the old line everywhere. |

### Ad platforms

The stage senders (`journey/providers`) read click ids from the lead's record, including its `attribution` part
(`click_ids`). So website leads with a `gclid`, `gbraid` or `wbraid` (or a hashed email/phone, for enhanced conversions
for leads) already reach Google Ads offline conversions, and Microsoft, TikTok and LinkedIn the same way, through the
existing connectors. Meta's sender takes only Meta lead-form leads today (Conversions API for CRM needs Meta's
`lead_id`); website leads with `fbc` / `fbp` need a website event without `lead_id`. That change is agreed with the
Meta/Google session rather than duplicated here.

### Spam and bots

- The browser must send an Origin that matches the page it names.
- Turned away and counted (the bot is told nothing): a headless browser (`navigator.webdriver`), a form sent in under
  3 s with no key press or tap, a link in a name or phone field.
- Per address: 60 hellos a minute and 8 leads per 10 minutes (`http/rate_limits.py`). Per site: 30 leads per 10 minutes.
- Never kept: passwords, card numbers (also by shape), OTPs, identity numbers, captcha tokens and form plumbing.
- A form needs a phone or an email to become a lead.

## Not in this slice (follow-ups)

- Meta website events for website leads with `fbc` / `fbp` (with the Meta/Google session).
- A hosted form for sites without a code box (bio links, iframe-only builders).
- The release spool for `/site/lead` (the browser keeps and resends, so a hold delays leads but doesn't lose them).
- "Website" as a pipeline source choice (the route already passes `kind="website"`).
- Pruning page counters older than 400 days.
