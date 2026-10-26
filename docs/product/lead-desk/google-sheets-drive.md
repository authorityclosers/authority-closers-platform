# Google Sheets and Drive for Sales X-Ray (design, 27 Oct 2026)

The owner asked, through the orchestrator: "connect all Google apps… Drive as well… Google Sheets integration is important, even making folders on Drive and managing all data there".

This is a design for review. Nothing is built yet. Slice 1 is at the end.

## Rules this design keeps

- **Scopes:** only `drive.file` (non-sensitive), with the Google Picker.
  - With `drive.file`, Sales X-Ray sees only the files a person picks in the Picker and the files Sales X-Ray creates. It never sees the rest of their Drive.
  - The Sheets API works on those files under `drive.file`. Google's Sheets scope list names it as the recommended scope ([Sheets scopes][sheets-scopes], [Drive scopes][drive-scopes]).
  - We don't use `drive` (restricted, which needs a security assessment) or `spreadsheets` (sensitive).
- **One Google project and consent screen:** `ac-sales-xray-ads`, "Sales X-Ray". The scopes are `openid`, `email`, `profile`, `adwords` and `drive.file`.
  - `adwords` is sensitive and needs brand verification anyway.
  - `drive.file` adds no extra review.
- **Owners and admins only** connect or disconnect. Sellers never see a token. Tokens are sealed with `AC_LEAD_DESK_TOKEN_KEY`, as the Google Ads and Meta connectors already do.
- **Sales X-Ray stays the record.** The Sheet is the client's copy and backup, never the other way round. Where the Sheet changes Sales X-Ray, it goes through the app's own moves and leaves a history line.

## 1. One Google connection per organisation

Today Google Ads keeps a refresh token on each Ads account's lead source. Sheets and Drive need the same Google sign-in, so the design moves to one connection per organisation:

- **Table `lead_desk_google_connections` (one migration):**
  - organisation;
  - the person who connected;
  - the Google account's `sub` and email;
  - the scopes granted;
  - the sealed refresh token;
  - created, and revoked.

  One live row per organisation. The Ads accounts point to it, and their old per-source tokens keep working until reconnected.

- **Incremental consent:** each feature asks only for its own scope, with `include_granted_scopes=true`.
  - Turning on Ads asks for `adwords`.
  - Turning on Sheets or Drive asks for `drive.file`.
  - Someone who only wants a Sheet never sees an Ads permission.
- **One redirect:** the existing `<Sales X-Ray URL>/v1/lead-desk/google/callback`, already registered. The signed state carries what the sign-in was for (`ads` or `files`), so no new redirect URI is needed.
- **Settings → Connections → Google** shows:
  - the Google account and who connected it;
  - what it's used for (Ads, Sheets, Drive);
  - **Disconnect**, which revokes the token at Google (`oauth2.googleapis.com/revoke`) and stops every use.
- **If the person who connected leaves,** the connection keeps working until it's revoked. The card names them and offers "Reconnect as me".
- **On the phone app,** Google refuses sign-in inside an app's web view, so Connect opens the phone's browser, as Google Ads and Meta already do. The Picker also opens there.

## 2. Google Sheets

### a) Import from a Google Sheet (Picker)

- **Where:** Lead sources → **Import from Google Sheet**.
- **Flow:**
  1. The Google Picker opens, showing spreadsheets only.
  2. The person picks one, and `drive.file` now covers that file.
  3. They pick a tab.
  4. Sales X-Ray reads it with `spreadsheets.values.get` into the import screen that exists today. That screen matches columns, including stage and owner (the "called by" mapping), and shows the preview count.
- **What it replaces:** today's "Google Sheet" source, which asks the client to share the sheet with **Anyone with the link**. That makes the client's lead list public. The Picker needs no public link. The old source keeps working until its owners move.
- **Later, "keep checking for new rows":** every 10 minutes Sales X-Ray reads the sheet again and files new rows. Rows it has seen read as "known", so nothing doubles. That's the same safety the audit found for today's sheet sync.

### b) Keep a copy in Google Sheets (append-only, slice 1)

- **Turning it on** creates a spreadsheet, "Sales X-Ray leads · <organisation>", in the organisation's Sales X-Ray folder (section 3). Being app-created, it's covered by `drive.file`. Its first row holds the column names:
  - Received, Name, Phone, Email, City, Source, Stage, Owner, Lead ID, Link.
- **Each new lead** adds one row (`spreadsheets.values.append`).
- **Sending is durable:** an outbox table, `lead_desk_sheet_rows`, holds one row per lead per sheet. The API's every-minute loop sends them in batches.
  - A lead is written once, even across restarts and releases, because the outbox key is (sheet, lead).
  - A failure waits and retries, and the card says when the last send worked.
- **The client owns the Sheet.** Disconnecting stops new rows and never deletes the Sheet.

### c) Stage and owner changes (slice 2)

- **Sales X-Ray to the Sheet:** a stage or owner change updates that lead's row. It's found by Lead ID; a hidden column keeps the row number, which is re-found by Lead ID if someone sorts the sheet.
- **The Sheet to Sales X-Ray, opt-in:** the "Stage" and "Owner" columns are read every 10 minutes.
  - A changed value that names a real stage or teammate becomes the app's own move, with the history line "from the Google Sheet".
  - Anything else is left alone, and listed on the card as "3 rows we couldn't read".
  - If both sides changed, Sales X-Ray wins and the Sheet is rewritten.

## 3. Google Drive: a "Sales X-Ray" folder per organisation

- **On first use,** Sales X-Ray creates "Sales X-Ray · <organisation>" with Exports, Call reports and Imports inside. Being app-created, they're covered by `drive.file`; a quick test confirms that folder creation works under `drive.file` before building on it.
- **Saving there:**
  - **Leads export:** "Save to Drive" on the Leads export (CSV or XLSX) saves to Exports.
  - **Call report PDF:** "Save to Drive" on a call report saves the PDF to Call reports, named "<date> · <lead> · <seller>". It's only for the people who can open that report today.
  - **Imports:** a file picked from Drive with the Picker is copied to Imports when it's imported, so the client can see what came in.
- **Never** a whole-Drive browse or search. Only files picked or created.

## 4. Privacy and limits

- **Privacy policy** gets one line, for the owner to approve: "When you connect Google Sheets or Drive, Sales X-Ray creates and updates only the files and folders you choose or that it makes for you. Data copied there is in your Google account and under your control."
- **Data stays where it is.**
  - Lead data goes only to the organisation's own Google account.
  - Nothing goes to an AI model.
  - Call reports go only to the folder the organisation chose.
- **Rate limits:**
  - The Sheets API allows about 300 requests a minute per project; appends are batched each minute per sheet, one request per sheet.
  - Drive uploads happen only on a person's tap.

## 5. What Google needs (no new review for `drive.file`)

- **[Orchestrator, Cloud Console, ac-sales-xray-ads]**
  - Enable the Google Sheets API, the Google Drive API and the Google Picker API.
  - Add the `drive.file` scope to the "Sales X-Ray" consent screen, plus `openid`, `email` and `profile`.
- **[Orchestrator, then owner]** Create an API key for the Picker (browser key). Restrict it to the Sales X-Ray web addresses and the Picker API. The owner puts it in Infisical as `AC_GOOGLE_PICKER_API_KEY`.
- **The project number** is the Picker's "app ID". It's public, and goes in settings as `AC_GOOGLE_PROJECT_NUMBER`.
- **The OAuth client and redirect** are the ones the Google Ads checklist already creates.

## Slice 1 (for your go)

1. **The shared Google connection.**
   - The table above (one migration; I'll ask Align for the number).
   - Connect and Disconnect.
   - Scopes added per feature.
   - The Ads connector reads its token from the connection when there is one.
2. **Import from Google Sheet with the Picker.**
   - `GET /v1/lead-desk/google/picker`: the client ID, the Picker key and the app ID, for owners and admins.
   - `POST /v1/lead-desk/imports/google-sheet`: a spreadsheet ID and a tab, into the existing preview and commit.
3. **Keep a copy in Google Sheets, append-only.**
   - `POST`/`DELETE /v1/lead-desk/google/sheet-copy`: the Sheet in a new "Sales X-Ray" folder.
   - The `lead_desk_sheet_rows` outbox.
   - A sender in the API's minute loop.
4. **Tests:**
   - Google's APIs faked (httpx `MockTransport`);
   - a lead is written once across retries;
   - a revoked token stops sends and says so;
   - only owners and admins connect;
   - the Picker config never carries a secret.
5. **Web (builder):** the Connections card, the Picker launcher (`apis.google.com/js/api.js`) and the two buttons. On the phone app, both open in the browser.

**Size:** about 700 lines of API and tests, one migration, and about 250 lines of web.

**What it needs first:** the Ads checklist's OAuth client, the three APIs enabled, and the Picker key. Slice 2 (stage and owner both ways) and the Drive exports come after.

[sheets-scopes]: https://developers.google.com/workspace/sheets/api/scopes
[drive-scopes]: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
