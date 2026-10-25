# Sign in, then leads flow: one-tap ad connections after Facebook, Google or LinkedIn sign-in

Owner, 25 Oct 2026: "once someone logs in with Meta for example they are automatically
prompted or automatically the pages and all are fetched and they can smoothly fetch leads".
This is the plan. It's built after the platform reviews have started.

## What can and can't be one step

**Sign-in and lead access are two different Meta apps.**
- "Continue with Facebook" uses **Sales Xray Sign-in** (a consumer app, `public_profile` and `email`, Live).
- Pages and leads need **Sales Xray Leads** (a business app, Facebook Login for Business, with `pages_*`, `leads_retrieval` and `business_management`).
- Meta keeps consumer and business permissions apart, and one dialog can't grant both.

So the smooth version is **sign in → one tap → Meta's own dialog (already signed in, no password) → done**, not zero taps.

**Who may connect:**
- Leads belong to an organisation, so only an **owner or admin of an organisation workspace** connects a Page (`LeadDesk._require_manager`).
- A seller who signs in sees "Your owner connects Facebook leads", with a one-tap request to the owner, never the dialog.
- A Personal workspace keeps no leads.

**What depends on Meta's approvals** (submission 29297824896491997, pending since 19 Oct; Messaging not yet submitted):

| Piece | Before Advanced Access | After Advanced Access + Live |
|---|---|---|
| The prompt after sign-in | shows for everyone who qualifies | same |
| Meta's dialog | works only for people with a role on our app | anyone who manages a Page |
| Pages listed and switched on | works | works |
| Leads that arrive | **only test leads** made by people on our app | every lead |
| The card's honest line | "Meta approval pending: test leads only for now" (shipped in v0.89) | gone (`META_REVIEW = ("approved", …)`) |

## The flow (Meta)

1. **The trigger.**
   - The person signs in with Facebook, or opens Home.
   - They are an owner or admin of an organisation workspace.
   - That workspace has no Meta lead source.
   - They haven't said "Not now" in the last 14 days.
2. **The prompt.** A card on Home and a one-time sheet after the first such sign-in:
   - "Bring your Facebook and Instagram leads into Sales Xray? Your Pages and forms are found for you."
   - buttons [Connect Facebook leads] and [Not now].
3. **Meta's dialog.** It's the existing `/v1/lead-desk/meta/connect` with a new `auto=1`, carried in the signed state. The person picks Pages ("All current and future Pages" is offered) and allows.
4. **Auto switch-on.** In `finish_meta`, when the state says `auto`, each new Page is created **on**:
   - forms "all";
   - subscribed to the `leadgen` webhook (`subscribed_apps`);
   - backfilled (last week at once, then 90 days in the background, as Connect does today).
   - Pages that were already connected keep their own on or off setting.
   - A Page whose business uses the Leads Access Manager without allowing us gets its existing "Allow Sales Xray in Leads access" reason.
5. **Back in Sales Xray:**
   - a corner card says "3 Pages connected. 12 recent leads brought in";
   - Leads opens on New;
   - Settings → Connected apps shows the Pages, each with a switch.
6. **The Android app:** the same, through the system browser (`app_return`), as today.

## Google (Ads lead forms) and LinkedIn (Lead Gen Forms)

- **Google:**
  - Sign in with Google uses `openid email profile` on the sign-in client.
  - The Ads connector needs the **sensitive** `adwords` scope on the Ads client (project `ac-sales-xray-ads`).
  - Incremental authorisation (`include_granted_scopes`) works only within one client. So it's the same pattern: sign-in, then a one-tap "Connect Google Ads" (Google's consent, already signed in).
  - `auto=1`: every accessible account that has lead forms is turned on. Our webhook goes into its forms, and 30 days are pulled.
  - It depends on OAuth verification (until then, "unverified app" warnings and a 100-user cap) and on Basic API access.
- **LinkedIn:**
  - There's no LinkedIn sign-in today. Adding "Sign in with LinkedIn" (OpenID Connect product) is its own small task.
  - The lead part is the same pattern once the Lead Sync API is granted: list the ad accounts and Lead Gen Forms, subscribe `leadNotifications`, backfill.
- **Microsoft:** no lead forms by API confirmed (see `microsoft-ads-api-access.md`). It's for lead stages back only.

## Build (after the reviews start; one task per lane)

1. **API:**
   - `auto` in the Meta connect state (`connectors/meta.make_state`), and `finish_meta` switches new Pages on, subscribes them and starts the backfill.
   - The same `auto` for the Google Ads callback (turn on accounts with lead forms).
   - A `GET /v1/lead-desk/connect-suggestions` endpoint for the prompt: which providers this person signed in with, whether each lead connector is set up and connected here, their role, and the "Not now" date.
2. **Web:**
   - the Home card and the one-time sheet;
   - "Not now" saved per person;
   - the member variant ("Ask your owner" sends one notification to the owners);
   - the corner card on return.
3. **Tests:**
   - the state round-trip with `auto`;
   - new Pages created on (and existing ones untouched);
   - a backfill queued;
   - suggestions for owner, admin, member and Personal;
   - the web card's states (connect, not now, member, connected).
4. **Screens:** a fixture route for the card and the sheet, shot at 390 and 1440 in light and dark, then a review against the sales-xray-ux rubric.
