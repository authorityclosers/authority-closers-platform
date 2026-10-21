# Accuracy Brain 4.0: Digest A (lines 1 to 12625)

Source: `Accuracy Brain 4.0.txt` (UTF-8 with BOM, CRLF, 25,465 lines; the last line has no trailing newline).
Range read: lines 1 to 12,640, read in full with the Read tool in consecutive chunks. Line 12625 is the header of Dimension 11, which belongs to the other reader. Lines 12626 to 12640 were read only to confirm where my range ends.
Coverage: the table of contents and Dimensions 01 to 10.
Conventions: line numbers refer to the source file. "SP" means salesperson. "(inference)" marks my own reading and is not rubric text. Quotes are short. Person names from the examples are left out of the body and listed under "Names seen" at the end.

---

## 0. Overview of the range

### 0.1 Table of contents (lines 1 to 22)
"Accuracy Brain 4.0" defines 18 dimensions in 3 categories:
- **Category 1, How You Talk:** 1 Starting the Call, 2 Setting the Plan, 3 Tone, Pace & Pauses, 4 Listening Well, 5 Asking the Right Questions, 6 Building Connection, 7 Being Professional.
- **Category 2, How Well You Understand the Buyer:** 8 Finding the Decision-Makers, 9 Understanding Problems & Goals, 10 Understanding What They're Doing Now, 11 Understanding the Real Impact, 12 Understanding How They Will Decide.
- **Category 3, How Well You Move the Sale Forward:** 13 Matching the Right Solution, 14 Explaining the Solution Clearly, 15 Talking About Price & Budget, 16 Handling Objections, 17 Asking for the Decision, 18 Setting Clear Next Steps.

The text has no overall preamble, weighting or aggregation rule. No dimension weights or category scores appear in lines 1 to 12625.

### 0.2 Sizes (counted with awk; words are whitespace-separated tokens)

| Block | Lines | Lines (count) | Words |
|---|---|---|---|
| Table of contents | 1–26 | 26 | 110 |
| D01 Starting the Call | 27–917 | 891 | 3,472 |
| D02 Setting the Plan | 918–1951 | 1,034 | 4,881 |
| D03 Tone, Pace & Pauses | 1952–3268 | 1,317 | 5,435 |
| D04 Listening Well | 3269–4592 | 1,324 | 5,888 |
| D05 Asking the Right Questions | 4593–5943 | 1,351 | 5,695 |
| D06 Building Connection | 5944–7367 | 1,424 | 5,962 |
| D07 Being Professional | 7368–8754 | 1,387 | 5,780 |
| D08 Finding the Decision-Makers | 8755–9956 | 1,202 | 5,320 |
| D09 Understanding Problems & Goals | 9957–11255 | 1,299 | 5,721 |
| D10 Understanding What They're Doing Now | 11256–12624 | 1,369 | 5,631 |
| **Total, lines 1–12624** | | | **53,895** |

### 0.3 Shared template (every dimension follows it)
Each dimension block starts "BRAIN 4.0 — ACCURACY ENGINE", then gives the Simple Report Name and Category. The numbered sections are:
1. Purpose.
2. Boundaries with other dimensions.
3. Which part of the call is evaluated.
4. Context to consider.
5. Core evidence signals, which are always "evidence lenses, not a checklist".
6. What is not required.
7. 5/5, 4/5, 3/5, 2/5 and 1/5. Each level has a Definition, a "Simple Brain 4.0 Meaning" and worked examples (Why X/5?).
8. "Difference between 5/5 and 4/5".
9. "Not enough evidence", displayed as "—", with scenarios.
10. "1/5 vs — must never be confused", with a Canonical Rule.
11. A score calibration table.
12. "Confidence is separate from score" (High, Medium or Low).
13. "Do not score outcome".
14. Special accuracy rules.
15. Brain 3.0 development or coaching rule, and a longitudinal rule (in D04 to D10).
16. Final scoring rule.
17. Internal output format.
18. Example analyzer output.
19. Locked scoring table.

### 0.4 Rules repeated in all ten dimensions
- **Missing evidence is never a low score.** "—" (not enough evidence) must not be turned into 1/5, 3/5 or 5/5. A 1/5 needs clearly observed damaging behaviour.
- **Confidence is separate from the score.** "Score = quality of the behavior. Confidence = certainty …" Poor audio or a partial transcript lowers confidence, not the score.
- **Outcome is not scored.** Buying, saying no, call length and buyer friendliness never raise or lower a score.
- **5/5 needs positive evidence.** "Nothing went wrong" earns 4/5, not 5/5. This is stated explicitly in D01, D03, D04 and D06, and implied in the others.
- **Signals are lenses, not a checklist.** Nobody needs every signal to reach 5/5. Ritual phrases, counts and scripts are never scored.
- **No penalty for personality, accent, language mix, grammar or the use of "sir".** Accent and language are explicit in D01, D03 and D07. Personality is explicit in D01, D03 and D06. D06 also says language mirroring is not automatic rapport.
- **Whole-pattern rule** (D03 to D07). One bad moment does not define the call, and one good moment does not hide a bad pattern. D07 has an exception: one material ethics breach can define the call.
- **Longitudinal rule** (D04 onward). One call is evidence, not identity. Coaching must name the specific behaviour, never "listen better".
- **Common output fields.** Dimension, Category, Applicability, Rating (1–5 or —), Confidence, Evidence Span(s) as timestamps, Observed Behavior, Positive Evidence, Negative Evidence, Severity (Minor/Meaningful/Material; D07 differs), Reason for Rating, Inference (None or clearly labelled).

### 0.5 Artefacts in the text
- **Trailing source tags.** 163 lines end with a source tag: "Brain 2.1" ×86, "Brain 3.0" ×41, "Brain 2.0" ×32, "Brain 1.0" ×2 (lines 48, 553), "Pasted text" ×2 (262, 697). These look like citation chips from a chat export. The cited documents (Brain 1.0, 2.0, 2.1, 3.0) are not in this file.
- **Chat leftovers.** Every dimension ends with a chat-assistant line: "This is the version I would lock for Dimension NN … under the final 18-point Brain 4.0 framework." These are at lines 915, 1949, 3266, 4590, 5941, 7365, 8752, 9954, 11253 and 12622.
- **Formatting.** Tables are flattened into tab-indented lines, and "________________" separators remain.

---

## D01. Starting the Call

**1. Name, category, lines.** "Starting the Call". Category 1, How You Talk. Lines 27–915; blank lines to 917.

**2. Purpose (36–48).** "How well did the salesperson enter the conversation and get the call started?" A good start makes it easy for the buyer to begin talking. The SP should be natural, comfortable, prepared for the situation, easy to engage with and not immediately pushy. "The opening does not need to be impressive. It needs to make the conversation easy to begin."

**3. Boundaries (52–116).**
Scored here:
- how the SP enters the call;
- whether the start feels natural or awkward;
- whether the buyer is acknowledged;
- whether the opening fits the situation;
- whether it creates unnecessary resistance;
- whether the SP rushes into selling;
- whether the SP responds to an obvious opening situation;
- whether the call gets going smoothly.

Owned elsewhere:
- Agenda, how the call will work, permission to ask questions and the purpose of the call belong to **D02 Setting the Plan**.
- Full-call tone, speed, pacing, silence and pauses belong to **D03**. A "severely robotic or aggressive opening" can still lower D01 because it damages the entry (84).
- Relationship-building across the call belongs to **D06**.
- Honesty, respect, boundaries and ethics belong to **D07**. Unprofessional behaviour that "directly destroys the opening" also affects D01. Example: "This isn't a sales call" followed by a pitch. The D01 reason is "misleading opening immediately created distrust"; the D07 reason is "deceptive framing". The rule: "Same evidence can occasionally support two dimensions, but each dimension must judge a different effect." (116)

**4. Part of the call and context (120–164).**
- Evaluate the opening phase, not a fixed number of seconds. It is usually about the first 15–90 s, but "must not use a fixed time rule".
- The phase ends when the call moves into the plan, discovery, the buyer's situation, continuing an earlier conversation, or the substantive reason for the call.
- Opening length varies with the call: a scheduled consultation may need about 20 s, a referral about 60 s, an existing client one line.
- Identify the call type first: inbound enquiry, outbound cold call, scheduled consultation, follow-up, referral, existing relationship, returning prospect, previously interrupted conversation, or re-engagement.
- "The same opening may be excellent in one context and strange in another." For example, a formal self-introduction to someone already spoken with five times sounds "disconnected".

**5. Core evidence signals (168–244).**
- **A. Natural Entry:** the start sounds like a human conversation, not robotic, telecaller-style, over-rehearsed or abrupt.
- **B. Context Awareness:** the SP behaves as though they understand which conversation they are entering (an earlier enquiry, the last call, a referral, the buyer's time limit, the last topic). They need not say it every time.
- **C. Low Resistance:** the buyer is not made to feel trapped, pressured, confused, interrogated or ignored.
- **D. Appropriate Adaptation:** the SP reacts sensibly to what happens immediately. Example: the buyer is driving and the SP offers to talk later.
- **E. No Premature Selling:** no feature dumping, pitching, proving the company, defending price or pushing an offer before the conversation has begun.
- **F. Smooth Entry:** the opening leads somewhere. It is not greeting, then random small talk, then silence, then a sudden questionnaire.

**Not required (248–262).** "How are you?", using the buyer's name, weather, small talk, a joke, asking where the buyer is from, repeated thanks, a particular greeting, and following the Authority Closers script word for word. A 5/5 is possible without any of these. The opening "is evaluated by the effect created".

**6. Scores.**

**5/5, Excellent (266–350).** The opening clearly helps the call begin well: natural entry, understands context, easy participation, adapts, no unnecessary resistance, no rush to sell, smooth move into the conversation. There must be "clear positive evidence and no meaningful opening mistake". Meaning: "The opening actively helped the conversation."
- Ex1, scheduled enquiry: knows the context, enters naturally, wastes no time, leaves the buyer room to respond. Nothing elaborate is needed.
- Ex2, buyer sounds busy: the SP immediately offers to talk later or keep it focused. No ignoring, pushing, guilt or pitching; resistance is removed.
- Ex3, existing relationship: uses the context from the last call instead of pretending it is a first call. A formal introduction "would actually have been worse".
- Ex4, very simple opening (name plus "Good to connect"): can still be 5/5 if the situation needs nothing more. "Simple does not mean average." There is no explicit Rating line.

**4/5, Good (354–418).** Starts well and achieves the opening's purpose, with a minor weakness that does not meaningfully damage the call. Meaning: "The opening worked well."
- Ex1, slightly formal (good afternoon, how are you, thank you for your time): nothing wrong, but generic and formulaic.
- Ex2, a little unnecessary small talk (rain in the city): brief, harmless and well received.
- Ex3, slightly abrupt but fine: transactional but clear, respectful and efficient.

**5 vs 4 (421–431).** 5 needs "meaningful positive evidence that the opening was particularly well handled". A 5 is not automatic for having no obvious mistake. "5 should represent stronger execution than simply: 'Nothing bad happened.'"

**3/5, Average or mixed (435–525).** The opening works but is ordinary, mechanical, slightly awkward, transactional, somewhat scripted, or has noticeable but non-serious misses. The call stays workable. Meaning: "The opening worked, but it was average or mixed."
- Ex1, transactional ("you filled a form? … what do you do?"): it gets the call moving but feels like form-filling.
- Ex2, clearly scripted ("good morning sir … myself … calling from … sir"): functional and polite but mechanical. Indian English, grammar and accent are not penalised by themselves; "myself [name]" is not automatically a problem. If the buyer is comfortable, the same wording could earn 4/5.
- Ex3, mild talking over the buyer: the SP finishes their introduction over the buyer, then stops and recovers.
- Ex4, slight confusion ("I think regarding training?"): somewhat unprepared, but minor and quickly resolved.

**2/5, Weak (529–610).** Clear opening problems create noticeable friction, discomfort, confusion, resistance or seller-centred behaviour. The call is recoverable but below standard. Meaning: "The opening created noticeable friction."
- Ex1, immediate pitch (AI call-analysis features) before the buyer has spoken.
- Ex2, the buyer says they are driving and the SP carries on pitching. "The problem is not merely poor listening"; it makes the opening itself weaker.
- Ex3, forced small talk (city, area, family, kids) continued despite growing disengagement.
- Ex4, unprepared context ("you filled something somewhere"): the buyer has to explain why the SP called.

**1/5, Very poor or damaging (614–686).** The opening materially harms trust, comfort, willingness to engage or the chance of a productive call. Clear evidence is required. 1/5 is not "I didn't see a good opener"; it is "I clearly observed a damaging opener." Meaning: "The opening materially hurt the conversation."
- Ex1, aggressive entry ("just give me two minutes … just listen first").
- Ex2, the buyer clearly cannot talk (had asked the company not to call in office hours) and the SP overrides it ("just hear the offer once").
- Ex3, deceptive opening ("this isn't a sales call", then packages 30 s later). D07 may flag this separately.
- Ex4, hostile or condescending reply to "What is this regarding?" ("if you'll let me speak …").

**7. Not enough evidence, caps and overrides.**
- "—" scenarios (690–742): the recording starts mid-call (do not infer what came before); the beginning is missing, silent, distorted or unusable; speaker attribution is unclear; the call disconnects immediately.
- "Short call ≠ no evidence" (746–760): a 25-second call in which the SP says "you're making a mistake" after the buyer says not interested is enough for 1/5. "Evidence sufficiency is determined by observable behavior, not call duration."
- Canonical rule (777): "Absence of evidence is not evidence of poor performance."
- Confidence example (800–816): a good opening with muffled audio stays 4/5 with Low confidence. An average opening with clear audio is 3/5 with High confidence.
- Do not score:
  - outcome: a purchase, a friendly buyer or a long call does not raise the score; a no or a reserved buyer does not lower it (820–829);
  - personality: "A simple calm opener can be 5/5. A highly charismatic but pushy opener can be 2/5." (833–846);
  - accent or English quality: Hindi, Marathi, Hinglish, Indian English, regional accent, minor grammar (850–862).
- Final rule (866–867): never score against a preferred script. Score the observable effect, an "easy, natural and context-appropriate entry".
- Output format (871–884): the common fields. Applicability is Applicable or Not Enough Evidence only.
- Example output at 4/5 (888–896). Locked table (900–914).

**8. Inputs needed.**
- **Transcript text with speaker attribution: essential.** Unclear attribution means "—".
- **Timestamps or turn timing: essential** to bound the opening phase and give evidence spans; helpful for detecting talk-over.
- **Audio: helpful.** It shows a robotic or telecaller delivery, aggressive entry and overlap (3/5 Ex3). It is not strictly required for most findings.
- **Earlier-call or CRM context: essential** for Context Awareness. Was there an enquiry, a referral, previous calls, a request not to call in office hours? Whether a formal introduction is fine or "disconnected" depends on it.
- **Product knowledge: not needed.**

**9. Inconsistencies and unclear points.**
- Line 136 says "Both can be excellent." after three examples (lines 132–135).
- 5/5 Ex4 (339–350) gives 5/5 to a minimal opener with no special positive behaviour. That is in tension with 429–431, where 5 needs more than "nothing bad happened". It also has no Rating line.
- Delivery problems (robotic, aggressive, talking over) can lower both D01 and D03 (84, 494–506), and D04 owns interruptions. There is no de-duplication mechanism.
- The deceptive "not a sales call" opening is 1/5 here (666–675), 1/5 in D02 (1581–1588) and a hard violation in D07. One quote can therefore produce three 1/5s.
- 2/5 Ex2 (ignores "I'm driving") and 1/5 Ex2 (overrides "I can't talk") differ only by how explicit the buyer was and whether the override was deliberate. That is a judgement call.
- The example analyzer output (888–896) calls the opening "slightly formal", but the quoted line is informal Hinglish.
- Tags at 48, 236, 262, 553, 697–698, and the leftover line 915.

**10. Size.** 891 lines, about 3,470 words. It is the shortest dimension and has 19 scored examples plus 4 "—" scenarios.

---

## D02. Setting the Plan (Agenda)

**1. Name, category, lines.** "Setting the Plan". Category 1, How You Talk. Lines 918–1949; blank to 1951.

**2. Purpose (927–940).** "Did the salesperson make it clear what this conversation is for and how the call will move forward, in a way that feels useful rather than controlling?" The buyer should understand why they are talking, what the SP wants to understand, what may happen, why questions are asked, and that the call is meant to determine what makes sense for them. It is "not to perform an 'agenda script'" but to "reduce uncertainty". The Brain 2.0 opening flow is cited: Human Greeting → Why This Call? → Light Context → Agenda → Permission → Discovery.

**3. Boundaries (944–1015).**
Scored here: why-this-call clarity, useful direction, expectations, the reason for asking questions, choice or permission, fit to call type, and the transition into the real conversation.

Owned elsewhere:
- Greeting quality and the first seconds belong to **D01**. "Good to connect" may be a strong start but "has not yet established the plan".
- Quality and depth of the actual discovery questions belong to **D05**. D02 only asks whether there was a sensible frame for why questions are coming.
- Whether the SP then listens belongs to **D04**. A beautiful agenda followed by ignoring the buyer means D02 strong and D04 weak.
- Trust across the call belongs to **D06**. A transparent plan supports trust. The "Opening Trust Test" is cited: "I know why I'm here", "not rushing me", "I can speak honestly", "not being trapped".
- Lying about the call's purpose or hiding commercial intent also affects **D07**. D02 judges "plan misleading or unclear"; D07 judges "deceptive framing". Dual scoring is allowed "only when it represents two genuinely different failures".

**4. Part of the call and context (1019–1064).**
- Usually after the greeting and before or during the transition into discovery. There is no fixed window: the plan may come within 15 s, after 30 s of context, after the buyer explains why they called, or later.
- The word "agenda" need not be said. Judge whether the buyer received useful orientation.
- Call types that change how much planning is needed: first consultation, inbound, demo, discovery, cold outbound, follow-up, existing client, quick pricing clarification, second-stage buying call, joint decision-maker call, support-style sales call.
- A 45-minute discovery benefits from explicit framing; a 3-minute continuation needs almost none. "Formal agenda length must never be used as a quality measure."

**5. Core evidence signals (1068–1140).**
- **A. Why-This-Call Clarity:** the buyer reasonably knows why the call is happening. No need to restate it if both sides already know.
- **B. Useful Call Direction:** some idea of how the call will go. "Orientation, not ceremony"; announcing "17 questions" is too mechanical.
- **C. Reason for Discovery:** the buyer understands why questions are asked, which reduces suspicion.
- **D. Appropriate Permission / Participation:** room for the buyer to take part. Permission is not needed after every sentence ("Ask permission five times" must not be taught).
- **E. Expectation Setting:** realistic expectations, for example "I'll show you only what looks relevant".
- **F. Mutual Relevance:** the plan includes what the buyer wants from the call.
- **G. Transition Into Discovery:** the plan leads naturally onward and is not a five-minute speech.

**Not required (1144–1168).** "Here's the agenda", a stated duration, "first I will ask questions / then present / then decide", or "Is that okay?" / "Do I have your permission?". A very short frame can be 5/5. Long, polished or memorised agendas are not automatically better.

**6. Scores.**

**5/5 (1172–1267).** A clear, relevant, natural frame. The buyer knows why they are talking, what the SP wants to understand, how the call will go and what outcome it is moving towards. The frame is transparent, buyer-friendly, concise, context-specific and flexible: "direction without making the call feel scripted or controlled". Meaning: "The plan made the conversation clear and easy to follow."
- Ex1, first consultation: understand first, then show only what's relevant if it genuinely helps, "Is that okay?". It establishes why questions come first, that not everything will be pitched, that fit matters, and that the buyer can take part.
- Ex2, the buyer came only for pricing: the SP promises price, explains why 5–10 minutes of discovery comes first (to avoid a wrong quote), and commits to return to price.
- Ex3, follow-up: recaps three pending items without restarting discovery and links the call to the next decision.
- Ex4, joint call with a new stakeholder: a brief recap, then the new person's questions, avoiding a repeat pitch and second-hand relaying.
- Ex5, very short but strong ("understand the problem, then see if we're relevant. Fair?"). "Quality of framing matters more than length of framing."

**4/5 (1271–1343).** A useful plan with a minor weakness: generic wording, too formal, the buyer's priorities not explicit, permission implied, slightly long, or the reason for discovery could be clearer. Meaning: "The plan worked well."
- Ex1, good but generic ("questions, then I'll explain our solution"): no mention of fit or why discovery matters.
- Ex2, clear but slightly seller-led ("then I'll take you through our program, pricing and next steps" before fit is known).
- Ex3, follow-up plan without explicit permission: "Could even be 5 depending on context. If slightly unilateral: 4/5."
- Ex4, slightly long agenda (a list of six steps): 4/5 if engagement holds; 3/5 if it becomes a rigid speech.

**5 vs 4 (1347–1363).** 5 is context-aware, relevant, buyer-friendly and "clearly improves the conversation". 4 is a good, functional plan with small imperfections.

**3/5 (1367–1459).** Some framing exists but it is incomplete, mechanical, vague, overly procedural, somewhat seller-centred or only partly useful. The buyer can proceed, but an opportunity is missed. Meaning: "There was some plan, but it was average or incomplete."
- Ex1, minimal ("I'll ask you a few questions first"): no why and no what-next.
- Ex2, seller-centred agenda (company, products, packages, pricing, then your questions).
- Ex3, scripted ("as per our call flow, seven questions … objections").
- Ex4, ignores the buyer's stated priority (CRM integration question answered with "first some questions, then everything").
- Ex5, excessive permission language: this "can become 3/5" because it sounds uncertain and fragments the call. "More permission = higher score" is wrong.

**2/5 (1463–1559).** Poor framing creates noticeable confusion, resistance, mistrust, rigidity or misalignment, or "the situation clearly needed framing and the salesperson largely failed to provide it". Meaning: "The plan created noticeable confusion or resistance."
- Ex1, the buyer doesn't know why they are being questioned ("Revenue?", "Why do you need that?", "just tell me first").
- Ex2, a rigid agenda ignores the buyer's 10-minute limit ("we'll try").
- Ex3, vague purpose ("business related").
- Ex4, hidden discovery: the buyer asks the price, the SP says "definitely", then asks 15 questions without explaining the delay, which reads as evasion.
- Ex5, an overly controlling frame ("Please answer those, and after that I'll explain"): clear, but authoritarian.

**1/5 (1563–1628).** Framing materially damages trust, willingness, buyer autonomy or usefulness, or the SP "deliberately misrepresents the purpose of the call". Clear evidence is required. Meaning: "The plan materially hurt trust or the conversation."
- Ex1, deceptive purpose ("not about selling anything"). D07 may also flag it.
- Ex2, trapping frame ("at the end tell me yes or no … I need a decision today").
- Ex3, the buyer rejects the 45-minute plan for 10 minutes and the SP answers "No sir, this is our process."
- Ex4, misleading context ("calling regarding your account", then a premium package).

**7. Not enough evidence and special rules.**
- "Do not automatically give a low score merely because a formal agenda was not heard" (1635).
- "—" scenarios:
  - the recording starts after discovery has begun;
  - the opening is missing (audio starts at 02:10), unless later evidence shows how expectations were set;
  - a clear continuation where no agenda is needed (the buyer calls back with an answer). Do not give 1/5; "— / Not Applicable may be more accurate";
  - a very short operational call (payment link).
- Locked rule (1685–1695): absence of a formal agenda is not a poor plan; "Was useful orientation created?"
- Canonical rule (1716): "Missing agenda evidence is not evidence of bad agenda-setting."
- Calibration (1720–1734): "—" also covers "not reasonably required".
- Confidence example (1738–1754): muffled audio with a partly heard frame gives 4/5 with Low confidence. Do not reduce the rating for audio quality.
- Do not score:
  - outcome: deep discovery, a 45-minute call or a liked SP do not raise it; a no or a time-poor buyer do not lower it (1758–1770);
  - script compliance: no reward for a professional-sounding script (1774–1784).
- Do not penalise flexibility (1788–1797): briefly answering "what does the product do?" before returning to discovery is fine. "A good agenda provides direction. It is not a prison."
- Do not penalise a short or implicit plan (1801–1809): "Length and sophistication of agenda language are not scoring criteria."
- **Special rules:**
  - Buyer-created agenda (1813–1822): adopting the buyer's three topics can be 5/5; replacing the buyer's agenda may make the call worse.
  - Discovery without explicit permission (1826–1846): permission can be explicit, implicit or established by the nature of the call. The test is whether the buyer is informed, able to take part and not trapped.
  - Time expectations (1850–1863): give credit when time framing is materially useful. Do not downgrade for never stating a duration "unless lack of time alignment actually causes a problem".
  - The agenda should not pre-commit to a sale (1867–1876): "… and then we'll get you enrolled" before fit is weak framing.
  - Authority is not control (1880–1890): "calm conversational leadership. Direction without domination." Over-asking ("Can I ask? Is it okay?") and "This is our process. Just answer" are both weak extremes.
- Final rule (1894–1895).
- Output (1899–1918) adds these fields:
  - Applicability: Applicable / Not Applicable / Not Enough Evidence;
  - Why-This-Call Clarity: Clear / Partial / Missing / Unobservable;
  - Plan/Agenda: Strong / Functional / Weak / Harmful / Unobservable;
  - Permission/Participation: Explicit / Implicit / Weak / Not Required / Unobservable;
  - Buyer Priority Included: Yes / Partial / No / Not Relevant;
  - Expectation Setting: Strong / Functional / Weak / Not Required;
  - Transition: Natural / Mixed / Abrupt / Unobservable.
- Example output 5/5 (1922–1930). Locked table (1934–1948).

**8. Inputs needed.**
- **Transcript: essential.**
- **Timestamps: helpful** to place the frame relative to discovery and to give spans.
- **Audio: helpful only** for a controlling or rigid tone.
- **Earlier-call and CRM context: essential.** Is this a first consultation, a follow-up or a callback? What was pending? It decides whether a plan was needed at all ("—/NA").
- **Product knowledge: marginal.** Needed only to know whether the call is commercial, which bears on deception.

**9. Inconsistencies and unclear points.**
- The 2/5 definition (1472–1473) penalises a missing frame when "the situation clearly needed framing". Lines 1635, 1685–1695 and 1801–1809 warn against penalising an absent agenda. No criterion says when framing is "clearly needed" beyond call type.
- 4/5 Ex3 (1331–1333) and 3/5 Ex5 (1450) do not give a fixed rating.
- "Not Applicable" and "Not Enough Evidence" are both shown as "—" (1670, 1734). D02 has an NA applicability value but D01 does not.
- 2/5 Ex1 (unexplained "Revenue?") overlaps D05 (sensitive questions need a reason, 4844–4857).
- The deceptive-purpose 1/5 duplicates D01 1/5 Ex3 and D07.
- 2/5 Ex2 and 1/5 Ex3 are near-identical scenarios (a rigid agenda against a 10-minute buyer). The difference is "we'll try" versus an explicit refusal.
- Tags at 939–940, 1003, 1101, 1168, 1496, 1637, 1784, 1797, and the leftover line 1949.

**10. Size.** 1,034 lines, about 4,880 words. 23 scored examples and 4 "—" scenarios.

---

## D03. Tone, Pace & Pauses

**1. Name, category, lines.** "Tone, Pace & Pauses". Category 1, How You Talk. Lines 1952–3266; blank to 3268.

**2. Purpose (1961–1974).** "Did the salesperson use their voice, speaking speed and silence in a way that made the conversation easier to understand, comfortable to participate in, and appropriate to what was happening?"
- Delivery should adapt to the moment: softer and slower for sensitive questions; calm and direct for explanation; normal and confident for price; slower, not faster, for objections; silence before responding to an emotional disclosure; calm and natural for a direct close.
- Tonality is "part of the reasoning itself, not … decoration" (Brain 2.1 cited).

**3. Boundaries (1978–2059).**
Scored here: vocal tone, calmness or intensity, speed, rushing, slowing down, appropriate silence, filling silence, matching seriousness, delivery changes around price, objections and closing, and whether the voice supports clarity and comfort.

Owned elsewhere:
- Whether the SP understood the buyer belongs to **D04**. Good pauses followed by a reply to the wrong issue means D03 strong and D04 weak.
- Whether a question was useful belongs to **D05**. D03 asks only how it was delivered. "Why did you do that?" can sound curious or aggressive.
- Overall trust belongs to **D06**.
- Insults, dishonesty, disrespect and ethics belong to **D07**, but shouting, mocking or intimidating delivery affects both.
- Logical clarity of explanation belongs to **D14 Explaining the Solution Clearly**. A correct explanation that is rushed means D14 acceptable and D03 weak.
- Diagnosis and resolution of objections belong to **D16**. D03 asks whether the SP stayed calm, paused and kept an appropriate pace.

**4. Part of the call, evidence gate and context.**
- **Audio is required (2063–2105).** "Tone cannot be reliably judged from plain text alone." The same holds for pacing, pauses, volume, nervous laughter, vocal tension, confidence and emotional register.
  - With reliable audio, evaluate normally.
  - With a transcript only, **default to "—"** "unless the transcript contains reliable explicitly captured delivery evidence". Never infer "sounded confident" from "The price is ₹60,000."
  - With timestamps but no audio, approximate speaking duration, long monologues and obvious gaps may be supported, but not tone, register, volume, confidence or sarcasm. Timestamps alone "should not normally support a full … rating".
- **Whole call (2109–2123):** opening, discovery, sensitive questions, disclosures, explanation, presentation, price, objections, silence and closing. Never judge from one random sentence; give extra attention to high-stakes moments.
- **Context (2127–2140):** there is no universally right speed, energy, pitch, volume or pause length. Fast buyers, reflective buyers, B2B versus consumer and painful topics all differ. "Context wins" over enthusiasm. Evaluate appropriateness.
- **Style is not performance (2144–2162):** a flat voice may come from personality, tiredness, distraction, stress or language comfort. "Quiet ≠ weak. Energetic ≠ strong. Slow ≠ boring. Fast ≠ automatically bad."

**5. Core evidence signals (2166–2301).**
- **A. Tonal Appropriateness:** soft for sensitive topics, direct for clarity, steady for conviction, serious with serious buyers, light where appropriate.
- **B. Pace Control:** no rushing, machine-gun delivery or rapid monologues; slows for important points. "Controlled and appropriate", not simply slow.
- **C. Pause Quality:** space after important questions, price, objections, disclosures, close questions and realisations.
- **D. Comfort With Silence:** lets the buyer think instead of panicking and filling the gap.
- **E. Emotional Register:** delivery changes when emotion changes, for example a calm response to "the team almost collapsed" rather than "Great! … product is perfect".
- **F. Pressure Response:** composed at price, objections, disagreement, challenge, rejection and the close. Conviction is "steady, clear, unhurried", not shouted.
- **G. Price Delivery:** clear, normal, no apology, no nervous laugh, no rush. Whether budget was checked is scored elsewhere.
- **H. Objection Delivery:** slow down, stay calm, leave a moment, no rush into defence. "Objections should slow you down, not speed you up."
- **I. Closing Delivery:** natural, calm and direct, with no sudden "closing voice". The content of the decision question belongs to D17.
- Pauses have no universal meaning (2305–2332). Silence can mean thinking, discomfort, disengagement or emotion. A pause after an impact question can be excellent; 10 s of silence after "Can you hear me?" is not.
- No fixed pause lengths (2336–2351): "responsive timing, not stopwatch compliance."

**6. Scores.**

**5/5 (2355–2459).** Tone, pace and pauses consistently and clearly improve the call: natural, controlled, easy to follow, emotionally appropriate, calm under pressure, flexible and responsive. The SP knows when to speak, slow down, emphasise, pause and let the buyer think. It needs "strong positive evidence across more than one relevant part of the call when the full call is available". Meaning: "Your delivery actively helped the conversation."
- Ex1, sensitive disclosure (a loss year, three people let go): pause, calmer voice, then a careful question.
- Ex2, price: "₹60,000" stated normally, a pause, then a calm "Higher compared to what you had in mind?"
- Ex3, objection ("discuss with my wife"): brief pause and a calm diagnostic question, with no panic, rebuttal or speed-up.
- Ex4, a fast-speaking buyer: the SP matches the brisk pace without rushing and slows for an important financial point.
- Ex5, closing: asks "what would you like to do next?" and stops talking, without rescuing the silence.

**4/5 (2463–2524).** Clearly effective with minor imperfections: occasional filler, one slightly rushed section, one missed pause, a slightly repetitive pattern, or one tone mismatch quickly corrected. Meaning: "Your delivery worked well."
- Ex1, 40 seconds of slight rushing during an explanation, then back to normal.
- Ex2, price stated well but "we have EMI" added a little too quickly after "Hmm…".
- Ex3, slightly high energy with a calm, formal buyer; adjusted after a few minutes.
- Ex4, clear and calm but could leave a little more space after questions.

**5 vs 4 (2528–2544).** Do not give 5 "merely because the salesperson sounded fine".

**3/5 (2548–2636).** Understandable and workable, but inconsistent or ordinary: somewhat monotone, frequent filler, mildly rushed, unnecessary speed, few pauses, awkward silences, a non-damaging tonal mismatch, or decent in easy moments and weaker under pressure. Meaning: "Your delivery worked, but it was mixed or average."
- Ex1, consistently slightly fast, with little space between turns.
- Ex2, flat delivery: the same style for greeting, problem, product, price and close.
- Ex3, fills some silences ("I mean…", "Basically…") but sometimes waits.
- Ex4, slight nervousness at price (faster, justifying) then regains control.
- Ex5, a question tone that is occasionally too sharp ("Why didn't you do that earlier?"): "could become 4 or 2" depending on frequency and severity. No fixed rating.

**2/5 (2640–2716).** Tone, pace or pauses repeatedly create pressure, discomfort, confusion, difficulty following, interruption, emotional mismatch or reduced buyer space. Recoverable. Meaning: "Your delivery created noticeable friction."
- Ex1, rapid-fire stacked questions; the buyer says "one by one".
- Ex2, panic after a price objection: speeds up and lists inclusions with no pause.
- Ex3, repeatedly fills silence ("I need to think…", half a second, "one more thing…").
- Ex4, high energy during a serious disclosure ("Amazing … huge opportunity!").
- Ex5, nervous price delivery (umm, a laugh, an immediate defence).

**1/5 (2720–2782).** Delivery materially harms psychological safety, trust, clarity, participation or the buyer's ability to process. Clear observed evidence is required. Meaning: "Your delivery materially hurt the conversation."
- Ex1, aggressive raised voice ("you're not understanding me").
- Ex2, repeated domination: talks over the buyer with no pauses until "Can I finish?".
- Ex3, mocking laugh about consulting a partner. D07 may also flag disrespect.
- Ex4, an emotional disclosure ("don't want to fail again") is immediately converted into "make the payment today".

**7. Not enough evidence, caps and special rules.**
- **Stricter gate** (2786–2836). "—" when:
  - transcript only;
  - audio is severely distorted (tone, timing, pauses or overlap unreliable);
  - only a tiny fragment exists (5 s), "unless those five seconds contain unmistakably material behavior and the scoring system explicitly allows a narrowly scoped rating". Default is "—";
  - speaker attribution is unreliable.
- **Partial audio is not a score** (2839–2845). Forty minutes of call with only the first 30 s usable cannot give 4/5 from a good introduction.
- **Short calls can be enough** (2849–2861). A 90-second call with repeated talking over, rushing and a raised voice can support a strong negative rating.
- Canonical rule: "Unavailable audio is not poor tonality." (2878)
- Confidence example (2900–2914): noisy audio but clear rushing after objections gives 2/5 with Medium confidence, not 3/5.
- **Do not:**
  - score the buyer's tone; buyer behaviour is context only (2918–2930);
  - mind-read: write "pace increased immediately after stating price", then optionally "may indicate discomfort", keeping observation and interpretation separate (2934–2946);
  - reward a "sales voice" (radio-host, exaggerated enthusiasm, theatrical pauses). The standard is "Natural + appropriate + clear + adaptive" (2950–2960);
  - penalise accent, language, a naturally high or low voice, or quirks (2964–2978).
- **Special rules:**
  - Pace is relative to context. Words-per-minute may support the analysis but must not alone determine the rating (2982–2990).
  - **Change from the SP's own baseline under pressure is "one of the strongest signals"** (2994–3007). For example: 20 minutes calm, then rapid speech, a nervous laugh and immediate justification at price. Slowing down at a disclosure is positive adaptation.
  - Always inspect the price moment (3011–3025) and the first seconds after an objection (3029–3037). Strong: objection → pause → understand → respond. Weak: speed rises → instant defence → long explanation.
  - After emotional disclosure, the SP should become "more careful, not more aggressive" (3041–3055).
  - Pause after a question (3059–3079): answering your own question after half a second ("Is it motivation? Training? Leads?") can affect D03 and D05 "for different reasons".
  - Pause after a close (3083–3091): "No pressure though…" weakens the moment. D03 scores the inability to tolerate silence; D17 scores the question itself.
  - **Interruption routing** (3095–3112): failing to let the buyer finish because of inattention belongs to D04 (primary). A rhythm so rushed that there is no space and frequent overlap can also support D03. "Do not automatically score the same interruption twice."
  - Natural overlap ("yeah", "right", laughter) is not failure (3116–3129). Ask: did the buyer lose their turn, was a thought cut off, did the SP dominate, or was it acknowledgement?
  - Energy should match the moment; more is not better (3133–3146). Confidence is not loudness: "Certainty sounds calm." (3150–3163)
  - One bad moment (3167–3181): weigh frequency, severity, importance, recovery and effect. A single small miss can still be 4/5. A single severe moment (humiliation, destroyed trust, at a decision point) can weigh more. One good moment does not hide a bad pattern (3185–3192). Outcome is not scored (3196–3203).
- Final rule (3207–3208).
- Output (3212–3234) adds:
  - Applicability: Applicable / Not Enough Evidence;
  - Audio Evidence Available: Yes / Partial / No;
  - Overall Tone: Appropriate / Mixed / Poor / Unobservable;
  - Pace: Controlled / Slightly Fast / Slightly Slow / Rushed / Poorly Adapted / Unobservable;
  - Pause Use: Strong / Functional / Weak / Harmful / Unobservable;
  - Emotional Adaptation: Strong / Mixed / Weak / Not Tested / Unobservable;
  - Price, Objection and Closing Delivery: Strong / Mixed / Weak / Not Occurred;
  - Pressure Stability: Stable / Some Change / Significant Change / Not Tested.
- Example output at 4/5 with three spans, including "slightly rushed immediately after price" (3238–3247). Locked table (3251–3265).

**8. Inputs needed.**
- **Audio: essential.** Tone, pace, pause durations, pitch, loudness, laughter, overlap or interruptions.
- **Diarisation: essential.**
- **Word or turn timestamps: essential** for pause, overlap and speech-rate measurement and for the baseline comparison.
- **Transcript: essential** to locate the price, objection, disclosure and close moments. It is not enough on its own.
- **Per-speaker baseline speech rate: helpful.**
- **Call context (B2B or consumer, buyer style): helpful.**
- **CRM and product knowledge: not needed.**

**9. Inconsistencies and unclear points.**
- Line 2084: "explicitly captured delivery evidence" in a transcript is undefined. Does "[laughs]" or "[raises voice]" count?
- Line 2826: it does not say whether the system "explicitly allows a narrowly scoped rating".
- 3/5 Ex5 (2636) has no fixed rating.
- 2/5 Ex1 (stacked questions) is visible in a transcript, which strains the transcript-only "—" default. It also overlaps D05.
- 1/5 Ex2 (2749–2757, "Can I finish?") nearly duplicates D04 1/5 Ex2 (4058–4066), despite the routing rule at 3095–3112.
- 1/5 Ex3, the mocking laugh about a partner (2761–2769), is the same scenario as D06 1/5 Ex1 (6766–6774) and is serious humiliation under D07.
- 1/5 Ex4 (2773–2782) matches D06 1/5 Ex2 and D07 1/5 Ex6.
- Line 3022 calls D15 "Price & Budget" (the TOC name is "Talking About Price & Budget").
- The leftover line 3266.

**10. Size.** 1,317 lines, about 5,435 words. 23 scored examples and 4 "—" scenarios.

---

## D04. Listening Well

**1. Name, category, lines.** "Listening Well". Category 1, How You Talk. Lines 3269–4590; blank to 4592.

**2. Purpose (3278–3296).** "Did the salesperson actually understand and use what the buyer was saying, rather than simply waiting for their turn to speak?" Listening is active, not silence. It means:
- following what the buyer says;
- tracking facts and remembering earlier information;
- noticing contradictions and changes;
- allowing completion;
- acknowledging what matters;
- responding to the actual point;
- carrying information forward.

**3. Boundaries (3300–3380).**
Scored here: following meaning, answers shaping what comes next, remembered details, carried threads, noticed contradictions, no repeated answered questions, completion allowed, acknowledgements showing understanding, responses to what was said, earlier information used accurately later.

Owned elsewhere:
- **D05** asks "Was the next question useful?". D04 asks "Did the salesperson understand and use the answer?". Example: the buyer says leads are fine and conversion is weak; the SP says "Got it. How many leads do you get?". That lowers D04 even if the question is not inherently bad.
- Calm, slow, soft or confident delivery belongs to **D03**, but repeated cut-offs are listening evidence.
- Overall rapport belongs to **D06**.
- Depth of diagnosis belongs to **D09**. Accurate but shallow listening means D04 strong and D09 weaker.
- Whether an objection was solved belongs to **D16**. D04 asks only whether it was heard and understood.
- Personalisation of the presentation belongs to **D13 Matching the Right Solution**. The heading says "Connecting the Solution to Buyer Needs". Weak memory may explain weak matching; listening is "upstream".

**4. Part of the call and context (3384–3434).**
- Whole call, opening through next steps. Look for a pattern, not one "Okay". The key test: "Does what the salesperson says next prove that they understood what came before?"
- Listening is not quietness (3406–3419). Silent for three minutes followed by an unrelated scripted question is not listening. The talk–listen ratio is "supporting evidence" only.
- Listening is proven through response (3423–3434). A plain "I understand" is weak. An accurate reflection of the issue, number, timeline and distinction is strong.

**5. Core evidence signals (3438–3576).**
- **A. Tracks Important Facts:** team size, numbers, dates, attempts, priorities, stakeholders, timelines, concerns. A detail from minute 5 used at minute 18 shows continuity.
- **B. Responds to the Actual Meaning:** "Price is not my biggest issue … adoption" should be reflected as adoption, not answered by defending ₹60,000.
- **C. Uses Relevant Follow-Up:** answer → acknowledgement → relevant follow-up, not a fixed sequence.
- **D. Remembers Earlier Statements.**
- **E. Notices Contradictions:** clarify, do not accuse (budget not an issue, then ₹30,000 hard this month).
- **F. Allows Completion.**
- **G. Does Not Repeat Already-Answered Questions,** unless there is a reason to reconfirm.
- **H. Acknowledges Meaningfully:** the acknowledgement must connect to what was said, not be filler.
- **I. Notices Emotional Changes:** evidence-grounded, with no mind-reading.
- **J. Notices Missing Information:** for example, an answer that gives duration but not "why now".

Further framing rules:
- Paraphrasing is not required after every answer (3580–3596). "Got it" plus a sharp next question can be excellent. Reflect after *important* answers only.
- Listening is not agreeing (3600–3616). Respectfully challenging a buyer's belief with their own earlier data can be excellent listening.
- Interruptions need context (3620–3647): "Interrupt for value, not control." Redirecting an off-topic buyer to a relevant point is healthy. "Yeah yeah, price, right?" followed by "No." is poor.
- Natural overlap is not poor listening (3651–3665). Ask whether the buyer lost their turn, was cut off, or had their ending assumed.

**6. Scores.**

**5/5 (3669–3765).** Consistently shows active tracking and use: accurate references, relevant responses, follow-ups built on answers, meaningful acknowledgement, caught contradictions, remembered numbers, completion allowed, no repeats, buyer language carried forward, understanding updated. The buyer feels "This person is actually following me." Meaning: "You clearly understood and used what the buyer was telling you."
- Ex1, follows the exact thread (an agency gave leads but no sales → where is the breakdown).
- Ex2, at minute 25 recalls the "15 hours a week reviewing calls" mentioned at minute 6.
- Ex3, notices a contradiction without attacking ("money isn't an issue" versus "can't do ₹60,000 now").
- Ex4, corrects their own wrong assumption ("I misunderstood that").
- Ex5, hears the meaning behind "tired of managing this team" and explores it after a pause.

**4/5 (3769–3834).** Strong overall with minor misses: one forgotten detail, one slightly unrelated question, one unnecessary interruption, one missed reflection, occasional generic acknowledgement, slight repetition. Meaning: "You listened well, with only small misses."
- Ex1, one repeated question (team size), with an apology, in an otherwise continuous call.
- Ex2, generic "Got it" but consistently relevant follow-ups.
- Ex3, one interruption followed by "Sorry, continue."
- Ex4, misses one secondary thread (the manager resigned last month); 4/5 rather than 3 if it was not central.

**5 vs 4 (3838–3856).** Do not give 5 "simply because the salesperson didn't interrupt".

**3/5 (3860–3933).** Some real listening, but inconsistent: scripted jumps, forgotten information, generic acknowledgements, missed details, a few repeated questions, occasional interruptions, lost secondary threads. Meaning: "You listened enough to keep the conversation going, but important things were missed."
- Ex1, an important answer (the team doesn't follow up) followed by "What's your monthly revenue?"; the SP returns to it later.
- Ex2, repeats two answered questions.
- Ex3, "I understand", then a generic product explanation; asks about adoption later.
- Ex4, occasionally finishes the buyer's sentences.
- Ex5, a missed contradiction with otherwise reasonable fact tracking. No Rating line.

**2/5 (3937–4021).** Repeatedly fails to use what the buyer says: unrelated scripted questions, repeats, assumptions, interrupting important answers, ignoring corrections, missing obvious contradictions, unrelated responses, steering back to the seller's topics. "The buyer receives clear signals that they are not being properly heard." Meaning: "You missed or ignored important things the buyer was telling you."
- Ex1, script over answer: asks about lead quality right after "leads are actually good".
- Ex2, asks team size three times.
- Ex3, assumes the ending ("Wife, right? common objection" when it was the finance partner).
- Ex4, ignores the real concern (implementation) and defends the price.
- Ex5, the buyer says "that's not what I mean" repeatedly while the SP keeps their own interpretation.

**1/5 (4025–4091).** Failure to listen materially damages trust, accuracy, comfort, decision quality or usefulness, with clear repeated or severe evidence. Meaning: "The buyer was clearly not being heard."
- Ex1, the buyer says "You're not listening" after explaining twice that price is not the issue.
- Ex2, repeated dominating interruptions ("Can I finish first?", then interrupted again).
- Ex3, critical information ignored: the buyer says the CEO decides, and 20 minutes later the SP asks "shall we make the payment today?".
- Ex4, emotional disclosure ignored: "lost trust with my team", followed by "let me show you our three packages".

**7. Not enough evidence, caps and special rules.**
- "—" scenarios (4095–4145):
  - only salesperson audio exists, so "Okay" and "Got it" cannot be checked;
  - severe transcript gaps: "—", or a lower-confidence score only if other evidence suffices;
  - an extremely short call ("entering a meeting", "Sure"): "—", and "do not automatically give 5 because the salesperson politely accepted";
  - unreliable attribution.
- Short calls can be enough (4148–4157): a 90-second call in which the buyer says three times they only called about a payment and the SP keeps selling can support a low score.
- Canonical rule: "Missing buyer evidence is not poor listening." (4174)
- Confidence example (4196–4210): attribution uncertain in overlaps but clear recall gives 4/5 with Medium confidence.
- **A transcript can be strong evidence** (4214–4228): fit of responses, remembered details, repeats, contradictions, reuse of buyer language, connected threads. Audio adds interruptions, overlap, emotional changes and timing. Audio is not mandatory.
- **Never score by:**
  - acknowledgement words alone; ask what happened after them (4232–4248);
  - question count (4252–4260);
  - talk time alone; the ratio is supporting context only (4264–4274).
- **Special rules (4278–4480):**
  - Exact words matter: "accountability" must not become "you need more training".
  - Numbers, dates and commitments: forgetting an incidental detail is minor. Misremembering "₹1 lakh is too high" as "your budget is ₹1 lakh" is material. "Severity matters."
  - Contradictions are not dishonesty: notice → clarify → update. Never weaponise them ("But you already said budget isn't a problem!").
  - Correction and recovery: misunderstanding alone is not a severe penalty. Defending the wrong interpretation is "materially worse".
  - Redirection can be good listening.
  - Not every thread must be followed. Relevance sets severity: the office's suburb versus "head of sales resigned yesterday".
  - Listen to emotion without mind-reading. Report observable change ("responses became shorter and quieter").
  - Listening continues during the presentation (skip a feature the buyer says is unimportant), price (₹60,000 "isn't impossible", the worry is onboarding, so do not reply with EMI), objections ("I need to think" → what specifically?) and closing (a partner returns Monday, so do not ask to process payment now).
  - Listening must survive pressure. A five-minute defence after "price is high" without clarifying lowers the whole-call score.
  - One minor miss can still be 4/5, or 5/5 if truly inconsequential. One good reflection does not hide a bad pattern.
- Coaching rule (4484–4494): name exactly what was missed, never "Listen better".
- Longitudinal rule (4498–4511): "Listening was weak on this call", never "[name] is a bad listener".
- Outcome is not scored: do not lower for a difficult buyer or short answers (4515–4525).
- Final rule (4529–4530).
- Output (4534–4558) adds:
  - Buyer Audio/Transcript Coverage: Complete / Partial / Insufficient;
  - Fact Tracking: Strong / Mixed / Weak / Unobservable;
  - Earlier-Detail Recall: Strong / Mixed / Weak / Not Tested;
  - Response Relevance and Follow-Thread Quality: Strong / Mixed / Weak;
  - Contradiction Detection: Strong / Missed / Not Occurred;
  - Allows Completion: Strong / Mixed / Weak / Unobservable;
  - Repeated Answered Questions: None / Occasional / Repeated;
  - Acknowledgement Quality: Genuine / Functional / Robotic / Weak;
  - Correction/Recovery: Strong / Mixed / Weak / Not Tested;
  - Interruption Pattern: Healthy / Mixed / Problematic / Unobservable.
  - Applicability: Applicable / NEE only.
- Example output 4/5 (4562–4571). Locked table (4575–4589).

**8. Inputs needed.**
- **Two-sided transcript with reliable diarisation: essential.** Missing buyer audio means "—".
- **Timestamps: essential** for spans and for "earlier detail" references.
- **Audio: helpful** for interruptions, overlap and emotional change.
- **Earlier-call context: helpful.** Follow-ups often rely on what the buyer said last time.
- **Product knowledge: not needed.**

**9. Inconsistencies and unclear points.**
- The heading "Connecting the Solution to Buyer Needs" (3375) is an old dimension name; the text routes it to "Matching the Right Solution".
- **The same evidence is scored in D04 and D05.**
  - D04 4/5 Ex4 (a manager-resigned thread not returned to) is essentially D05 4/5 Ex1 (a senior-closer-left thread not explored).
  - D04 2/5 Ex1 and 3/5 Ex1 (an unrelated next question after an important answer) is essentially D05 2/5 Ex2 and 3/5 Ex2.
  - The boundary text separates "understood/used" from "useful next question", but the observable behaviour is the same.
- **Severity mismatch with D08.** Ignoring "my CEO decides" and asking for payment is 1/5 here (4070–4078). The near-identical scenarios in D08, the owning dimension, are 2/5 (9377–9389, 9404–9411).
- **Severity mismatch with D06.** Disclosure followed by an immediate pitch is 1/5 here (4082–4091). D06 calls the same sequence "weak" (7003) and lists it as a 2/5 pattern (6672).
- 1/5 Ex2 duplicates D03 1/5 Ex2.
- 4/5 Ex4 and 3/5 Ex5 have no Rating lines.
- The leftover line 4590.

**10. Size.** 1,324 lines, about 5,890 words. 23 scored examples and 4 "—" scenarios.

---

## D05. Asking the Right Questions

**1. Name, category, lines.** "Asking the Right Questions". Category 1, How You Talk. Lines 4593–5941; blank to 5943.

**2. Purpose (4602–4623).** "Did the salesperson ask useful questions at the right time that helped them understand the buyer, clarify uncertainty and move the conversation forward?" It is not about more questions; it is about "the next useful question". Abilities: clarify vague statements, follow threads, go deeper, understand context, test assumptions, find missing information, explore causes and consequences, learn what the buyer wants, ask difficult questions when relevant, and "stop questioning when enough understanding already exists". The Brain 2.0 formula is cited: Depth × Relevance × Listening, with question count not rewarded, and the loop Question → Understand → Hypothesize → Test → Update → Next Question.

**3. Boundaries (4627–4714).**
Scored here: relevance, the right next question, follow-ups drawn from answers, clarification of vague answers, useful depth, tested assumptions, explored gaps, adaptation, appropriate difficult questions, knowing when to stop, avoiding a questionnaire.

Owned elsewhere:
- Understanding and retention belong to **D04**, which is called a prerequisite.
- Final completeness of the problem and goal model belongs to **D09**. Good questions with limited answers means D05 strong and D09 incomplete.
- Whether the current approach, attempts and alternatives were understood belongs to **D10**.
- Completeness of impact belongs to **D11**.
- Whether stakeholders were identified belongs to **D08**.
- Whether the decision process was understood belongs to **D12**; the heading says "Decision Process".
- Diagnosis and resolution of objections belong to **D16**.
The questions themselves can count here as evidence of good questioning.

**4. Part of the call (4718–4757).**
- Whole call, not only the discovery section. "A powerful question at minute 30 may matter more than ten generic questions during minute 5."
- **Locked rule:** question count must never decide the score (4734–4748). Score relevance, timing, adaptability, depth and usefulness.
- Core loop (4752–4757): Ask → Listen → Understand → Clarify → Update → Ask the next useful question. Not: prepared question → answer → ignore → next prepared question.

**5. Core evidence signals (4761–4899).**
- **A. Relevance:** tied to what the buyer said, needed information, a decision variable or an open point. Asking the office location mid-problem is weak.
- **B. Clarification:** turns vague statements into specifics ("sales aren't good" → fewer leads, fewer conversions, or lower order value?).
- **C. Follow-Up Depth:** pursues important threads (what exactly the agency handled; expected versus actual).
- **D. Surface → Context → Cause → Impact:** Brain 2.0's four levels. It is not mechanically required, but strong questioning often moves beyond the surface.
- **E. Hypothesis Testing:** tests explanations instead of declaring them.
- **F. Missing Information:** "trying for six months" → what was tried → what happened.
- **G. Useful Difficult Questions:** money, failure, authority, personal impact, implementation capacity. They need relevance and a reason or softener. A question is not good just because it is bold.
- **H. Question Sequencing:** each question builds on what is known.
- **I. Questions That Create Buyer Thinking:** they reveal reality and do not push the seller's conclusion.
- **J. Knowing When to Stop.**

Further framing rules:
- Not an interview form (4903–4915): "Revenue? Team size? Budget?…" is disconnected even if each item is useful.
- Open is not automatically better than closed (4919–4934). Confirmations and either-or clarifications are useful. Ask: "Was this the right question for this moment?"
- "Why" questions need care (4939–4957). Quality covers relevance and framing. Tone is D03's, but poor framing can make the question itself inappropriate.
- **Do not manufacture pain** (4961–4968). Example: "How devastating is this for your family?" about a slight drop in email response.
- **No leading questions to force agreement** (4972–4980).

**6. Scores.**

**5/5 (4984–5093).** Consistently highly relevant, adaptive questions that create useful clarity. They follow answers, clarify, go deeper, test assumptions, uncover gaps, explore causes and consequences, handle sensitive areas well, adapt, and stop when it is clear. "The conversation does not feel like a script." Meaning: "You consistently asked the question that the conversation needed next."
- Ex1, from a vague problem to precise data: leads versus conversion → 18% to 9% → since when.
- Ex2, a previous attempt: what the agency handled, what was expected, where the gap remained.
- Ex3, a difficult question with context: asks about health or family after 15–20 hours a week for months, with a reason and a softener.
- Ex4, updates after an unexpected answer ("follow-up was fixed" → "what's the biggest breakdown now?").
- Ex5, knows when to stop ("I have enough context now. Let me show you the part that's relevant.").

**4/5 (5097–5167).** Strong with minor misses: one generic, missed, awkward, shallow or unnecessary question, or slight over-questioning. Meaning: "You asked good questions, with only a few missed opportunities."
- Ex1, misses one thread (the senior closer left).
- Ex2, generic openers ("tell me about your business") but sharp follow-ups.
- Ex3, a slightly premature budget question. No Rating line.
- Ex4, slightly too much depth while the buyer stays engaged. No Rating line.

**5 vs 4 (5170–5184).** 5 is not "They asked lots of good sales questions"; it means "highly adaptive and consistently useful".

**3/5 (5187–5281).** Some useful questions but inconsistent: a mix of relevant and generic, occasional checklist behaviour, missed follow-ups, surface questions only, disconnected sequencing, unnecessary questions, vague answers accepted. "Functional, but not consistently diagnostic." Meaning: "Some questions helped, but too many stayed generic, shallow or disconnected."
- Ex1, mostly surface level: never asks since when, why, what changed, what was tried or the impact after "conversion has fallen badly".
- Ex2, some strong follow-ups and some script jumps (an abrupt budget question).
- Ex3, accepts a vague "team isn't performing". No Rating line.
- Ex4, too many questions while the buyer's answers get shorter. No Rating line.
- Ex5, one-dimensional: the problem only, nothing on outcome, attempts or consequences.

**2/5 (5284–5386).** Questioning repeatedly fails to create understanding: a rigid script, unrelated questions, missed obvious follow-ups, accepted vague answers, repeated leading questions, premature assumptions, intrusive questions without relevance, confusing or frustrating questioning, a line continued despite evidence it is wrong, over-questioning after clarity. Meaning: "Your questions repeatedly missed what the conversation actually needed."
- Ex1, checklist interview with no acknowledgement or follow-up.
- Ex2, ignores an important answer ("our manager resigned" → "how many leads per month?").
- Ex3, leading ("your team lacks discipline, right?" … "consistency is the main issue, correct?").
- Ex4, premature diagnosis ("so lead quality is the problem. What's your ad spend?").
- Ex5, intrusive without context ("Is this affecting your marriage?" after mild workload).
- Ex6, endless discovery ("Before that, I have 12 more questions") after fit is clear. No Rating line.

**1/5 (5390–5459).** Questioning materially damages trust, comfort, the truthfulness of buyer answers, diagnostic accuracy or usefulness. Clear severe or repeated evidence is required. Meaning: "The questions materially damaged the conversation or pushed the buyer away from honest answers."
- Ex1, aggressive interrogation ("Why haven't you fixed this already?").
- Ex2, manufacturing pain ("your entire business could collapse, right?", "But eventually it could.").
- Ex3, a manipulative leading question ("If you really care about growing your company, investing today makes sense, doesn't it?").
- Ex4, repeatedly ignores a stated boundary (family) with two more family questions.

**7. Not enough evidence and special rules.**
- "—" scenarios (5462–5510):
  - the recording starts after discovery: "—" unless later sections give enough;
  - the buyer explains everything unprompted: do not penalise few questions; a positive rating is possible if the few questions were clearly appropriate; "—" if almost no question opportunity occurred;
  - a very short operational call;
  - buyer audio missing: "often —", or "low-confidence partial scoring only when question relevance is independently clear".
- Few questions is not "—" (5514–5523): five excellent questions can be 5/5. "Never require a minimum question count."
- Many questions is not positive evidence (5527–5537): 40 generic questions is abundant evidence of weak questioning, 2/5 or 1/5.
- Canonical rule: "Missing questioning evidence is not poor questioning." (5554) Calibration "—" includes "not reasonably required".
- Confidence example (5576–5589): missing sections but strong follow-up gives 4/5 with Medium confidence. Confidence here is defined as "certainty that available evidence represents the skill accurately".
- A transcript is often enough (5593–5609); audio adds tone, discomfort, interruption and emotional reaction.
- **Special rules (5613–5828):**
  - Follow-up questions matter more than prepared ones. Inspect what comes after an unexpected answer.
  - "New evidence should update questioning."
  - Each question should reduce a named uncertainty: timeline, attempt history, authority, objection.
  - Questions should not only confirm the seller's theory (solution bias).
  - Clarify before going deeper: "Depth without relevance becomes intrusion."
  - Quantification should follow reality, with no fake precision.
  - Ask about impact without assuming it (not "how badly is this affecting your mental health?").
  - Difficult questions need relevance; do not penalise direct questions for being uncomfortable.
  - **Do not penalise not asking what is already known** (for example, the buyer already said co-founders decide together).
  - Presentation questions count ("Does this connect to the manager visibility problem?").
  - Objection questions ("High compared to what?").
  - Buying signals should change the questioning ("What do you need to feel clear enough to decide?").
  - **Know when not to ask:** answer direct buyer questions (for example, how onboarding works).
  - One bad question can still allow 4/5, or 5/5 if insignificant. One great question does not hide a weak pattern.
  - Success is not measured by long answers.
  - Buyer resistance ("Why are you asking me this?") is diagnostic of the questioning. Do not conclude "the buyer is difficult".
- Coaching (5832–5848): name the exact failure (follow-up, root cause, history, attempts, consequence, emotional depth, quantification).
- Longitudinal (5852–5860). Outcome is not scored: do not lower for short answers or a private buyer (5864–5874).
- Final rule (5878–5879).
- Output (5883–5908) adds:
  - Applicability: Applicable / NA / NEE;
  - Question Opportunities Observed: Low / Moderate / High;
  - Question Relevance: Strong / Mixed / Weak;
  - Follow-Up Quality and Clarification Quality: Strong / Mixed / Weak / Not Tested;
  - Depth: Surface / Context / Root Cause / Meaning-Impact / Mixed;
  - Adaptation: Strong / Mixed / Rigid;
  - Hypothesis Testing: Strong / Mixed / Assumptive / Not Tested;
  - Sensitive-Question Framing: Strong / Mixed / Weak / Not Occurred;
  - Leading Question Risk: None / Occasional / Repeated;
  - Script Interrogation Risk: None / Some / Strong;
  - Over-Questioning: None / Some / Material;
  - Knows When to Stop: Strong / Mixed / Weak / Not Tested.
- Example output 4/5 (5912–5922). Locked table (5926–5940).

**8. Inputs needed.**
- **Two-sided transcript: essential.**
- **Timestamps: helpful.**
- **Audio: helpful** for framing and tone of "why" questions and buyer discomfort.
- **Earlier-call and CRM context: helpful.** It tells what is "already known", so the SP is not penalised for skipping it.
- **Product knowledge: marginal.** Useful only to detect solution bias.

**9. Inconsistencies and unclear points.**
- The heading "Decision Process" (4700) is not the TOC name.
- **Duplicates across dimensions:**
  - 1/5 Ex2, manufacturing pain (5421–5432), is near-identical to D09 1/5 Ex1 (10732–10742).
  - 2/5 Ex4, premature diagnosis, matches D09 2/5 Ex2.
  - 4/5 Ex1 and 2/5 Ex2 match D04 4/5 Ex4 and D04 2/5 Ex1.
  - The sharp "why" question is used in D03 3/5 Ex5 and here (4939–4957).
- **Severity mismatch with D07.** Ignoring a stated family boundary twice is 1/5 here (5448–5459). D07 rates returning twice to a stated finance boundary as 2/5, rising to 1/5 only on explicit refusal and aggressive persistence (8047–8055).
- 4/5 Ex4, 3/5 Ex4 and 2/5 Ex6 form an over-questioning gradient (slight, buyer shortens answers, "12 more questions"). The deciding factor is the buyer's reaction, which is implicit.
- The example output lists spans out of chronological order (5918–5921).
- Several examples have no Rating line.
- The leftover line 5941.

**10. Size.** 1,351 lines, about 5,700 words. 24 scored examples and 4 "—" scenarios.

---

## D06. Building Connection

**1. Name, category, lines.** "Building Connection". Category 1, How You Talk. Lines 5944–7365; blank to 7367.

**2. Purpose (5953–5966).** "Did the salesperson create a conversation in which the buyer had reason to feel comfortable, understood, respected and safe enough to speak honestly?" It is not about becoming friends, laughter, personal questions, hobbies, repeating the buyer's name or rapport techniques. The objective is "enough human comfort and trust that the buyer can communicate honestly — including when they disagree, feel uncertain, admit a problem, reveal a concern or say no."

**3. Boundaries (5970–6047).**
Scored here:
- whether the buyer can speak naturally;
- genuine versus performative interest;
- whether the SP stays on the buyer's side;
- disagreement without conflict;
- safe uncertainty;
- careful handling of vulnerability;
- non-judgement;
- natural rather than manufactured rapport;
- whether trust grows or weakens;
- whether the relationship survives money, objections and hard topics.

Owned elsewhere:
- The entry belongs to **D01**. An awkward start can be followed by excellent connection, or the reverse.
- Listening belongs to **D04**. An accurate listener can be cold, and a warm SP can listen poorly. "Rapport is not discovery."
- Detailed delivery belongs to **D03**. Tone counts here only as far as it helps or harms the relationship.
- Diagnostic usefulness belongs to **D05**. D06 asks whether the buyer felt understood rather than "interrogated or processed".
- Respect, honesty, ethics and boundaries as conduct belong to **D07**. The SP can be professional but distant, or warm but unprofessional.

**4. Part of the call and context (6051–6160).**
- Whole call. The real test is often after the comfortable part: "I don't agree", "too expensive", "I don't want to buy". "Does the human connection survive?"
- **Locked rule (6080–6098): rapport is not likability.** Do not score personality. Ask whether the SP was "genuinely with them rather than simply working them toward a sale".
- No rapport checklist (6102–6121): hobbies, hometown, family, sports, weather, jokes, compliments are not required. Forced similarity, such as "my cousin also lives in [your city]", can reduce trust.
- Trust must be observed in behaviour (6125–6139): the buyer voluntarily reveals failures, mistakes, money realities, private concerns or fears, or asks for advice. These are "signals, not proof".
- Buyer openness supports the judgement but is not the score (6143–6160). Some buyers are open and some private. Judge what the SP did with the opportunities: made openness easier, preserved comfort, responded safely, respected boundaries, and whether trust rose, held or fell.

**5. Core evidence signals (6164–6289).**
- **A. Genuine Interest:** curiosity that feels real, not procedural.
- **B. Prospect-Side Thinking:** for example, "If adoption doesn't happen, it doesn't matter how good the product is", without defending the product.
- **C. Non-Judgmental Response:** "wasted ₹4 lakh" → "what went wrong?", not "why would you spend that much?".
- **D. Emotional Safety:** the buyer can say "I don't know", "I'm worried", "I made a mistake", "I disagree", "I can't afford this", "I'm not ready", "I don't trust that claim" or "I don't want this" without the SP becoming defensive, dismissive, pressuring, mocking or cold. "One of the strongest signs."
- **E. Meaningful Acknowledgement:** appreciation for openness, without exaggerated emotional language.
- **F. Comfort Through Difficult Questions:** comfort + relevance + respect ("slightly direct … is ₹60,000 realistically within range?").
- **G. Safe Disagreement:** respectful challenge using the buyer's own data.
- **H. Consistency When Money Appears:** no personality shift at price or closing.
- **I. Comfort With Buyer Uncertainty:** "That's okay. What's still unclear?" rather than "I've explained everything".
- **J. Trust Repair:** "You're right — I misunderstood that."

Further framing rules:
- Empathy must be real, not performed (6293–6301).
- Empathy is not always agreeing (6305–6320). Over-accommodation is weak; "Can I challenge one part of that?" can strengthen connection.
- Connection supports truth, not just comfort (6323–6335).
- **Locked rule: trust must never be exploited (6338–6353).** "Trust gives permission for deeper truth — not permission for more pressure."

**6. Scores.**

**5/5 (6357–6474).** Consistently natural, safe and trustworthy. The buyer has strong reason to feel heard, respected, comfortable being honest, free to disagree, safe with uncertainty and not manipulated. The SP shows genuine interest, does not judge, protects dignity, stays consistent under pressure, handles vulnerability carefully, challenges respectfully and avoids fake friendliness. Meaning: "The buyer had strong reason to feel comfortable, understood and safe being honest with you."
- Ex1, the buyer admits about ₹5 lakh wasted: the SP pauses, thanks them, does not shame or exploit, and stays curious.
- Ex2, the buyer challenges the SP's motive: the SP owns their commercial intent transparently ("if it doesn't fit, I don't want you buying it either").
- Ex3, safe disagreement ("my team is the entire problem" → respectful challenge).
- Ex4, buyer uncertainty treated as information.
- Ex5, the connection survives price: equally calm after "higher than I expected".
- Ex6, natural humour that fits the buyer's register.

**4/5 (6477–6551).** Clearly good with minor misses: one generic empathy line, one awkward transition after vulnerability, limited warmth but good trust, one mild defensiveness repaired, good but not deep. Meaning: "You built good comfort and trust, with only a few small misses."
- Ex1, professional and genuine but somewhat formal; the buyer still raises concerns openly.
- Ex2, a slightly generic "that must have been frustrating" followed by a genuine follow-up.
- Ex3, a minor defensive moment, then "Sorry — let me understand what part you disagree with".
- Ex4, comfortable but mostly functional; "Not automatically 5 because nothing went wrong."

**5 vs 4 (6554–6567).** 5 needs evidence that the connection "actively improves the quality of honesty". Do not give 5 because the buyer was friendly, the SP smiled or there was laughter.

**3/5 (6571–6656).** Workable and respectful but ordinary or inconsistent: polite but transactional, mixed curiosity, generic empathy, occasional approval-seeking, awkward around difficult topics, weakens slightly at money or objection. Meaning: "The conversation was comfortable enough, but the connection stayed average or inconsistent."
- Ex1, polite but transactional ("Okay sir. Understood sir.").
- Ex2, repetitive "I understand".
- Ex3, friendly in easy parts, slightly defensive and formal at a price concern, recovers. No Rating line.
- Ex4, too much small talk, manufactured rather than meaningful. No Rating line.
- Ex5, over-accommodating ("Yes sir, absolutely" to "my staff is useless"), challenges later. No Rating line.

**2/5 (6661–6745).** Repeated distance, discomfort, judgement or mistrust: fake rapport, obvious techniques, dismissing concerns, judgement, frequent defensiveness, trying too hard to be liked, ignoring emotional cues, cold and transactional after a disclosure, personality change at price or close, forced humour, a buyer growing guarded. Meaning: "The buyer had noticeable reasons to hold back or trust you less."
- Ex1, fake rapport (city, cricket) despite short answers.
- Ex2, judgemental ("Then obviously how will sales come?") and the buyer goes quiet.
- Ex3, defensive ("hundreds of clients use it. You haven't even tried it.").
- Ex4, empathy as a sales setup ("That's exactly why our premium program is perfect"). No Rating line.
- Ex5, a personality shift at price: cold, argumentative, impatient. No Rating line.

**1/5 (6749–6820).** Material damage to trust, emotional safety, dignity, honesty or willingness to continue openly. Strong observed evidence is required. Meaning: "Your behavior materially damaged the buyer's trust or sense of safety."
- Ex1, humiliating the buyer (laughs at consulting a spouse).
- Ex2, exploiting vulnerability ("If you don't act today you'll probably repeat the same mistake").
- Ex3, attacks expressed distrust ("Then maybe you're not serious enough.").
- Ex4, uses a personal disclosure against the buyer ("You told me your family is suffering. Then how can you not buy this?").
- Ex5, relationship breakdown with refused repair ("If you can't handle it, that's your choice.").

**7. Not enough evidence and special rules.**
- "—" scenarios (6824–6876): an extremely short call (do not give 5 "merely because they were polite"); buyer side missing ("often —"); recording begins late (unless later interactions give independent evidence); purely operational (resend invoice).
- A reserved buyer is not "—" (6879–6888): calm, honest, non-defensive handling of a cautious buyer's concerns can earn 4/5 or 5/5. An open buyer is not automatically a high score (6892–6901).
- Canonical rule: "Lack of connection evidence is not evidence of bad connection." (6917)
- Confidence example (6939–6952): a strong transcript with partly missing audio gives 4/5 with Medium confidence; do not reduce to 3.
- A transcript can give strong evidence (6956–6973). Audio adds warmth, sarcasm, emotional matching, tension, laughter and vocal defensiveness. Audio "improves this dimension, but unlike Tone/Pace/Pauses it is not always mandatory".
- Do not mind-read trust (6977–6987). Write "The buyer openly disagreed twice without withdrawing", not "felt psychologically safe".
- **Special rules (6991–7243):**
  - Vulnerability sequence: strong is disclosure → acknowledgement → space → understanding. Weak is disclosure → immediate pitch. Damaging is disclosure → pressure.
  - Disagreement: strong "That's fair. Let me understand…"; weak "No sir, that's not correct."; damaging "You're thinking about this completely wrong."
  - Objection: did the human relationship change?
  - A "No": strong is clarify fit, timing or priority and then respect it; weak is a punitive "Why not?"; damaging is "Then you're making a mistake." Safety must not be conditional on purchase.
  - Reward trust repair.
  - Humour is contextual.
  - With multiple stakeholders, protect everyone's dignity and avoid "us vs them".
  - Challenge can strengthen connection.
  - **Approval-seeking is not rapport**: agreeing with everything, unnecessary discounts, avoiding hard questions, excessive apologies, constant compliments.
  - Balance empathy with challenge ("Empathy + Honesty; Comfort + Challenge; Trust + Clarity").
  - Connection should not vanish when selling starts (congruence).
  - Commercial intent need not be hidden.
  - The SP's own personal stories are not rewarded unless they help the buyer.
  - Language mirroring is not automatic rapport.
  - **Connection can be repaired mid-call.** Score the whole pattern. A great start can be destroyed later.
  - One friendly moment does not prove connection. One awkward moment can still allow 4/5.
- Coaching (7247–7265): use specific behaviour (for example, stay with a disclosure "for one more response before presenting"). Longitudinal (7269–7283): "Connection was weak on this call", never "You are bad at connecting with people."
- Outcome is not scored (7287–7298): "A buyer can say no while having excellent trust."
- Final rule (7302–7303).
- Output (7307–7332) adds:
  - Applicability: Applicable / NA / NEE;
  - Genuine Interest: Strong / Mixed / Weak / Unobservable;
  - Prospect-Side Thinking;
  - Non-Judgment and Emotional Safety (… / Not Tested);
  - Buyer Honesty Signals: Strong / Some / None / Unobservable;
  - Vulnerability Handling and Disagreement Handling (… / Not Occurred);
  - Price/Objection Relationship Stability: Stable / Some Shift / Strong Shift / Not Tested;
  - Approval-Seeking Risk and Fake Rapport Risk: None / Some / Strong;
  - Trust Repair (… / Not Required);
  - Stakeholder Respect (… / Not Applicable).
- Example output 5/5 (7336–7346). Locked table (7350–7364).

**8. Inputs needed.**
- **Two-sided transcript: essential.**
- **Audio: important but not mandatory.** It reveals warmth, sarcasm, coldness at the price shift, laughter and tension.
- **Timestamps: helpful** for spans and for before/after-price comparisons.
- **Earlier-call context: helpful** to know whether this is an existing relationship.
- **Product knowledge: not needed.**

**9. Inconsistencies and unclear points.**
- **Same evidence across dimensions.**
  - 1/5 Ex1 (6766–6774) duplicates D03 1/5 Ex3, and is serious humiliation, a 1/5 item, in D07.
  - 1/5 Ex2 matches D03 1/5 Ex4 and D07 1/5 Ex6.
- **Severity mismatches.**
  - Disclosure → pitch is "weak" here (7003) and a 2/5 pattern (6672, 6724–6731), but 1/5 in D04 Ex4.
  - Disclosure used as leverage is 1/5 here (6801–6809), but similar wording is 2/5 in D07 Ex4 (8059–8066) ("beginning to be used").
- Several examples have no Rating line.
- The leftover line 7365.

**10. Size.** 1,424 lines, about 5,960 words. It is the largest in the range: 25 scored examples and 4 "—" scenarios.

---

## D07. Being Professional

**1. Name, category, lines.** "Being Professional". Category 1, How You Talk. Lines 7368–8752; blank to 8754.

**2. Purpose (7377–7396).** "Did the salesperson behave in a truthful, respectful, responsible and professionally appropriate way throughout the conversation — even when doing so could make the sale harder?" "Much bigger than sounding formal." The list:
- tell the truth and represent the product accurately;
- respect the buyer and protect dignity;
- respect boundaries and consent;
- avoid manipulation, fake urgency or scarcity, false promises and misleading claims;
- stay respectful in disagreement;
- respect a genuine "no";
- correct mistakes;
- be willing to recommend no sale.
Brain 2.0's hard constraints and Brain 3.0's critical-issue override are cited.

**3. Ethics Gate and boundaries.**
- **Ethics Gate (7400–7438).** Unlike the other dimensions, D07 has a 1–5 score **plus** an internal Ethics Status:
  - **PASS:** no meaningful ethical issue.
  - **WARN:** questionable behaviour, ambiguity, or not enough context around a potentially important issue.
  - **FAIL:** a clear material ethical violation.
  - A FAIL does not disappear because the deal closed or the score is high. Example: 40 respectful minutes, then a false "This offer expires tonight" gives "Being Professional: 1/5 or severely reduced; Ethics Gate: FAIL". "One material lie can outweigh many minutes of polite behavior."
- **Boundaries (7442–7518).**
  - Scored here: truthfulness, claim accuracy, honesty about uncertainty, respect, dignity, ethics, autonomy, consent, boundaries, confidential or personal topics, responsible recommendation, fairness to competitors, promises and guarantees, urgency and scarcity, response to stop or no, transparency, correcting mistakes, responsible commercial conduct.
  - Warmth belongs to **D06**.
  - Fast or flat delivery and pauses belong to **D03**, unless the delivery is mocking, threatening, humiliating or disrespectful.
  - Question usefulness belongs to **D05**, but D07 scores questions that cross boundaries, invade privacy without relevance, manipulate, shame or ignore a "don't discuss" request.
  - Objection quality belongs to **D16**; D07 asks whether the SP was truthful and respectful while handling it.
  - Close timing belongs to **D17**; D07 asks whether autonomy and informed consent were preserved.
- **Locked:** professional does not mean formal (7522–7539). "Professionalism is conduct, not formality." Corporate words, "sir/ma'am" and polished English are not rewarded.
- Professional does not mean passive (7543–7555). The SP may challenge, disagree, ask difficult questions, recommend strongly, ask directly for the sale, clarify a vague no, or confront inconsistency. Never "use disrespect, dishonesty or manipulation to create movement."

**4. Part of the call.** Whole call (inference: not stated in a dedicated section; implied by "throughout the conversation" and the whole-call examples). Context: almost every genuine sales interaction is applicable (8177).

**5. Core evidence signals (7559–7707).**
- **A. Truthfulness:** no lies, no pretending to know, no misleading framing ("I'll confirm rather than guess" versus "definitely supported" when unsure).
- **B. Accurate Claims:** distinguishes fact, estimate, expectation, possibility and guarantee ("you will definitely double conversion" is weak).
- **C. No Fake Urgency:** no invented deadlines, expiring offers, price rises, limited slots, management approvals or "last chance". Real urgency is fine.
- **D. No Fake Scarcity.**
- **E. Honest Proof:** no fabricated or distorted testimonials, results, case studies, client counts, success rates, screenshots or stories.
- **F. Buyer Dignity:** no humiliating, mocking, shaming, talking down or controlling sarcasm, including towards a spouse or partner.
- **G. Respect for Boundaries:** do not return to a declined topic; stop calling when asked, per the business process.
- **H. Respect for Genuine "No":** clarify, then respect. "One-call resolution must never override informed consent."
- **I. Responsible Recommendation:** refuse the sale when the product cannot solve the need, outcomes are impossible, harm is foreseeable, service cannot be delivered, or ethics or contract would be violated. "Long-term trust outranks short-term revenue."
- **J. Honest Competitor Discussion.**
- **K. Responsible Handling of Mistakes.**
- **L. Respect for Consent & Autonomy.**

**Hard ethical violations (7711–7727):**
- deliberate lie;
- fake scarcity or fake urgency;
- fabricated testimonial or result;
- unsupported guarantee presented as fact;
- deliberately hiding material information;
- knowingly selling an unsuitable solution;
- pressure after a clear genuine no;
- false competitor or product claims;
- invented ROI or financial outcome;
- falsified qualification;
- ignoring an explicit stop or opt-out;
- knowingly misrepresenting commercial terms.

**A hard violation overrides averaging (7731–7741).** 39 good minutes plus 1 minute of knowingly false guarantee is not 4/5. "Severity matters more than duration."

**6. Scores.**

**5/5 (7745–7843).** Consistently honest, respectful and sound in judgement: accurate facts, certainty separated from uncertainty, dignity, boundaries, autonomy, no manipulation, no fake urgency or scarcity, professional under disagreement, mistakes corrected, fit-based recommendation, willing to lose the sale. Gate **PASS**. Meaning: "You were consistently honest, respectful and responsible — even when doing the right thing could make the sale harder."
- Ex1, admits uncertainty about a custom CRM integration and will confirm.
- Ex2, says "not the best fit" and declines to sell.
- Ex3, real urgency (pricing changes Monday) given without weaponising it ("You don't need to decide because of that").
- Ex4, fair competitor comparison (the other product is cheaper and may suit a price-first buyer).
- Ex5, a genuine no is clarified once and then respected.
- Ex6, corrects an earlier error (onboarding is "three to five business days", not three days).

**4/5 (7847–7905).** Strong with minor lapses: careless wording, one unnecessary competitor comment, mild defensiveness, one non-material fact stated too confidently and then corrected, one slightly pushy phrase repaired. No material violation. Gate normally **PASS**, possibly **WARN** if a claim needs verification. Meaning: "You were professional throughout, with only small moments that could be cleaner."
- Ex1, an overconfident integration claim immediately qualified.
- Ex2, a mild competitor dismissal, then self-correction.
- Ex3, a slight push then respect: "Depending on execution this could be 5. If slightly more pressure than necessary: 4/5."

**5 vs 4 (7908–7918).** 5 means judgement is strong "especially in moments where revenue and ethics could conflict".

**3/5 (7922–7991).** Generally acceptable with no major violation, but inconsistent: careless claims, casual at the wrong moment, mild defensiveness, unnecessary competitor criticism, some pressure, questionable humour, exaggeration without material deception, unclear boundaries, sloppy commitments. The gate is not specified. Meaning: "You were generally professional, but some moments were careless or unnecessarily risky."
- Ex1, a casual competitor attack ("isn't that good") with vague reasons, later fair.
- Ex2, mild overstatement ("probably solve most of your follow-up issues"), later qualified.
- Ex3, slightly pushy after hesitation ("What's stopping you?", "But why wait?"). No Rating line.
- Ex4, a slightly inappropriate joke. No Rating line.

**2/5 (7995–8066).** Repeated conduct causing noticeable professional concern without clearly crossing a severe hard boundary: repeated pressure, disrespectful comments, careless claims, dismissing boundaries, recurring competitor attacks, repeated overstatement, implied unsupported certainty, inappropriate use of private information, aggressive selling despite discomfort, irresponsible commercial behaviour. Gate "often **WARN**; could become **FAIL** if the behavior is material enough". Meaning: "Your conduct repeatedly created professional or ethical concern."
- Ex1, repeated escalating pressure ("If you were serious, you'd decide now").
- Ex2, repeated competitor attacks without evidence. If knowingly fabricated, it becomes 1/5 + FAIL.
- Ex3, returns twice to a declined personal-finance topic. Explicit refusal plus aggressive persistence makes it 1.
- Ex4, uses "your team is suffering" as a reason not to delay. Stronger manipulation makes it 1.

**1/5 (8070–8170).** A clear material ethical or professional violation: deliberate lie, fake urgency or scarcity, fabricated proof, unsupported guarantee, knowingly false financial outcome, deliberate concealment, manipulating an unsuitable buyer, deliberate competitor or product misrepresentation, pressure after a clear no, ignoring stop or opt-out, serious humiliation, knowingly exploiting vulnerability, knowingly recommending a clear misfit. Gate **FAIL** "unless evidence is insufficient to establish the violation". Meaning: "A material professional or ethical boundary was crossed."
- Ex1, fake deadline ("offer ends tonight") where "internal/context evidence shows this is false".
- Ex2, "I guarantee you'll double your sales in 90 days" where no guarantee exists.
- Ex3, pressure after "No … Please stop", continuing after a second "No".
- Ex4, knowingly sells the wrong fit ("our program will handle that").
- Ex5, knowingly invents "Competitor X has shut down their support team".
- Ex6, exploits fear ("If you walk away you're choosing failure").

**7. Not enough evidence, caps and special rules.**
- "—" scenarios (8174–8220):
  - an extremely short polite call: potentially "—" rather than automatic 5/5;
  - recording begins mid-call with a neutral segment: "—" or a lower-confidence score on the observed sections only;
  - **a claim that cannot be verified** ("Our guarantee covers this" with no policy evidence) is marked "Unknown / needs verification"; do not invent a FAIL.
- **Critical rule (8224–8242): never accuse the SP of lying without evidence.** An observed falsehood differs from an unverified claim. "We have served 2,000 clients" unverified becomes "could not be verified", Ethics WARN/Unknown, not FAIL.
- Canonical rule: "Unverified misconduct is not observed misconduct." (8258)
- Confidence example (8280–8295): a claim that appears inconsistent with another statement, with incomplete evidence, gives 3/5, Low confidence, WARN, rather than 1/5 "lied".
- A transcript is often enough (8299–8318): fake claims, pressure, disrespect, consent, competitor attacks, boundaries, promises, guarantees, explicit no or stop. Audio helps with sarcasm, mocking, intimidation, joking and aggression. "Don't infer vocal disrespect from neutral words alone."
- Do not score grammar or English ("I check and tell you" can be strong conduct) or "sir/ma'am" (8322–8347).
- Confidence is not professionalism (8351–8360): "confidence within evidence".
- **Special rules (8364–8613):**
  - Classify product claims as Known, Estimated, Conditional or Unsupported guarantee. Clearer certainty levels mean stronger professionalism.
  - **Commercial terms are high-consequence and weighted more heavily:** price, discounts, refunds, guarantees, payment terms, EMI, start date, contracts, deliverables.
  - Ask whether urgency is "truthful and relevant". Urgency itself is not penalised.
  - Directness versus pressure: "What's actually stopping you from deciding today?" is fine where context supports it. Pressure is a problem when it overrides autonomy, consent, real constraints, a clear no or emotional capacity.
  - A clear no: one clarifying question is fine; repeated closing after a clarified no is a problem.
  - A stop request ("Please don't call again") is stronger than "not interested right now".
  - Quota, ticket size, scarcity and hard-close culture never justify a wrong-fit sale.
  - Compare competitors on capabilities, evidence and fit, never identity ("They're scammers").
  - Sensitive personal information is used only to understand and serve the decision; never shamed, shared or weaponised.
  - Multiple stakeholders: no insulting a spouse, undermining a co-founder or encouraging secret payment.
  - Own the commercial intent.
  - Do not promise outcomes that depend on implementation, effort, adoption, market or team.
  - **"I don't know" can be 5/5 behaviour.**
  - Reward correction. Hiding a mistake is weak. Continuing to use a known false statement to close is damaging.
  - **Intention matters, but score observable behaviour:** "stated two contradictory refund terms", not "intentionally deceived", unless evidence shows deliberate deception.
  - Buyer misconduct does not justify seller misconduct; the SP may set boundaries or end the call.
  - Ending the call cleanly can be 5/5.
  - One minor slip: possibly 4. A repeated careless pattern: 3 or 2. A material violation: 1. **One material violation can define the call: 1/5 + FAIL** even if everything else was professional.
- Coaching (8617–8630) classifies the cause as a Knowledge Gap, Judgment Gap, Habit Gap, Confidence Gap, or Ethical Boundary Violation. The last needs immediate correction regardless of the coaching focus.
- Longitudinal (8634–8647). Outcome (8651–8656): a closed deal cannot erase an ethics FAIL.
- Final rule (8660–8661).
- Output (8665–8696) adds:
  - Applicability: Applicable / NEE;
  - Ethics Gate: PASS / WARN / FAIL;
  - Truthfulness: Strong / Mixed / Concern / Violation / Unverifiable;
  - Product Claims: Grounded / Mixed / Unsupported / False / Unverifiable;
  - Guarantees: Appropriate / Questionable / Unsupported / Not Occurred;
  - Urgency/Scarcity: Genuine / Questionable / Fake / Not Occurred;
  - Buyer Respect: Strong / Mixed / Weak / Harmful;
  - Dignity Protection;
  - Boundary Respect (… / Violation / Not Tested);
  - Consent/Autonomy (… / Violation);
  - Response to Clear No: Appropriate / Pushy / Violation / Not Occurred;
  - Stop/Opt-Out Handling: Appropriate / Violation / Not Occurred;
  - Competitor Claims: Fair / Mixed / Misleading / Unverifiable / Not Occurred;
  - Fit Integrity (… / Wrong-Fit Sale Attempt / Not Tested);
  - Sensitive Information Handling (… / Exploitative / Not Occurred);
  - Stakeholder Respect;
  - Mistake Correction;
  - Material Ethical Finding: None / Suspected / Confirmed;
  - **Severity: Low / Medium / High / Critical;**
  - Verification Needed: Yes / No.
- Two example outputs: 5/5 PASS (8700–8710), and 1/5 FAIL Critical for a false "price rises tomorrow" claim (8714–8724). Locked table plus a separate Ethics Gate table (8728–8751).

**8. Inputs needed.**
- **Transcript: essential.**
- **Product, pricing, offer-calendar, policy and guarantee facts: essential** for any truthfulness or urgency FAIL. Without them, claims are "Unverifiable" or WARN.
- **Competitor facts: needed** to call a competitor claim false.
- **CRM or earlier calls: helpful to essential.** Prior opt-out or stop requests, terms quoted earlier, and contradictions across calls.
- **Audio: helpful** for sarcasm, mocking and intimidation.
- **Timestamps: needed** for evidence spans.

**9. Inconsistencies and unclear points.**
- "1/5 or severely reduced" (7436) is ambiguous against 8608–8613 and 8088–8090, which make one material violation 1/5 + FAIL.
- **D07's Severity scale is Low/Medium/High/Critical (8693); every other dimension uses Minor/Meaningful/Material.**
- The gate is unspecified for 3/5. A 2/5 "could become FAIL" (8012), yet FAIL is defined as a "clear material ethical violation", which is the 1/5 definition. Whether 2/5 + FAIL is a legal combination is unclear.
- "Unsupported guarantee" in the 1/5 list (8077) versus "unsupported guarantee presented as fact" in the hard list (7719), while mild overstatement is 3/5. The line is fuzzy.
- 3/5 Ex3 ("What's stopping you?" asked several times) versus 8410–8412 ("What's actually stopping you from deciding today?" is fine) versus 2/5 Ex1. Frequency is the only separator.
- **Cross-dimension severity mismatches.** Sensitive information used as pressure is 2/5 here but 1/5 in D06 Ex4. A stated boundary revisited twice is 2/5 here but 1/5 in D05 Ex4.
- **Duplication with other dimensions:**
  - deception with D01 and D02;
  - mockery with D03 and D06;
  - secret payment with D08;
  - competitor fabrication with D10.
- The fake-deadline 1/5 Ex1 depends on "internal/context evidence" that the pipeline must actually have.
- The leftover line 8752.

**10. Size.** 1,387 lines, about 5,780 words. 23 scored examples and 3 "—" scenarios.

---

## D08. Finding the Decision-Makers

**1. Name, category, lines.** "Finding the Decision-Makers". Category 2, How Well You Understand the Buyer. Lines 8755–9954; blank to 9956.

**2. Purpose (8764–8786).** "Did the salesperson correctly understand who actually needs to be involved in the buying decision — and what role each relevant person plays?" Do not assume the person on the call decides. Others may include a spouse, co-founder, business partner, manager, finance team, procurement, board, parent or other stakeholder. The objective is not "find a name" but to "understand who matters, why they matter, and whether the people currently involved are enough for a legitimate decision".

**3. Boundaries (8790–8857).**
Scored here: who has authority, must approve, influences or needs to be informed; individual or shared authority; who can block; missing stakeholders; correct roles; late surprises that could have been prevented; moving to involve the right people.

Owned elsewhere:
- **Locked against D12: "WHO" versus "HOW / WHEN / BY WHAT CRITERIA".** "My co-founder and I both approve" is D08. "Review Friday, compare three vendors, finance releases payment" is D12.
- The quality of "Who else needs to be involved?" as a question is partly **D05**. D08 asks whether the authority picture was established.
- "I need to ask my wife" is not automatically a **D16** objection. First determine whether she is a co-decision-maker, influencer, informed party, emotional validator or a delay.
- How to close is **D17**, but closing someone who clearly lacks authority may reveal a D08 failure.
- Secretly bypassing a spouse or co-founder also hits **D07**. Here the issue is "mishandled the stakeholder structure".

**4. Part of the call and context (8861–8939, 9037–9116).**
- **Authority mapping**, not "did they ask who decides". Map the prospect's role, other stakeholders, the approval requirement, influence, any formal process (finance, procurement, board) and missing people.
- **Decision-Maker ≠ Influencer ≠ Informed Party** (8881–8890). Not every mention of another person is "decision-maker found".
- "I'll tell my co-founder" has several possible meanings: must approve, opinion wanted, informing only, expected resistance, personal uncertainty, or a safe delay. Diagnose the role.
- **Treat shared decisions as real when the evidence supports it** (8910–8914). Example: "no financial decision above ₹20,000 without each other". Bring both people into an informed conversation; never encourage secret payment. A "critical Brain 4.0 principle".
- Do not try to "overcome" a real decision-maker (8918–8924). If the buyer can't decide alone, close towards the correct next step, for example a joint call.
- Second-hand information is a risk (8928–8939). A direct conversation may improve decision quality. The aim is "shared understanding", not "two-person pressure".
- The exact question "Who is the decision-maker?" is not required (9037–9047); score understanding. Natural phrasings are listed (9051–9061); the score rests on what became clear, not on wording.
- Do not assume:
  - that the person on the call has authority (9065–9078). They may be a researcher, employee, influencer, manager, user, consultant, child, spouse or champion. This is a "core failure condition";
  - that a senior title means final authority (9082–9090);
  - that a spouse or partner mention is a fake objection (9094–9104).
- Not every stakeholder needs to join (9108–9116). "Inform my CFO after I buy" does not justify forcing a CFO call. The key is "material stakeholder relevance".

**5. Core evidence signals (8943–9033).**
- **A. Authority Identification.**
- **B. Stakeholder Identification.**
- **C. Role Clarification:** formal joint decision or only an opinion?
- **D. Authority vs Influence.**
- **E. Shared Decision Rules:** "above ₹50,000 both founders approve" versus "I'll probably mention it".
- **F. Formal Organizational Approval:** CFO, procurement, manager, legal, board, finance. The highest title is not the only decision-maker.
- **G. Timing of Identification:** a late "I need to speak to my partner" may be a late-discovery problem, not poor objection handling.
- **H. Reconfirmation When Context Changes:** at ₹3 lakh, finance must approve.
- **I. Appropriate Next Stakeholder Step:** for example, bring the co-founder onto a short call.

**6. Scores.**

**5/5 (9120–9211).** A clear, accurate authority and stakeholder picture fit for the call: who decides, who matters, roles, shared or formal approval, who is missing. No assuming, stereotyping, treating real stakeholders as objections or pressuring a bypass. Where authority is incomplete, the SP moves to the right stakeholder step. Meaning: "You clearly understood who needed to be involved in the decision and what role each person played."
- Ex1, B2B co-founder approval with role clarified (financial and product) and a joint call proposed.
- Ex2, a manager's opinion distinguished from approval.
- Ex3, a genuine spouse rule (₹25,000) leads to a 15-minute three-way call.
- Ex4, finance confirmed as only processing payment.
- Ex5, authority changes after price (board approval above ₹2 lakh); the map is updated without accusing the buyer.

**4/5 (9215–9267).** The important structure is correct with minor gaps: a secondary influencer's role is unclear, identification is slightly late, each person's concerns are not explored, or the next step could be more specific. Meaning: "You identified the important decision-makers correctly, with only small gaps."
- Ex1, the right stakeholder but the co-founder's concerns are not explored.
- Ex2, identified at minute 25 (earlier hints were weak) and a joint call arranged. No Rating line.
- Ex3, procurement never asked about, though nothing suggested it mattered. No Rating line.

**5 vs 4 (9271–9280).** 5 is "clear, role-specific and action-ready".

**3/5 (9284–9354).** A partial picture with meaningful uncertainty: knows someone else is involved but not how, a generic question only, unclear role, late identification, unverified assumptions. Meaning: "You understood some of the stakeholder picture, but it was still unclear who really needed to approve or influence the decision."
- Ex1, "I'll discuss with my wife" → "Okay, no problem", with no follow-up.
- Ex2, "Are you the decision-maker?" → "Mostly, yes", and "mostly" is not clarified.
- Ex3, director approval surfaces only at the close after 40 minutes, despite earlier opportunities.
- Ex4, a mentor whose opinion is wanted is wrongly treated as an approver.

**2/5 (9358–9425).** Important authority is repeatedly missed, wrongly assumed or found too late, causing noticeable friction: never checked despite a clear need, mentions ignored, the prospect assumed to decide, a spouse or co-founder treated as an excuse, repeated closing before authority is known, influence and approval not separated, a surprise that materially delays the deal. Meaning: "You missed or misunderstood important people in the decision."
- Ex1, an early co-founder mention is ignored and the SP asks for payment 40 minutes later.
- Ex2, the wife is treated as a fake objection ("just hesitation … you can decide yourself"). Pressure for secret payment or deliberate bypass makes it 1/5 plus a D07 concern.
- Ex3, someone evaluating for their CEO is repeatedly closed ("let's get you enrolled today").
- Ex4, "a few people need to sign off" is never clarified.

**1/5 (9429–9494).** Handling of decision-makers materially damages decision quality, trust or autonomy: knowingly pressuring a bypass, encouraging secret payment, deliberately excluding a required stakeholder, humiliating a stakeholder, treating a legitimate decision-maker as an obstacle, aggressively closing someone without authority, manufacturing consensus. Meaning: "You materially mishandled who had the right to be involved in the decision."
- Ex1, encourages secret payment ("pay the token now, explain to your wife later"). Potentially a severe D07 issue.
- Ex2, on a joint call, tells the husband his wife "doesn't understand this side".
- Ex3, pushes the buyer to pretend they have authority ("just say yes and we'll sort finance later").
- Ex4, advises "Better not involve him until after payment."

**7. Not enough evidence and special rules.**
- Do not automatically penalise the absence of a decision-maker question.
- "—" scenarios (9498–9541):
  - an early exploratory call with no decision expected: "— / Not Applicable";
  - the recording starts after authority was already discussed;
  - a very short operational call;
  - **the buyer is clearly the sole decision-maker from reliable context:** do not penalise skipped questions; "a positive score may still be possible" if behaviour confirms it, otherwise "—".
- No other stakeholder is not the same as no evidence (9544–9551). "It's entirely my decision" after a natural question is evidence.
- **A missing-stakeholder surprise is strong negative evidence** (9555–9563), but only if it "could reasonably have been discovered earlier". Otherwise do not automatically punish.
- Canonical rule: "Missing decision-maker evidence is not automatically weak decision-maker identification." (9579)
- Confidence example (9601–9617): "may have to check with my partner" with an unclear role gives 3/5, Medium confidence. Do not pretend the partner definitely decides.
- A transcript is usually strong evidence (9621–9631); audio is not mandatory.
- **Special rules (9635–9841):**
  - "I need to ask my wife" is a hypothesis, not a conclusion.
  - Establish the role, not just the person (for example, "wife = co-decision-maker because purchases above ₹20,000 need both").
  - Authority can be split: the CTO picks the product, the CFO approves spend, procurement signs.
  - Economic approval differs from product approval.
  - User ≠ buyer ≠ decision-maker.
  - Importance changes with price (₹10,000 versus ₹3 lakh).
  - Involve stakeholders at the right time: not after a 60-minute presentation, and not five stakeholders before basic fit.
  - **Do not over-qualify simple B2C sales** ("Anyone else involved?" "No." Done).
  - A joint call is for shared clarity, not ganging up.
  - Do not make the buyer sell internally ("Rather than put you in the middle, I'm happy to explain it directly").
  - Stakeholder concerns may differ.
  - An absent stakeholder is not automatically a blocker (repairable via a call).
  - **A late "decision-maker objection" may be an upstream miss.** Do not first coach "spouse objection handling".
  - Discovery should not feel like a trap ("So you're saying you're not the decision-maker?").
  - Do not disrespect non-decision-makers: "role accuracy, not hierarchy worship".
  - Reconfirm authority when the deal changes (₹50K to ₹5L).
  - **Success may be a stakeholder call, not payment.** Do not penalise not forcing payment.
- Coaching (9845–9856), for example "establish who approves this type of spend before presentation". Longitudinal (9859–9873).
- Outcome (9876–9884): a deal closed because the buyer later persuaded their co-founder does not make the SP's process excellent. No immediate payment does not make the skill weak.
- Final rule (9888–9889).
- Output (9893–9918) adds:
  - Applicability: Applicable / NA / NEE;
  - Primary Prospect Role: Decision-Maker / Co-Decision-Maker / Influencer / Informed Party / User / Unknown;
  - Authority Level: Full / Shared / Partial / None / Unknown;
  - Other Stakeholders Identified: Yes / No / None Required / Unknown;
  - Stakeholder Roles: Decision-Maker / Influencer / Informed Party / Finance / Procurement / Other;
  - Shared Decision Rule: Confirmed / Possible / No / Unknown;
  - Approval Requirement: Clear / Partial / Unclear;
  - Authority Timing: Early Enough / Slightly Late / Late / Not Tested;
  - Role Clarification Quality;
  - Second-Hand Information Risk: High / Medium / Low / NA;
  - Required Stakeholder Missing: Yes / No / Unknown;
  - Correct Next Stakeholder Step: Clear / Partial / Missing / Not Required;
  - Bypass Risk: None / Some / Material.
- Example output 5/5 with an "Authority Map" block (9922–9935). Locked table (9939–9953).

**8. Inputs needed.**
- **Transcript: essential.**
- **Timestamps: essential** for the timing of identification (early versus at the close or after the presentation).
- **Call stage, deal size or price tier, and B2B or B2C: essential.** They decide whether D08 is required and how much qualification is proportional.
- **Earlier-call and CRM context: helpful to essential** (authority established before; "I told you, my co-founder…").
- **Audio: marginal.**
- **Product or price knowledge: helpful**, because approval thresholds change with tier.

**9. Inconsistencies and unclear points.**
- **Severity mismatch with D04.** The same pattern (told someone else decides, then asked for payment) is 2/5 here, in the owning dimension (Ex1 9377–9389, Ex3 9404–9411), and 1/5 in D04 Ex3.
- The timing gradient is subjective and hinges on "earlier opportunity" (Section 24):
  - 4/5 Ex2: identified at minute 25;
  - 3/5 Ex3: found only at the close;
  - 2/5: "discovered too late creating noticeable friction".
- In "—" Scenario 4 (9535–9540), it is unclear what score a sole decision-maker case gets. 23 and 36 suggest a quick "No one else" is evidence. Whether it supports 5/5 or 4/5 is not stated.
- NA and NEE are merged in the display (9512).
- The secret-payment 1/5 also appears as a D07 boundary (8492).
- Several examples have no Rating line.
- The leftover line 9954.

**10. Size.** 1,202 lines, about 5,320 words. 20 scored examples and 4 "—" scenarios.

---

## D09. Understanding Problems & Goals

**1. Name, category, lines.** "Understanding Problems & Goals". Category 2, How Well You Understand the Buyer. Lines 9957–11253; blank to 11255.

**2. Purpose (9966–9981).** "Did the salesperson develop a clear and accurate understanding of what is wrong now, what the buyer wants instead, and the meaningful gap between those two states?" Both sides are needed. The target summary is "The buyer is currently here → this is the main problem → these are the likely causes → and this is where they want to go."

**3. Boundaries (9985–10076).**
The five Category 2 dimensions:
- D08 is WHO;
- **D09 is WHAT is wrong and WHAT they want**;
- D10 is HOW they handle it now and WHAT they tried;
- D11 is WHAT it costs or affects in money, time, effort, emotion and opportunity;
- D12 is HOW, WHEN and by WHAT criteria they decide.

What D09 covers:
- Problems: the main problem; what specifically is failing; vague or defined; secondary problems; symptom or root; plausible causes; what blocks progress; what is still uncertain.
- Goals: the desired outcome; what "better" looks like; specificity; any target; the future state; success; realism; multiple goals and their priority.

What D09 does not primarily score:
- impact (monthly loss, time wasted, stress, cost of inaction), which is D11;
- previous attempts, tools, agencies and alternatives, which are D10;
- urgency ("Why now?", deadlines), which belongs to "later qualification/decision understanding".

**4. Part of the call and context.**
- Mostly discovery, but evidence can appear anywhere, including the confirming summary.
- **"Surface statement ≠ diagnosis"** (10080–10100). "Sales are low" can hide 13 listed realities, from leads to ICP. Generate hypotheses and eliminate them with evidence.
- The problem should become more specific than the buyer's first statement when evidence allows (10105–10112). Perfect root-cause certainty is not required.
- **Root cause stays a hypothesis until confirmed** (Observed, Possible, Confirmed; 10116–10125). Do not reward sounding certain on weak evidence.
- **The goal matters equally** (10129–10137). Knowing "what hurts" without "where the buyer wants to go" is incomplete discovery.
- Goal clarity test (10141–10164): "clear enough that a solution can meaningfully connect to it". SMART is a lens, not a gate. Qualitative goals ("team runs without me reviewing every call") are valid; do not force numbers.
- **Buyer model (10167–10179):** Current State, Problem, Likely Cause or Barrier, Desired State, Gap. "The conceptual heart."

**5. Core evidence signals.**
- **Problem side (10183–10253):**
  - A Problem Specificity;
  - B Surface vs Root Distinction (diagnose, don't assume);
  - C Primary Problem;
  - D Secondary Problems (don't flatten);
  - E Cause Clarity (useful evidence, plausible reasoning, less ambiguity);
  - F Contradiction Handling (update as evidence changes).
- **Goal side (10257–10314):**
  - A Desired Outcome;
  - B Goal Specificity;
  - C Future-State Clarity;
  - D Goal Priority;
  - E Goal Realism ("₹2 lakh to ₹2 crore next month": clarify, don't accept);
  - F Goal Evolution (use the later, more precise statement).
- Need and desire differ (10318–10329); qualification consequences are handled elsewhere.
- "Never confuse pain with drama" (10333–10340). Do not reward making the buyer emotional.
- **Do not manufacture a problem** (10343–10352). **Do not force a goal the buyer doesn't have** (10356–10366): stable revenue is not the same as "wouldn't ₹1 crore/month be better?".

**6. Scores.**

**5/5 (10369–10479).** A clear, evidence-grounded understanding of the problem and the desired outcome: what is wrong, specifics, the primary and important secondary issues, plausible or confirmed causes, remaining uncertainty, what the buyer wants, what success looks like and the gap. No manufactured pain or invented root cause. Meaning: "You clearly understood what is wrong now and exactly what the buyer wants instead."
- Ex1, a full model plus a confirming summary (leads stable, close rate 18%→9% after the senior closer left, weak manager visibility; the goal is back above about 15% with the manager owning performance). The buyer says "Exactly."
- Ex2, the buyer's wrong self-diagnosis ("need more leads") is corrected with evidence; the drop is after the demo.
- Ex3, the goal becomes more precise (growth becomes independence from the founder).
- Ex4, uncertainty kept honestly ("still unclear whether it's skill, management or process").
- Ex5, multiple goals prioritised (immediate goal: run without daily founder supervision; revenue is the result).

**4/5 (10482–10536).** Main problem and outcome well understood with minor gaps: a secondary problem unclear, the cause partly explored, the goal slightly vague, a target missing, the gap not explicit. The model is still enough to guide a relevant solution. Meaning: "You understood the buyer's main problem and goal well, with only a few missing details."
- Ex1, strong problem, slightly vague goal ("improve conversion significantly").
- Ex2, strong goal, the primary cause not established. No Rating line.
- Ex3, a secondary problem (CRM adoption) not explored; 4/5 if it is secondary.

**5 vs 4 (10540–10551).**

**3/5 (10555–10627).** Basic understanding, but partly vague, shallow or incomplete: surface without causes, a generic goal, primary unclear among several, important ambiguity, one side stronger than the other. Meaning: "You understood the general problem and goal, but the picture was still too broad or incomplete."
- Ex1, surface only ("down three months", goal "increase sales").
- Ex2, good problem, weak goal ("So you want this fixed?").
- Ex3, good goal (₹10 lakh a month), weak problem.
- Ex4, many problems touched lightly with no priority.

**2/5 (10631–10711).** Materially weak: accepts a vague problem, assumes the root cause too early, misunderstands the real problem, talks mostly about the seller's preferred problem, never clarifies the goal, confuses symptom and cause, ignores correction, or presents before understanding. Meaning: "You did not clearly understand what the real problem was or what the buyer actually wanted."
- Ex1, "sales aren't coming" → "our training solves sales problems", then presents.
- Ex2, an invented root cause ("your team doesn't know how to close") that is wrong; lead volume had collapsed.
- Ex3, 20 minutes on pain and the desired outcome never asked.
- Ex4, the buyer says manager accountability; the SP steers to "your closers need training".
- Ex5, the buyer has to correct leads versus conversion repeatedly.

**1/5 (10714–10769).** Materially distorts, manufactures or ignores the real problem or goal, damaging diagnosis or decision quality: knowingly exaggerates, pressures acceptance of the seller's diagnosis, repeatedly ignores explicit correction, invents a desired outcome, manipulates the buyer into a bigger problem, or presents or closes on a clearly false model. Meaning: "You materially misunderstood or distorted what the buyer actually needed and wanted."
- Ex1, manufactures pain ("whole company could collapse") and keeps that frame after "not realistic".
- Ex2, forces a false diagnosis ("mindset and closing confidence") against repeated disagreement.
- Ex3, invents the goal (the buyer wants stable ₹5 lakh; the SP uses ₹20 lakh "throughout the rest of the pitch").

**7. Not enough evidence and special rules.**
- "—" scenarios (10772–10821):
  - the recording starts after discovery: "—" unless later sections give independent evidence;
  - a short operational call: "—";
  - **a follow-up where the problem and goal were set earlier:** the SP's retention of the model may be scored, but original discovery quality cannot; "— / lower-confidence score";
  - **the buyer refuses details despite reasonable attempts:** do not automatically give 2/5; "— / insufficient evidence or a strong question score with low problem-understanding completeness".
- When the buyer volunteers everything and the SP summarises accurately, that can be 5/5 "even with relatively few questions". "This dimension scores understanding, not effort spent discovering." (10825–10840)
- Thirty questions without a clear model can still be 2/5 or 3/5 (10843–10851).
- Canonical rule (10867).
- Confidence example (10889–10906): clear problem and goal with the root cause explicitly uncertain gives 4/5 with High confidence. Do not reduce the score because not every causal question is resolved. "Score = quality of the buyer model created."
- A transcript is usually strong evidence (10910–10920); audio is not needed for most of it.
- **Special rules (10924–11124):**
  - Problem history supports D09, but detailed past agencies, tools and processes are scored in D10.
  - The root cause need not be fully solved; keep uncertainty.
  - Primary versus secondary follows the buyer's evidence, not a fixed hierarchy.
  - The ladder runs from symptom to direct problem to cause to root system cause. Reward movement beyond the first symptom "when relevant"; the deepest level is not required.
  - Goals can be immediate, operational, business or personal. D09 maps the structure; D11 covers the depth of impact.
  - Do not force full SMART goals.
  - **The goal must belong to the buyer.** A seller-suggested aspiration answered "Sure" is not a real goal.
  - The goal may change; update it.
  - Contradictions lead to clarification, not accusation.
  - **Presentation readiness:** "Premature presentation is strong negative evidence when the problem/goal model is still unclear."
  - **Solution fit must not create a fake problem retroactively.** Reject "solution-first diagnosis", for example reframing a broken compensation model as a skill problem.
  - Understanding is not agreement.
  - Do not over-deepen once the problem is clear.
  - **Problem depth and impact depth are separate:** D09 can be 5/5 while D11 is 2/5 or 3/5.
  - Goal clarity drives solution relevance. A weak D09 may explain a weak D13, "but do not automatically duplicate the penalty".
- Coaching (11127–11149) with specific examples. Longitudinal (11153–11164). Outcome (11168–11175).
- Final rule (11178–11179).
- Output (11183–11213) adds:
  - Applicability: Applicable / NA / NEE;
  - Current State Clarity;
  - Primary Problem;
  - Secondary Problems;
  - Surface vs Root Distinction;
  - Root-Cause Status: Confirmed / Plausible Hypotheses / Unclear / Invented;
  - Problem Specificity;
  - Desired Outcome: Clear / Partial / Missing;
  - Goal Specificity;
  - Future-State Clarity;
  - Primary Goal;
  - Multiple Goals Prioritized;
  - Goal Realism;
  - Current-to-Desired Gap;
  - Remaining Uncertainty: Explicit / Implicit / Ignored;
  - Manufactured Pain Risk;
  - Seller-Imposed Goal Risk;
  - Premature Presentation Risk.
- Example output 5/5 with Current Problem, Desired State and Remaining Uncertainty blocks (11217–11234). Locked table (11238–11252).

**8. Inputs needed.**
- **Transcript: essential.**
- **Timestamps: helpful**, especially to tell whether the presentation started before the model was clear.
- **Earlier-call context: essential for follow-ups** (Scenario 3).
- **Product knowledge: helpful** to detect solution-first reframing.
- **Audio: optional.**

**9. Inconsistencies and unclear points.**
- Urgency is assigned to "later qualification/decision understanding" (10075). No dimension by that name exists; it is presumably D11 or D12 (inference).
- Scenario 4 (10818–10821) mixes a D05 outcome into D09's "—" guidance. It is unclear whether D09 should be "—" or a low completeness score.
- Scenario 3 gives "— / lower-confidence score" without saying which.
- 3/5 "partly vague … incomplete" and 2/5 "materially vague … incomplete" overlap. The only separator is "materially".
- 3/5 Ex2 (weak goal) and 2/5 Ex3 (goal never asked) differ only by whether the goal was asked at all.
- **Duplicates:**
  - 1/5 Ex1 duplicates D05 1/5 Ex2;
  - 2/5 Ex2 duplicates D05 2/5 Ex4;
  - 2/5 Ex5 duplicates D04 2/5 Ex5 and Ex1.
- Several examples have no Rating line.
- The leftover line 11253.

**10. Size.** 1,299 lines, about 5,720 words. 20 scored examples and 4 "—" scenarios.

---

## D10. Understanding What They're Doing Now

**1. Name, category, lines.** "Understanding What They're Doing Now". Category 2, How Well You Understand the Buyer. Lines 11256–12622; blank to 12624.

**2. Purpose (11265–11284).** "Did the salesperson clearly understand how the buyer is currently dealing with the problem, what they have already tried, what is working or not working, and what other options or alternatives are already in the picture?" The SP should know:
- current actions and process;
- what or whom the buyer relies on (tools, services, people);
- past attempts and their results;
- what worked, what failed and why;
- what was stopped and why;
- alternatives being considered;
- what the buyer already believes about solutions.

**3. Boundaries (11288–11330, 11691–11707).**
- The same five-way split as D09: D10 is HOW they deal with it now, WHAT they tried and WHAT alternatives exist. D12 is "HOW and WHEN will they choose between the available options".
- **Three parts:**
  - A **Current Approach** (what they do now);
  - B **Previous Attempts** (what they tried before);
  - C **Alternatives** (competitors, internal options, "do nothing").
  - Not all exist in every call; score what was relevant and observable.
- **Competitor discussion lives here** when it is about the current or alternative approach. "The old standalone competitor dimension was removed." "We're also considering [vendor]" is D10. "[Vendor] is cheaper" as resistance may also enter D16.
- Professionalism of competitor claims is D07.

**4. Part of the call and context (11334–11541).**
- **Current approach** can be: existing process, sales workflow, team structure, manual workaround, agency, software, consultant or coach, spreadsheets, CRM, internal manager, founder doing it manually, vendor, outsourced service, or no formal process. Key question: "How is the buyer currently trying to achieve the outcome or manage the problem today?"
- **Previous attempts:** what was tried, who was hired, what worked and didn't, expected versus actual, and the buyer's view of why it failed. The next recommendation must not "blindly repeat something that already failed".
- **Alternatives:** competitor, other vendor, internal hire, in-house build, continuing as now, software, agency, training the team, doing nothing, postponing, a cheaper or familiar option. "Competitor = objection" must not be assumed.
- **The goal is a model, not a list** (11393–11398). The example model chains current CRM and manual founder review, the agency's leads without conversion, a short-lived workshop and the hire-versus-coaching comparison.
- Why it matters (11410–11420): it avoids recommending what was tried, criticising unknown tools, repeating failed mechanisms, misdiagnosing, missing implementation barriers, misreading competitors, generic value and needless resistance.
- **Keep layers separate** (11424–11436): manual call review is the current approach (D10), founder dependency is the problem (D09), 15 hours a week is the impact (D11), a manager-led operation is the goal (D09).
- A previous attempt is not automatically a failure (11440–11452).
- **Failure types are hypotheses, not labels** (11455–11477): Solution, Execution, Accountability, Skill, Consistency, Expectations, Fit, Timing, Measurement.
- Do not invent the failure cause (11480–11490): "The training didn't work" → ask what happened after, not "that's because there was no accountability".
- Depth must match relevance (11494–11500).
- Ownership matters (11504–11517).
- The current approach can be "nothing" (ad hoc, manual, reactive; 11520–11531), or several approaches at once (11534–11541).

**5. Core evidence signals.**
- **Current approach (11544–11594):**
  - A Current Process;
  - B Current Tools/Services;
  - C Current Ownership;
  - D Current Strengths (what already works, so good systems are not replaced);
  - E Current Weaknesses (where it breaks).
- **Previous attempts (11597–11651):**
  - A What was tried;
  - B Why it was tried;
  - C Expected result;
  - D Actual result;
  - E What worked;
  - F What failed;
  - G Why it may have failed (evidence; keep hypotheses);
  - H Why it stopped (cost, result, adoption, timing, resistance, bandwidth, vendor).
- **Alternatives (11654–11688):**
  - A Competitor;
  - B Internal Alternative;
  - C Status Quo;
  - D Alternative Evaluation (why preferred: price, trust, convenience, familiarity, capability, effort). This may connect later to D12; D10 first establishes what alternatives exist.
- Do not attack the current solution (11711–11717).
- Do not assume the old solution failed because yours is better (11721–11728).
- Do not only ask about failures (11732–11739). For example, an agency's good leads mean lead generation may not be the problem.
- Do not over-dig irrelevant history (11743–11752).

**6. Scores.**

**5/5 (11756–11871).** A clear, useful understanding of the current approach, what works and where it breaks, relevant previous attempts, expected versus actual outcomes, plausible reasons and meaningful alternatives. No assuming, attacking competitors, treating every attempt as failure, or recommending before understanding what exists. Meaning: "You clearly understood what the buyer is doing today, what they already tried, what happened, and what other options are in the picture."
- Ex1, the current CRM is understood: it is good at lead tracking; the gap is call-quality visibility; "CRM isn't really the issue".
- Ex2, a previous two-day workshop: knowledge improved for about two weeks; nobody tracked application.
- Ex3, a competitor understood without attack: cheaper with built-in CRM, and the real preference is "fewer tools".
- Ex4, a complete picture: manual founder review, activity-only manager, a workshop, a new CRM, and a considered senior-manager hire. No dialogue is given.
- Ex5, uncertainty kept: whether the agency issue was lead quality or conversion is still unclear.

**4/5 (11875–11931).** The main approach and attempts are understood with minor gaps: a secondary tool, the exact reason for a failure, the competitor motive or ownership is partly unclear. Meaning: "You understood their current setup and past attempts well, with only a few missing details."
- Ex1, the current system is clear but the earlier training is only partly explored.
- Ex2, "Why X?" answered "Mainly price" and accepted. No Rating line.
- Ex3, the agency is well understood but whether the founder or manager owns follow-up is unclear. No Rating line.

**5 vs 4 (11934–11944).** 5 is "highly actionable".

**3/5 (11947–12014).** Some useful information but an incomplete picture: the tool is known but not how it is used; the agency failed but not why; a competitor exists but its appeal is unknown; one attempt explored and others ignored; a workaround without what works or fails. Meaning: "You understood some of what they're doing now, but the current and past picture was still incomplete."
- Ex1, a CRM name only ("Okay").
- Ex2, "Agency didn't work" → "So you need a better solution". No Rating line.
- Ex3, "comparing two other products", followed only by price questions. No Rating line.
- Ex4, the current process is partly understood (no frequency, ownership or gap). No Rating line.

**2/5 (12018–12087).** Materially fails to understand the existing approach or attempts despite clear opportunity: ignores the current solution, repeats a recommendation already tried, dismisses past attempts, assumes the competitor is bad, misunderstands a tool, does not ask why something failed, labels the failure wrongly, or presents a replacement before understanding what to replace. Meaning: "You missed important information about what the buyer already does or has already tried."
- Ex1, recommends weekly call-review sessions after the buyer said they ran them for six months.
- Ex2, "[CRM] won't solve your problem" with no questions asked.
- Ex3, "the training was good, team stopped using it" → "bad training programs don't work".
- Ex4, "They're cheaper but low quality", with no evidence. D07 may be affected if misleading.

**1/5 (12091–12144).** Materially distorts, dismisses or knowingly ignores current reality in a way that damages recommendation quality: falsely claims a working solution doesn't work, knowingly misrepresents a competitor or provider, forces abandonment of something useful, repeatedly ignores evidence on why attempts failed, or recommends something fundamentally inconsistent with the setup. Meaning: "You materially misunderstood or distorted what the buyer already has, does or has tried."
- Ex1, keeps pitching a CRM replacement after "Our CRM works perfectly".
- Ex2, rewrites the past failure ("agency lead quality failed") after an explicit correction.
- Ex3, knowingly invents a competitor weakness ("no support after purchase"). This is also a D07 ethics concern.

**7. Not enough evidence and special rules.**
- "—" scenarios (12147–12188):
  - the recording starts after discovery: "—" unless later dialogue gives evidence;
  - **the buyer has never tried anything:** still scoreable; "Do not automatically use dash";
  - no existing approach is relevant, and establishing that clearly "can be good performance". This scenario has no Result line;
  - a short operational call: "—".
- **"Nothing tried" can be a complete answer** and can still earn a high score (12191–12201).
- Previous attempts may have partly worked; keep mixed outcomes, not a worked/failed binary (12205–12221).
- **The buyer's explanation of a failure is evidence, not fact** (12225–12234). Record it as observed outcome, buyer attribution and other explanations that remain uncertain.
- Calibration (12238–12252).
- **Confidence per fact** (12256–12274): "High on attempt, Low on cause".
- A transcript is usually strong evidence; audio is not mandatory (12278–12288).
- **Special rules (12292–12490):**
  - Describe the current approach as a system, not a product list.
  - Ask what works before replacing.
  - Compare expected and actual results.
  - "Why did it fail?" must not become blame ("What got in the way of implementation?").
  - **The current approach can change between calls; use the latest evidence.**
  - A competitor's name alone is not enough; understand why, what they like and what is missing.
  - **Status quo** and an **in-house hire** (for example, a senior sales manager at ₹1 lakh a month instead of the product plus coaching) are real alternatives.
  - Different options may solve different parts.
  - Using a product is not the same as being satisfied with it (contract, switching cost, familiarity, price).
  - **Previous failure can feed later objections** ("How do I know my team will use this?"). D10 scores understanding of that context; D16 scores the objection.
  - Previous success matters too ("What made that one work?").
  - The current process must connect to the problem (payroll software is irrelevant to conversion).
  - **Do not present before understanding the relevant current system.** Premature presentation is negative evidence.
  - Judge complement versus replace (keep the CRM and add call intelligence).
  - One missed irrelevant tool should not destroy the score. One casually mentioned competitor should not dominate.
  - "Not a procurement interview / software inventory."
- Coaching (12494–12511). Longitudinal (12515–12523). Outcome (12527–12534).
- Final rule (12538–12539).
- Output (12543–12576) adds:
  - Applicability: Applicable / NA / NEE;
  - Current Approach, Current Process, Current Tools/Services, Current Ownership, What Works Now, What Does Not Work Now, Previous Attempts, Expected Result, Actual Result: Clear / Partial / Unclear, None or Unknown as relevant;
  - Failure Cause: Confirmed / Plausible / Unknown / Invented;
  - Failure Type Hypotheses: the 9 types plus Other or Unknown;
  - Past Successes;
  - Competitors/Alternatives;
  - Alternative Motivation;
  - Status Quo Alternative: Relevant / Not Relevant / Unknown;
  - Replace vs Complement;
  - Material Unknowns: Explicit / Implicit / Ignored;
  - Assumption Risk;
  - Competitor-Attack Risk;
  - Premature Replacement Risk: None / Some / Material.
- Example output 5/5 with Current Approach, Previous Attempt, What Worked, What Failed, Likely Failure Mechanism and Alternative blocks (12580–12603). Locked table (12607–12621).

**8. Inputs needed.**
- **Transcript: essential.**
- **Earlier-call and CRM context: helpful to essential.** The current approach changes across calls; earlier calls may already hold attempt history.
- **Product knowledge: helpful.** It is needed for complement-versus-replace judgement and to see overlap with the seller's own offer.
- **Competitor knowledge: needed** to judge whether a claim is a misrepresentation; otherwise it is unverifiable.
- **Timestamps: helpful** (premature presentation, spans).
- **Audio: not needed.**

**9. Inconsistencies and unclear points.**
- Line 11317 says "four different scores" while listing five dimensions.
- Scenario 3 (12175–12180) has no Result line.
- Confidence is per fact (12271), but the output schema has a single Confidence field.
- **Duplicates:**
  - 1/5 Ex3 and 2/5 Ex4 overlap D07's competitor rules. A fabricated competitor claim gives D10 1/5 plus D07 1/5 FAIL;
  - 2/5 Ex1 overlaps D04 (ignoring stated information) and likely D13 (inference; D13 is outside my range).
- Real CRM and vendor brand names appear in examples (see Names seen).
- Several examples have no Rating line.
- The leftover line 12622.

**10. Size.** 1,369 lines, about 5,630 words. 19 scored examples and 4 "—" scenarios.

---

## 11. Cross-dimension findings (D01 to D10)

### 11.1 The same evidence is scored in several dimensions, sometimes at different severities
The rubric allows dual scoring only when each dimension judges a different effect (116, 1015, 3111–3112). It gives no merge or de-duplication rule.

| Behaviour | Where it appears (lines) | Ratings given |
|---|---|---|
| "This isn't a sales call", then a pitch | D01 666–675; D02 1581–1588; D07 hard list 7714 | 1/5, 1/5, FAIL |
| Laughing at consulting a spouse or partner | D03 2761–2769; D06 6766–6774; D07 "serious humiliation" 8085 | 1/5, 1/5, 1/5 |
| Emotional disclosure turned into "pay today" | D03 2773–2782; D06 6778–6787; D07 8162–8170 | 1/5, 1/5, 1/5+FAIL |
| Emotional disclosure turned into a product pitch | D04 4082–4091 vs D06 6724–6731 and 7003 | **1/5 vs 2/5** |
| Repeated talk-over, "Can I finish?" | D03 2749–2757; D04 4058–4066 | 1/5, 1/5 |
| "My CEO or co-founder decides", then a payment ask | D04 4070–4078 vs D08 9377–9389, 9404–9411 | **1/5 vs 2/5** |
| Unexplored thread (manager resigned, senior closer left) | D04 3828–3834; D05 5116–5131; D05 5326–5334 | 4/5, 4/5, 2/5 |
| Manufacturing pain ("business could collapse") | D05 5421–5432; D09 10732–10742 | 1/5, 1/5 |
| Premature or invented diagnosis | D05 5352–5360; D09 10665–10675 | 2/5, 2/5 |
| Buyer has to correct the SP repeatedly | D04 4014–4021; D09 10700–10711 | 2/5, 2/5 |
| Returning to a declined personal topic | D05 5448–5459 vs D07 8047–8055 | **1/5 vs 2/5** |
| Private disclosure used as leverage | D06 6801–6809 vs D07 8059–8066 | **1/5 vs 2/5** |
| Fabricated competitor weakness | D07 8151–8158; D10 12135–12143 | 1/5+FAIL, 1/5 |
| Secret payment around a spouse | D08 9448–9458; D07 8492 | 1/5, severe |
| A sharp "Why didn't you…?" question | D03 2628–2636; D05 4939–4957; D10 12322–12331 | 3/5 (or 4/2); framing issue |

### 11.2 Structural inconsistencies
- **Applicability values differ by dimension.**
  - D01, D03, D04 and D07 allow only Applicable or Not Enough Evidence.
  - D02, D05, D06, D08, D09 and D10 also allow Not Applicable.
  - Both NA and NEE display as "—".
- **Severity scales differ.** D07 uses Low/Medium/High/Critical; the others use Minor/Meaningful/Material.
- **Non-deterministic example ratings:**
  - D01 5/5 Ex4 (implied);
  - D02 4/5 Ex3 ("could even be 5");
  - D02 3/5 Ex5 ("can become 3/5");
  - D03 3/5 Ex5 ("could become 4 or 2");
  - D07 4/5 Ex3 ("could be 5").
  Many 2/5 and 3/5 examples in D04 to D10 end at "Why X/5?" with no Rating line.
- **"5 needs positive evidence" versus "simple can be 5"** (D01 429–431 vs 339–350).
- **Naming drift:**
  - "Connecting the Solution to Buyer Needs" (3375);
  - "Decision Process" (4700);
  - "Price & Budget" (3022);
  - "later qualification/decision understanding" (10075);
  - a removed "standalone competitor dimension" (11692).
- **Partial-evidence rules are left open:**
  - D03 "narrowly scoped rating" (2826);
  - D07 "— or a lower-confidence score" (8205–8207);
  - D09 Scenario 3 and 4 (10809, 10818–10821);
  - D08 Scenario 4 (9535–9540).
- **No aggregation.** Category or overall scores are not defined in this range.

### 11.3 Example inventory, usable as a seed for an evaluation set (my count)
There are 219 scored example snippets and 39 "—" scenarios:

| Dimension | Scored examples | "—" scenarios |
|---|---|---|
| D01 | 19 | 4 |
| D02 | 23 | 4 |
| D03 | 23 | 4 |
| D04 | 23 | 4 |
| D05 | 24 | 4 |
| D06 | 25 | 4 |
| D07 | 23 | 3 |
| D08 | 20 | 4 |
| D09 | 20 | 4 |
| D10 | 19 | 4 |

All of them are short fragments, not whole calls. The "Special accuracy rules" contain dozens more paired strong/weak micro-examples. (Inference) These examples test whether rules are applied, but not the whole-call pattern judgement that D03 to D10 require. An evaluation set also needs full transcripts labelled on all dimensions together, so the duplications in 11.1 can be measured.

---

## 12. Implications for an AI pipeline

### 12.a Compact rubrics for D01 to D10 (prompt-ready)

Shared header, written once in the prompt:

> Score each dimension 1–5, or "—". Use "—" when the behaviour cannot be observed, with a reason of NEE (not enough evidence) or NA (not reasonably required). Never turn missing evidence into a score, and never give 5 for politeness on a near-empty call. Give 1/5 only for clearly observed damaging behaviour; a short call can still justify it.
>
> 5 needs positive evidence that the skill improved the call. "Nothing went wrong" is 4.
>
> Judge the whole relevant pattern: weigh frequency, severity, importance of the moment, recovery and effect on the buyer. One small miss can still be 4; one great moment cannot lift a weak pattern to 5.
>
> Confidence (High/Med/Low) is separate and never changes the score.
>
> Never score:
> - outcome (bought or declined), call length or buyer friendliness;
> - personality, energy or charisma;
> - accent, language mix (Hindi/Marathi/Hinglish), grammar or "sir";
> - script compliance, ritual phrases, or counts (questions, acknowledgements, talk ratio).
>
> Report observations before interpretations. Label inferences. Never mind-read emotion or intent.
>
> When one moment touches several dimensions, score each only for its own effect and name the shared evidence.

**D01 Starting the Call.**
- *Scope:* the opening phase until the call moves into plan, discovery or substance. Use no fixed seconds. Identify the call type first (inbound, cold, scheduled, follow-up, referral, existing client, returning, interrupted, re-engagement), because the right opening depends on it.
- *Look for:*
  - natural entry rather than robotic or telecaller style;
  - context awareness (behaves as if it knows which conversation it is entering);
  - low resistance;
  - sensible adaptation to immediate signals (busy, driving, can't talk);
  - no premature pitching;
  - a smooth move into substance.
- *Not required:* "How are you", the buyer's name, small talk, jokes, script wording.
- *Not scored here:*
  - agenda and permission (D02);
  - full-call delivery (D03), except a severely robotic or aggressive opening;
  - rapport over the call (D06);
  - ethics (D07), except that deception which wrecks the entry also scores here.
- *5:* natural and context-aware, actively helps, no meaningful mistake. A minimal opener can be 5 only when the situation needs nothing more.
- *4:* worked well; slightly formal, generic, abrupt, or brief harmless small talk.
- *3:* works but transactional, form-filling, scripted, mildly talks over the buyer then recovers, or slightly unprepared.
- *2:* noticeable friction: an immediate pitch before the buyer speaks; ignoring "I'm driving"; forced small talk despite disengagement; unprepared ("you filled something somewhere").
- *1:* material harm: an aggressive "just listen"; overriding a clear "can't talk / told you not to call"; deceptive "not a sales call"; hostile or condescending entry.
- *—:* opening missing, corrupted, unclear speaker, or the call drops instantly.
- *Note:* a 25-second call can still be 1/5.

**D02 Setting the Plan.**
- *Scope:* orientation after the greeting and around the transition into discovery. The word "agenda" is not needed.
- *Look for:*
  - why-this-call clarity;
  - useful direction ("understand first, then show only what's relevant");
  - a reason for discovery;
  - appropriate (explicit, implicit or established) participation;
  - realistic expectations;
  - the buyer's own priorities included;
  - a natural transition.
- *Context:* call type sets how much framing is needed. A follow-up recap of pending items can be 5. A short continuation or operational call needs none, so give "—" (NA).
- *Never use length, polish or the word "agenda" as quality.*
- *Credit:*
  - adopting a buyer-created agenda;
  - short frames;
  - flexible deviation (briefly answering a "what does it do?" question);
  - time framing when the buyer has a constraint.
- *Penalise:*
  - frames that pre-commit to a sale ("then we'll get you enrolled");
  - submissive over-permission ("Can I ask? Is it okay?");
  - controlling frames ("our process, just answer").
- *5:* clear, buyer-friendly, context-specific, flexible frame that creates alignment (including acknowledging a buyer who came for price and explaining why brief discovery comes first).
- *4:* functional but generic, slightly seller-led, implied permission, or slightly long.
- *3:* minimal ("a few questions first"), seller-centred, scripted, ignores the buyer's stated priority, or excessive permission.
- *2:* questions asked with no reason ("just tell me first"); a rigid agenda against the buyer's time limit; vague purpose; hidden discovery after a price request; a controlling frame; or a call that clearly needed framing and got none.
- *1:* deceptive purpose; a trapping yes-or-no-today frame; "No sir, this is our process" after the buyer rejects the plan; misleading "about your account".

**D03 Tone, Pace & Pauses.**
- *Gate:* requires reliable audio and speaker attribution. With a transcript only, give "—". With timestamps only, give "—" (they may support notes about monologues or gaps). Partial audio covering only part of the call gives "—". A short call with clear repeated bad delivery can still be scored.
- *Whole call, with extra attention to* sensitive questions, disclosures, explanation, **price**, **the first seconds after an objection**, and **the close**.
- *Strongest signal:* change from the SP's own baseline under pressure (speed-up, nervous laugh or justification at price or objection). No fixed pause lengths or WPM thresholds; there is no universal right style.
- *Positive signals:*
  - pause after important questions, price and disclosures;
  - slows down at objections;
  - softer and slower after emotional disclosure;
  - states price plainly without apology;
  - lets silence work after a close.
- *Negative signals:*
  - rapid-fire stacked questions;
  - panic speed-up after objections;
  - filling every silence;
  - upbeat tone during serious disclosure;
  - nervous or apologetic price;
  - answering own question after half a second;
  - "no pressure though…" after a close question.
- *Interruptions:* inattentive cut-offs belong to D04. Only a rushed rhythm with constant overlap counts here. Natural backchannel overlap is fine.
- *Do not:* reward a "sales voice", loudness or energy; penalise a quiet or flat natural voice or accent; score the buyer's tone.
- *5:* consistent, adaptive, calm under pressure, with strong evidence in more than one part of the call.
- *4:* one slightly rushed section, a quick follow-up after price, or an early energy mismatch corrected.
- *3:* consistently slightly fast, flat across all phases, fills some silences, brief nervousness at price.
- *2:* repeated friction (stacked questions, panic after objection, constant filling, register mismatch, nervous price).
- *1:* raised voice or aggression, continuous domination ("Can I finish?"), mocking, exploiting a disclosure for immediate payment.

**D04 Listening Well.**
- *Test:* does what the SP says next prove they understood what came before? Whole call, including presentation, price, objections and close.
- *Evidence:*
  - tracks facts (numbers, team size, dates, stakeholders);
  - responds to meaning, not keywords;
  - follow-ups built on answers;
  - recalls earlier statements;
  - notices and clarifies contradictions without weaponising them;
  - allows completion;
  - no repeated answered questions;
  - meaningful acknowledgements;
  - notices emotional change (observable, no mind-reading);
  - notices missing parts of answers;
  - keeps the buyer's exact words.
- *Not evidence:* silence, talk ratio, acknowledgement words, question count.
- *Not required:* paraphrasing after every answer.
- *Allowed:* disagreement and redirection when grounded in what the buyer said. Interrupting "for value, not control" is fine.
- *Severity:*
  - incidental detail forgotten: minor;
  - misremembering money, commitments or authority: material;
  - an irrelevant ignored thread: minor;
  - a key resignation, authority statement or disclosure ignored: material;
  - misunderstanding with quick correction: fine;
  - defending a wrong interpretation: materially worse;
  - listening that collapses at price or objection affects the whole score.
- *5:* consistent tracking, recall, contradiction handling and self-correction.
- *4:* one repeated question, generic "Got it" with good follow-ups, one interruption with "Sorry, continue", one secondary thread missed.
- *3:* scripted jumps, a couple of repeats, "I understand" without proof, occasionally finishes sentences, a missed contradiction.
- *2:* script over answers, repeated re-asking, assuming the ending ("Wife, right?"), answering a concern the buyer said wasn't theirs, the buyer correcting repeatedly.
- *1:* the buyer says "you're not listening"; repeated domination; a material fact ignored (not the decision-maker, then a payment ask); a critical disclosure ignored.
- *—:* buyer side missing, severe gaps, no real opportunity, attribution unreliable.

**D05 Asking the Right Questions.**
- *Test:* was each important question the next useful one? Whole call. Never use question count; few excellent questions can be 5 and 40 generic ones can be 2.
- *Evidence:*
  - relevance;
  - clarification of vague terms;
  - follow-up depth;
  - moving surface → context → cause → impact when relevant;
  - hypothesis testing;
  - noticing missing information;
  - well-framed difficult questions (reason or softener);
  - logical sequencing;
  - questions that make the buyer think;
  - stopping when clear.
- *What comes after an unexpected answer reveals the most.* New evidence must change the next question. Buying signals should move the questioning to decision readiness.
- *Open versus closed does not matter;* fit to the moment does. "Why" questions need careful framing.
- *Anti-patterns:*
  - interview-form checklists;
  - leading or agreement-forcing questions;
  - manufacturing pain;
  - assuming impact (mental health, marriage);
  - fake precision;
  - confirming only the seller's theory;
  - hiding direct answers behind more questions;
  - endless discovery.
- *Do not penalise:* skipping what is already known; direct but relevant uncomfortable questions; short buyer answers.
- *Buyer pushback* ("why are you asking?") is evidence about the questioning.
- *5:* consistently adaptive, deepening, updates hypotheses, knows when to stop.
- *4:* one missed thread, generic openers then sharp follow-ups, one premature budget question, slight over-depth.
- *3:* mostly surface, a mix of adaptive and checklist questions, accepts vague answers, keeps asking as answers shorten, one-dimensional.
- *2:* checklist with no follow-up, ignores an important answer, leading, premature diagnosis, intrusive without bridge, "12 more questions".
- *1:* aggressive interrogation, manufacturing pain against the buyer's denial, manipulative "if you really care…", repeated breach of a stated boundary.

**D06 Building Connection.**
- *Test:* did the buyer have reason to feel safe enough to be honest, including disagreeing, doubting, admitting failure or saying no? Whole call. **The real test is after the easy part:** disagreement, price, objection, "no".
- *Not required or rewarded:* personality, likability, small talk, hobbies, compliments, shared hometown, SP self-disclosure, language mirroring.
- *Trust must be observed in behaviour* (voluntary disclosure of failures, money, fears, open disagreement). Buyer openness is supporting evidence only. A reserved buyer can still yield 4 or 5; an open buyer is not automatically high.
- *Signals:*
  - genuine interest;
  - prospect-side thinking;
  - non-judgement;
  - emotional safety;
  - meaningful (not performed) acknowledgement;
  - comfort with relevant direct questions;
  - safe disagreement;
  - no personality shift at money or close;
  - comfort with uncertainty;
  - trust repair.
- *Empathy must be balanced with honesty;* approval-seeking (agreeing with everything, discounting, constant apology) is not rapport.
- *Vulnerability sequence:*
  - acknowledgement → space → understanding is strong;
  - → pitch is weak (about 2/5);
  - → pressure is damaging (1/5).
- *Commercial intent may be owned openly.* Connection can be repaired mid-call; a great start can be destroyed later.
- *5:* strong behavioural evidence that the relationship enabled honesty: dignified handling of an admitted failure, transparent answer to "you just want to sell", respectful challenge, stability after price, fitting humour.
- *4:* slightly formal but genuine; generic empathy then real follow-up; a mild defensive moment repaired; comfortable but functional.
- *3:* polite but transactional; repetitive "I understand"; a slight shift at objection; manufactured small talk; initial over-accommodation.
- *2:* fake rapport; judgemental remarks; defensive dismissal of doubt; empathy used as a pitch bridge; a personality shift at price.
- *1:* humiliation; exploiting vulnerability; attacking distrust; using a private disclosure as leverage; refusing to repair an evident breakdown.

**D07 Being Professional (plus Ethics Gate).**
- *Output:* a 1–5 score **and** an Ethics Gate.
  - PASS: no material issue.
  - WARN: questionable, unverified material claim, or missing context.
  - FAIL: a clear material violation.
  - A FAIL survives a closed deal and is never averaged away. **One material violation gives 1/5 + FAIL** even after 39 good minutes.
- *Hard violations:*
  - deliberate lie;
  - fake urgency or scarcity;
  - fabricated proof;
  - unsupported guarantee as fact;
  - hiding material information;
  - knowingly selling a misfit;
  - pressure after a clear genuine no;
  - false competitor or product claims;
  - invented ROI;
  - falsified qualification;
  - ignoring stop or opt-out;
  - misrepresenting commercial terms.
- **Never call something a lie without evidence.** An unverifiable claim gets Verification Needed and WARN, not FAIL. Score observable statements ("stated two contradictory refund terms"), not intent.
- *Professional ≠ formal ≠ passive.* Direct asks, strong recommendations and challenge are fine.
- *Credit:* "I don't know, I'll confirm"; correcting earlier errors; declining a wrong-fit sale; one clarifying question after a no, then respect; ending an abusive or unproductive call cleanly.
- *Weigh commercial-term misstatements more heavily* (price, discount, refund, guarantee, EMI, start date, deliverables).
- *Distinguish claims* as known, estimated, conditional or guaranteed.
- *Urgency* is fine when true and relevant.
- *Sensitive information* is used only to serve the decision.
- *Competitor talk* compares capability, evidence and fit, never reputation.
- *5 (PASS):* consistently truthful, separates certainty levels, respects no and boundaries, fit over revenue.
- *4 (PASS or WARN):* one overconfident claim self-corrected, a mild competitor jab corrected, a slight push then respect.
- *3:* casual competitor criticism, mild overstatement later qualified, repeated "why wait?", ill-timed humour.
- *2 (WARN, FAIL if material):* escalating pressure; repeated unsupported competitor attacks; returning to a declined personal topic; using sensitive information as a reason not to delay.
- *1 (FAIL):* fake deadline (only if evidence shows it is false), unsupported guarantee, pressure after "No, please stop", knowingly selling a misfit, a fabricated competitor claim, weaponised fear.
- *—:* too little behaviour (do not award 5 for one polite line).

**D08 Finding the Decision-Makers.**
- *Test:* is there an accurate authority map: who approves, who influences, who is only informed, whether authority is shared or split (product, budget, procurement), formal approvals, who is missing? Does the call move towards involving the right people?
- *Owned elsewhere:* HOW, WHEN and criteria (D12).
- *Do not assume* that the person on the call, the senior title, or a spouse mention means anything until diagnosed. "I need to ask my wife" is a hypothesis.
- *Treat stated joint-decision rules as legitimate.* The right move is a joint conversation, never secret payment or bypass.
- *Reconfirm authority when price or scope changes.*
- *The exact question "Are you the decision-maker?" is not required;* understanding from natural dialogue counts. A buyer stating "it's entirely my decision" is evidence.
- *Keep it proportional:* no long qualification on simple B2C sales; no forced calls with merely informed parties.
- *Late "I need my partner" at the close* lowers the score only if it was reasonably discoverable earlier, and is an upstream miss rather than objection handling.
- *A stakeholder call can be the correct success,* not a missed close.
- *5:* roles clarified (approval versus opinion, finance just processes), shared rules respected with a joint call, authority updated after price.
- *4:* right stakeholder but role or concerns thin; identified slightly late with good recovery.
- *3:* "I'll discuss with my wife" → "okay"; "mostly, yes" unclarified; authority surfaced only at close; an influencer treated as an approver.
- *2:* a stated co-founder or CEO authority ignored and the wrong person closed; a spouse dismissed as an excuse; "a few people sign off" left unclear.
- *1:* encourages secret payment; turns one stakeholder against another; pushes the buyer to fake authority; advises keeping the decision-maker out until after payment.
- *—/NA:* early exploratory call, authority discussed before the recording, operational call.

**D09 Understanding Problems & Goals.**
- *Test:* by the end, can the SP state current state → main problem → likely causes or open uncertainty → desired state → gap, accurately and in the buyer's terms?
- *Owned elsewhere:* impact or cost (D11), current approach, attempts and alternatives (D10), urgency.
- *Reward:*
  - moving from vague to specific;
  - separating symptom from cause;
  - naming the primary versus secondary problems;
  - keeping root cause as a hypothesis unless confirmed (explicit uncertainty is a strength);
  - eliciting the buyer's own goal (qualitative goals are fine; SMART is a lens);
  - prioritising multiple goals;
  - noticing unrealistic goals;
  - updating as the goal evolves;
  - confirming with a summary.
- *Understanding is scored, not effort:* a volunteered story accurately summarised can be 5; 30 questions without a model can be 2 or 3.
- *Penalise:*
  - accepting "sales are down" as the diagnosis;
  - premature or invented causes;
  - solution-first reframing;
  - seller-imposed aspirations;
  - manufactured pain;
  - **presenting before the problem and goal are clear** (strong negative evidence).
- *Do not duplicate* the D11 or D13 penalty for the same gap.
- *5:* full model plus confirmation; correcting the buyer's wrong self-diagnosis with evidence; goal sharpened to its real form; uncertainty stated; goals prioritised.
- *4:* goal slightly vague, cause not pinned down, a secondary issue unexplored.
- *3:* surface only; good problem with weak goal or the reverse; many issues without priority.
- *2:* vague problem accepted and pitched; invented cause proved wrong; goal never asked; steering to the seller's preferred problem; repeated corrections.
- *1:* pushes an exaggerated problem against denial; forces a false diagnosis; substitutes a bigger goal the buyer rejected and pitches to it.
- *—:* discovery not recorded, operational call, or a follow-up where only retention can be judged.

**D10 Understanding What They're Doing Now.**
- *Test:* does the SP hold a working model of:
  - (a) the current approach as a system (process, tools, ownership, what works, where it breaks);
  - (b) relevant previous attempts (why tried, expected versus actual, what worked, what failed, why stopped, failure cause kept as a hypothesis: solution, execution, accountability, skill, consistency, expectations, fit, timing, measurement);
  - (c) alternatives (competitors, in-house hire, status quo or do nothing, cheaper or familiar options) and why the buyer likes them?
- *Score only what is relevant and observable.* "We've never tried anything" or "no process yet", clearly established, can score high.
- *The buyer's failure attribution is evidence, not fact.* Keep mixed outcomes; previous success is diagnostic too.
- *Use the latest call's evidence* when the setup has changed.
- *Penalise:*
  - recommending what was already tried;
  - attacking or dismissing current tools or competitors without understanding them;
  - mislabelling the failure the buyer described;
  - premature replacement when complementing fits;
  - a procurement-style inventory of irrelevant tools.
- *A casual competitor mention or a missed irrelevant tool* should not dominate.
- *5:* clear current system and gap, a past attempt diagnosed (what improved and what broke), competitor appeal understood without attack, open uncertainty kept.
- *4:* current system clear but one past attempt or competitor motive shallow; ownership slightly unclear.
- *3:* tool name only; "agency failed" accepted; a competitor noted but not explored; process only partly understood.
- *2:* recommends what was already tried; dismisses a tool unexamined; contradicts the buyer's own failure account; "cheaper but low quality" with no evidence.
- *1:* keeps pitching replacement of something the buyer says works; rewrites the buyer's history after correction; knowingly invents competitor weaknesses (also D07).

### 12.b What a transcript alone cannot reliably judge
- **D03 Tone, Pace & Pauses: not judgeable without audio.** The rubric's default with a transcript only is "—". It needs audio prosody, pause and overlap timing, and a per-speaker baseline.
- **Partly judgeable; audio or timing changes some findings:**
  - D01: robotic or aggressive delivery, talk-over;
  - D04: interruptions versus natural overlap, emotional change;
  - D06: warmth, sarcasm, coldness after price, laughter;
  - D07: mocking, intimidation, sarcasm. The rubric warns "don't infer vocal disrespect from neutral words".
- **Need knowledge from outside the call to reach the harshest findings:**
  - **D07** needs product, pricing, offer-calendar, guarantee and competitor facts to call a claim false or fake (otherwise WARN or Unverifiable), and CRM history for earlier stop requests;
  - **D10** needs competitor facts to call a claim a misrepresentation;
  - **D08** needs deal size or stage to judge proportionality.
- **Need earlier-call or CRM context to judge what was needed:**
  - D01 (context awareness, prior relationship);
  - D02 (whether a plan was needed, pending items);
  - D05 (what was "already known");
  - D09 (follow-ups: retention versus original discovery);
  - D10 (current approach changes between calls).
- **Every dimension needs reliable speaker attribution.** Unreliable attribution means "—" in D01, D03 and D04, and it is implied for the others. Missing buyer audio means "—" or low confidence in D04, D05 and D06.

### 12.c Output schema per dimension (recommended)
- **From the rubric:**
  - `dimension_id`, `category`;
  - `applicability`: `applicable` | `not_applicable` | `not_enough_evidence`. Keep NA and NEE distinct even though both display "—";
  - `rating`: 1–5 or null;
  - `confidence`: high, medium or low, plus an optional per-claim confidence (D10 uses "High on attempt, Low on cause");
  - `evidence`: a list of {`segment_ids`, `start_ts`, `end_ts`, `speaker`, short `quote`, `polarity` positive or negative, `note`};
  - `observed_behavior`, `positive_evidence`, `negative_evidence`, `reason_for_rating`;
  - `severity`: unified to minor | meaningful | material, with D07's critical mapped to material plus an ethics FAIL;
  - `inference`: none, or labelled inferences;
  - `coaching_point`: one specific behaviour, never generic.
- **Dimension-specific sub-fields** from each rubric's "Internal output format" (enums listed in the sections above). For example: D02 Why-This-Call Clarity; D03 Audio Evidence Available, Price/Objection/Closing Delivery; D04 Repeated Answered Questions; D05 Leading Question Risk; D06 Price/Objection Relationship Stability; D08 Authority Map; D09 Root-Cause Status and Remaining Uncertainty; D10 Failure Type Hypotheses and Replace vs Complement.
- **D07 extras:** `ethics_gate` PASS | WARN | FAIL, `material_ethical_finding` none | suspected | confirmed, and `verification_needed` as a list of claims with the fact needed to verify each.
- **Recommended additions (inference):**
  - `boundary_notes`: other dimensions that the same evidence also touches, and the different effect each judges. This lets reviewers see double counting.
  - `evidence_coverage`: which parts of the call were usable (audio and transcript coverage, opening present or absent).
  - `call_context_used`: call type, follow-up or first call, sources consulted (CRM or prior calls), so a "—" or NA can be audited.
  - `rubric_rule_ids`: the rubric rules applied (for example, D07-§43 one material violation), so scoring can be traced in evaluation.

### 12.d Failure modes the rubric warns about most
1. **Treating missing evidence as poor performance**, or politeness on a near-empty call as 5/5. This is canonical in every dimension.
2. **Rewarding the absence of mistakes with 5/5.** 5 needs positive evidence.
3. **Counting instead of judging:** question count, talk ratio, acknowledgements, pause seconds, WPM, agenda length, rapport techniques.
4. **Scoring rituals and scripts:** "How are you", name use, the word "agenda", "Is that okay?", "Who is the decision-maker?", "sir/ma'am", polished English.
5. **Inferring delivery from text** ("sounded confident") or **mind-reading** emotion, trust or intent from one cue. Observation must come before interpretation.
6. **Penalising style, personality, accent, language mix or grammar**, or rewarding a charismatic "sales voice".
7. **Scoring outcomes:** a sale raising scores, a "no" or a reserved buyer lowering them.
8. **Letting one moment define the call,** except D07, where one material violation does, or letting one good moment hide a bad pattern.
9. **Accusing the SP of lying without verifiable evidence.** Unverified claims are WARN, not FAIL.
10. **Domain misreads:**
    - treating a spouse or partner mention as a fake objection;
    - treating a competitor mention as an objection;
    - assuming prior attempts failed or why;
    - accepting the buyer's first problem statement as the diagnosis;
    - seller-imposed goals;
    - manufactured pain;
    - solution-first diagnosis;
    - premature presentation.
11. **Double counting** one quote across D01/D02/D07, D03/D04/D06/D07, D04/D05/D09 and D07/D08/D10. The rubric's own examples do this, and sometimes at conflicting severities (11.1).
12. **Vague coaching or personality labels from one call** ("You are a bad listener").
13. **Letting confidence change the score.**

---

## Names seen (lines 1–12624)
These are example names in the rubric. They look like illustrative placeholders, not real customers, but they are listed here instead of repeated in the body.
- **Person first names (illustrative salesperson or buyer names):**
  - Rajesh: 159, 288, 512, 751, 895, 967, 1197;
  - Rahul: 159, 161, 162, 288, 308, 310, 368, 405, 455, 474, 487, 496, 500, 548, 562, 751, 895, 1662, 4129, 4502, 5856, 5858, 6834, 7273, 8184, 9862, 11155, 12517;
  - Amit: 135, 1246;
  - Priya: 195, 1079, 1246;
  - Aman: 308;
  - Neha: 330;
  - Rohit: 341;
  - Dipak: 341, 343, 967 (also the name of the folder holding this file);
  - Akash: 405;
  - "Mr. Sharma": 602.
- **Places:** Pune (387, 6687), Mumbai (578, 582), Andheri (584), Nagpur (6117), Baner (4370).
- **Real companies or products:**
  - HubSpot: 1817, 11498, 11781, 11783, 12296, 12584, 12586, 12592;
  - Zoho: 11695, 11699, 11702, 12052, 12054, 12056, 12058;
  - Salesforce: 11966, 11970.
  These are named as the buyer's CRM or a competitor; one example (12052–12058) has the SP dismissing one of them.
- **Own organisation and product:** Authority Closers (159, 162, 259, 368, 455, 500, 1207, 1601, 1888, 7428, 8718), Sales X-Ray (12375).
- **Placeholders:** "XYZ company" (474), "ABC" (548), "Competitor X" (throughout D07 and D10).
