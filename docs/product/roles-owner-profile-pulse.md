# Business roles, owner transfer, profiles and Pulse

Status: design, 25 Oct 2026. Owner: the sign-in session.
Contract for the Pulse side: `docs/architecture/pulse-identity-contract.md`.

## The asks (owner, 25 Oct 2026, ~17:30 IST)

> Fix this, only two options that is admin and member, there are many roles
> businesses need and this admin is not to be made to all… also make owner is
> one click what and why?

> I need to have the salesperson to save all info… I need Pulse attachment to
> here so anytime any profile pic and all details on Pulse are updated here the
> image updates… add login with Pulse as well… make this feature in Pulse that
> we could login, also we need the org once connect Pulse org with this that
> then fetches the profile pic and all. Also everyone should be prompted to keep
> profile pic as well as choose user id and fill all details so that it's easy
> for us to do telemetry, also business owner can identify who did what work

## Where we are today

- **Roles in the database:** `memberships.role` allows learner, support, admin,
  owner, processing and member. Organisation invites allow admin or member only.
- **"Manager" is hard-coded as owner or admin in about 158 places in 50 files:**
  - the lead desk's `MANAGERS`;
  - `organisation_manage`;
  - `sees_team`;
  - billing;
  - the sign-in rule's `_MANAGERS`;
  - and more.

  There is no single place that says what a role may do.
- **Owner transfer:**
  - The server is sound: exactly one owner, the old owner becomes Admin, and an
    audit event is written (`organisations/service.py`, `transfer_ownership`).
  - The web is one tap on a crown icon and a two-button confirm.
- **Profiles:**
  - A person has a first name and a display name.
  - A photo exists only when it comes from Google (`person_google_profiles`,
    served at `/v1/me/sales-xray-profile/photo`).
  - There is no user id (handle), job title or team.
- **Sign-in:** Google, Facebook and Apple each have a provider module; Pulse
  already connects to Sales X-Ray as an app (Connect, the MCP server, lead stages).

## 1. Business roles

### The roles

| Role | For | May |
|---|---|---|
| **Owner** | the business owner (exactly one) | everything, including transferring ownership and closing the organisation |
| **Admin** | runs the workspace | everything except ownership: members and invites, settings, integrations, AI apps, billing (view and pay) |
| **Sales manager** | team lead | the team's leads (assign, reassign, bulk, targets, nudges), the team's calls and reports, team view. Not members, settings, integrations or billing |
| **Seller** | the salesperson (today's "Member") | their own leads, calls and tasks, as today |
| **Viewer** | analyst, coach, investor | read the team's dashboards, reports, calls and leads. Changes nothing |
| **Finance** | accounts | billing and invoices only, plus their own profile |

- "Admin is not to be made to all" is met by Sales manager: it covers what team
  leads need without settings, members or billing.
- Seller keeps the stored value `member`, so no row changes meaning.

### One place that says what a role may do

`organisations/roles.py`, with a capability map:

| Capability | Owner | Admin | Manager | Seller | Viewer | Finance |
|---|---|---|---|---|---|---|
| `org.own` (transfer, close) | ✓ | | | | | |
| `org.manage` (settings, integrations, AI apps) | ✓ | ✓ | | | | |
| `members.manage` (invite, change role, remove) | ✓ | ✓ | | | | |
| `billing.view` | ✓ | ✓ | | | | ✓ |
| `billing.pay` | ✓ | ✓ | | | | ✓ |
| `team.view` (team leads, calls, reports, activity) | ✓ | ✓ | ✓ | | ✓ | |
| `leads.manage` (assign, bulk, targets, delete) | ✓ | ✓ | ✓ (not delete) | | | |
| `leads.work` (own leads, calls, tasks) | ✓ | ✓ | ✓ | ✓ | | |
| `writes` (any change) | ✓ | ✓ | ✓ | ✓ | | billing only |

Rules for the change:

- **Nothing loosens.** The first commit replaces every hard-coded owner-or-admin
  check with `can(role, capability)`, with exactly today's answers for owner,
  admin and member. That commit is tested on its own before any new role exists.
- **Read-only is enforced in one place.** For Viewer and Finance,
  `require_actor` refuses every non-GET request (403 "Your role can view
  only."). The exceptions are an allowlist: own profile, consent, sign-out, bug
  report and feedback, and Finance's billing routes. A forgotten route stays
  closed, not open.
- **Lead deletion stays with Owner and Admin.**
- **Invites can offer any role except Owner.** Only Owner and Admin change roles.
  An Admin cannot make another Admin into an Owner.
- **Migration 0134** (number to confirm with the orchestrator): widen the
  `memberships.role` and `organisation_invites.role` checks with `manager`,
  `viewer` and `finance`. Rollback while no row uses them.
- **Web:** Organisation → Members shows the role names above, each with a
  one-line "can do" in the role picker. The Android app shares the web.

## 2. Owner transfer is never one click

- **A sheet, not a tooltip:** "Make Rahul Example the owner?"
  - Rahul gets everything, including billing and closing the organisation.
  - You become an Admin.
  - Only the new owner can give it back.
- **Typed confirmation:** type the organisation's name to enable the button.
  The **server** checks it too (`confirm_name` on `POST /organisation/owner`,
  compared case-insensitively). A one-tap client or a script cannot skip it.
- **Who may:** the current owner only, as today. An operator path keeps its own
  reference.
- **After:**
  - the existing audit event;
  - an email to both people, through the outbox: "Ownership of {org} moved
    from A to B on {date}. Not you? Reply to this email.";
  - a corner card for the actor.
- **The crown icon** moves into a "More" menu on the member's row. It is no
  longer one of the row's two buttons.

## 3. Sign in with Pulse, org link and profile sync

Contract: `docs/architecture/pulse-identity-contract.md`. In short:

- **Pulse becomes an OpenID Connect provider:**
  - discovery, authorize with PKCE, token, userinfo, JWKS and revoke;
  - claims: `sub`, name, verified email, `picture` (its URL changes when the
    photo does) and the person's Pulse orgs.
- **Sign in with Pulse in Sales X-Ray:**
  - a generic OIDC provider module, added beside Google, Facebook and Apple;
  - the same identity path: a verified email links to an existing person, and
    a new person gives consent as with Google;
  - the button sits on the sign-in screen and in Settings → Sign-in methods.
- **Org link:**
  - in Organisation → Integrations, an Owner or Admin chooses "Connect your
    Pulse org"; a Pulse org admin approves on Pulse;
  - Sales X-Ray then reads the org's member profiles (name, photo, title,
    team) and subscribes to Pulse webhooks;
  - members are matched by Pulse `sub` (once they have signed in with Pulse)
    or by verified email.
- **Sync:**
  - Pulse sends a webhook (`person.updated`, `person.photo_updated`,
    `membership.*`, `link.revoked`);
  - Sales X-Ray fetches the person from the Pulse API (pull-on-push, so a
    forged or stale payload changes nothing);
  - photo, name, title and team update.
  - A photo the person uploaded in Sales X-Ray wins over Pulse, and Pulse wins
    over Google.
- **Work signals back to Pulse:**
  - kinds: calls analysed, leads worked, follow-ups done, talk time;
  - counts per person per day;
  - off by default; an Owner or Admin switches each kind on;
  - never call content, transcripts or lead contact details.
- **Security:**
  - the link is revocable from either side;
  - tokens are sealed in `integration_secrets`;
  - every link, sync and switch is audited on both sides.
- **Migration 0136** (to confirm): `pulse_org_links`, plus `pulse` in the
  provider names if the identity tables check them.

## 4. Every member completes their profile

- **What:** photo, full name, a user id (`@rahul.e`: 3–30 characters, `a-z 0-9 .
  _ -`, unique across Sales X-Ray, changeable at most once a month), job title,
  team and phone.
- **Prompted, not blocked:**
  - a "Your profile: 3 of 6" card on Home and in Settings, with the next missing
    item as its button;
  - it shows at most once a day, until done;
  - owners and admins see the team's completion in Members ("4 of 7 complete")
    and can send a reminder.
- **Photo:**
  - uploaded in Settings (cropped square, at most 2 MB, stored like the Google
    photo with its SHA-256);
  - or from Pulse or Google, until the person uploads one.
- **Who did what:**
  - every line in a lead's history, every note and every task shows the
    person's avatar and name ("via ChatGPT" stays for app changes);
  - the API adds `actor_id` and `actor_avatar` to history items;
  - the UI is agreed with the builder session.
- **Telemetry:**
  - events keep using the internal person id, which is pseudonymous;
  - the user id is for people, never the telemetry key, so a person can change
    it without breaking history.
- **Migration 0135** (to confirm): `handle` (unique, case-insensitive), `title`
  and `team` on the profile, and a `person_photos` table (one current photo per
  person, its source and SHA-256).

## Slice order

| # | Slice | Migration | Depends on |
|---|---|---|---|
| 0 | AI writes slice 1 (in CI now) | 0131, 0132 | — |
| 1 | Owner transfer: sheet, typed name checked on the server, emails | — | — |
| 2 | Roles A: the capability map, every check moved, no behaviour change | — | — |
| 3 | Roles B: Sales manager, Viewer and Finance; the read-only guard; Members UI | 0134 | 2 |
| 4 | Profile A: user id, title, team, photo upload, completion card | 0135 | — |
| 5 | Profile B: avatars on history, notes and tasks (with the builder) | — | 4 |
| 6 | Sign in with Pulse (generic OIDC provider) | — | Pulse OIDC live |
| 7 | Pulse org link and initial profile sync | 0136 | 6, Pulse org-link API |
| 8 | Pulse webhooks: live sync | — | 7 |
| 9 | Work signals to Pulse (switches) | — | 7 |

Slices 1, 2 and 4 can start now. Slices 6–9 wait for the Pulse card.
