# The test world: three fictional companies that sell every day (bible, 14 Nov 2026)

The owner, 13 Nov 2026 (via the orchestrator): "a proper organisation, proper sales, a coherent story. Daily
calls coherent, testing coherent, flowing. Sellers perfect, accounts perfect. Calling durations, work hours
followed… agents that see the screen, being the seller, and report bugs on their own… each update tests a
different thing."

This is the world those tests live in: who works where, what they sell, who calls them and how each story
moves from one day to the next. The machine-readable twin is `scripts/call_testing/world.py`; the daily runner
plays it. Everything here is fictional. Every workspace name starts with "TEST ·", every phone number is
`+91 00000 xxxxx` (no such Indian number exists), every email is at `example.com` or a plus-alias of AC's own
mailbox, and no real customer is ever in it.

## The three companies

### 1. TEST · Sahyadri Homes (Pune): a real-estate channel partner

Sells new flats for two builders and handles resale for flat owners. 4 sellers and an owner-manager.

| Person | Role | Speaks | Strength | What coaching keeps finding |
|---|---|---|---|---|
| Rajesh Bhonsle | Owner and manager | Marathi, Hindi, English | Knows every builder | Calls the team mid-visit to chase numbers |
| Priya Nair | Senior seller, 6 years | English, Hindi | Closes; strong on payment plans | Talks too much; goes to price before needs |
| Amol Jadhav | Seller, 2 years | Marathi, Hindi | Rapport; families trust him | Never asks the budget or who else decides |
| Faiz Shaikh | New seller, 3 months | English, Hinglish | Energy; follows up fast | Folds on the first objection; forgets the next step |
| Sneha Patil | Inside sales, cold lists only | Marathi-English | Gets through 60 dials a day | Gives up after the first "not interested" |

**What they sell** (prices all-in, as the sellers quote them):
- Sunleaf Residences, Hinjawadi (builder: Sunleaf Developers): 2BHK ₹68–76 L, 3BHK ₹92–98 L; Tower A ready by
  December, Tower B a year later.
- Riverbend Towers, Kharadi (builder: Riverbend Group): 3BHK ₹1.05–1.25 Cr, 4BHK ₹1.6 Cr; ready to move.
- Resale mandates: a flat owner lists with Sahyadri for 1% commission on the deal.

**Leads come from:** Meta lead ads (many, low intent), the HomeFinder portal (fictional), the website form, site
walk-ins, referrals from past buyers, and an old enquiry list worked cold.

**Who picks up their calls:** first-time buyers, upgrading families, investors who want rental yield, NRIs buying
for parents, flat owners who want to sell, tenants who only want to rent (not a fit), other brokers who want to
co-broke, and the odd wrong number.

### 2. TEST · Suryoday Solar (Nashik): rooftop solar for homes and shops

| Person | Role | Speaks | Strength | What coaching keeps finding |
|---|---|---|---|---|
| Vikas Thorat | Owner, runs installations | Marathi, Hindi | Technical trust | Discounts to close |
| Ganesh More | Senior seller, 8 years | Marathi | Explains savings in rupees a month | Skips the site-survey booking |
| Kavya Iyer | Seller, commercial roofs | English, Hindi | Numbers and payback | Long monologues; few questions |
| Rahul Pawar | New seller | Hinglish | Persistent | Can't answer subsidy questions; promises dates |

**What they sell:** a 3 kW home system ₹1.9 L before the government rooftop subsidy; 5 kW ₹2.9 L; a 25 kW shop or
school roof ₹11 L; yearly maintenance ₹4,500. **The steps:** enquiry → site survey → quotation → net-meter
paperwork → installation.

**Who picks up:** homeowners with big summer bills, housing-society secretaries, shop owners, schools; existing
customers calling about a dirty panel or a meter delay (support, not sales); the electricity office's clerk
(internal paperwork).

### 3. TEST · Kavach Insurance Advisors (Thane): term, health and motor cover

| Person | Role | Speaks | Strength | What coaching keeps finding |
|---|---|---|---|---|
| Farhan Merchant | Owner-manager | English, Hindi | Renewals book | Reviews only the wins |
| Anjali Rao | Top seller | English | Needs analysis; families | Skips the medical-disclosure questions |
| Sachin Gaikwad | Renewals desk | Hindi, Marathi | Never misses a renewal date | Reads the script word for word |
| Deepa Menon | New seller | English | Warm | Lets the call end without a follow-up time |

**What they sell:** term cover ₹1 Cr for ₹12,000–18,000 a year, a family health floater ₹10 L for
₹22,000–28,000 a year, motor renewals. **Non-sales calls:** claim help for existing customers, chasing KYC
documents (onboarding), the insurer's back office (internal).

## How a day goes

- **Work hours:** Monday to Saturday, 10:30 to 19:00, lunch 13:30–14:15 (Kavach: 10:00–18:30). No call is stamped
  outside them; a seller's calls never overlap.
- **Volumes per seller per day:** real estate 40–60 dials, solar 25–35, insurance 30–45. About 40% connect.
  The planner (`world.plan_day`) plays the story calls today: about 5–15 a seller. The no-answer dials that
  fill a day to these volumes come next, as call-history entries with no recording (no analysis cost).
- **Analysis per day:** 3 connected calls per company by default (`--analyse`), always including one call that
  isn't sales when the day has one. That's about Rs 25–35 a day for the three companies.
- **Call lengths:** not connected 0 s; cold opener turned down 20–60 s; inbound qualification 2–5 min; meeting or
  survey booking 3–6 min; negotiation 6–15 min; closing 5–10 min; the odd 45-minute family discussion.
- **Leads arriving:** Sahyadri 6–12 a day, Suryoday 3–6, Kavach 4–8, through the app's own intake (form, import,
  connected sources), at realistic times (Meta leads cluster at lunch and after 20:00, the next morning's
  first calls).
- **Not sales, about 15% of connected calls:** a family call on the work phone, the manager checking numbers, a
  vendor or the builder's back office, an existing customer with a complaint, a wrong number, an IVR, dead air.

## Stories: why every call follows from the last

Each lead has an arc, and each call carries what was agreed before ("you said Sunday at 11 works"). Arcs:
- **Win:** inbound → qualified → site visit or survey → objection handled → booking or policy issued.
- **Slow win:** interested → goes quiet for a week → comes back after a price change.
- **Lost:** budget, location, a competitor, or "my son decides" and the son says no; the reason is recorded.
- **Junk:** wrong number, duplicate, a tenant on a buyer's form.
- **Follow-up kept or missed:** the next call lands on the agreed day and hour, or a day late (the app should show
  it overdue).
- **Handover:** a lead moves from Faiz to Priya after two missed follow-ups.
- **Language switch:** the call starts in English and moves to Marathi or Hindi when the buyer does.

The sellers' weaknesses stay the same over weeks, so coaching should find them again and again (and a seller
who improves, from week 3, should be seen improving).

## What gets tested, and where

| Layer | How | Where |
|---|---|---|
| Phone path on the real app | Dial → the phone's recorder → the app's capture → upload → report → coaching (`run.py release`) | Redmi 13, production Play app, QA lead (already running) |
| Many sellers and agencies | The app's own phone-capture API as each seller ("fake phone", `scripts/simulation/inject.py`), recordings rendered from the day's scripts | The three TEST workspaces (dev first) |
| Screens, as the seller | AI seller agents walk Flow 1 (open → today's work → call → outcome) at phone size and file bugs with the in-app reporter, as that seller | Dev, then staging |
| Analysis quality | Each analysed call has its answer key: who said what, the facts, the outcome, sales or not | All |

**Each release tests what changed.** The runner maps the release's changed paths to tags (capture, upload,
reports, coaching, leads, stages, languages, long calls, work hours) and weights the day's scenarios towards
them; the smoke set always runs.

## The daily page

One page per simulated day and company: calls dialled and connected, recordings analysed, reports, sales and
not-sales verdicts (right or wrong against the key), stage moves, follow-ups kept or overdue, bugs filed by the
seller agents, and the day's spend.

## Decisions this needs

1. **Where the workspaces live:** dev first (the sandbox generator already builds this kind of organisation),
   then production TEST workspaces so the owner sees them in the real app. Creating them is an owner-approved
   data change per environment: "approve data change: create the three TEST workspaces of the test world,
   <environment>".
2. **Seller logins:** plus-aliases of AC's mailbox with passwords in Infisical (as the dev sandboxes do).
3. **Live calls phone to phone, free:** the Redmi 13 dials a second phone with its own SIM that answers by itself
   and stays silent, while the laptop's speaker plays the conversation beside the Redmi's microphone. Both voices
   then pass through a real phone mic, codec, network, recorder and the app. This needs a second SIM phone that
   isn't the Note 8 Pro; none is connected today.
4. **Writing each day's scripts:** a model writes each call from its lead's story. Proposed: `claude -p` on ac
   under the included Team plan (rule 7 of AGENTS.md: no paid API credits), cached per story step, with the
   fixed library as the fallback.
