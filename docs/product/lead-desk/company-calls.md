# Calls from the company number

**The owner's go, 27 Oct 2026:** "Bridge via Exotel (Plivo second), ₹5,000/month cap while testing, consented leads only,
recording notice on, … counsel before real customer calls." The decision memo with sources is in the orchestrator's
side notes, `calling-whatsapp-mic-memo-20261027.md`.

## What a seller sees

1. On a lead who asked to be contacted, **Call** rings the seller's own mobile first. The line under Call says
   "Ringing your phone. Pick up, and we'll call Asha."
2. When the seller picks up, the lead hears the recording notice. Then the lead's phone rings, showing the
   **company number**.
3. The call lands on the lead's history by itself (talk time, answered or not), and the lead counts the call.
4. The ended call's recording is offered in the lead's recording panel, like one the phone found.
   - It goes through the usual upload: the same terms, the seller's AI level, and "Analyse my calls
     automatically" when it's on.
   - Otherwise it's one tap.
5. Every other lead (imported lists, numbers typed by hand, anyone who asked more than 7 days ago) is called from the
   seller's own phone, as before.
6. If the company number can't place a call (phone switched off, calling paused), the line says so, with **Call from
   my phone** one tap away.

No price, cost or minute count appears anywhere in the app. They are kept in the ledger and in Admin only.

## Settings → Selling → Calls from the company number

This panel shows only where the workspace has company calling.

- **Everyone:** their own mobile, which is rung first.
- **Owners and admins:**
  - the on/off switch;
  - the company number;
  - which leads may be called from it: the sources, by default lead forms, website forms and chats;
  - the window, by default asked within 7 days.
- **The recording notice:** always on. Its words are shown: "This call is recorded, for quality and training."
  New wording means a new version (`policy.NOTICES`); a version's words are never edited.

## Where it runs (environment settings, names only; values live in Infisical)

| Name                                                                | What                                                                                                                                  |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `AC_TELEPHONY_PROVIDER`                                             | `exotel`, `plivo` (not wired yet) or `fake` (no phone rings; never in production). Unset: off                                         |
| `AC_TELEPHONY_EXOTEL_SID`, `_API_KEY`, `_API_TOKEN`, `_SUBDOMAIN`   | Exotel's keys (owner's account). The subdomain must be Exotel's, e.g. `api.in.exotel.com`                                             |
| `AC_TELEPHONY_WEBHOOK_SECRET`                                       | Signs the status-webhook address. Without it, the app follows a call by polling                                                       |
| `AC_TELEPHONY_TENANTS`                                              | The organisations staff turned it on for (comma-separated tenant ids)                                                                 |
| `AC_TELEPHONY_TEST_NUMBERS`                                         | Outside production, real calls ring only these (the team's phones)                                                                    |
| `AC_TELEPHONY_COUNSEL_CLEARED`                                      | `yes` once counsel has cleared real customer calls. Production places nothing until then                                              |
| `AC_TELEPHONY_MONTHLY_CAP_PAISE`, `_DAILY_CAP_PAISE`, `_RATE_PAISE` | AC's caps and the per-leg-minute rate. Defaults: ₹5,000 a month, ₹500 a day, ₹1.00 a leg-minute (a careful rate until Exotel's quote) |

A staff override per organisation goes in the lead desk settings' `company_calling_limits`, through a
`scripts/data-changes/` script, never through the organisation's own Settings.

## How it's built (`packages/python/ac_platform/lead_desk/telephony/`)

- **`providers.py`:**
  - Exotel's Connect API: seller first; `RecordingChannels=dual`; `CustomField` = our call id; status webhook; the
    notice to the callee with `StartPlaybackToNew=Callee`.
  - The report reader, and recording fetches from Exotel's hosts only.
  - A Plivo stub, and the fake.
- **`policy.py`:**
  - consented leads only (TRAI's 12 Feb 2025 amendment, clause (bh)(ii): explicit consent, 7 days);
  - test phones off production, and the counsel gate;
  - the spend guard: 30-second pulses on both legs, a reserve while a call is live, and the time limit set from the
    budget left.
- **`ledger.py`:** each call is append-only audit events (`lead_desk_company_call`): requested → placed or not placed
  → status … → recording fetched (size and SHA-256). Numbers are kept as their last four digits. No migration.
- **`service.py`:**
  - The request is written first. The provider is asked with **no database transaction open** (the 26 Oct
    provider-call convoy).
  - Reports are folded in under a lock on the lead.
  - The ended call goes on the lead as the seller's `call` event (`via: company`).
- **`http.py`:** the routes (`/v1/lead-desk/calling…`, `/leads/{id}/calls/company`, `/calls/company/{id}`, `…/recording`,
  the webhook and the notice audio).
  - The webhook only nudges: the provider's API has the last word.
  - On development, the webhook and the notice sit under the Leads webhook's Cloudflare Access bypass
    (`/v1/lead-desk/meta/webhook/telephony/…`).

Web: `leads/company-call-client.ts`, `leads/company-call.tsx` (the hook and the line under Call),
`settings/company-calling.tsx`. Starting a call never goes through the write queue: a call placed late would ring
nobody waiting.

## Trying it on dev

- **Without keys:**
  1. Set `AC_TELEPHONY_PROVIDER=fake` and list the organisation in `AC_TELEPHONY_TENANTS`.
  2. In Settings → Selling, turn calling on with any number, and add a mobile.
  3. Open a lead whose source is a form. The fake rings for 6 s, talks until 20 s, then ends with 14 s of talk. A lead
     number ending in 0 doesn't answer. There's no recording.
- **With Exotel's keys:** list the team's phones in `AC_TELEPHONY_TEST_NUMBERS`. Only those ring.
- **Before any real customer call:** counsel's answer (owner steps, item 9), then the AC-GOV-AUD-001 check for Exotel
  as a processor of call audio, then `AC_TELEPHONY_COUNSEL_CLEARED=yes` in production with a release.

## Not in this slice

- Callbacks to the company number routed to the lead's seller (Exotel's passthru applet).
- A "they asked us to call" mark for leads typed by hand.
- Plans and tiers instead of `AC_TELEPHONY_TENANTS`.
- Admin's usage screen.
- Plivo.
- In-app VoIP.
