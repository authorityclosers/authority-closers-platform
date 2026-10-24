# 01 — The field: sales intelligence, conversation intelligence and inside-sales CRMs (India focus)

Programme: Sales X-Ray sales-intelligence research programme, chapter 01
Date: 25 Oct 2026
Status: research note. It is internal only, and the prices in it must never be shown to users.

---

## 0. Key findings

1. **The market splits into three groups, and on public evidence no vendor covers all three jobs together.** The jobs are capturing SIM calls on the phone, AI coaching in Indian languages, and a CRM priced for Indian SMBs. Global conversation-intelligence (CI) tools record VoIP or meeting calls and are priced in dollars per seat plus a platform fee [3][4][21][27]. Indian telecalling apps capture native SIM calls and recordings cheaply, but their public pages show no AI analysis [69–72][82–84]. Indian contact-centre AI (Convin, Exotel, Ozonetel) analyses Indian languages but sells to call centres on cloud telephony, by demo [90–92][98][99].
2. **The gap is closing.** On 25 Oct 2026 Kylas advertised AI recaps, sentiment and intent from uploaded call recordings [62]. LeadSquared advertises real-time call sentiment and a voice-AI agent [56]. HubSpot and Gong list Hindi, Marathi and other Indian languages for transcription [7][34].
3. **The Indian price anchor is low.** Telecalling CRMs list at ₹150–₹2,500 per user per month [55][69][74][82]. Gong seats alone run about $1,200–$2,400 a year, before a platform fee [4]. At an assumed ₹88 per US$, that is 11–22 times TeleCRM's annual-plan seat price [M, A].
4. **Users like automatic capture and dislike mobile apps that are weaker than the desktop.** Silent logging is the praised pattern [88]. The recurring complaints are mobile apps weaker than desktop (Gong, Kylas, LeadSquared, Freshsales), transcription errors on accents and speaker labels (Gong, Chorus, Convin), and price and tier gating (Gong, Chorus, Outreach, HubSpot, Zoho) [13][17][43][59][65][94].
5. **Code-mixed telephony audio is still hard for speech recognition.** The public Hindi-English challenge baselines were around 30–32% WER [112]. One vendor reports Whisper large-v3 at 25.6% mixed error rate on 8 kHz Hinglish calls, against 16.2% for its tuned model (vendor claim) [114]. AI coaching built on these transcripts needs confidence handling and a human in the loop.
6. **The best field evidence on AI coaching supports a hybrid design.** In randomised field experiments, middle-ranked sales agents gained most from an AI coach. Bottom-ranked agents were overloaded by too much feedback, and top-ranked agents resisted it. An AI-plus-manager combination did best for both [102]. No vendor documents adjusting its coaching to a rep's rank.
7. **Regulation is getting tighter.** The DPDP Rules 2025 make the main notice, security and retention duties binding from 13 May 2027 [108]. TRAI's February 2025 amendments penalise telemarketing from ordinary 10-digit numbers [109]. Google Play has blocked call recording through the Accessibility API since May 2022 [110]. Recording, consent and calling volume are design constraints, not afterthoughts.

---

## 1. Scope, method and evidence labels

**Scope.** This chapter covers 24 vendors in five groups (section 3), with a feature × vendor matrix, pricing models, evidence of what wins, UX patterns, Indian specifics, white space and recommendations.

**Method.** Vendors' own pricing, help and product pages were fetched on 25 Oct 2026. Web search was used for review-site ratings, funding, filings and research. Two earlier internal notes (17 and 24 Oct) were built on [1][2]; facts from them carry their original access date. Every price was re-checked on 25 Oct.

**Limitations. They matter for how far to trust this chapter.**
- G2, Capterra, TrustRadius, GetApp and Capterra India returned HTTP 403 to direct fetches, as did pipedrive.com/pricing. Review ratings and themes therefore come from **search-engine summaries** of those pages, marked "(search summary)" in the references. Treat them as indicative.
- Google Play pages could not be read; Play ratings come from the 17 Oct note.
- **Reddit is blocked for these tools**, so there is no community or forum evidence. Practitioner sentiment is missing, not absent.
- The shared web-search budget ran out partway through. The checks left undone are listed in section 12.

**Evidence labels.** **[M]** measured: our own observation or calculation. **[E]** external: a vendor or third-party source (vendor claims are marked "vendor claim"). **[A]** assumed: an input we chose. Bracketed numbers such as [12] are references; any cited fact without a label is external.

---

## 2. Market map

| Segment | Vendors covered | Typical buyer | Call channel | Price model |
|---|---|---|---|---|
| Global revenue and conversation intelligence | Gong, Chorus (ZoomInfo), Salesloft (with Clari), Outreach | Mid-market and enterprise B2B, mostly US | Web meetings, VoIP dialers | Quote-only; per seat plus platform fee; annual contracts [3][4][21][27] |
| Global SMB CRMs with calling | Close, HubSpot Sales Hub, Pipedrive, Freshsales, Zoho CRM, Bigin | SMB sales teams worldwide | Built-in VoIP; some Android call logging | Public per-seat tiers; AI and calling as add-ons or credits [30][33][45][48][53] |
| Indian CRMs | LeadSquared, Kylas, Refrens | Indian SMB to enterprise; high-volume B2C | Telephony partners; Kylas also syncs phone call logs | INR per user, or flat per organisation [55][61][66] |
| Indian phone-sales and call-tracking apps | TeleCRM, NeoDove, Privyr, Callyzer, Salestrail (Finland, sells in India) | Telecalling teams and solo sellers | Native SIM dialer; recordings from the phone's own recorder | Low INR per user or per number; flat yearly plans [69][74][79][82][86] |
| Indian and contact-centre CI and voice AI | Convin, Salesken, Observe.AI, Exotel, Ozonetel, MyOperator, Enthu.AI | Contact centres, collections, large inside-sales teams | Cloud telephony and contact-centre platforms | Demo or quote; per minute or per conversation for voice AI [90][95][97–101] |

---

## 3. Vendor profiles

Each profile lists who the vendor serves, its core jobs, how it captures calls, how coaching and manager views work, AI and Indian-language support, its pricing model and evidence of traction. Prices are list prices seen on 25 Oct 2026 unless noted.

### 3.1 Global revenue and conversation intelligence

**Gong**
- **Who and what:** mid-market and enterprise B2B teams. It records calls and meetings, then builds deal boards, forecasts and coaching on top.
- **Call page:** opens on an AI "brief": a recap, key points and next steps [11]. An outline, points of interest and trackers let a manager jump to the right moment [11].
- **Coaching:**
  - Scorecards can be pre-filled by AI, and the scorer accepts or changes each answer [10].
  - A coaching inbox and a weekly digest suggest calls to review. Managers can mark offline coaching as given [9].
  - Rep stats are shown against published targets. Examples: rep talk share near 43% on the best-converting calls, longest monologue about 2:30 or less, and 18 or more questions per hour [8].
- **Mobile:** the app is for listening, commenting, deals, forecasts and recording in-person meetings. Capturing SIM phone calls is not among its listed features. It rates 3.9 on the App Store and 2.9 on its Google Play developer page (17 Oct) [12].
- **Languages:** transcription covers Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada and Malayalam. Red-flag alerts, recommended to-dos and example-based trackers work only on English calls [7].
- **Pricing model:**
  - Per-user licence plus a platform fee that scales with users; no public prices [3].
  - Vendr data (1,146 purchases, page updated Mar 2026): median contract $55,430 a year, range $11,502–$203,598, seats commonly $1,200–$2,400 a year [4].
- **Traction:** ARR passed $300M in early 2025 [6] and $500M by spring 2026, growing 55% a year (press reports) [5]. A Leader in Gartner's first Magic Quadrant for Revenue Action Orchestration, Dec 2025 [14]. G2 about 4.7 from about 6,700 reviews; the commonest con is price for small teams, and one review says transcripts can miss accents (search summary) [13].

**Chorus (ZoomInfo)**
- **Who and what:** B2B teams already buying ZoomInfo data. It covers call and meeting capture, transcripts, coaching and scorecarding, and deal and market intelligence [15].
- **Traction:** ZoomInfo bought Chorus for $575M in July 2021 [16]. G2 4.5 from 2,991 reviews; TrustRadius 8/10 from 471 ratings (search summary) [17].
- **Complaints:** speaker mix-ups in summaries, gaps in transcripts, keyword search, high price and dependence on the ZoomInfo ecosystem [17].
- **Pricing model:** not published. Third parties cite about $8,000 a year for three seats plus about $1,200 per extra seat. These come from competitor blogs, so confidence is low [18].

**Salesloft (incl. Conversations and Rhythm)**
- **Who and what:** a sales-engagement platform. Rhythm turns buyer signals into a ranked to-do list for each rep, with "Focus Zones" and a prioritiser agent [19]. Conversation Intelligence records, transcribes and scores calls, writes smart summaries and action items, and shows live coaching cards and battlecards during calls [20].
- **Corporate:** merged with Clari on 3 Dec 2025. The combined company reportedly has more than 5,000 customers and about $450M ARR (Forrester blog) [22]. Gartner placed Salesloft as a Visionary and Clari as a Leader, Dec 2025 [23].
- **Languages:** a reseller listing says transcription covers six languages but does not name them, so Hindi is not verified [24].
- **Pricing model:** quote-only. Vendr (710 purchases, Feb 2026): median $30,740 a year; list estimates of Essentials $75–100, Advanced $125–150 and Premier $165–200+ per user per month [21].
- **Reviews:** G2 4.5. The review count ranges from 4,200+ to about 9,900 depending on the page. Cons include caller ID and voicemail issues and Salesforce sync duplicates (search summary) [20][25].

**Outreach**
- **What:** Kaia records and transcribes meetings live, shows real-time content cards, writes recaps and follow-ups, and supports playlists and coaching [26].
  - It offers one-sided recording that captures only the seller's voice, for compliance [26].
  - Kaia for Mobile shows summaries and action items [26].
  - Outreach claims Kaia raises the chance of booking a follow-up meeting by up to 36% (vendor claim) [26].
- **Pricing model:** quote-only. Vendr median $45,600 a year (919 purchases) [27]. Third parties put core seats at about $100–150 per user per month, with Kaia possibly an extra $30–50 [28].
- **Traction and reviews:** Outreach says it was named a Leader in Gartner's 2025 Magic Quadrant [29]. G2 4.3 from about 3,600 reviews; cons include cost, learning curve and inconsistent transcript delivery (search summary) [25].

### 3.2 Global SMB CRMs with calling

**Close**
- **Who and what:** SMB inside-sales teams that call heavily. It has built-in VoIP calling worldwide, a power dialer on Growth, a predictive dialer on Scale, and listen, whisper and barge coaching on Scale [30].
- **AI:**
  - Call Assistant transcribes and summarises calls. It is an add-on at $50 a month per organisation plus $0.02 a minute [30].
  - It covers 20 languages, including Hindi, but warns that non-English summary quality may vary. The help page is dated [31].
  - An AI calling agent, Chloe, is English-only [32].
- **Pricing (USD per user per month; the lower figure is presumably annual billing):** Solo $9/$19, Essentials $35/$49, Growth $99/$109, Scale $139/$149. Outbound calls cost about $0.02 a minute [30].
- **Evidence:** the pricing page shows G2 4.7 from 2,000+ reviews (vendor-displayed) [30].

**HubSpot Sales Hub**
- **Who and what:** SMB to enterprise.
  - The Android app can log calls, including calls made outside the app, once Caller ID and call-log permissions are granted. The post-call "Log calls" screen is limited to Android and Xiaomi devices [35].
  - Transcription hours are included from Starter; conversation-intelligence analysis needs Professional or above (search summary of the KB). Coaching playlists appear in the Enterprise column [33][34].
  - HubSpot's language list includes Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada and Malayalam for call transcription. Which analysis features work per language is not stated [34].
  - AI suggests stage and next-activity updates, which the rep accepts or rejects (24 Oct) [38].
- **Pricing (USD per seat per month):** Free (up to 2 users); Starter $20, though the page also shows a $7 "starts at" figure and third parties disagree on the annual price ($7–15) [33][39]; Professional $90–100 plus $1,500 onboarding; Enterprise $150 plus $3,500 onboarding. Calling minutes included: 500, 3,000 and 12,000 [33].
- **Traction:** 306,446 customers and $911.7M revenue in Q2 2026 [36]. G2 4.4 from about 14,000 reviews; the main con is cost rising sharply with tier (search summary) [37].

**Pipedrive**
- **What:** a visual pipeline. Deals "rot" (turn red) after idle days, and any activity resets the clock (24 Oct) [42].
  - On Android the app prompts the rep to log each incoming or outgoing call when it ends. Calls outside the app need Pipedrive set as the default caller-ID app [41].
  - On iOS only calls placed from inside the app can be logged [41].
- **Pricing:** Lite, Growth, Premium and Ultimate. The pricing page could not be fetched (403), and third parties give conflicting USD figures, commonly $14 / $39 / $49 / $79 per seat per month on annual billing (low confidence) [40].
- **Evidence:** G2 4.3 (about 3,200 reviews); cons include support, add-on costs and the learning curve (search summary) [43]. The only customer count found (about 30,000) is a 2023 third-party estimate [44].

**Freshsales (Freshworks)**
- **What:** the built-in phone logs calls automatically and attaches recordings [46].
  - A Freddy summariser for call transcripts is a paid add-on [46].
  - Transcription is documented as English-only [46].
- **Pricing (USD per user per month, annual):** Growth $9, Pro $39, Enterprise $59 [45].
- **Traction:** the page claims 74,000+ businesses (vendor claim) [45]. Freshworks reported $237.4M Q2 2026 revenue [47]. G2 4.5 (about 1,200 reviews); one con is a slower, reduced mobile app (search summary) [43].

**Zoho CRM**
- **What:**
  - Built-in telephony runs on Twilio. Zia AI can transcribe recorded calls and tag sentiment, intent and emotion, with a one-line summary. Transcription is charged per minute from Zoho Voice credits [50].
  - Gamescope (games, trophies and badges) and Motivator (KPIs, targets and leaderboards) are built in on Professional and above [51].
- **Pricing:** Zoho's page text gave no per-edition amounts on 25 Oct [48]. A Sep 2025 report lists ₹800 / ₹1,400 / ₹2,400 / ₹2,600 per user per month (Standard / Professional / Enterprise / Ultimate, annual, excluding GST) (search summary) [49].
- **Evidence:** the page claims 250,000+ businesses (vendor claim) [48]. G2 4.1 from about 2,950 reviews; cons are complexity, the learning curve and support speed (search summary) [52].

**Zoho Bigin**
- **What:** a pipeline CRM for small businesses.
  - A built-in phone with recording, a mobile app, and WhatsApp Business from the Express plan up [53].
  - AI (record summary, writing assistant, credits) from Premier up [53].
- **Pricing:**
  - USD Free / $7 / $12 / $18 per user per month annual ($9 / $15 / $21 monthly) [53].
  - INR ₹400 / ₹720 / ₹1,080 per user per month annual, per Bigin's own India article [54].
- **Evidence:** 50,000+ small businesses (vendor claim) [53].

### 3.3 Indian CRMs

**LeadSquared**
- **Who:** high-volume Indian B2C sellers in financial services, education, healthcare and automotive [56].
- **What:**
  - The mobile CRM adds check-in and check-out, offline mode, geofencing, pin-code lead assignment, beat plans, a target-versus-achievement view and alerts for new leads and tasks [57].
  - Call dispositions can be made mandatory and can trigger tasks or field updates (24 Oct) [60].
  - The homepage advertises Invorto voice AI and real-time "call sentiment insights" [56].
- **Pricing:** Sales Pro ₹2,500 and Sales Super ₹5,000 per user per month, billed annually; offline mode, geofencing and territories are Super-only [55].
- **Traction:** $153M Series C (June 2022) at a $1B valuation, $188M raised in total, 2,000+ customers then [58]; the 2026 site says 1,600+ organisations [56]. G2 4.5 (303 reviews), mobile listing 4.3 (31); cons include slowness, a steep learning curve and the mobile app double-saving or missing records (search summary) [59].

**Kylas**
- **Who:** Indian SMBs across many industries [62].
- **What:**
  - A separate Kylas Dialer app syncs the phone call log, picks up recordings from a folder the user sets, and shows a caller pop-up with "View Lead" (17 Oct) [64].
  - Its AI now produces recaps, intent and sentiment from uploaded call recordings [62].
- **Pricing model:** flat, unlimited users; Embark is free. The Elevate amount was not shown on 25 Oct; older Kylas comparison pages say ₹12,999 a month (search summary) [61][63]. Add-ons: field tracking ₹400 per user per month, goals ₹2,500 a month [61].
- **Evidence:** 5,000+ businesses in one place on the site and 13,000+ in another (vendor claims, inconsistent) [62]. Capterra 4.8 from about 570 reviews (17 Oct); complaints: the mobile app is slower than web, calling is unreliable, and there is no recording without an IVR (search summary) [65].

**Refrens**
- **Who and what:** a CRM inside an invoicing and accounting suite for Indian SMBs.
  - Lead capture from IndiaMART, TradeIndia, Meta forms and the web; multiple pipelines; WhatsApp contact; reminders; an MCP connector [66].
  - No calling or call logs are described [66].
- **Pricing:** Refrens's own pricing page showed no amounts [67]. A G2 listing shows CRM Essentials at $150 a year for 2 users and CRM Pro at $250 a year for 5 users (search summary) [68].
- **Evidence:** 300k+ users and 4.8/5 from 11,700+ ratings, platform not named (vendor claims) [66].

### 3.4 Indian phone-sales and call-tracking apps

**TeleCRM**
- **Who and what:** a SIM-based telecalling CRM; calls go from the team's own phones [70]. Recordings come from the phone's own recorder, and each SIM can be set to Personal, Work or Block (17 Oct) [72]. It has a 1-click dialer, WhatsApp templates and an API add-on, a leaderboard (sales, calls, talk time), hourly and idle-time reports, and push plus WhatsApp alerts on lead assignment [71].
- **AI:** none on the features page or homepage on 25 Oct [70][71].
- **Pricing:** ₹799 per user per month on annual billing or ₹1,099 quarterly; no monthly plan. WhatsApp API setup is ₹1,999 one-time [69].
- **Evidence:** G2 4.5 and Capterra 4.0, on only 6–16 reviews. A 2025 review complains of app instability and a WhatsApp bot that stops (search summary) [73]. In our 17 Oct test the app showed a blank screen in landscape [M][1].

**NeoDove**
- **Who and what:** a telecalling dialer and CRM for SMBs [75].
  - Auto-dialer, lead distribution, WhatsApp and SMS automation, real-time reports and break notifications; AI voice agents [75].
  - Call recording and AI call analysis are not mentioned [75].
  - Audits leads marked "connected" that were never dialled (24 Oct) [78].
- **Pricing:** flat yearly fee with user caps, GST extra: NeoLite ₹17,999 (up to 10 users), NeoPlus ₹24,999 (up to 20); AI versions ₹22,999 and ₹29,999 with 250 or 500 AI-agent minutes [74]. At full cap NeoLite is about ₹150 per user per month [M].
- **Traction:** $1.5M seed from India Quotient (2021); acquired by Vyapar in 2022, amount undisclosed (search summary) [77]. Capterra India 4.1 from 17 reviews [76]. The site's "4.8 from 107k reviews" names no platform [74]. In our 17 Oct test it was sales-gated [M][1].

**Privyr**
- **Who and what:** mobile-first lead follow-up for B2C sellers such as real-estate and insurance agents [80].
  - Instant lead alerts, and an auto-reply on WhatsApp from the user's existing number even when offline [81].
  - Round-robin assignment and follow-up sequences [81].
- **Pricing:** free for 1–3 members. Pro is $25 per user per month billed annually, per a search snippet of the pricing page; the amount did not render on fetch. Ultimate is custom [79].
- **Evidence:** 500,000+ businesses in 125 countries and 100,000+ downloads (vendor claims) [80]. Usable on a self-serve sign-up in our 17 Oct test [M][1].

**Callyzer**
- **Who and what:** call tracking for telecalling teams. It reads the native call log for the work SIM only, syncs recordings made by the phone's own recorder, shows a notes overlay after calls and publishes per-brand battery and autostart guides [84]. Reports cover working hours, "never attended" and "never received" calls [82]. WhatsApp templates arrived in March 2026 [85].
- **AI:** none listed [83].
- **Pricing:** from ₹175 per phone number per month. Add-ons: recording storage ₹500 per 5 GB per month; Meta lead capture ₹150 per form per month; IndiaMART ₹500 a month [82].
- **Evidence:** 1,000+ clients, 12,000+ tracked numbers and 1M+ downloads (vendor claims) [83]. Needed a SIM to try in our 17 Oct test [M][1].

**Salestrail**
- **Who and what:** silent background logging of SIM and WhatsApp voice calls on Android (17 Oct) [88].
  - Recordings are picked up from the phone's own recorder. Phones on Google Dialer need a separate recorder APK installed outside Play [87].
  - A private "Untracked" tab and SIM selection [89].
  - Leaderboards in custom dashboard views [89].
- **AI:** speech-to-text notes only [86].
- **Pricing (USD per user per month, 25 Oct):** Essential $5 monthly or $3.5 annual; recording +$2 / $1.4; CRM +$4 / $2.8 [86]. **Conflict:** the 17 Oct note recorded $8 / $5.60, +$3 / $2.10 and +$7 / $4.90 [88]; a price cut or location-based pricing, not resolved.
- **Evidence:** Google Play India 3.5 from 274 reviews, 100K+ downloads (17 Oct) [88].

### 3.5 Indian and contact-centre conversation intelligence and voice AI

**Convin**
- **Who and what:** contact centres, collections and sales teams.
  - Automated QA scoring 100% of calls, AI summaries, real-time agent and supervisor assist, automated coaching with a learning management system, and AI phone agents [90].
  - Lists Hindi, Marathi, Tamil, Telugu, Bengali, Gujarati, Kannada, Malayalam, Punjabi and Urdu [91].
  - Claims code-mixed speech-to-text trained on Indian telephony, without publishing a benchmark method [92].
- **Pricing:** demo only [90].
- **Traction:** $6.5M Series A (Aug 2024) and 80+ clients at the time (search summary) [93]. G2 4.7 from 549 reviews. Pros: faster audits. Cons: price, accuracy still needing human checks, and a busy interface (search summary) [94].

**Salesken.** Real-time in-call cues, QA, transcripts and summaries; says it analyses "multiple languages" without naming them; 200+ businesses (vendor claim) [95]. $8M Series A led by Sequoia India in 2020 (search summary) [96].

**Observe.AI.** Contact-centre AI (QA, agent assist, voice agents). $125M Series C in 2022 and about $213M raised in total (search summary) [97]. Built for contact centres rather than SMB inside sales; no Indian-language detail found.

**Exotel and Ozonetel (cloud telephony with AI add-ons)**
- **Exotel:** conversation intelligence that analyses 100% of interactions, AI assist, voice agents and 150+ integrations including Zoho [98].
- **Ozonetel:** AI quality audit of every conversation, after-call summaries, and voicebots in "10+ Indian languages" in one customer case; 3,500+ businesses (vendor claim) [99].
- **Pricing:** neither publishes it.

**MyOperator.** A ₹10,000-a-month AI voice plan including 2,000 conversations, then ₹8 per conversation; voicebots in Hindi, English and Hinglish (search summary) [100].

**Enthu.AI.** Auto-QA, scorecards and coaching workflows; USD billing on semi-annual or annual terms; quote-based [101].

---

## 4. Pricing models compared

All rows were seen on 25 Oct 2026 unless noted. Currency is as shown. Vendor = the vendor's own page; 3rd = third-party estimate.

| Vendor | Pricing unit | List price seen | Source |
|---|---|---|---|
| Gong | Seat plus platform fee | Seats ~$1,200–2,400 a year; median contract $55,430 a year | Vendor model [3]; Vendr [4] |
| Chorus | Seat (bundled with ZoomInfo) | ~$8,000 a year for 3 seats, +~$1,200 a seat | 3rd, low confidence [18] |
| Salesloft | Seat | $75–200+ a user a month by tier; median contract $30,740 a year | Vendr [21] |
| Outreach | Seat, plus AI credits reported | ~$100–150 a user a month; median contract $45,600 a year | Vendr [27]; 3rd [28] |
| Close | Seat, plus usage | $9–149 a user a month; AI $50 an organisation a month + $0.02 a minute; calls ~$0.02 a minute | Vendor [30] |
| HubSpot Sales Hub | Seat, onboarding fee, AI credits | $0 / $20 (also "$7 starts at") / $90–100 / $150 | Vendor [33] |
| Pipedrive | Seat | ~$14 / $39 / $49 / $79 annual | 3rd, conflicting [40] |
| Freshsales | Seat | $9 / $39 / $59 annual; AI add-ons | Vendor [45] |
| Zoho CRM | Seat | ₹800 / ₹1,400 / ₹2,400 / ₹2,600 annual + GST | 3rd [49] |
| Bigin | Seat | ₹400 / ₹720 / ₹1,080 annual | Vendor [54] |
| LeadSquared | Seat | ₹2,500 / ₹5,000 a user a month, annual | Vendor [55] |
| Kylas | Flat, unlimited users | Free; Elevate not shown (older vendor page: ₹12,999 a month) | Vendor [61]; [63] |
| Refrens | Per business, yearly | $150 a year (2 users), $250 a year (5 users) | G2 listing [68] |
| TeleCRM | Seat | ₹799 annual / ₹1,099 quarterly a user a month | Vendor [69] |
| NeoDove | Flat yearly, user cap | ₹17,999–29,999 a year for 10–20 users | Vendor [74] |
| Privyr | Seat | Free (≤3 members); Pro $25 a user a month, annual | Vendor (snippet) [79] |
| Callyzer | Per phone number | From ₹175 a number a month, plus add-ons | Vendor [82] |
| Salestrail | Seat, plus add-ons | $3.5–5 + $1.4–2 + $2.8–4 (17 Oct: $5.6–8 base) | Vendor [86]; [88] |
| Convin, Salesken, Observe.AI, Exotel, Ozonetel, Enthu.AI | Quote (often per agent or per minute) | Not public | [90][95][97–99][101] |
| MyOperator AI voice | Monthly bundle plus per conversation | ₹10,000 a month for 2,000 conversations; ₹8 each after | 3rd snippet of vendor page [100] |

**What the pricing says** [M, A: ₹88 = US$1]:
1. Indian phone-sales tools price per seat at roughly ₹150–₹800 a month, or per phone number. NeoDove at full cap is about ₹150; TeleCRM ₹799; Callyzer from ₹175 per number.
2. Indian CRMs sit at ₹400–₹5,000.
3. Global CI seats alone are ₹8,800–₹17,600 a month equivalent (Gong $100–200), before platform fees.
4. AI is increasingly sold as **usage**: Close per minute, HubSpot credits, Zoho Voice transcription credits, NeoDove AI minutes, MyOperator per conversation [30][33][50][74][100]. Indian buyers are being taught to expect AI as a metered add-on, not a seat feature.

---

## 5. Evidence of what wins

| Vendor | Scale or funding | Ratings (source) | Note |
|---|---|---|---|
| Gong | ARR >$500M, +55% YoY, spring 2026 [5] | G2 ~4.7 (~6,700) [13]; App Store 3.9, Play 2.9 [12] | Gartner RAO Leader 2025 [14] |
| Chorus | Acquired for $575M (2021) [16] | G2 4.5 (2,991); TrustRadius 8/10 [17] | Sold inside ZoomInfo bundles [18] |
| Salesloft + Clari | >5,000 customers, ~$450M ARR combined [22] | G2 4.5 [20][25] | Gartner Visionary (Salesloft) [23] |
| Outreach | Not verified | G2 4.3 (~3,600) [25] | Gartner Leader (vendor claim) [29] |
| HubSpot | 306,446 customers, Q2 2026 [36] | G2 4.4 (~14,000) [37] | Public filings |
| Freshworks | $237.4M Q2 2026 revenue [47] | Freshsales G2 4.5 (~1,200) [43] | 74,000+ businesses (vendor) [45] |
| Zoho CRM | 250,000+ businesses (vendor) [48] | G2 4.1 (~2,950) [52] | Gamification built in [51] |
| Pipedrive | ~30,000 customers (3rd, 2023) [44] | G2 4.3 [43] | |
| LeadSquared | $153M Series C, unicorn, 2022 [58] | G2 4.5 (303); Mobile 4.3 (31) [59] | 1,600–2,000 customers [56][58] |
| Kylas | 5,000–13,000 businesses (vendor) [62] | Capterra 4.8 (~570) [65] | Flat price, unlimited users [61] |
| Convin | $6.5M Series A, 80+ clients (2024) [93] | G2 4.7 (549) [94] | Indian-language QA |
| NeoDove | $1.5M seed; acquired by Vyapar 2022 [77] | Capterra 4.1 (17) [76] | |
| TeleCRM | Funding not found | G2 4.5 / Capterra 4.0, n≤16 [73] | |
| Salestrail | Not verified | Play 3.5 (274), 100K+ installs [88] | |
| Privyr, Callyzer, Refrens | Not verified | Vendor-displayed only [80][83][66] | Large install claims |

**Reading this.** Gong's growth shows buyers pay for AI on recorded conversations [5]. Indian telecalling apps have thin review bases and unaudited traction claims, so comparisons among them are low confidence. Global CI mobile ratings are weak (Gong 2.9 on Play) [12], a sign the phone is not where they invest.

---

## 6. Feature × vendor matrix

Legend:
- ● documented
- ◐ partial, add-on or conditional
- ○ not found in the pages checked (absence on public pages is not proof)
- — not checked in this chapter

Columns:
1. Android SIM-call auto-log
2. Call recording capture (channel)
3. AI call summary
4. Coaching or scoring
5. Indian-language call AI
6. WhatsApp to lead
7. Leaderboard or gamification
8. Manager activity reports
9. Public INR price

| Vendor | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Gong | ○ | ● meetings, VoIP [11] | ● [11] | ● [9][10] | ◐ transcription; some AI English-only [7] | ○ | ◐ rep vs team [8] | ● [8] | ○ |
| Chorus | ○ | ● meetings, VoIP [15] | ● [17] | ● [15] | — | — | — | ◐ [15] | ○ |
| Salesloft | ○ | ● [20] | ● [20] | ● [20] | — (6 languages unnamed) [24] | — | — | ◐ [19] | ○ |
| Outreach | ○ | ● [26] | ● [26] | ● [26] | — | — | — | — | ○ |
| Close | ○ | ● VoIP [30] | ◐ add-on [30] | ◐ listen/whisper [30] | ◐ Hindi listed [31] | — | — | — | ○ |
| HubSpot | ◐ caller ID [35] | ● VoIP [33] | ◐ Pro+ [33] | ◐ playlists [33] | ◐ transcription [34] | — | — | — | ○ |
| Pipedrive | ◐ prompt [41] | — | — | ○ | — | — | — | — | ○ |
| Freshsales | — | ● VoIP [46] | ◐ add-on [46] | ○ | ○ English only [46] | — | — | — | ○ |
| Zoho CRM | — | ● VoIP [50] | ◐ credits [50] | ○ | — | — | ● [51] | ◐ [51] | ◐ 3rd [49] |
| Bigin | — | ● VoIP [53] | ○ | ○ | — | ● [53] | — | — | ● [54] |
| LeadSquared | ○ | — | ◐ sentiment [56] | ○ | — | ● [56] | ◐ targets [57] | ● [57] | ● [55] |
| Kylas | ● [64] | ● phone recorder [64] | ● upload [62] | ◐ [62] | — | ● [61] | ◐ goals [61] | ◐ [61] | ◐ [61] |
| Refrens | ○ | ○ | ○ | ○ | ○ | ◐ [66] | ○ | ◐ [66] | ○ |
| TeleCRM | ● [70][72] | ● phone recorder [72] | ○ [71] | ◐ listen [70] | ○ | ● [71] | ● [71] | ● [71] | ● [69] |
| NeoDove | ◐ [74] | ○ [75] | ○ [75] | ○ | ○ | ◐ add-on [74] | ○ | ● [75] | ● [74] |
| Privyr | ◐ [79] | ○ | ○ | ○ | ○ | ● [81] | ○ | ◐ [80] | ○ |
| Callyzer | ● [84] | ● phone recorder [82] | ○ [83] | ◐ player [82] | ○ | ● [85] | ◐ [82] | ● [82] | ● [82] |
| Salestrail | ● [88] | ◐ add-on, APK [87] | ○ [86] | ○ | ○ | ◐ calls only [88] | ● [89] | ● [89] | ○ |
| Convin | ○ | — | ● [90] | ● [90] | ● [91][92] | ○ | — | ● [90] | ○ |
| Exotel / Ozonetel | ○ | ● cloud [98] | ● [99] | ● [98][99] | ◐ [99] | ◐ [98] | — | ● [98] | ○ |
| **Sales X-Ray** (per programme brief, internal) | ● | ● Android | ● | ● skill scores | ● Hindi, Marathi, English, Hinglish (not externally benchmarked) | ● templates | ○ (targets in build) | ● | — |

**Reading the matrix.** Only Kylas documents both automatic SIM-call capture (columns 1–2) and an AI call summary (column 3). Its AI works on uploaded recordings, and its public pages show no coaching scorecards. No competitor row documents columns 1, 2, 4 and 5 together.

---

## 7. UX patterns that win

These are patterns vendors build repeatedly and reviewers praise.

1. **Zero-tap capture.** Salestrail logs silently beside the native dialer, Callyzer reads the call log and the Kylas Dialer syncs [64][84][88]. A Play reviewer named silent logging as the reason to keep Salestrail [88]. Coaching depends on this.
2. **A post-call prompt that asks only for the outcome.** Callyzer's notes overlay [84], Pipedrive's Android prompt [41], HubSpot's "Log calls" screen [35] and TeleCRM's disposition list ordered by use [72].
3. **Brief-first call reports with jump-to-moment.** Gong opens on a recap, key points and next steps, with an outline and points of interest [11]; Salesloft and Outreach do similar [20][26].
4. **Few coaching numbers, each against a target band.** Gong publishes its targets [8].
5. **AI suggests, a person confirms.** Gong's AI-prefilled scorecards [10] and HubSpot's suggested stage changes [38]. This matches the field evidence that AI plus a human coach beats either alone [102]. A study of 5,172 support agents found AI assistance raised productivity 15% on average, mostly among less experienced workers, while the most skilled saw small quality declines [103].
6. **Coaching as a manager loop.** A coaching inbox, a weekly digest, "mark feedback given" and comments tied to moments [9].
7. **Leaderboards on activity.** TeleCRM [71], Salestrail [89], Zoho Gamescope and Motivator [51]. Telling workers their rank, with no pay change, raised productivity durably in one firm's records [105]. That it carries over to sales calling is an **assumption** [A].
8. **Speed-to-lead tooling.** Instant push alerts, an automatic WhatsApp reply from the seller's own number, and WhatsApp alerts on assignment [71][81]. The basis is Oldroyd et al. (HBR 2011): per secondary summaries, leads contacted within an hour were nearly seven times likelier to qualify than those contacted an hour or more later (HBR full text not reached) [104].
9. **Privacy controls on the phone.** Per-SIM Personal / Work / Block (TeleCRM) [72], work-SIM-only tracking (Callyzer) [84], and a private "Untracked" tab with office hours (Salestrail) [89].
10. **Reports on time as well as outcomes.** Hourly and idle reports (TeleCRM) [71]; "never attended" and working-hours reports (Callyzer) [82].
11. **Board urgency cues.** Pipedrive's rotting colours [42]; NeoDove's audit of dispositions logged without a dial [78].

---

## 8. Patterns users complain about

These come from review-site summaries (search summaries; G2 and Capterra were not directly readable). Community forums such as Reddit could not be checked.

| Complaint | Where it appears |
|---|---|
| Price and tier gating; costs jump with tier | Gong [13], Chorus [17], Outreach [25], HubSpot [37], Zoho [52], Convin [94] |
| Mobile app weaker or slower than desktop; records not saved | Gong (Play 2.9) [12][13], Kylas [65], LeadSquared [59], Freshsales [43] |
| Transcription errors on accents and similar voices; speaker mix-ups; AI needs human checks | Gong [13], Chorus [17], Convin [94] |
| Calling reliability: dropped features, caller-ID or voicemail faults, no recording without IVR | Kylas [65], Salesloft [25], TeleCRM [73] |
| Complexity and learning curve | Zoho [52], Pipedrive [43], LeadSquared [59], Outreach [25] |
| CRM sync errors and duplicates | Salesloft–Salesforce [25] |
| Android setup friction: battery optimisation, autostart, a recorder folder per brand, Google Dialer phones unreadable, Truecaller as default dialer breaks detection | Callyzer guides [84], Salestrail KB [87][89] |
| Sales-gated or demo-only trials | NeoDove and Kylas in our 17 Oct test; only Privyr and Salestrail were usable self-serve out of six installed apps [M][1] |

---

## 9. Where Indian inside-sales teams differ

1. **Android dominates.** Android had about 92% of India's mobile OS share in July 2026, iOS about 7.5% (search summary of StatCounter) [106]. iPhone-only apps (Fathom's notetaker, which also cannot record phone calls [115]) or weak Android apps (Gong, Play 2.9 [12]) do not fit.
2. **SIM calling, not VoIP.**
   - Indian telecalling tools build on the native dialer and the phone's own recorder [72][84][87]. Built-in recorders are commoner on phones sold in India; phones on Google Dialer (Pixel, OnePlus and Redmi are named) need a recorder APK from outside Play [87].
   - Google Play has barred Accessibility-API call recording since May 2022, exempting pre-loaded default dialers [110].
   - So recording coverage varies by phone model, and sellers and managers must be told which phones work.
3. **Telemarketing rules bite at volume.** TRAI's February 2025 amendments restrict telemarketing from ordinary 10-digit numbers (promotional on the 140 series, service and transactional on 1600). Reported penalties are a 15-day bar on the first violation, then one-year disconnection and blacklisting (secondary coverage of TRAI PR 11/2025; official text not read) [109]. Whether follow-up calls to leads who filled a form count as commercial communication is **not verified**; it needs legal advice [A].
4. **WhatsApp is the second channel.** Meta has said WhatsApp has more than 500 million users in India, about 60% of whom interact with businesses weekly (search summary) [107]. Every Indian phone-sales vendor sells WhatsApp templates or auto-replies [71][74][81][85].
5. **Multilingual, code-mixed calls.** Global tools now list Indian languages for transcription [7][34], but some AI features stay English-only [7][31][46]. Code-mixed telephony is the hard case:
   - MUCS 2021 challenge baselines were about 30–32% WER; one leading system reported about 19.5% transliterated WER on the Hindi-English development set [112].
   - Balanced monolingual pre-training gave relative gains of 14.1% (Hindi-English) and 27.1% (Bengali-English) [113].
   - A vendor reports 25.6% (Whisper large-v3) against 16.2% (its own model) mixed error rate on 8 kHz Hinglish calls (vendor claim, proprietary test set) [114].
6. **Price sensitivity.** The Indian per-seat anchor is ₹150–₹2,500 a month, against ₹8,800+ for global CI seats (section 4) [M, A].
7. **DPDP Act 2023 and Rules 2025.**
   - The Rules were notified on 13 Nov 2025. The main obligations (standalone itemised notices, security safeguards, breach reporting, retention) apply from **13 May 2027** (law-firm and press summaries) [108].
   - A 2023 Chhattisgarh High Court ruling held that secretly recording someone's calls violated the Article 21 right to privacy. It was a family dispute; its effect on business call recording is **not verified** [111].
   - Recording notices, seller notices and retention limits should be designed in now [A].

---

## 10. White space Sales X-Ray can own

1. **One phone app that captures SIM calls and coaches in the seller's language, at an Indian SMB price.** No competitor row in section 6 documents capture, coaching and Indian-language AI together [M]. Kylas is closest, but its recaps come from uploaded recordings and it shows no scorecards [62]; Convin has the languages and coaching but sells to contact centres by demo [90][91].
2. **Coaching for the seller on the phone, not only for the manager's desktop.** Global CI mobile apps are for listening and forecasts [12]; Indian telecalling apps give managers a recording player, with no seller-facing coaching documented [82].
3. **Coaching adjusted to the rep's rank:** shorter feedback for weaker sellers, AI plus manager for all, as the field evidence suggests [102]. No vendor page documents this.
4. **Stage moves backed by the call itself,** preventing fake "connected" dispositions rather than auditing them afterwards [78][2].
5. **A WhatsApp follow-up drafted from the call, in the lead's language.** Gong and Salesloft draft follow-up emails [11][20]; Indian vendors send fixed templates [71][85].
6. **Consent and data handling designed for DPDP,** with seller privacy controls (SIM roles, private calls) [72][89][108].
7. **Honest accuracy:** show transcript confidence and let sellers correct key fields. Reviews penalise silent transcript errors [13][17][94].

---

## 11. Implications for Sales X-Ray

Impact: H, M or L. Effort: S, M or L. The evidence column names the sources each recommendation rests on.

| # | Recommendation | Impact | Effort | Evidence |
|---|---|---|---|---|
| 1 | **Make "zero-tap call capture" the core promise and measure it.** Track the share of work calls logged and the share with a usable recording, per seller and per phone model, weekly. Treat drops as incidents. | H | S | Silent logging praised [88]; Android setup failures are the main complaint [84][87][89] |
| 2 | **Ship a phone-health checklist with fixes for each brand.** Cover battery, autostart, recorder folder, Google Dialer detection and Truecaller conflicts. Mirror each seller's red or green status on the manager view. | H | M | Callyzer and Salestrail per-brand guides [84][87][89]; Play policy [110] |
| 3 | **Brief-first call report on the phone.** One-line recap, 3 key points, the agreed next step with date and time, then a one-tap "create task" and a "send WhatsApp follow-up" draft in the lead's language. | H | M | Gong and Salesloft brief patterns [11][20]; WhatsApp centrality [107]; no vendor drafts WhatsApp from the call (section 10) |
| 4 | **Coach the seller with at most 3–5 measures, each against a target band, and one "try this on your next call" tip.** Show the full breakdown only on request. | H | M | Gong targets [8]; information overload for bottom-ranked agents [102] |
| 5 | **Run AI suggestion plus manager confirmation as the default coaching loop.** Add a coaching inbox, a weekly digest of calls worth hearing, "mark coached", and comments tied to a moment in the call. | H | M | Hybrid AI–human coach best in field experiments [102]; Gong workflow [9][10] |
| 6 | **Validate before scoring Indian-language calls.** Benchmark our transcription (WER or MER) on a labelled sample of our own Hindi, Marathi and Hinglish 8 kHz calls each quarter. Show a confidence level; let sellers correct outcome, date and objection fields. Publish no accuracy claim until measured. | H | M | MUCS baselines [112]; 8 kHz Hinglish results [114]; review complaints on accents [13][17][94] |
| 7 | **Build DPDP-ready recording controls now.** Per-SIM Work / Personal / Off, a private-calls tab, clear seller notices, a recording-announcement option, and retention limits per organisation. | H | M | TeleCRM and Salestrail patterns [72][89]; DPDP Rules timeline [108]; High Court privacy ruling [111] |
| 8 | **Speed-to-lead as a first-class metric.** Instant push on a new or assigned lead, an optional WhatsApp template reply, and a first-call timer. Report median minutes to first call per seller and per source. | H | S | Oldroyd et al. [104]; Privyr and TeleCRM alerts [71][81] |
| 9 | **Add leaderboards that blend activity and quality** (calls connected, talk time, skill-score trend). Teams see the leaderboard; each seller sees their own rank privately; managers can turn it off. | M | S | Rank feedback raises productivity [105]; TeleCRM and Zoho patterns [51][71]; the effect in sales is assumed [A] |
| 10 | **Add time-based manager reports.** Calls by hour, idle gaps, missed calls never returned, and leads never attempted. | M | S | TeleCRM hourly and idle reports [71]; Callyzer "never attended" [82]; NeoDove audit [78] |
| 11 | **Keep stage moves backed by the call.** A move out of "not connected" needs a connected call or an explicit, logged "we spoke". | M | M | NeoDove only audits afterwards [78]; internal Lead OS design [2] |
| 12 | **Price AI as included value per seat, with internal usage guards, not as a visible meter.** Competitors meter AI per minute or credit [30][33][50]; Indian seat anchors are low (section 4). This is a packaging option for the owner to decide, not a recommendation on price levels; no prices go in the product. | H | S | Section 4 pricing table [M] |
| 13 | **Add a guard on calling volume and a positioning note.** Present the product for following up inbound and consented leads, flag patterns of bulk cold calling from SIMs, and get legal advice on TRAI rules. | M | S | TRAI Feb 2025 amendments [109] |
| 14 | **Keep self-serve onboarding to under 10 minutes,** with no sales gate and no SIM needed to explore. Use a demo workspace with sample leads and calls. | M | S | Only 2 of 6 Indian apps were usable self-serve in our test [M][1]; TeleCRM claims setup in under 10 minutes [72] |
| 15 | **Later: import recordings from cloud-telephony providers** (Exotel, Ozonetel, MyOperator) for teams already on an IVR, through their APIs, instead of building a VoIP dialer. | M | M | Kylas reviews: no recording without IVR [65]; Exotel lists 150+ integrations [98] |

---

## 12. Not verified in this chapter (to close later)

- Close and Callyzer review themes from G2 and Play: the search budget ran out, and Play pages are unreadable.
- Official TRAI amendment text; the HBR 2011 full text; the full DPDP gazette rule-by-rule mapping.
- Hindi and Indian-language support in Chorus, Salesloft and Outreach.
- Whether Pipedrive, HubSpot, Freshsales and Zoho CRM offer native WhatsApp messaging in India.
- Funding for TeleCRM, Kylas, Privyr and Refrens.
- Kylas Elevate's current price; Pipedrive's official prices; why Salestrail prices differ between 17 and 25 Oct.
- Community evidence from Reddit and Indian sales forums (blocked).

---

## References

All web sources were accessed 25 Oct 2026 unless another date is given. "(search summary)" means the claim was read from a search engine's summary of the page, not from the page itself. The listed page is the source the summary cited.

1. AC internal note, "Lead Desk UX study — HANDOFF" (owner's phone walk of six Indian sales apps). Internal file crm-ux-study-20261017/HANDOFF.md, 17 Oct 2026.
2. AC internal note, "Lead OS: best pipeline patterns from top CRMs". Internal file lead-os-20261024/RESEARCH.md, 24 Oct 2026.
3. Gong, "Pricing". https://www.gong.io/pricing/
4. Vendr, "Gong software pricing" (updated Mar 2026). https://www.vendr.com/marketplace/gong
5. Globes, "Gong ARR exceeds $500m calming AI fears". https://en.globes.co.il/en/article-1001542789 (search summary)
6. Gong press release, "Gong surpasses $300M ARR amid increased demand for AI-powered revenue solutions", 5 Mar 2025. https://www.gong.io/press/gong-surpasses-300m-arr-amid-increased-demand-for-ai-powered-revenue-solutions (search summary)
7. Gong Help Center, "What languages are supported in Gong". https://help.gong.io/hc/en-us/articles/360041931991-What-languages-are-supported-in-Gong
8. Gong Help Center, "Analyze team performance". https://help.gong.io/docs/analyze-team-performance (accessed 17 Oct 2026)
9. Gong Help Center, "Create coaching workflows". https://help.gong.io/docs/create-coaching-workflows.md (accessed 17 Oct 2026)
10. Gong Help Center, "Gong AI for scoring". https://help.gong.io/docs/gong-ai-for-scoring (accessed 17 Oct 2026)
11. Gong Help Center, "Use transcripts, outline and call details" and "Intro to the call page". https://help.gong.io/docs/use-transcripts-outline-and-call-details ; https://help.gong.io/docs/intro-to-the-call-page (accessed 17 Oct 2026)
12. Apple App Store, "Gong" listing; Google Play, Gong developer page; Gong Help Center, "Intro to the Gong mobile app". https://apps.apple.com/app/id1289289459 ; https://play.google.com/store/apps/developer?id=Gong ; https://help.gong.io/docs/intro-to-the-gong-mobile-app.md (accessed 17 Oct 2026)
13. G2, "Gong Pricing" and "Gong reviews, page 3". https://www.g2.com/products/gong/pricing ; https://www.g2.com/products/gong/reviews?page=3 (search summary)
14. Gartner, "Magic Quadrant for Revenue Action Orchestration" (abstract); Gong press release on its Leader placement. https://www.gartner.com/en/documents/7283830 ; https://www.gong.io/press/gong-named-a-leader-in-2025-gartner-magic-quadrant-for-revenue-action-orchestration (search summary)
15. ZoomInfo, "Chorus". https://www.zoominfo.com/products/chorus
16. SiliconANGLE, "ZoomInfo acquires Chorus.ai for $575M to expand sales intelligence platform", 13 Jul 2021. https://siliconangle.com/2021-07-13/zoominfo-acquires-chorus-ai-575m-expand-sales-intelligence-platform/ (search summary)
17. G2, "Chorus by ZoomInfo reviews"; TrustRadius, "Chorus by ZoomInfo reviews". https://www.g2.com/products/chorus-by-zoominfo/reviews ; https://www.trustradius.com/products/chorus-ai/reviews (search summary)
18. JustCall, "Chorus pricing"; Convo, "Chorus pricing". https://justcall.io/hub/cost/chorus-pricing/ ; https://www.itsconvo.com/pricing/chorus (search summary)
19. Salesloft, "Rhythm". https://www.salesloft.com/platform/rhythm
20. Salesloft, "Conversation Intelligence". https://www.salesloft.com/platform/conversation-intelligence
21. Vendr, "Salesloft software pricing" (updated Feb 2026). https://www.vendr.com/marketplace/salesloft
22. Forrester (blog), "Clari-Salesloft merger: a bold, high-stakes bid for market dominance". https://www.forrester.com/blogs/clari-salesloft-merger-a-bold-high-stakes-bid-for-market-dominance/ (search summary)
23. Business Wire, "Clari recognized as a Leader and Salesloft a Visionary in the first 2025 Gartner Magic Quadrant for Revenue Action Orchestration", 16 Dec 2025. https://www.businesswire.com/news/home/20251216171118/en/ (search summary)
24. SoftwareOne marketplace, "Salesloft Conversations". https://platform.softwareone.com/product/salesloft-conversations/PCP-9277-1074 (search summary)
25. G2, "Salesloft reviews", "Outreach reviews" and "Outreach vs. Salesloft". https://www.g2.com/products/salesloft/reviews ; https://www.g2.com/products/outreach/reviews ; https://www.g2.com/compare/outreach-vs-salesloft (search summary)
26. Outreach, "Kaia". https://www.outreach.ai/platform/kaia
27. Vendr, "Outreach software pricing" (updated Feb 2026). https://www.vendr.com/marketplace/outreach
28. Woodpecker, "How much does Outreach cost". https://woodpecker.co/blog/how-much-does-outreach-cost/ (search summary)
29. Outreach blog, "Outreach named a Leader in the 2025 Gartner Magic Quadrant for Revenue Action Orchestration Platforms". https://www.outreach.ai/resources/blog/gartner-magic-quadrant-2025 (search summary)
30. Close, "Pricing". https://www.close.com/pricing
31. Close Help, "Call Assistant". https://help.close.com/docs/call-assistant (search summary)
32. Close, "Meet Chloe, your AI sales teammate" (Call Assistant page). https://www.close.com/call-assistant
33. HubSpot, "Sales Hub pricing". https://www.hubspot.com/pricing/sales
34. HubSpot Knowledge Base, "HubSpot language offerings". https://knowledge.hubspot.com/help-and-resources/hubspot-language-offerings
35. HubSpot Knowledge Base, "Manage Caller ID, manual contact syncs, and call logs in the HubSpot mobile app". https://knowledge.hubspot.com/calling/manage-caller-id-manual-contact-syncs-and-call-logs-in-the-hubspot-mobile-app (search summary)
36. Business Wire, "HubSpot reports Q2 2026 results", 5 Aug 2026. https://secure.businesswire.com/news/home/20260805185463/en/HubSpot-Reports-Q2-2026-Results (search summary)
37. G2, "HubSpot Sales Hub reviews". https://www.g2.com/products/hubspot-sales-hub/reviews (search summary)
38. HubSpot Knowledge Base, "Move deals forward with deal progression". https://knowledge.hubspot.com/records/move-deals-forward-with-deal-progression (accessed 24 Oct 2026)
39. HubSpot Blog, "HubSpot Sales Hub pricing"; Hublead, "HubSpot pricing calculator". https://blog.hubspot.com/sales/hubspot-sales-hub-pricing ; https://www.hublead.io/hubspot-pricing-calculator (search summary)
40. Zeeg, "Pipedrive 2026 pricing: plans, add-ons and cost guide". https://zeeg.me/post/pipedrive-pricing (search summary). The official page https://www.pipedrive.com/pricing returned HTTP 403.
41. Pipedrive Knowledge Base, "Call and log calls in the mobile app". https://support.pipedrive.com/en/article/calling-and-logging-calls-in-the-mobile-app (search summary)
42. Pipedrive Knowledge Base, "The rotting feature". https://support.pipedrive.com/en/article/the-rotting-feature (accessed 24 Oct 2026)
43. G2, "Pipedrive reviews" and "Freshsales pros and cons". https://www.g2.com/products/pipedrive/reviews ; https://www.g2.com/products/freshsales/reviews?qs=pros-and-cons (search summary)
44. Latka, "Pipedrive". https://getlatka.com/companies/pipedrive (search summary)
45. Freshworks, "Freshsales pricing". https://www.freshworks.com/crm/pricing/
46. Freshworks Support, "Voice Transcription Summarizer" and "How to enable call transcriptions". https://crmsupport.freshworks.com/support/solutions/articles/50000008383-voice-transcription-summarizer ; https://crmsupport.freshworks.com/support/solutions/articles/50000005725-enabling-call-transcriptions (search summary)
47. Freshworks Inc., Form 8-K, Q2 2026 earnings release (SEC). https://www.sec.gov/Archives/edgar/data/0001544522/000154452226000135/q226quarterlyearningsrelea.htm (search summary)
48. Zoho, "Zoho CRM pricing". https://www.zoho.com/crm/zohocrm-pricing.html
49. Business Today, "Zoho explained: products, features, and pricing for Indian businesses", 23 Sep 2025. https://www.businesstoday.in/amp/technology/news/story/zoho-explained-products-features-and-pricing-for-indian-businesses-495208-2025-09-23 (search summary)
50. Zoho Help, "Call Analytics in VoC" and "Working with built-in telephony". https://help.zoho.com/portal/en/kb/crm/apps-for-zoho-crm/voice-of-the-customer/voc-analytical-dashboards/articles/call-analytics ; https://help.zoho.com/portal/en/kb/crm/connect-with-customers/telephony/articles/working-with-built-in-telephony (search summary)
51. Zoho Blog, "Work hard, play hard with Gamescope for Zoho CRM"; Zoho, "Motivator". https://www.zoho.com/blog/crm/gamescope-for-crm.html ; https://www.zoho.com/crm/motivator.html (search summary)
52. G2, "Zoho CRM pros and cons". https://www.g2.com/products/zoho-crm/reviews?qs=pros-and-cons (search summary)
53. Bigin by Zoho CRM, "Pricing". https://www.bigin.com/pricing.html
54. Bigin, "What is the real starting price of Bigin by Zoho CRM in India? [Official clarification]". https://www.bigin.com/articles/bigin-india-pricing-clarification.html
55. LeadSquared, "Sales CRM pricing". https://www.leadsquared.com/sales-crm-pricing/
56. LeadSquared, homepage. https://www.leadsquared.com/
57. LeadSquared, "Mobile CRM". https://www.leadsquared.com/mobile-crm/
58. LeadSquared, "LeadSquared joins the unicorn club with $153 million funding from WestBridge Capital", 21 Jun 2022. https://www.leadsquared.com/news/leadsquared-joins-the-unicorn-club-with-153-million-funding-from-westbridge-capital/ (search summary)
59. G2, "LeadSquared Sales CRM reviews"; Capterra, "LeadSquared reviews". https://www.g2.com/products/leadsquared-sales-crm/reviews ; https://www.capterra.com/p/130199/LeadSquared/reviews/ (search summary)
60. LeadSquared Help, "Universal Connector" (mandatory call disposition and post-call actions). https://help.leadsquared.com/universal-connector/ (accessed 24 Oct 2026)
61. Kylas, "Pricing". https://www.kylas.io/pricing
62. Kylas, homepage. https://kylas.io/
63. Kylas, "Kylas vs Bigin". https://kylas.io/kylas-vs-bigin (search summary; the page states it was last verified 19 Dec 2023)
64. Kylas Support, "How to sync the mobile phone call logs with Kylas". https://support.kylas.io/portal/en/kb/articles/how-to-sync-the-mobile-phone-call-logs-with-kylas (accessed 17 Oct 2026)
65. Capterra, "Kylas Sales CRM reviews". https://www.capterra.com/p/210630/Kylas/reviews/?page=4 (accessed 17 Oct 2026; review themes from search summary, 25 Oct 2026)
66. Refrens, "Sales CRM". https://www.refrens.com/rf-sales-crm
67. Refrens, "Pricing". https://www.refrens.com/pricing
68. G2, "Refrens ABC pricing". https://g2.com/products/refrens-abc/pricing (search summary)
69. TeleCRM, "Pricing". https://telecrm.in/pricing
70. TeleCRM, homepage. https://telecrm.in/
71. TeleCRM, "Features". https://telecrm.in/features
72. TeleCRM, "Call tracking and recording CRM software" and "Features generic". https://telecrm.in/call-tracking-recording-crm-software ; https://digital.telecrm.in/features-generic (accessed 17 Oct 2026)
73. G2, "TeleCRM reviews"; Capterra, "TeleCRM"; Software Advice AU, "TeleCRM". https://www.g2.com/products/telecrm/reviews ; https://www.capterra.com/p/213134/TeleCRM/ ; https://www.softwareadvice.com.au/software/350332/telecrm (search summary; Software Advice accessed 17 Oct 2026)
74. NeoDove, "Pricing". https://neodove.com/pricing
75. NeoDove, homepage. https://neodove.com/
76. Capterra India, "NeoDove". https://www.capterra.in/software/204000/neodove (search summary)
77. Bar & Bench, "Vertices acts on Vyapar acquiring SaaS startup NeoDove"; Bar & Bench, "Vertices Partners advises NeoDove on raising $1.5 mn from India Quotient". https://www.barandbench.com/dealstreet/vertices-acts-on-vyapar-acquiring-saas-startup-neodove ; https://www.barandbench.com/dealstreet/vertices-partners-advises-neodove-on-raising-15-mn-from-india-quotient (search summary)
78. NeoDove Docs, "Find out if your leads are even being attempted or not" (Sept 2023 product update). https://docs.neodove.com/product-updates/september-2023/find-out-if-your-leads-are-even-being-attempted-or-not (accessed 24 Oct 2026)
79. Privyr, "Pricing". https://www.privyr.com/pricing (Pro price from search snippet of this page)
80. Privyr, homepage. https://www.privyr.com/
81. Privyr Help, "Instantly contact and follow up with new leads". https://help.privyr.com/knowledge-base/instantly-contact-follow-up-with-new-leads/
82. Callyzer, "Pricing". https://callyzer.co/pricing
83. Callyzer, homepage. https://callyzer.co/
84. Callyzer Help, "How to register your employees" and "Troubleshooting" collection. https://help.callyzer.co/article/how-to-register-your-employees/ ; https://help.callyzer.co/collection/troubleshooting/ (accessed 17 Oct 2026)
85. EIN Presswire, Callyzer product release, March 2026. https://www.einpresswire.com/article/902898604/ (accessed 17 Oct 2026)
86. Salestrail, "Pricing". https://www.salestrail.io/pricing
87. Salestrail Knowledge Base, "How call recording works" and "How to record your calls using the Salestrail Recorder APK". https://www.salestrail.io/knowledge-base/how-call-recording-works ; https://www.salestrail.io/knowledge-base/how-to-record-your-calls-using-the-salestrail-recorder-apk (accessed 17 Oct 2026)
88. Google Play, "Salestrail – Sync Calls & Recs" (India listing), plus prior pricing recorded in the AC internal note salestrail.md. https://play.google.com/store/apps/details?id=com.liid.react.android&hl=en_IN&gl=IN (accessed 17 Oct 2026)
89. Salestrail Knowledge Base, "How to not track my personal calls", "Calls not logged in the Salestrail app", and "Reporting and analytics". https://www.salestrail.io/knowledge-base/how-to-not-track-my-personal-calls ; https://www.salestrail.io/knowledge-base/calls-not-logged-in-the-salestrail-app-causes-and-solutions ; https://www.salestrail.io/reporting-analytics (accessed 17 Oct 2026)
90. Convin, "Pricing" page (feature list; no prices). https://convin.ai/pricing
91. Convin, "Language support". https://convin.ai/language-support
92. Convin, "Speech-to-text built for how India speaks". https://convin.ai/speech-to-text
93. Entrackr, "Convin raises $6.5 Mn in Series A round led by India Quotient", Aug 2024; YourStory coverage of the same round. https://entrackr.com/2024/08/convin-raises-6-5-mn-in-series-a-round-led-by-india-quotient ; https://cwv.yourstory.com/2024/08/convin-raises-65-million-in-series-a-funding-led-by-india-quotient (search summary)
94. G2, "Convin.ai reviews". https://www.g2.com/products/convin-ai/reviews (search summary)
95. Salesken, homepage. https://salesken.ai/
96. YourStory, "[Funding alert] Salesken raises $8M in Series A round from Sequoia India", Mar 2020. https://yourstory.com/2020/03/funding-startup-salesken-sequoia-india (search summary)
97. Business Wire, "Observe.AI raises $125M Series C to usher in AI-empowered era for contact centers", 12 Apr 2022. https://www.businesswire.com/news/home/20220412005208/en/ (search summary)
98. Exotel, homepage. https://exotel.com/
99. Ozonetel, "AI". https://ozonetel.com/ai/
100. MyOperator, "Pricing". https://www.myoperator.com/pricing (search summary)
101. Enthu.AI, "Pricing". https://enthu.ai/pricing/
102. Luo, X., Qin, M. S., Fang, Z. and Qu, Z. (2021), "Artificial intelligence coaches for sales agents: caveats and solutions", Journal of Marketing, DOI 10.1177/0022242920956676. Study design and findings from the American Marketing Association press release. https://www.ama.org/2020/11/19/coaching-sales-agents-use-ai-and-human-coaches-jointly/
103. Brynjolfsson, E., Li, D. and Raymond, L., "Generative AI at Work", arXiv:2304.11771 v2 (6 Nov 2024); published in the Quarterly Journal of Economics 140(2), 2025. https://arxiv.org/abs/2304.11771
104. Oldroyd, J. B., McElheran, K. and Elkington, D. (2011), "The short life of online sales leads", Harvard Business Review, March 2011 (teaser only reached); figures via SmartCompany. https://hbr.org/2011/03/the-short-life-of-online-sales-leads ; https://www.smartcompany.com.au/marketing/20110704-are-you-letting-online-leads-go-cold/ (search summary)
105. Blanes i Vidal, J. and Nossol, M. (2011), "Tournaments without prizes: evidence from personnel records", Management Science 57(10), 1721–1736. https://ideas.repec.org/a/inm/ormnsc/v57y2011i10p1721-1736.html
106. StatCounter Global Stats, "Mobile operating system market share India". https://gs.statcounter.com/os-market-share/mobile/india (search summary)
107. Storyboard18, "Meta doubles down on WhatsApp Business in India"; The Tribune, "WhatsApp testing Meta AI chatbot in India, other markets". https://www.storyboard18.com/amp/how-it-works/meta-doubles-down-on-whatsapp-business-in-india-23713.htm ; https://www.tribuneindia.com/news/science-technology/whatsapp-testing-meta-ai-chatbot-in-india-other-markets-610136 (search summary)
108. Press Information Bureau, DPDP Rules 2025 document (Nov 2025); Khaitan & Co, "ERGO – Digital Personal Data Protection Rules", 15 Nov 2025; Storyboard18 coverage. https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf ; https://www.khaitanco.com/sites/default/files/2025-11/ERGO%20-%20Digital%20Personal%20%20Data%20Protection%20Rules%20-%2015%20November%202025.pdf ; https://www.storyboard18.com/amp/digital/breaking-govt-notifies-final-dpdp-rules-sets-staggered-rollout-with-key-obligations-for-data-fiduciaries-84201.htm (search summary)
109. TRAI, Press Release No. 11 of 2025 (Feb 2025); FoneArena, "TRAI amends TCCCPR 2025". https://cms.trai.gov.in/sites/default/files/2025-02/PR_No.11of2025.pdf ; https://www.fonearena.com/blog/446114/trai-tcccpr-2025-tougher-rules-spam-calls-sms.html (search summary)
110. The Register, "Google banning third-party call recording apps", 22 Apr 2022. https://www.theregister.com/2022/04/22/google_banning_thirdparty_callrecording_apps/ (search summary)
111. LiveLaw, "Recording phone conversation without permission violates right to privacy under Article 21: Chhattisgarh High Court" (2023). https://www.livelaw.in/amp/high-court/chattisgarh-high-court/chhattisgarh-high-court-ruling-recording-telephonic-conversations-without-consent-violates-privacy-right-article-21-240133 (search summary)
112. "Code switched and code mixed speech recognition for Indic languages", arXiv:2203.16578; Wiesner et al., JHU–GoVivace system for MUCS 2021, Interspeech 2021. https://arxiv.org/pdf/2203.16578 ; https://www.isca-archive.org/interspeech_2021/wiesner21_interspeech.pdf (search summary)
113. Hussein, A., Chowdhury, S., Dehak, N. and Ali, A., "Balanced end-to-end monolingual pre-training for low-resourced Indic languages code-switching speech recognition", arXiv:2106.05885. https://arxiv.org/abs/2106.05885
114. Gnani.ai Research, "Code-switching at 8 kHz" (vendor research page; self-reported results). https://gnani.ai/resources/research/code-switching-at-8khz
115. Apple App Store, "Fathom AI Notetaker". https://apps.apple.com/us/app/fathom-ai-notetaker/id6751613402 (accessed 17 Oct 2026)
