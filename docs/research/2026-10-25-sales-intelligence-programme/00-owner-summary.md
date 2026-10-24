# Owner summary: the 10 changes the research implies for Sales X-Ray

*25 Oct 2026. One page. Ranked by impact, then by effort (smallest first). Each line says
what to change, why (the evidence, in the chapters), who builds it, and how telemetry
proves it worked. H/M = impact; S/M = effort.*

| # | Change | Why (evidence) | Impact · effort | Owner | Proof in telemetry |
|---|---|---|---|---|---|
| 1 | **"How did it go?" in seconds after every call.** Opens within 1 s of the call ending, 5 big answers or fewer in thumb reach, a voice note instead of typing, saved on the phone first. Target: median under 8 s, ≥92% of calls logged within 10 minutes. | People recall about 10% of a conversation five minutes later (ch 2); the call's end is the strongest habit cue (ch 2); logging is the daily core journey (ch 3, 5.2 s expert time). | H · M | Lead OS, builder | `log_result` flow: finished share, where people stop, refused Saves |
| 2 | **Zero-tap call capture, proven per phone model.** A phone-health check with per-brand fixes (battery, autostart, recordings folder, dialler); the share of work calls logged and recorded, weekly, per model. | Silent logging is what users praise; Android setup failures are the top complaint across Indian call apps (ch 1). | H · M | Android, builder | `phone_setup` flow and permission prompts: granted, denied, blocked per phone |
| 3 | **Speed-to-lead as a headline number.** Instant alert on a new or assigned lead, a first-call timer, median minutes to first call per seller and source. | Leads contacted within an hour were about 7 times likelier to qualify (Oldroyd et al. 2011, via secondary summaries, ch 1); Indian rivals already alert instantly. | H · S | Lead OS | time from lead arrival to first call |
| 4 | **Tiered notifications with hard caps, and a private, calm drift nudge.** Four Android channels; nothing during a call; quiet hours 20:00–09:00; at most 1 sounded drift nudge an hour and 3 a day; "On a break" option; managers see daily totals only, never live idle alerts. | Every extra reminder cut acceptance about 30%; batching improved attention; monitoring raises stress without raising performance unless it is light and developmental (ch 2). | H · M | builder, Android | nudge dismiss rate, channel switched off, time back to the next call |
| 5 | **Weekly target, daily pacing ring.** Counts conversations and follow-ups done (from call records, never dials or analytics), base and stretch tiers, "carried to tomorrow" instead of red failure, targets co-set with the seller. | Daily targets make people stop at the line; near-miss targets invite gaming; goals the seller helps set hold up better (ch 2). | H · M | Lead OS (team engine) | daily totals clustering at the target line (a warning sign) |
| 6 | **A brief-first call report on the phone, coaching one thing.** A one-line recap, the agreed next step with one-tap task and WhatsApp follow-up, one focus skill with a "next call, try…" line; strength first for new sellers; scores labelled as coaching estimates and kept out of targets, pay and leaderboards. | More than a third of feedback makes performance worse when it is about the person, not the task; weaker sellers are overloaded by detail (ch 1, ch 2). | H · M | Report (Brain 4.0) | report opened → section read; quick backs and loops on the report |
| 7 | **AI suggests, the manager confirms.** A coaching inbox, a weekly digest of calls worth hearing, "mark coached". Validate Hindi, Marathi and Hinglish transcription on our own calls before any score is shown as fact. | AI plus manager beat either alone in field experiments; code-mixed phone audio still has 16–30% error rates (ch 1). | H · M | Report, Admin | digest opened, calls coached per manager |
| 8 | **Budget phones first.** Tap feedback within 100–200 ms, screens within 1 s at p75 on low-end phones, written into the release gate per journey. | Most sellers use budget Android; waiting feels longer without feedback (ch 2); per-journey budgets in ch 3. | H · S | builder, Align (gate) | p75 tap-to-response by device tier (release gate) |
| 9 | **Speak the seller's language.** Hindi, Marathi and English UI with the code-mixed words sellers use, both scripts for input and search, icon plus label everywhere, counts instead of percentages, a native Marathi review. | Indian-language internet users outnumbered English users from 2016 and 70% found English keyboards hard (2017 industry survey); "call", "lead" and "follow-up" live as loanwords; numeracy varies widely (ch 2). | H · M | builder, Tutorials | screens with more quick backs and dead taps in hi/mr than en |
| 10 | **A research rhythm, not one-off opinions.** Monday friction report (top 3 fixes a week); a monthly 6–8 seller think-aloud round in their language, with an Indian moderator who isn't the designer, on a fictional "Sunrise Rooftops" workspace; a quarterly n=20 benchmark (SUS, SEQ, completion, time) with a pass rule; no A/B tests on completion until about 1,000 active sellers. | Sample-size and culture evidence (ch 3); Indian participants please the interviewer, so who moderates matters. | H · S | orchestrator, builder | Admin → Product telemetry → Friction |

**Also decided by the evidence (small, do with the above):** leaderboards off by default
(opt-in, top-3 recognition, never AI scores or dials); weekly consistency with grace days
instead of daily streaks; DPDP-ready recording controls (per-SIM Work/Personal/Off, private
calls) before the DPDP Rules bind in May 2027.

**Where the chapters disagreed, and the call:** chapter 1 suggested leaderboards that blend
in the skill-score trend; chapter 2's evidence (and AGENTS.md: no official AI scoring before
the AC-SVAL gates) says keep AI scores off leaderboards. This summary follows chapter 2.

**Built today to measure all of this:** the friction lab (Admin → Product telemetry →
Friction; the Monday markdown report). **Scale:** stay on Hostinger and fix the shared-box
risks first; move production to AWS Mumbai when net revenue reaches about ₹4 lakh a month or
a capacity or customer trigger fires (chapter 5). Prices and revenue stay internal.
