# Universal lead intake: every source in one click

Owner, 25 Oct 2026, ~16:00 IST: "design a pipeline easy import leads from other CRMs like Privyr one
click Zoho and LeadRat and what not so easiest once click import without a single thing stress or
verification auto added… making our own leads universal intake engine that stores objects from
everywhere… a nice webpage landing page connect to this option… google analytics meta analytics…
attachment with our app as well".

This doc is the design. The orchestrator owns sequencing. Each slice is one lane task through wb-ci.

## 1. What exists today (25 Oct 2026, v0.89)

- **One path.** Every source ends in `LeadDesk.ingest`: one record in, its original kept as the lead's
  `payload` (16 KB at most), deduped, then given out by the lead rules.
  - Sources: file upload (CSV and XLSX, `capture.read_file`), paste, website or Zapier webhooks
    (`/capture/{source}`), Google Sheets sync, Meta lead forms, and the sandbox seed.
- **Dedupe.**
  - The same source reference (a form's or ad's own id, or a hash of a file row) is "known" and
    changes nothing.
  - The same phone is a "repeat": one lead, plus a history line.
  - Email is not used yet.
- **Files.** A preview shows the headers and suggests a column per field (`capture.ALIASES`), plus
  stage and owner columns. Applying keeps a row's stage and owner when they match the pipeline and
  the team. A Lost or Junk lead without a reason is "Imported".
- **Gaps against the order:**
  - Column names only cover generic headers, so CRM exports need hand-mapping.
  - Cells holding two numbers are refused.
  - A record without a phone is never deduped.
  - Raw objects live only on the lead (the first one), so a re-sent record that changed is lost.
  - No CRM is pulled directly.
  - There is no single page listing every way in.

## 2. The engine

Every source is a **connection**. Every record a connection delivers is a stored **intake object**.
Every object resolves to one **lead** through the same `ingest`.

| Piece                                                        | What it holds                                                                                                                                                                                                                    | Rule                                                                                                                                                                       |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Connection (`lead_desk_connections`, new)                    | The kind (file, webhook, sheet, meta, oauth:zoho, key:leadsquared, …); its label, state, cursor, last run and errors; its saved column map; a reference to its secret                                                            | Secrets are encrypted at rest with the app's token key, never logged or shown again; one connection per account per workspace                                              |
| Intake object (`lead_desk_intake_objects`, new, append-only) | The connection, the source's own id, the raw record (bounded), its sha256, when received, the resulting lead and outcome (created, repeat, known, updated, skipped), and `supersedes` (the earlier object of the same source id) | Never edited or deleted, except when its lead is deleted through the app's own delete. A changed record for the same source id is a new object that supersedes the old one |
| Lead (existing)                                              | The normalised fields, provenance (`source`, `source_label`, `source_ref`) and history                                                                                                                                           | A superseding object fills **empty** fields only and adds one history line. It never overwrites what a seller typed                                                        |

**Dedupe order:**

1. The same connection and source id: "known" (or "updated" when the raw record changed).
2. The same phone (E.164; a cell with several numbers uses the first, the others go in the payload):
   "repeat".
3. No usable phone and the same email (lower case): "repeat".
4. Otherwise a new lead.
   A phone match with a different email is still the same lead. The email is kept in the payload, and
   the lead page may show "also used".

**Provenance:** the lead keeps the first object's source. Every repeat or update adds a history line
naming its connection ("Again from Zoho CRM export"), so reports count each lead once and can still
say where else it came from.

**Mapping** (pure, `capture.py`):

- Aliases for every field, including CRM export spellings (section 3).
- A first and last name are joined.
- When the chosen phone column is empty, the next phone-like column is used (Zoho has "Phone" and
  "Mobile").
- Status words map to stage kinds ("Attempted to Contact" is Not Connected, "Qualified" is Interested,
  "Closed Won" and "Converted" are Won, "Junk" and "Spam" are Junk).
- Owners match by full name, by a first name only one teammate has, or by email.
- A map saved on a connection is reused.

**One click:**

- When name or phone is matched and at least 90% of rows yield a lead, the preview is one line:
  "Zoho CRM export · 340 leads · 12 already here · Import".
- The column list stays behind "Change columns".
- The CRM is recognised from its headers, and its name becomes the lead's source label
  ("Zoho CRM export: leads.csv").

**Pulls** (API key and OAuth):

- A background job per connection reads pages since its cursor (updated-since), at most N objects a
  run.
- It respects the vendor's rate limits and backs off on 429.
- Each object goes through the dedupe above, so a rerun is harmless.
- The first pull imports everything; later pulls take new and changed records.

**Limits:**

- 1,000 objects per file and per pull page.
- Raw records up to 16 KB (64 KB for CRM pulls, with long text fields cut and marked).
- A failed object is kept with its error and shown on the connection, never dropped silently.

## 3. Sources and CRMs

The ranking is **assumed**: Indian SMB sales teams in our market (education, real estate, insurance,
B2B services), ordered by how often our testers and AC's own team name them. To make it measured,
the importer records which CRM each file came from (a count, not canonical state) and the "Connect"
page records which button was pressed. API facts are from vendor documentation where cited; anything
marked _unverified_ needs a vendor check before building.

| Rank | CRM                   | Pull route                                                                                                                                                                | Status of evidence                                                                                                                                                     | Plan                                                                 |
| ---- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| 1    | Zoho CRM              | OAuth 2.0 REST and Bulk Read. India data centre `accounts.zoho.in` / `zohoapis.in`; scopes `ZohoCRM.modules.leads.READ` (+ `ZohoCRM.bulk.read`). Also CSV export          | API: third-party guides, official reference to confirm ([knit](https://www.getknit.dev/blog/zoho-crm-api-integration-guide-oauth-2-0-use-cases-step-by-step-tutorial)) | File now; **OAuth first**                                            |
| 2    | LeadSquared           | Access key + secret key (Settings > API and Webhooks), region host (e.g. `api.in21.leadsquared.com`), `Leads.GetByPaging`. Also export                                    | Official developer centre ([apidocs](https://apidocs.leadsquared.com/?p=518))                                                                                          | File now; **API key second**                                         |
| 3    | Privyr                | No pull API found. CSV export of the client list (Integrations > Import/Export Clients > Export Client List, filtered by date, group, team member). Inbound webhooks only | Official help ([export](https://help.privyr.com/knowledge-base/client-import-export), [webhooks](https://help.privyr.com/?p=3633))                                     | File (its CSV) now; ongoing via Zapier/webhook from its lead sources |
| 4    | TeleCRM               | Workspace webhook URLs (POST) for inbound; a "custom API" is marketed but undocumented publicly; export _unverified_                                                      | Official LMS pages for webhooks ([lms](https://lms.telecrm.in/telecrm/integrating-with-telecmi-ivr-co24ch10tp3))                                                       | File; ask vendor about pull                                          |
| 5    | Kylas                 | API key (CRM Settings > Integrations > API Key; Explore and Elevate plans), base `api.kylas.io/v1`                                                                        | Key: official support ([kylas](https://support.kylas.io/portal/en/kb/articles/how-to-use-api-key-in-to-access-kylas-apis)); base URL: community                        | File; API key third candidate                                        |
| 6    | LeadRat (real estate) | No public API or export documentation found; portals (99acres, MagicBricks, Housing) feed it                                                                              | _Unverified_ ([listing](https://www.techjockey.com/detail/leadrat-crm))                                                                                                | File from its export, if any; ask vendor                             |
| 7    | HubSpot               | OAuth 2.0 public app or a private-app token; CRM objects and exports API (`crm.export`)                                                                                   | Official docs ([exports](https://developers.hubspot.com/docs/api-reference/latest/crm/exports/create-export.md))                                                       | File; OAuth after Zoho                                               |
| 8    | Freshsales            | API key, `Authorization: Token token=…`, account domain                                                                                                                   | Official docs ([developer.freshsales.io](https://developer.freshsales.io/api/))                                                                                        | File; API key later                                                  |
| 9    | Pipedrive             | API token or OAuth 2.0                                                                                                                                                    | Vendor docs (not re-checked today)                                                                                                                                     | File; later                                                          |
| 10   | Salesforce            | OAuth 2.0 connected app; REST or Bulk API (API access depends on edition)                                                                                                 | Vendor docs (not re-checked today)                                                                                                                                     | File (report export)                                                 |

Other ways in, and their honest state:

- Meta lead forms: live, while the Meta app is in development mode (test leads only) until App
  Review.
- Website forms, Zapier, Make and Pabbly: live (the webhook).
- Google Sheets: live.
- CSV and XLSX: live.
- Google Ads lead forms: the webhook (Google's lead form webhook). To verify end to end.
- LinkedIn Lead Gen Forms: waits for LinkedIn's API approval.
- IndiaMART (its Lead Manager pull API with a key) and JustDial: candidates. _Unverified_, so ask
  testers which matter.

**First direct pulls, after files:** Zoho CRM (OAuth), then LeadSquared (API key), then Kylas or
HubSpot by what testers use. Each OAuth app needs our app registered with the vendor:

- the client id and secret go to Infisical by the owner's process (OWNER-APPROVED SECRETS);
- the customer then connects in one click (Settings → Integrations, as the self-serve rule asks).

## 4. "Connect your leads": one page

`/leads/connect` (signed in) plus a public landing section on the website. It shows one row per
source: the logo-free name, one button and an honest state:

- **Live:** connect now.
- **By file:** shows "Export from <CRM>: Settings > … then drop it here", with the drop zone right
  there.
- **Waiting for platform review:** for example LinkedIn, or Meta for real leads.
- **Coming next:** registers interest, counted.
  Each connected source shows what came in: last received, how many, and errors. There's no
  verification step anywhere: a file's preview is the only stop.

## 5. Google Analytics 4 and Meta Pixel (planned; check with the orchestrator before shipping)

- **Where:** the public site and the signed-in app's page views and a few product events (signed up,
  connected a source, imported, first call). Never lead names, numbers, emails or any lead data.
  Hashed identifiers only if the privacy page says so.
- **Consent:**
  - A choice on first visit (accept analytics / only essential), stored per device and changeable in
    Settings.
  - Nothing loads before "accept". This is a consent-mode default of denied.
  - The privacy page names Google Analytics and Meta Pixel, what they get and how to opt out.
  - The Play listing's data safety form is updated before the app build that carries them.
- **State:** analytics events never become canonical progress, payment or lead state (AGENTS.md).
  They are counts for growth only. The app's own telemetry stays the source of truth.
- **Keys:** the measurement id and pixel id are public identifiers, set per environment in Admin.
  Dev and staging use test properties.

## 6. Slices

1. **Files from any CRM, one click (no migration).**
   - CRM recognition and export aliases.
   - First and last names joined; multi-number and multi-email cells; the next phone column when one
     is empty.
   - Status-word stages; owners by email.
   - Email dedupe when there is no phone.
   - The source label names the CRM.
   - The preview carries `detected`, and the commit carries it back.
   - Tests: a fictional export per CRM, through preview and commit.
2. **Intake objects and connections (migration; number from Align 3).**
   - The raw object store; supersede on change.
   - "Updated" and "again from" history lines.
   - Saved maps per connection.
3. **"Connect your leads" page and landing section.** The builder draws it; Lead OS supplies
   `GET /intake/catalogue` (sources, states, counts).
4. **Zoho CRM OAuth pull,** then LeadSquared API key, then the next by measured demand.
5. **GA4 and Meta Pixel with consent**, after the orchestrator's go.

## 7. Acceptance

1. A Zoho, HubSpot, Pipedrive, Salesforce, LeadSquared, Kylas, Freshsales, Privyr, TeleCRM or LeadRat
   style export imports with no column picked by hand. Name, phone, email, company and city land;
   stage and owner land when they match.
2. A cell "98765 43210, 91234 56780" gives the first number; the other stays in the payload.
3. A row with no phone and an email already on a lead is a repeat, not a new lead.
4. Importing the same file again adds nothing.
5. The lead's source says which CRM's export it came from.
6. No verification step: drop the file, see one line, press Import.
