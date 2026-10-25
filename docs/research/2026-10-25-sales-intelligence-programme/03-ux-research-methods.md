# 03 — UX research methods and benchmarks for Sales X-Ray

*Sales intelligence research programme, chapter 3. Written 25 Oct 2026. Status: draft for CTO and CEO review.*

**Evidence labels used throughout.** **[M] measured**: a number from AC's own data. There are none yet, because the new telemetry has only just started recording. **[E] external**: a number taken from a cited source. **[A] assumed**: our own proposal or derivation, to be replaced by [M] once we measure it. Citations are numbered [n], and the full list is at the end.

**How the sources were checked.** Each citation was checked against its DOI record (Crossref or OpenAlex), the publisher's page or the author's own page. Abstracts were read for all of them, and full text for some. The web-search budget for this session ran out partway through, so the last checks used direct DOI and publisher lookups only. Items that could not be fully checked are listed in "Method limits and unverified items". Reddit is blocked for these research tools. Community evidence from Reddit (seller complaints about CRMs, local norms for paying research participants) would have helped in sections 1.6 and 8, and it is missing.

---

## Summary

Sales X-Ray already has telemetry that shows *where* sellers struggle: slow taps, dead and rage taps, abandoned flows and writes still waiting to sync. It cannot show *why*. This chapter sets out a small, repeatable research system that answers both questions for a team that is small, uses AI heavily, and serves sellers who work on budget Android phones in Hindi, Marathi, English and Hinglish.

The system has five parts:

1. **Monthly moderated think-aloud rounds.** Each round runs 5–8 sellers on their own phones, using a fictional test workspace. Moderators are Indian and speak the participant's language. Think-aloud is concurrent everywhere except during the pretend call, which is covered by a retrospective walkthrough of the screen recording.
2. **Seven task scripts with fixed success criteria.** They cover the core journeys: take leads, call, log the result, add a note, set a reminder, send a WhatsApp template, and review an AI call report. Each is followed by the Single Ease Question (SEQ).
3. **A HEART metric set** (Happiness, Engagement, Adoption, Retention, Task success) worked out with Goals–Signals–Metrics. It uses only events and timings, never message content or phone numbers.
4. **Per-journey benchmark targets.** Expert times are estimated with a mobile Keystroke-Level Model. Response-time targets come from published thresholds. Every number carries a measured, external or assumed label.
5. **A quarterly benchmark study** (n = 20, same tasks every time, SUS plus task metrics) to compare releases. A/B tests wait until there are enough active sellers to detect realistic effects; at 40 testers they cannot.

---

## 1. Moderated usability tests with real sellers

### 1.1 Why moderated tests are still needed

Telemetry says that, for example, 30% of "log call result" sheets are dismissed without saving on low-end phones. Only watching and listening to sellers tells us whether that is because the sheet appears too late, the outcome chips are unclear, the seller wants to log the result later, or the sheet covers the next lead. Moderated tests are where hypotheses come from. Telemetry measures how far a problem reaches and whether a fix worked (section 8.5).

### 1.2 Recruiting inside-sales staff in India

**Who to recruit.** Recruit people who make or take sales calls for most of their working day: inside sales for rooftop solar, real estate, education admissions, insurance, loans and similar small and medium businesses. Managers and owners are a separate segment, since their journeys are the owner dashboard and the report review. Do not recruit AC staff or people who build the product.

**Screener (one short form, about 2 minutes, in English, Hindi or Marathi):**

| Question | Keep if | Why |
|---|---|---|
| Role and calls per day | Seller, roughly 30 or more calls a day [A] | The core user |
| Phone brand, model and RAM (shown on the "About phone" screen) | Mix of low-end (3–4 GB) and mid-range [A] | Performance problems show up on low-end phones |
| Languages used at work: speaking, typing | Quota across Hindi, Marathi, English and code-mixed | Think-aloud language and SEQ version |
| CRM or sheet used today | Any; note it | Prior habits shape expectations |
| Uses WhatsApp for customer follow-up | Most | Journey (f) |
| Dual SIM | Note it | Journey (b): the SIM chooser |
| Age 18 or over | Required | DPDP rules for children (section 1.5) |
| Works for an AC customer? Is a Play tester? | Note; balance the mix | Testers who already use the app are no longer naïve |

**Where to find them.** (1) The Play alpha tester panel. (2) Sellers at customer organisations, recruited through the owner but never with the manager in the room. (3) Sales-training and job communities. Recruiting through a seller's employer adds pressure to please (section 2.3), so tell participants in writing that their employer will not see their individual results.

### 1.3 Sample sizes

The classic model is that the share of problems found with *n* participants is 1 − (1 − *p*)^*n*, where *p* is the chance that one participant runs into a given problem [1, 2]. Nielsen and Landauer's projects averaged *p* ≈ 0.31 [E], which gives about 84% of problems with 5 users [1, 5]. Virzi found that 4–5 participants revealed about 80% of problems, and that the most severe problems tend to appear early [2]. These figures are averages, though. Faulkner tested 60 users and resampled them: sets of 5 found anywhere from 55% to 99% of problems, sets of 10 found at least 80%, and sets of 20 found at least 95% [3] [E]. A meta-analysis by Hwang and Salvendy suggests 10 ± 2 participants for 80% discovery in think-aloud tests [6] [E].

Problems that affect only a minority of users matter most for Sales X-Ray: one phone brand, dual-SIM users, Marathi keyboards. Here is what the same formula gives for them [computed, E-model]:

| Share of sellers affected (*p*) | n = 5 | n = 8 | n = 10 | n = 15 | n = 20 |
|---|---|---|---|---|---|
| 0.31 (average problem) | 84% | 95% | 98% | ≈100% | ≈100% |
| 0.10 (one segment) | 41% | 57% | 65% | 79% | 88% |
| 0.05 (rare) | 23% | 34% | 40% | 54% | 64% |

**Recommendation [A].**
- *Formative rounds:* 6–8 participants a month, with at least 3 per key segment (Hindi-dominant, Marathi-dominant, low-end phone). This follows Nielsen's advice to test distinct groups separately with 3–4 users each [5].
- *Benchmark rounds:* 20 participants a quarter (section 8.8). Confidence intervals become usable at that size (section 6.1).
- *Rare segments:* leave rare, segment-specific problems to telemetry, which sees every opted-in session, rather than to small tests.

Sauro and Lewis cover the statistics of both kinds of sample size [4].

### 1.4 Remote or in person, on their own phones

Remote *synchronous* testing, where the moderator watches live from elsewhere, found about as many problems as lab testing in a controlled comparison. Remote *asynchronous* testing found fewer problems and took participants more time [7] [E]. For mobile products, field studies tend to show more about real behaviour and context than about pure interaction problems [8].

**Use the participant's own phone.** Their device speed, storage, keyboard and language settings, dual SIM, battery saver and OEM permission screens are exactly what we need to see. A lab phone would hide them.

**A practical constraint for the call journey.** On a single Android phone, a cellular call takes the audio away from a Google Meet or WhatsApp video session. A remote moderator therefore cannot hear the participant during journey (b), and may lose the screen share too.
- **In person** (at the seller's office or a café, with the manager not present) for sessions that include journeys (b) and (c).
- **Remote synchronous** for journeys (a) and (d)–(g). The participant shares their screen through Meet, and the moderator calls them on a second device for audio.
- **Fallback for remote calls:** the participant props up a second phone or laptop camera that films the test phone, so it does not depend on screen share.

Keep one budget "lab" phone (3–4 GB RAM [A]) for anyone who will not use their own device.

### 1.5 Consent and recording under India's DPDP Act 2023

The Digital Personal Data Protection Act, 2023 [9] applies to the session recordings, which hold a participant's voice, face, screen and opinions. Under it, AC is the data fiduciary. The main provisions (from the PRS summary [10]):
- processing needs consent for a lawful purpose, and consent can be withdrawn at any time;
- a notice must come before consent and describe the data and the purpose;
- participants have rights to information, correction and erasure, and to raise a grievance;
- anyone under 18 is a child, and processing their data needs verifiable parental consent;
- penalties reach Rs 250 crore for security failures.

The Act also lets people read the notice in English or in a language of the Constitution's Eighth Schedule, which includes Hindi and Marathi (s. 5(3); the Act's text could not be opened in this session, so confirm with counsel). The DPDP Rules 2025 phase in over time. An earlier AC note, relying on third-party commentary, dates the main obligations to around May 2027. Treat that date as **not verified** and design to the Act now.

**Session consent pattern [A]:**
1. A one-page notice in the participant's language, sent in advance. It covers what is recorded, why, who sees it, how long it is kept, how to withdraw and whom to contact.
2. **Separate tick-boxes:** (a) taking part; (b) screen and audio recording; (c) face video (optional); (d) internal clips in AC reports (optional). Each one is a clear affirmative act, and saying no to the optional ones has no penalty.
3. Repeat the recording consent on the recording itself at the start (the wording is in section 3.0).
4. **Retention:** delete raw video 90 days after the round's report [A]. Keep anonymised notes and metrics. Log each deletion.
5. **No external processing of recordings** (cloud transcription or AI summaries) unless the consent names it. This follows the AGENTS.md rule against external processing before consent and provider gates.

### 1.6 Incentives

Pay for the participant's time and mobile data, in a form that does not run through their employer: a UPI transfer or a voucher. As a starting point [A], offer about ₹500 for 30 minutes remote and ₹1,000 for 60 minutes in person, plus a data top-up. Check this against local norms (community sources were not available, as noted above). Pay the same whatever the participant says or how they perform, and say so up front, because payment tied to the outcome encourages praise. The team makes the payment, not an AI agent.

### 1.7 Keeping real customer data out

- **A test workspace, "Sunrise Rooftops" [fictional],** holds fictional leads: "Priya Sample", "Rahul Demo", "Asha Test" and others. Each phone number is a team-owned test SIM that the moderator answers.
- **The AI report for journey (g)** comes from a role-played call between two consenting team members, never from a customer call.
- **Ask the participant to turn on Do Not Disturb.** Pause the recording when the dialler's recent-calls list or WhatsApp's chat list is on screen. Cut any accidental customer data before the clips are stored.
- **Never ask participants to open their real workspace.** If they do so by habit, stop the recording and delete that part.

---

## 2. Think-aloud in Hindi and Marathi

### 2.1 Concurrent or retrospective

Ericsson and Simon's model holds that speaking thoughts aloud as they occur changes cognition little, provided people report what they are attending to rather than explaining it [11, 12]. Usability practice departs from that model; for example, moderators often probe. Boren and Ramey suggest treating the session as a speech genre. In practice that means short, neutral acknowledgement tokens ("mm-hm") keep people talking without steering them [15].

**Comparison.** Van den Haak, De Jong and Schellens compared concurrent think-aloud (CTA) with retrospective think-aloud (RTA). Both found similar numbers of problems. CTA found more of them through what the evaluator observed, and RTA found more through what participants said. Thinking aloud concurrently also hurt task performance [13] [E]. Stimulated RTA, where the participant comments while watching their own recording, gave a valid account of what people attended to, with little fabrication [14] [E].

**Implication [A].** Use CTA for formative rounds. Do not use CTA timings as benchmarks; measure time-on-task in silent benchmark sessions or from telemetry (sections 6.2 and 8.8).

### 2.2 Culture and the moderator–participant relationship

- **Clemmensen et al.** describe how cultural cognition affects each element of think-aloud: the instructions, what the user says, how the evaluator reads the user, and the relationship between them [16]. Their "Easterners" are people from China and cultures influenced by it, so applying the findings to India is our hypothesis, not their result.
- **Shi's field study** of Chinese tests found that users did not think aloud actively. Evaluators needed active communication skills, and some fell back on retrospective think-aloud [18].
- **Vatrapu and Pérez-Quiñones** found something directly relevant. Indian participants reported more usability problems, and offered more suggestions, to an interviewer from their own culture than to an Anglo-American one [17] [E].
- **Yammiyavar, Clemmensen and Kumar** found that think-aloud sessions carry a rich layer of non-verbal communication, and that some gesture types are specific to a culture [20].

**Implications [A].**
- Moderators are Indian, speak the participant's language, and are not the screen's designer.
- Allow a warm-up: chai, small talk, and a practice task on a neutral app such as the phone's calculator.
- Note-takers record head shakes, sighs and hesitation as findings.

### 2.3 Politeness and acquiescence bias

Dell et al. ran 450 interviews in Bangalore. Participants were about 2.5 times more likely to prefer a technology they believed the interviewer had made, even when the alternative was identical. The figure rose to about 5 times when the interviewer was a foreign researcher working through a translator. Participants preferred the interviewer's version even after it was made obviously worse [19] [E]. Sales X-Ray sessions risk exactly this, since AC both builds the app and often has a relationship with the seller's employer.

**Countermeasures [A]:**
- **Separate the moderator from the product.** "I didn't design this; the team wants to find what's broken." This is truthful when the moderator is not the designer.
- **Invite criticism.** For example: "Sellers last month found three problems on this screen. What would you change?"
- **Trust behaviour over words.** Use completion, errors and time as primary evidence. Read praise ("बहुत अच्छा है") as low signal.
- **Keep employers out.** No managers in the room, and no results reported to the employer by name.
- **Use balanced scales.** Ask the SEQ after every task, including failed ones, and interpret it against behaviour (section 4.3).

### 2.4 Translating prompts and code-mixed speech

Sellers switch freely between English and Hindi or Marathi, often inside a single sentence. Analysis of English–Hindi social-media text found that most mixed words fall on a continuum between borrowing and true mixing rather than in clear categories [21]. Practical rules [A]:

1. Tell participants that any language, mixed freely, is fine. The prompts in section 3.0 say this.
2. Keep product terms in the form sellers use, usually English in Devanagari or Roman script: "लीड", "कॉल", "WhatsApp", "टेम्पलेट". Do not invent formal Hindi words for UI terms.
3. Transcribe verbatim in the script the person spoke, and add an English gloss column. Code all findings in English.
4. Any machine transcription of session audio must be covered by the consent in section 1.5. Spot-check Hinglish transcripts by hand.
5. Translate the moderator prompts and SEQ with the forward and back-translation process in section 4.6, using a lighter version: one forward translator, one back translator, and a review with two sellers.

### 2.5 Running think-aloud around a pretend call

A seller cannot think aloud while talking to a customer. **Protocol [A]:**

1. **Before the call:** concurrent think-aloud while the seller finds the lead and taps Call.
2. **During the call:** the moderator, or a colleague on the team's test SIM, plays "Priya Sample" from a 60–90 second script (section 3.2). The participant talks to the "customer" and does not think aloud. The observer notes when the participant looks at the app during the call.
3. **After the call:** concurrent think-aloud while they log the result, add a note and set a reminder (journeys c–e).
4. **Straight afterwards:** stimulated retrospective think-aloud [14]. Play the screen recording of steps 1–3 and ask what they were thinking at each pause. This brings out intentions that were silent during the call, such as "I was trying to remember what she said about the roof."

---

## 3. Task scripts for the seven journeys

*All Hindi (HI) and Marathi (MR) text below is a **draft, to be checked by a native speaker** before use.*

### 3.0 Session frame (about 45 minutes)

1. **Welcome, consent and recording check** (5 min).
   - EN: "May we record your screen and voice for this session? You can say no or stop at any time."
   - HI: "क्या आप इस सेशन की स्क्रीन और आवाज़ रिकॉर्ड करने की अनुमति देते हैं? आप कभी भी मना कर सकते हैं या रोक सकते हैं।"
   - MR: "या सेशनची स्क्रीन आणि आवाज रेकॉर्ड करायला तुमची परवानगी आहे का? तुम्ही कधीही नकार देऊ शकता किंवा थांबवू शकता."
2. **Think-aloud instructions and a practice task** on the phone's calculator (5 min).
   - EN: "Today we are testing the app, not you. No answer is wrong. While you work, keep saying whatever you are thinking, in Hindi, Marathi or English, whatever is easiest. If something is confusing or you get stuck, say so; that is the most useful thing for us."
   - HI: "आज हम ऐप को टेस्ट कर रहे हैं, आपको नहीं। कोई जवाब गलत नहीं है। काम करते समय जो भी सोच रहे हैं, बोलते रहिए — हिंदी, मराठी या इंग्लिश, जैसे भी आसान लगे। अगर कुछ समझ न आए या आप अटक जाएँ, तो वही बताइए; वही हमारे लिए सबसे काम की बात है।"
   - MR: "आज आम्ही ॲप तपासतोय, तुम्हाला नाही. कोणतंही उत्तर चूक नाही. काम करताना मनात जे येईल ते मोठ्याने बोलत राहा — मराठी, हिंदी किंवा इंग्रजी, जसं सोपं वाटेल तसं. काही समजलं नाही किंवा अडकलात, तर तेच सांगा; तीच आमच्यासाठी सर्वात उपयोगी गोष्ट आहे."
3. **Neutral prompts** when the participant goes quiet for about 5 seconds. Use acknowledgement tokens only; never say "good" or "right".
   - EN: "What are you thinking now?" / "Keep talking."
   - HI: "आप अभी क्या सोच रहे हैं?" / "बोलते रहिए।" Tokens: "हम्म", "हाँ".
   - MR: "आत्ता तुम्ही काय विचार करताय?" / "बोलत राहा." Tokens: "हं", "हो".
4. **Expectation probe** after an error, asked only after the task ends.
   - EN: "When you tapped that, what did you expect to happen?"
   - HI: "जब आपने उस पर टैप किया, तब आपको क्या होने की उम्मीद थी?"
   - MR: "तुम्ही त्यावर टॅप केलं तेव्हा काय होईल असं तुम्हाला वाटलं होतं?"
5. **Retrospective cue** after journeys (b)–(e).
   - EN: "Let's watch what you just did. Tell me what you were thinking at each moment."
   - HI: "अभी जो आपने किया, उसकी रिकॉर्डिंग साथ में देखते हैं। हर पल पर आप क्या सोच रहे थे, बताइए।"
   - MR: "आत्ता तुम्ही जे केलं त्याचं रेकॉर्डिंग आपण एकत्र पाहू. प्रत्येक क्षणी तुम्ही काय विचार करत होतात ते सांगा."
6. **Post-task SEQ** after every task, asked aloud with a printed or on-screen 1–7 card [22].
   - EN: "Overall, how difficult or easy was this task? 1 = very difficult, 7 = very easy."
   - HI: "कुल मिलाकर, यह काम करना कितना मुश्किल या आसान था? 1 = बहुत मुश्किल, 7 = बहुत आसान।"
   - MR: "एकूण पाहता, हे काम करणं किती अवघड किंवा सोपं होतं? 1 = खूप अवघड, 7 = खूप सोपं."
7. **End of session:** SUS or UMUX-Lite (section 4), one open question ("What would you change first?"), thanks and payment.

**Standard rules for every task.**
- Read the scenario aloud and also hand it over on a card.
- Start the timer when the participant says they are ready.
- A task fails if the participant gives up, if a wrong end state is reached and accepted, or at the time cap of 3 minutes per task (5 minutes for g) [A].
- Do not help, except after a fail, to set up the next task.

### 3.1 Journey (a): Take leads

- **Setup:** Taking new leads is switched OFF. Two fictional new leads are waiting to be assigned.
- **Scenario:**
  - EN: "It's 10 in the morning. Your manager says new enquiries from today's ads are coming in. Make sure the app gives you new leads, then find the newest lead you have received."
  - HI: "सुबह के 10 बजे हैं। आपके मैनेजर ने बताया है कि आज के विज्ञापनों से नई पूछताछ आ रही है। ऐसा कीजिए कि ऐप आपको नई लीड्स देने लगे, और फिर सबसे नई आई हुई लीड ढूँढिए।"
  - MR: "सकाळचे 10 वाजले आहेत. तुमच्या मॅनेजरने सांगितलं आहे की आजच्या जाहिरातींमधून नवीन चौकशी येत आहे. ॲप तुम्हाला नवीन लीड्स देईल असं करा, आणि मग सर्वात नवीन आलेली लीड शोधा."
- **Success:** Taking leads is ON, *and* the participant opens or names the newest assigned lead.
- **Observe:**
  - whether they find the switch, and whether they understand what ON means;
  - whether they confuse "new" with "all" leads;
  - waiting or refresh behaviour after switching on;
  - any notification-permission prompt and how they answer it.

### 3.2 Journey (b): Call a lead

- **Setup:** "Priya Sample (Sunrise Rooftops)" sits in the list, with her number on the team's test SIM.
- **Scenario:**
  - EN: "Call the lead Priya Sample from Sunrise Rooftops. The number belongs to our team; I'll answer as the customer."
  - HI: "'सनराइज़ रूफटॉप्स' की लीड 'प्रिया सैंपल' को कॉल कीजिए। यह नंबर हमारी टीम का है; ग्राहक बनकर मैं ही फ़ोन उठाऊँगा/उठाऊँगी।"
  - MR: "'सनराइज रूफटॉप्स'ची लीड 'प्रिया सॅम्पल' यांना कॉल करा. हा नंबर आमच्या टीमचा आहे; ग्राहक म्हणून मीच फोन उचलेन."
- **Role-play script (moderator as Priya):** interested in a 3 kW rooftop system, asks for the brochure on WhatsApp, says her roof is shared with a neighbour, and asks for a call back tomorrow at 11 a.m. Keep the call to about 60–90 seconds.
- **Success:** the call reaches the right number from inside the app, and the app records the call against Priya's lead.
- **Observe:**
  - how they search for the lead (scrolling or searching);
  - the dual-SIM chooser;
  - the call-log or phone permission prompt;
  - whether they look back at the app during the call;
  - whether the app comes back after the call.

### 3.3 Journey (c): Log the call result

- **Scenario:**
  - EN: "The call is over. Record in the app how it went: Priya is interested and wants a call back tomorrow."
  - HI: "कॉल खत्म हो गई है। ऐप में दर्ज कीजिए कि कॉल कैसी रही: प्रिया इच्छुक हैं और कल दोबारा कॉल चाहती हैं।"
  - MR: "कॉल संपला आहे. कॉल कसा झाला ते ॲपमध्ये नोंदवा: प्रिया इच्छुक आहेत आणि त्यांना उद्या पुन्हा कॉल हवा आहे."
- **Success:** the outcome is saved on this call as "interested" (or the equivalent) and the save is confirmed. A follow-up counts if the flow offers one.
- **Observe:**
  - whether the post-call sheet appears, and how quickly;
  - how the outcome labels are read;
  - whether they look for a Save button;
  - whether they try to type rather than tap;
  - any "waiting to sync" state.

### 3.4 Journey (d): Add a note

- **Scenario:**
  - EN: "Add a note on Priya's lead so a colleague would understand: 'Wants a 3 kW quote; roof shared with neighbour.'"
  - HI: "प्रिया की लीड पर एक नोट जोड़िए ताकि आपका साथी समझ सके: '3 kW का कोटेशन चाहिए; छत पड़ोसी के साथ साझा है।'"
  - MR: "प्रियाच्या लीडवर एक नोट जोडा, म्हणजे तुमच्या सहकाऱ्याला समजेल: '3 kW चं कोटेशन हवं आहे; छत शेजाऱ्यांसोबत शेअर्ड आहे.'"
- **Success:** a note holding both facts is saved on Priya's lead and visible after leaving and re-opening the lead. Any language or script is fine.
- **Observe:**
  - which keyboard and script they use, and whether they use voice typing;
  - whether the keyboard covers the Save button;
  - lost drafts.

### 3.5 Journey (e): Create a task or reminder

- **Scenario:**
  - EN: "Make sure you will be reminded to call Priya tomorrow at 11 a.m."
  - HI: "ऐसा इंतज़ाम कीजिए कि कल सुबह 11 बजे आपको प्रिया को कॉल करने की याद दिलाई जाए।"
  - MR: "उद्या सकाळी 11 वाजता प्रियाला कॉल करायची आठवण तुम्हाला मिळेल अशी व्यवस्था करा."
- **Success:** a reminder or task tied to Priya's lead is saved for tomorrow at 11:00, with an error of 15 minutes or less [A].
- **Observe:**
  - whether a preset fits ("Tomorrow morning"), or whether they need a custom time;
  - mistakes with the time picker (AM/PM, 12- or 24-hour);
  - whether they expect a phone notification and whether notifications are allowed.

### 3.6 Journey (f): Send a WhatsApp message from a template

- **Setup:** a "Brochure" template exists. Priya's number is a team test number that has WhatsApp.
- **Scenario:**
  - EN: "Priya asked for the brochure on WhatsApp. Send her the 'Brochure' message template from the app."
  - HI: "प्रिया ने WhatsApp पर ब्रोशर माँगा है। ऐप से उन्हें 'Brochure' वाला मैसेज टेम्पलेट भेजिए।"
  - MR: "प्रियाने WhatsApp वर ब्रोशर मागितलं आहे. ॲपमधून त्यांना 'Brochure' हा मेसेज टेम्पलेट पाठवा."
- **Success:** the template message, with Priya's name filled in, arrives at the test number. The moderator checks this on the test phone.
- **Observe:**
  - whether they find the template;
  - whether they check the preview;
  - the handoff to WhatsApp or WhatsApp Business, and which one opens;
  - whether they understand that the final send happens in WhatsApp;
  - whether they get back to the app.

### 3.7 Journey (g): Open and review an AI call report

- **Setup:** a finished report for "Rahul Demo", from the role-played call described in section 1.7.
- **Scenario:**
  - EN: "Your manager says the AI report for yesterday's call with Rahul Demo is ready. Open it and tell me the one thing it suggests you do differently next time."
  - HI: "आपके मैनेजर ने बताया है कि कल 'राहुल डेमो' के साथ हुई आपकी कॉल की AI रिपोर्ट तैयार है। उसे खोलिए और बताइए कि अगली बार आपको कौन-सी एक बात अलग तरीके से करने को कहा गया है।"
  - MR: "तुमच्या मॅनेजरने सांगितलं आहे की काल 'राहुल डेमो' सोबत झालेल्या तुमच्या कॉलचा AI रिपोर्ट तयार आहे. तो उघडा आणि पुढच्या वेळी कोणती एक गोष्ट वेगळ्या पद्धतीने करायला सांगितली आहे ते सांगा."
- **Success:** the participant states, in their own words, the report's main coaching point (judged against a key written in advance).
- **Observe:**
  - the route they take to the report;
  - how long before the first content appears;
  - which sections they skip;
  - terms they do not understand (score, skill names);
  - whether they trust the report and agree with it.
- **Extra question:** "Would you change anything in your next call because of this? Why or why not?"

---

## 4. Questionnaires

### 4.1 System Usability Scale (SUS)

**What it is.**
- Brooke's 10-item SUS [24] alternates positive and negative items, each answered on a 5-point scale, and is scored 0–100.
- Lewis's 2018 review concludes that it is quick and not "dirty", and that anyone who needs a measure of perceived usability should strongly consider it [28].

**Norms and how to read a score [E].**
- **Bangor, Kortum and Miller** analysed nearly ten years of SUS data [25]. They later added an adjective scale, finding SUS and adjective ratings highly correlated [26]. Summarised by Sauro, scores around 71 map to "Good", around 51 to "OK", and above about 85 to "Excellent" [27]. The exact means per adjective could not be confirmed against the original paper.
- **Sauro and Lewis's curved grades** put the average at 68 (the 50th percentile, grade C). Grade B starts at 74.1, A− at 78.9, and A+ at 84.1 [27].
- **Popular phone apps** averaged 77.7 (range 67.7–87.4) across 3,575 users [29]. This is a more relevant comparison for us than the all-products average of 68.

**Two cautions for our sellers.**
1. **Negatively worded items in translation.** These are easy to misread, especially in translation and for less fluent readers. An all-positive SUS behaved much like the standard version, with fewer mistakes and miscodings [30]. Use the all-positive version for the Hindi and Marathi drafts [A].
2. **Small samples.** SUS from 8 people is not a benchmark. Report it only in the quarterly n = 20 study, with a confidence interval.

### 4.2 UMUX and UMUX-Lite

**UMUX** has four items, follows ISO 9241-11, and tracks SUS closely [31].

**UMUX-Lite** keeps two of those items: "This system's capabilities meet my requirements" and "This system is easy to use".
- Its reliability was about .82–.83, and it correlated about .81 with SUS [32] [E].
- Its scores run slightly below SUS but can be adjusted by linear regression [32]. That regression held up on independent data [33].
- MeasuringU gives the regression as SUS ≈ 0.65 × UMUX-Lite (0–100) + 22.9 [34]. This is a secondary source; the primary paper's text was not checked.

**Use [A].** UMUX-Lite is short enough for an in-app survey, so make it the quarterly in-app perceived-usability measure for all opted-in users. Keep the full SUS for the benchmark study.

### 4.3 Single Ease Question (SEQ)

Sauro and Dumas compared three one-item post-task measures. A 7-point Likert-style item was easy to administer and more sensitive at small sample sizes than magnitude estimation [22]. Across more than 400 tasks and 10,000 users, the average SEQ is about 5.3–5.6. SEQ correlates with completion and time at about r = .5, and some users rate failed tasks as easy [23] [E]. **Always read SEQ together with whether the task was completed.**

### 4.4 NPS: caveats

Reichheld promoted "likelihood to recommend" as the one number a company needs to grow [35]. A longitudinal study of 21 firms could not replicate the claim that it is clearly better than other loyalty measures [36] [E].

Sellers also rarely choose their CRM; their employer does. Ask NPS, if at all, to the **buyers** (owners and managers), at most once a year, and never use it as a release gate [A]. Telemetry and SUS do that job better.

### 4.5 Versions in Indian languages: what exists

- **Hindi.** A systematic multi-language study translated the SUS into Arabic, Chinese, French, German, Hindi and Spanish, and tested the versions with native speakers [37]. Its abstract reports consistent reliability and validity **only for the Chinese, French, German and Spanish versions**. It does not make that claim for Hindi or Arabic, and the full text with the Hindi statistics could not be read here.
- **Marathi.** No published Marathi SUS, UMUX or SEQ was found.
- **Conclusion: there is no validated Hindi or Marathi SUS that we can rely on.** Any Hindi or Marathi scores we collect should be compared within the same language over time, not against the English norms in 4.1. The same applies to other translations without their own validation; the Slovene SUS-SI [38] is an example of the validation work a translation needs.

### 4.6 Translation and back-translation (Beaton et al.)

Beaton et al.'s guideline for adapting self-report measures across cultures [39] has six stages. Applied to our Hindi and Marathi versions [A, following 39]:

1. **Forward translation.** Two translators: one who knows UX and the app, and one with no UX or app knowledge.
2. **Synthesis.** Merge the two into one version and log each decision.
3. **Back-translation.** Two back-translators who are native English speakers, have not seen the original, and come from neither of the above backgrounds.
4. **Expert committee.** The translators, a UX researcher and a sales trainer check four kinds of equivalence: meaning, idiom, everyday experience and concept. For example, "cumbersome" has no natural Hindi equivalent, and we choose an everyday phrase for it.
5. **Pre-test.** Beaton et al. suggest 30–40 people [E]. Each completes the questionnaire and is then asked what they understood each item to mean.
6. **Documentation.** Write up and archive the record of every stage.

**For the quarterly benchmark:** report Cronbach's alpha by language once each language has 30 or more responses.

---

## 5. HEART and Goals–Signals–Metrics for Sales X-Ray

The HEART framework (Happiness, Engagement, Adoption, Retention, Task success) comes paired with a process that starts from **Goals**, finds the behavioural **Signals** that show whether a goal is met, and turns them into **Metrics** [40]. Every signal below comes from event types and timings (screens, actions, tap-to-settled times, errors shown, writes waiting) or from structured fields (an outcome code, a due date). None uses note text, message content, recordings or phone numbers. All metrics are per person, broken down by device tier and app version, and computed only for people who have not opted out.

| HEART | Goal | Signals (telemetry or data) | Metrics (weekly) [A] |
|---|---|---|---|
| **Happiness** | Sellers find daily work easy and the reports useful | In-app SEQ after core journeys; quarterly UMUX-Lite; one-tap "what stopped you?" reason after an abandoned flow | Mean SEQ per journey (with CI); UMUX-Lite mean; top abandonment reasons (coded options, not free text) |
| **Engagement** | Sellers run their calling day from Sales X-Ray | Calls placed from the app; outcomes logged; notes and tasks created (counts only); reports opened | Calls placed per active seller-day; **% of calls with an outcome logged within 10 min**; reports opened per analysed call; median dwell on the report |
| **Adoption** | New sellers reach their first productive day quickly | First sign-in; take-leads ON; first call placed; first outcome logged; first template sent; permission prompt outcomes | % of new sellers reaching "first call + first logged outcome" within 24 h and 7 days; permission grant rate per prompt and OEM |
| **Retention** | Sellers keep using it on working days | Active days (at least one call or log) | Week-1 and week-4 retention by sign-up cohort; share of seller-days active out of working days |
| **Task success** | Core journeys are fast and error-free on low-end phones | Funnels per journey; tap-to-settled per action; errors shown; dead and rage taps; back-and-forth loops; writes waiting; repeated org switches | Funnel completion and abandonment per journey; p75 tap-to-settled per action and device tier; rage taps per 100 sessions; % of writes synced within 60 s; org switches reversed within 30 s per 100 sessions |

**Org-switch confusion**, as a signal: a switch to another organisation followed by a switch back within 30 seconds with no action in between [A].

**Guardrail [A]:** an Engagement metric must not rise while Task success falls. More taps per call is a cost, not engagement.

---

## 6. Funnels, time-on-task and quantitative benchmarks

### 6.1 Completion rates with confidence intervals

Use the **adjusted Wald** interval for small samples: add z²/2 successes and z² trials (about 2 and 4 at 95%), then compute the ordinary Wald interval [41]. Sauro and Lewis recommend this method for task completion [4]. The table below shows how wide these intervals are at our sample sizes [computed]:

| Observed | 95% adjusted-Wald CI |
|---|---|
| 5/5 | 51%–100% |
| 7/8 | 51%–100% |
| 8/8 | 63%–100% |
| 10/10 | 68%–100% |
| 17/20 | 63%–96% |
| 18/20 | 69%–98% |
| 20/20 | 81%–100% |

The external average task completion rate is 78%, across 1,189 tasks. Above 92% is the top quartile, and below 49% is the bottom quartile [55] [E].

### 6.2 Time-on-task: report the geometric mean

Task times are skewed to the right. For samples under about 25, the geometric mean, which is the exponential of the mean of the log times, estimated the population median with 13% less error and 22% less bias than the sample median [42] [E]. Report:
- the geometric mean with a CI computed on the log scale;
- **successful attempts only;**
- failures separately.

Telemetry times include interruptions, such as a customer calling in. Cap each time at the journey's limit, or use log-scale statistics, and never report the arithmetic mean [A].

### 6.3 Funnels: completion and abandonment

Define each journey in telemetry as a **start event**, one or more **step events** and a **completion event**, all in the same session [A]:
- **Completed:** the completion event fires within the journey's window (for example, 10 minutes for "log result").
- **Abandoned:** the session continues, but the user leaves the flow without completing it (back, dismiss, or navigating away).
- **Interrupted:** the app goes to the background or a call comes in. Track these separately, since they are often not design failures.
- **Not started:** the step was expected but never began (for example, a call ended and no log sheet opened). This matters most for journey (c).

Telemetry already captures abandoned flows and back-and-forth loops, so this mainly needs a fixed definition for each journey (the table in section 7).

### 6.4 Keystroke-Level Model for mobile

The Keystroke-Level Model (KLM) predicts how long an *expert* takes to finish a task without errors. The task is written as a sequence of operators: keystrokes, pointing, homing, mental preparation (M = 1.35 s) and system response R(t) [43, 44]. Mobile versions of the model:
- **Holleis et al.** extended KLM to mobile phones with operators measured in user studies [45]. Among them: finger movement F = 0.23 s, hot-key press 0.16 s, gesture 0.80 s, homing the phone to the ear and back H = 0.95 s, initial act I = 1.18 s for an expected interaction, macro and micro attention shifts of 0.36 s and 0.14 s, and M kept at 1.35 s.
- **El Batran and Dunlop** added touch operators based on Fitts's law, with movement times of about 70 ms for a short swipe, 200 ms for a half-screen zoom and 80 ms for pointing at an icon from a home position [46].
- **Rice and Lartigue** proposed a Touch-Level Model with tap, swipe, drag, pinch and similar operators [47]. Its time values could not be retrieved here.

**Operator set for Sales X-Ray:**

| Op | Meaning | Value | Basis | Label |
|---|---|---|---|---|
| M | Mental preparation (decide or find) | 1.35 s | [43]; kept for phones in [45] | E |
| T | Tap an on-screen target (move finger and press) | 0.40 s | F 0.23 + press 0.16 [45]; movement alone is ≈0.08 s [46] | A (derived) |
| Sw | Short scroll or swipe, including touch and lift | 0.30 s | ≈0.07 s movement [46] plus contact | A |
| K | One character on the touch keyboard | 0.33 s expert; 0.50 s novice or Hinglish | 36.2 WPM average across 37,370 volunteers [48] at 5 characters per word; novice figure assumed | E / A |
| S | Glance between screen regions | 0.14 s | [45] | E |
| H′ | Phone from ear back to view (half of H) | 0.50 s | [45], halved | A (derived) |
| R(t) | System response | our budget per step | sections 6.5 and 7 | A |

Holleis et al.'s values were measured on 2007-era keypad phones. Treat them as a starting point, and replace them with timings from our own telemetry once experienced sellers have enough sessions [A].

### 6.5 Response-time thresholds

- **Nielsen:** 0.1 s feels instant; 1 s keeps the flow of thought; 10 s is the limit of attention [49] [E].
- **RAIL:** respond to input within 100 ms (handle the event within 50 ms); produce animation frames in about 10 ms; become interactive in under 5 s on a mid-range phone over slow 3G. web.dev now recommends Core Web Vitals over RAIL [50] [E].
- **Core Web Vitals** "good", at the 75th percentile: LCP ≤ 2.5 s, **INP ≤ 200 ms**, CLS ≤ 0.1 [51, 52] [E]. INP is above 200 ms and up to 500 ms for "needs improvement", and above 500 ms for "poor" [52].
- **Android vitals:** cold start is excessive at 5 s or more, warm start at 2 s or more, and hot start at 1.5 s or more [53]. The bad-behaviour thresholds are a 1.09% user-perceived crash rate and a 0.47% ANR rate overall, and 8% for each per phone model [54] [E].

**Our budget rules [A]:**
- every tap shows visible feedback within 200 ms at p75 (INP "good");
- in-app navigation is settled within 1.0 s at p75 (Nielsen's flow limit);
- local saves are settled within 300 ms, using an optimistic local write that syncs in the background;
- handoffs to the dialler or WhatsApp are visible within 1.5–2.0 s;
- cold start under 3 s at p75 on low-end phones, well inside Android vitals' 5 s limit.

---

## 7. Benchmark targets per journey

### 7.1 Expert KLM estimates

Each journey starts with the app open on the screen where it begins. R values use the budgets above.

| Journey | Operator sequence | Expert estimate |
|---|---|---|
| (a) Take leads | M T R(0.3) S M T R(0.3) M | **5.6 s** |
| (b) Call a lead | M T R(0.3) M T R(1.0, dialler) | **4.8 s**; 6.6 s with dual-SIM chooser (+M T) |
| (c) Log result | H′ R(0.5, back to app) M T M T T R(0.3) | **5.2 s** |
| (d) Add note (50 characters) | M T R(0.3) M K×50 T R(0.3) | **20.6 s**; 29.1 s with novice typing |
| (e) Reminder (preset) | M T R(0.3) M T T T R(0.3) | **4.9 s**; 7.5 s with a custom time (+M 3T) |
| (f) WhatsApp template | M T R(0.3) M T R(0.3) S T R(1.5, WhatsApp) M T | **7.9 s** |
| (g) Review AI report | M T R(1.0) M Sw Sw M T R(0.3), plus reading ≈10 s [A] | **16.8 s** |

**Novice median targets.** We set these at roughly 3 times the expert estimate, plus novice typing and reading time [A]. KLM models error-free expert performance only; there is no reliable published multiplier from expert to novice for this kind of app, so the first benchmark round should replace the factor with measured values.

### 7.2 Benchmark table

Labels: completion, SEQ and taps are **[A]**, anchored on the external averages (78% completion, 92% top quartile [55]; SEQ ≈ 5.5 [23]). KLM figures are **[A]** derived from **[E]** operators. Response thresholds are **[E]** where a source is shown and **[A]** otherwise. No figure is **[M]** yet.

| Journey | Completion target | Expert KLM | Novice median target | Max taps | SEQ target | p75 tap-to-settled, low-end Android | Telemetry signal |
|---|---|---|---|---|---|---|---|
| (a) Take leads | ≥ 85% | 5.6 s | ≤ 20 s | 3 | ≥ 5.8 | Toggle feedback ≤ 200 ms; new-leads list ≤ 1.0 s | Funnel: Home → toggle ON → new-leads list → lead opened; dead taps on the toggle |
| (b) Call a lead | ≥ 92% | 4.8 s (6.6 s dual-SIM) | ≤ 15 s (≤ 20 s dual-SIM) | 2 (3 with SIM chooser) | ≥ 6.2 | Lead page ≤ 1.0 s; dialler visible ≤ 1.5 s | Funnel: lead opened → Call tapped → dialler handoff → call detected; phone permission outcomes |
| (c) Log result | ≥ 92% | 5.2 s | ≤ 16 s | 4 | ≥ 6.0 | Post-call sheet ≤ 1.0 s after return; Save ≤ 300 ms; 95% of writes synced ≤ 60 s | % of calls with an outcome in 10 min; sheet dismissed unsaved; writes waiting |
| (d) Add note | ≥ 90% | 20.6 s | ≤ 45 s | 3 + typing | ≥ 6.0 | Editor ≤ 300 ms; Save ≤ 300 ms | Editor opened → saved; abandoned editor sessions (no text captured) |
| (e) Reminder | ≥ 85% | 4.9 s (7.5 s custom) | ≤ 15 s (≤ 25 s custom) | 4 (7 custom) | ≥ 5.8 | Sheet ≤ 300 ms; Save ≤ 300 ms | Sheet opened → saved; preset vs custom share; reminder fired → opened |
| (f) WhatsApp template | ≥ 85% | 7.9 s | ≤ 25 s | 5 (including the WhatsApp send) | ≥ 5.8 | Picker ≤ 1.0 s; WhatsApp opened ≤ 2.0 s | Picker opened → template chosen → handoff; return within 2 min; no content captured |
| (g) AI report | ≥ 80% (correct coaching point) | 16.8 s | ≤ 60 s | 4 | ≥ 5.5 | First content ≤ 1.0 s; full report ≤ 2.5 s (LCP-like) | Report viewed → section expanded; dwell; scroll depth; back-and-forth loops; revisits |

### 7.3 Pass rule for a release [A]

In the quarterly benchmark (n = 20), a journey **passes** when all three of the following hold:
1. the observed completion rate meets the target, *and* the lower bound of its adjusted-Wald CI is at least 70%;
2. the geometric-mean time of successful attempts is at or below the novice target;
3. telemetry shows p75 tap-to-settled on low-end phones within budget for two consecutive weeks.

A journey that fails any of these goes onto the "Fix next" list (section 8.6).

---

## 8. Feedback loops at scale

### 8.1 In-app micro-surveys

Google's Happiness Tracking Surveys (HaTS) collect attitudes and open feedback at scale, inside the product, using random sampling, careful invitations and tracking over time [56]. Our version [A]:

- **SEQ after a completed core journey.** Sample 15% of eligible completions. Ask at most once per journey per person every 14 days, and at most one survey of any kind per person every 7 days. Never ask during a call, within 30 s of the call ending, or after a failed save.
- **"What stopped you?" after an abandoned flow.** A one-tap reason list with no free text, so customer details cannot be typed in. Sample 10% of abandoned flows.
- **UMUX-Lite once a quarter.** Use the same two weeks each quarter for every opted-in active seller.
- **Language.** Show each survey in the app's language, using the draft translations once they are back-translated (section 4.6).
- **Consent.** Surveys respect the same opt-out as the rest of telemetry.

### 8.2 Weekly friction report

The automated weekly report should rank problems, not just list numbers. For each journey and device tier, show:
1. funnel completion, abandonment and "not started" against last week, with CIs;
2. p75 and p95 tap-to-settled for the journey's key actions, flagged when over budget;
3. dead and rage taps per 100 sessions, and the top five elements involved;
4. back-and-forth loops, repeated org switches, and permission prompts denied;
5. errors shown and writes waiting longer than 60 s;
6. SEQ and abandonment reasons from micro-surveys.

Each line carries a provisional severity (section 8.6). The report ends with **at most three** "Fix next" items, each with a hypothesis to test in the next moderated round [A].

### 8.3 Diary studies

Diary methods capture experience close to when it happens. Reports can be prompted by an event, at fixed intervals, or by a signal [57]. The medium matters: photos and audio make capture easier and help participants remember later [58].

**Our version [A]:**
- **Who and how long:** a two-week diary with 8–12 sellers, started every other month.
- **Event-triggered entries:** "Whenever the app slowed you down, or you went back to paper or WhatsApp, add a 20-second entry."
- **End of day:** a two-question check-in.
- **Medium:** in-app or a form that AC controls, with voice allowed. Repeat the rule: no customer names or numbers.
- **Closing interview:** a 20-minute interview that uses the entries as prompts.

### 8.4 Tester panel with cohorts

Turn the Play testers into a managed panel, with these cohorts recorded at entry [A]:
- language (Hindi, Marathi, English or mixed);
- device tier (low or mid);
- role (seller or manager);
- tenure (under 2 weeks or experienced);
- organisation size.

Panel rules [A]:
- **Limit research load.** No more than one moderated session per tester per quarter, and no more than one survey a week. This reduces fatigue and stops testers turning into experts on our app.
- **Refresh the panel.** Recruit about 25% new testers each quarter so formative rounds always include naïve users.
- **Run release cohorts.** New builds go first to a cohort balanced across languages and device tiers, so release comparisons are like for like.

### 8.5 Triangulation

HCI research gains from triangulating across methods: using several research approaches together, so that the weakness of one is covered by another [59]. Our rule [A]:

- **Hold a major redesign** until at least two independent sources agree. For example, a telemetry signal and a moderated observation, or a diary theme and a micro-survey reason.
- **Use each method for its part.** Telemetry finds where and how many, moderated tests explain why, and the next telemetry week checks the fix.
- **Keep one findings log.** Record each finding with its sources, severity, reach and status.

### 8.6 Prioritising findings

**Severity.** Nielsen's severity rating combines frequency, impact, persistence and market impact on a 0–4 scale: 0 is not a problem, 1 is cosmetic, 2 minor, 3 major, and 4 a catastrophe to fix before release [60]. Sauro recommends three levels (minor, moderate and critical) and rating severity *separately* from frequency, ideally by an analyst who does not know the frequency. Severity and frequency can then feed a structured prioritisation process such as FMEA [61].

**Our priority score [A, combining 60 and 61].**

> **Priority = severity (1 minor, 2 moderate, 3 critical) × reach (share of active sellers affected in telemetry, as a decimal) × journey weight (3 daily core: a, b, c; 2 frequent: d, e, f; 1 occasional: g and settings).**

Anything that loses data, such as a write never synced or a note lost, is critical no matter how far it reaches.

### 8.7 The limits of A/B testing at small n

For an A/B test, Kohavi et al. approximate the total sample needed as n ≈ (4rσ/Δ)², at 95% confidence and 90% power [62]. Here r is the number of variants, σ the standard deviation of the metric, and Δ the smallest difference worth detecting. For a completion rate p, σ = √(p(1−p)). Their survey sets out the wider practice: A/A tests, randomisation and variance reduction [63].

**Worked example [computed].** With baseline completion at 70% and two variants:
- detecting a 10-point gain needs about **1,344 sellers in total**;
- with **40 testers**, the smallest detectable difference is about **58 points**;
- with 200 sellers it is about 26 points, and with 1,000 sellers about 12 points.

Pooling taps across users does not help, because taps from the same person are not independent. Analyse per-person aggregates.

**Implications [A].**
1. **Until we reach about 1,000 active sellers, do not run A/B tests on completion metrics.** Use these instead:
   - comparisons within the same participants in moderated sessions;
   - before-and-after comparisons on release cohorts, matched by device tier and language;
   - week-over-week interrupted time series, with guardrail metrics.
2. **Watch continuously only with the right statistics.** Checking results repeatedly with ordinary p-values inflates false positives. Use always-valid (sequential) p-values and confidence intervals if results will be checked continuously [64].
3. **Latency tests (tap-to-settled) can start earlier.** Each person contributes many timing events, so these tests can run once per-person p75 values are stable.

### 8.8 Quarterly benchmark study

**Purpose:** compare releases on the same tasks, under the same conditions [4].

**Participants (n = 20) [A]:**
- stratified: 10 mostly Hindi, 5 Marathi, 5 English or mixed;
- at least half on low-end phones;
- 70% new to the app, and 30% from the experienced panel cohort.

**Procedure [A]:**
- *Session format:* remote synchronous or in person, as in section 1.4. Benchmark sessions are **silent** (no concurrent think-aloud) so the times are clean [13].
- *Tasks:* the same seven scripts in the same order, with the same fictional data.
- *After each task:* the SEQ.
- *At the end:* the all-positive SUS in the participant's language, plus UMUX-Lite, so the two can be compared.

**Analysis [A]:**
- completion with adjusted-Wald CIs, and the difference against last quarter tested with an N−1 two-proportion test [4];
- times as geometric means compared on the log scale;
- SUS mean and CI by language, compared within each language over time (section 4.5).

**Sensitivity [A].** The quarterly benchmark is a coarse instrument; telemetry covers the fine detail. With 20 people per quarter, only large changes are detectable:
- *SUS:* assuming a standard deviation of about 17 points, a quarter-on-quarter change of about 15 SUS points is needed to detect it.
- *Completion:* differences under about 25 points will rarely be significant.

---

## 9. Implications for Sales X-Ray

| # | Recommendation | Impact | Effort | Evidence |
|---|---|---|---|---|
| 1 | Fix the seven journey definitions (start, steps, completion, abandonment and "not started" events) in telemetry, and show them as funnels in Admin → Telemetry | H | S | §6.3; HEART/GSM [40] |
| 2 | Add the per-journey budgets in §7.2 to the weekly friction report and the release gate, broken down by device tier, with p75 on low-end phones as the headline | H | S | INP 200 ms, LCP 2.5 s at p75 [51, 52]; Nielsen 0.1/1/10 s [49]; Android vitals [53] |
| 3 | Make "log the call result" un-missable after every call: show the post-call sheet automatically, save locally first, and track "not started" | H | M | Journey (c) weighted daily core; KLM 5.2 s [43, 45]; Engagement metric in §5 |
| 4 | Run a monthly moderated round of 6–8 sellers in their own language, with an Indian moderator who is not the designer, at least 3 per key segment, on their own phones | H | M | Sample-size studies [1, 2, 3, 5, 6]; culture effects [16, 17, 19] |
| 5 | Hold call-journey sessions in person, or remotely with a second camera, because a cellular call takes the audio from the video session | M | S | §1.4; remote synchronous ≈ lab [7] |
| 6 | Use CTA plus stimulated RTA around the pretend call; never use CTA times as benchmarks | M | S | [13, 14, 15] |
| 7 | Build the "Sunrise Rooftops" fictional workspace, test SIMs and a role-played sample AI report; ban real customer data from sessions | H | S | DPDP consent and notice [9, 10]; AGENTS.md gate on external processing |
| 8 | Put the session consent pattern (separate optional tick-boxes, 90-day deletion of raw video, notice in the participant's language) in place before the first round | H | S | DPDP Act [9, 10] |
| 9 | Commission a Beaton-style Hindi and Marathi adaptation of the SEQ, the all-positive SUS and UMUX-Lite; until then, compare scores only within the same language | M | M | No validated Hindi or Marathi SUS [37]; process [39]; positive SUS [30] |
| 10 | Ship in-app micro-surveys (SEQ after completion, a one-tap reason after abandonment, quarterly UMUX-Lite) with frequency caps | M | M | HaTS [56]; SEQ [22, 23]; UMUX-Lite [32] |
| 11 | Start the quarterly benchmark (n = 20, silent, the same 7 tasks, SUS + SEQ + completion + geometric-mean time) and the pass rule in §7.3 | H | M | [4, 41, 42, 55] |
| 12 | Do not run A/B tests on completion metrics before about 1,000 active sellers; use matched release cohorts and sequential statistics | M | S | Sample-size formula [62]; peeking [64] |
| 13 | Run one findings log with severity rated separately from frequency, and a priority score of severity × reach × journey weight; send at most 3 "Fix next" items a week | M | S | [60, 61]; triangulation [59] |
| 14 | Track org-switch confusion and permission-prompt outcomes per OEM as first-class Task success and Adoption signals | M | S | §5; Android vitals per-model thresholds [54] |
| 15 | Replace the assumed T, Sw and K operators with values measured from experienced sellers' telemetry after 4 weeks, and re-derive the KLM targets | L | S | [45, 46, 48] |

---

## 10. Research operations calendar

**Weekly (owner: product lead, with an AI-assisted analyst)**

| Day | Activity |
|---|---|
| Monday | Automated friction report lands. 30-minute triage: severity ratings, update the findings log, choose up to 3 "Fix next" items, each with a hypothesis |
| Midweek | 1–2 short sessions to check a hypothesis (15–20 min, remote, one journey) when a "Fix next" item needs a "why" |
| Friday | Check last week's fixes in telemetry (the same funnel and the same device tier); close or reopen findings |
| Continuous | Micro-surveys run under their caps; diary entries are reviewed twice a week while a diary cohort is active |

**Monthly**

| Week | Activity |
|---|---|
| 1 | Plan the round: choose 2–3 journeys from friction ranking; recruit 6–8 from the panel and the screener; send notices and consent |
| 2 | Run the moderated round (CTA + stimulated RTA; in person for the call journeys) |
| 3 | Synthesise: affinity map, severity, cross-check against telemetry, write a 2-page round report with clips (where consent allows) |
| 4 | Panel upkeep (new testers, cohort balance); translation upkeep; delete raw videos past 90 days and log the deletions. Every other month, start a 2-week diary cohort |

**Quarterly**

| When | Activity |
|---|---|
| Weeks 1–2 | Quarterly UMUX-Lite wave in the app; HEART review: Adoption and Retention by cohort, Task success by device tier |
| Weeks 3–6 | Benchmark study (n = 20, silent, same 7 tasks, SUS + SEQ); apply the pass rule in §7.3; release-against-release comparison with CIs |
| Week 7 | Recalibrate: update the KLM operators from telemetry, revise the targets in §7.2 and change their labels from [A] to [M] |
| Week 8 | Research review with the CTO and CEO: what changed, what is still failing, the next quarter's research questions. Refresh the panel by about 25% |

**Yearly:** owner and manager NPS, with caveats [35, 36]; a full Beaton-style re-check of the translated questionnaires once 30 or more responses per language exist [39].

---

## Method limits and unverified items

- **Bangor, Kortum and Miller (2009) adjective means:** only the approximate values summarised by Sauro (Good ≈ 71, OK ≈ 51, Excellent ≳ 85) [27] were confirmed. The original table could not be opened.
- **The UMUX-Lite → SUS regression coefficients (0.65, 22.9)** come from MeasuringU [34], not from the primary paper's text. The 2013 abstract confirms that a regression adjustment exists [32].
- **DPDP Act section numbers (for example s. 5(3) on notice languages):** the Act's PDF and MeitY pages returned errors, so the provisions were confirmed through the PRS summary [10]. **The DPDP Rules 2025 notification date and phase-in are not verified**; they come from an earlier AC note citing third-party commentary.
- **The Touch-Level Model (Rice and Lartigue 2014) [47]:** the paper exists, but its operator times were not retrieved. **El Batran and Dunlop's values [46]** come from the abstract only.
- **Hindi SUS [37]:** the full text, including the Hindi reliability results, could not be read. No Marathi SUS, UMUX or SEQ was found.
- **Kaikkonen et al.'s 2005 *Journal of Usability Studies* paper** on lab versus field testing could not be fetched. The authors' 2008 book chapter on the same comparison [8] is cited instead.
- **Assumed values that need replacing with measurements:**
  - incentive amounts;
  - the 3× novice factor;
  - a novice typing speed of 0.5 s per character;
  - a reading time of 10 s;
  - an SUS standard deviation of about 17;
  - the micro-survey sampling rates.
- **Community evidence (Reddit)** was blocked for these tools and was not used.

---

## References

*All accessed 25 Oct 2026.*

1. Nielsen, J., & Landauer, T. K. (1993). A mathematical model of the finding of usability problems. *Proc. INTERCHI '93 / CHI '93*, 206–213. ACM. https://doi.org/10.1145/169059.169166
2. Virzi, R. A. (1992). Refining the test phase of usability evaluation: How many subjects is enough? *Human Factors, 34*(4), 457–468. https://doi.org/10.1177/001872089203400407
3. Faulkner, L. (2003). Beyond the five-user assumption: Benefits of increased sample sizes in usability testing. *Behavior Research Methods, Instruments, & Computers, 35*(3), 379–383. https://doi.org/10.3758/BF03195514
4. Sauro, J., & Lewis, J. R. (2016). *Quantifying the User Experience: Practical Statistics for User Research* (2nd ed.). Morgan Kaufmann. ISBN 978-0-12-802308-2.
5. Nielsen, J. (2000, 18 Mar). Why you only need to test with 5 users. Nielsen Norman Group. https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/
6. Hwang, W., & Salvendy, G. (2010). Number of people required for usability evaluation: The 10±2 rule. *Communications of the ACM, 53*(5), 130–133. https://doi.org/10.1145/1735223.1735255
7. Andreasen, M. S., Nielsen, H. V., Schrøder, S. O., & Stage, J. (2007). What happened to remote usability testing? An empirical study of three methods. *Proc. CHI 2007*, 1405–1414. https://doi.org/10.1145/1240624.1240838
8. Kaikkonen, A., Kekäläinen, A., Cankar, M., Kallio, T., & Kankainen, A. (2008). Will laboratory test results be valid in mobile contexts? In *Handbook of Research on User Interface Design and Evaluation for Mobile Technology* (pp. 897–909). IGI Global. https://doi.org/10.4018/978-1-59904-871-0.ch053
9. Government of India. (2023). *The Digital Personal Data Protection Act, 2023* (Act No. 22 of 2023). https://www.meity.gov.in/writereaddata/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf (returned HTTP 403 when accessed; provisions confirmed through [10]).
10. PRS Legislative Research. (2023). The Digital Personal Data Protection Bill, 2023: Bill summary and status. https://prsindia.org/billtrack/digital-personal-data-protection-bill-2023
11. Ericsson, K. A., & Simon, H. A. (1980). Verbal reports as data. *Psychological Review, 87*(3), 215–251. https://doi.org/10.1037/0033-295X.87.3.215
12. Ericsson, K. A., & Simon, H. A. (1993). *Protocol Analysis: Verbal Reports as Data* (rev. ed.). MIT Press. https://doi.org/10.7551/mitpress/5657.001.0001
13. Van den Haak, M. J., De Jong, M. D. T., & Schellens, P. J. (2003). Retrospective vs. concurrent think-aloud protocols: Testing the usability of an online library catalogue. *Behaviour & Information Technology, 22*(5), 339–351. https://doi.org/10.1080/0044929031000
14. Guan, Z., Lee, S., Cuddihy, E., & Ramey, J. (2006). The validity of the stimulated retrospective think-aloud method as measured by eye tracking. *Proc. CHI 2006*, 1253–1262. https://doi.org/10.1145/1124772.1124961
15. Boren, T., & Ramey, J. (2000). Thinking aloud: Reconciling theory and practice. *IEEE Transactions on Professional Communication, 43*(3), 261–278. https://doi.org/10.1109/47.867942
16. Clemmensen, T., Hertzum, M., Hornbæk, K., Shi, Q., & Yammiyavar, P. (2009). Cultural cognition in usability evaluation. *Interacting with Computers, 21*(3), 212–220. https://doi.org/10.1016/j.intcom.2009.05.003
17. Vatrapu, R., & Pérez-Quiñones, M. A. (2006). Culture and usability evaluation: The effects of culture in structured interviews. *Journal of Usability Studies, 1*(4), 156–170. https://uxpajournal.org/issue/volume-1-issue-4 (preprint: https://arxiv.org/abs/cs/0405045)
18. Shi, Q. (2008). A field study of the relationship and communication between Chinese evaluators and users in thinking aloud usability tests. *Proc. NordiCHI 2008*, 344–352. https://doi.org/10.1145/1463160.1463198
19. Dell, N., Vaidyanathan, V., Medhi, I., Cutrell, E., & Thies, W. (2012). "Yours is better!": Participant response bias in HCI. *Proc. CHI 2012*, 1321–1330. https://doi.org/10.1145/2207676.2208589
20. Yammiyavar, P. G., Clemmensen, T., & Kumar, J. (2008). Influence of cultural background on non-verbal communication in a usability testing situation. *International Journal of Design, 2*(2). http://www.ijdesign.org/index.php/IJDesign/article/view/313
21. Bali, K., Sharma, J., Choudhury, M., & Vyas, Y. (2014). "I am borrowing ya mixing?" An analysis of English-Hindi code mixing in Facebook. *Proc. First Workshop on Computational Approaches to Code Switching*, 116–126. ACL. https://doi.org/10.3115/v1/W14-3914
22. Sauro, J., & Dumas, J. S. (2009). Comparison of three one-question, post-task usability questionnaires. *Proc. CHI 2009*, 1599–1608. https://doi.org/10.1145/1518701.1518946
23. Sauro, J. (2012, 30 Oct; data updated May 2019). 10 things to know about the Single Ease Question (SEQ). MeasuringU. https://measuringu.com/seq10/
24. Brooke, J. (1996). SUS: A "quick and dirty" usability scale. In P. W. Jordan, B. Thomas, B. A. Weerdmeester, & I. L. McClelland (Eds.), *Usability Evaluation in Industry* (pp. 189–194 in the 1996 printing; pp. 207–212 in the CRC reprint, according to Crossref). Taylor & Francis. https://doi.org/10.1201/9781498710411-35
25. Bangor, A., Kortum, P. T., & Miller, J. T. (2008). An empirical evaluation of the System Usability Scale. *International Journal of Human–Computer Interaction, 24*(6), 574–594. https://doi.org/10.1080/10447310802205776
26. Bangor, A., Kortum, P., & Miller, J. (2009). Determining what individual SUS scores mean: Adding an adjective rating scale. *Journal of Usability Studies, 4*(3), 114–123. Listed PDF: https://uxpajournal.org/wp-content/uploads/sites/7/pdf/JUS_Bangor_May2009.pdf (returned HTTP 404 when accessed; the bibliographic details and the r = 0.822 correlation were confirmed through secondary sources).
27. Sauro, J. (2018, 19 Sep). 5 ways to interpret a SUS score. MeasuringU. https://measuringu.com/interpret-sus-score/
28. Lewis, J. R. (2018). The System Usability Scale: Past, present, and future. *International Journal of Human–Computer Interaction, 34*(7), 577–590. https://doi.org/10.1080/10447318.2018.1455307
29. Kortum, P., & Sorber, M. (2015). Measuring the usability of mobile applications for phones and tablets. *International Journal of Human–Computer Interaction, 31*(8), 518–529. https://doi.org/10.1080/10447318.2015.1064658
30. Sauro, J., & Lewis, J. R. (2011). When designing usability questionnaires, does it hurt to be positive? *Proc. CHI 2011*, 2215–2224. https://doi.org/10.1145/1978942.1979266
31. Finstad, K. (2010). The Usability Metric for User Experience. *Interacting with Computers, 22*(5), 323–327. https://doi.org/10.1016/j.intcom.2010.04.004
32. Lewis, J. R., Utesch, B. S., & Maher, D. E. (2013). UMUX-LITE: When there's no time for the SUS. *Proc. CHI 2013*, 2099–2102. https://doi.org/10.1145/2470654.2481287
33. Lewis, J. R., Utesch, B. S., & Maher, D. E. (2015). Measuring perceived usability: The SUS, UMUX-LITE, and AltUsability. *International Journal of Human–Computer Interaction, 31*(8), 496–505. https://doi.org/10.1080/10447318.2015.1064654
34. Sauro, J. (2017, 11 Oct). Measuring usability: From the SUS to the UMUX-Lite. MeasuringU. https://measuringu.com/umux-lite/
35. Reichheld, F. F. (2003, Dec). The one number you need to grow. *Harvard Business Review*. https://hbr.org/2003/12/the-one-number-you-need-to-grow
36. Keiningham, T. L., Cooil, B., Andreassen, T. W., & Aksoy, L. (2007). A longitudinal examination of net promoter and firm revenue growth. *Journal of Marketing, 71*(3), 39–51. https://doi.org/10.1509/jmkg.71.3.039
37. Gao, M., Kortum, P., & Oswald, F. L. (2020). Multi-language toolkit for the System Usability Scale. *International Journal of Human–Computer Interaction, 36*(20), 1883–1901. https://doi.org/10.1080/10447318.2020.1801173
38. Blažica, B., & Lewis, J. R. (2015). A Slovene translation of the System Usability Scale: The SUS-SI. *International Journal of Human–Computer Interaction, 31*(2), 112–117. https://doi.org/10.1080/10447318.2014.986634
39. Beaton, D. E., Bombardier, C., Guillemin, F., & Ferraz, M. B. (2000). Guidelines for the process of cross-cultural adaptation of self-report measures. *Spine, 25*(24), 3186–3191. https://doi.org/10.1097/00007632-200012150-00014
40. Rodden, K., Hutchinson, H., & Fu, X. (2010). Measuring the user experience on a large scale: User-centered metrics for web applications. *Proc. CHI 2010*, 2395–2398. https://doi.org/10.1145/1753326.1753687
41. Agresti, A., & Coull, B. A. (1998). Approximate is better than "exact" for interval estimation of binomial proportions. *The American Statistician, 52*(2), 119–126. https://doi.org/10.1080/00031305.1998.10480550
42. Sauro, J., & Lewis, J. R. (2010). Average task times in usability tests: What to report? *Proc. CHI 2010*, 2347–2350. https://doi.org/10.1145/1753326.1753679
43. Card, S. K., Moran, T. P., & Newell, A. (1980). The keystroke-level model for user performance time with interactive systems. *Communications of the ACM, 23*(7), 396–410. https://doi.org/10.1145/358886.358895
44. Card, S. K., Moran, T. P., & Newell, A. (1983). *The Psychology of Human-Computer Interaction*. Lawrence Erlbaum (reprinted CRC Press, 2018). https://doi.org/10.1201/9780203736166
45. Holleis, P., Otto, F., Hussmann, H., & Schmidt, A. (2007). Keystroke-level model for advanced mobile phone interaction. *Proc. CHI 2007*, 1505–1514. https://doi.org/10.1145/1240624.1240851 (operator table read from the full text).
46. El Batran, K., & Dunlop, M. D. (2014). Enhancing KLM (keystroke-level model) to fit touch screen mobile devices. *Proc. MobileHCI 2014*, 283–286. https://doi.org/10.1145/2628363.2628385
47. Rice, A. D., & Lartigue, J. W. (2014). Touch-level model (TLM): Evolving KLM-GOMS for touchscreen and mobile devices. *Proc. ACM Southeast Regional Conference 2014*, 1–6. https://doi.org/10.1145/2638404.2638532 (operator values not retrieved).
48. Palin, K., Feit, A. M., Kim, S., Kristensson, P. O., & Oulasvirta, A. (2019). How do people type on mobile devices? Observations from a study with 37,000 volunteers. *Proc. MobileHCI 2019*, 1–12. https://doi.org/10.1145/3338286.3340120
49. Nielsen, J. (1993; updated 2014). Response times: The 3 important limits. Nielsen Norman Group (excerpt from *Usability Engineering*, ch. 5). https://www.nngroup.com/articles/response-times-3-important-limits/
50. Google. (2020, updated 10 Jun). Measure performance with the RAIL model. web.dev. https://web.dev/articles/rail
51. Google. (updated 31 Oct 2024). Web Vitals. web.dev. https://web.dev/articles/vitals
52. Google. (updated 2 Sep 2025). Interaction to Next Paint (INP). web.dev. https://web.dev/articles/inp
53. Android Developers. App startup time (Android vitals). https://developer.android.com/google/play/vitals/launch-time
54. Android Developers. Android vitals. https://developer.android.com/topic/performance/vitals
55. Sauro, J. (2011, 21 Mar). What is a good task-completion rate? MeasuringU. https://measuringu.com/task-completion/
56. Müller, H., & Sedley, A. (2014). HaTS: Large-scale in-product measurement of user attitudes & experiences with happiness tracking surveys. *Proc. OzCHI 2014*, 308–315. https://doi.org/10.1145/2686612.2686656
57. Bolger, N., Davis, A., & Rafaeli, E. (2003). Diary methods: Capturing life as it is lived. *Annual Review of Psychology, 54*, 579–616. https://doi.org/10.1146/annurev.psych.54.101601.145030
58. Carter, S., & Mankoff, J. (2005). When participants do the capturing: The role of media in diary studies. *Proc. CHI 2005*, 899–908. https://doi.org/10.1145/1054972.1055098
59. Mackay, W. E., & Fayard, A.-L. (1997). HCI, natural science and design: A framework for triangulation across disciplines. *Proc. DIS '97*, 223–234. https://doi.org/10.1145/263552.263612
60. Nielsen, J. (1994, 1 Nov). Severity ratings for usability problems. Nielsen Norman Group. https://www.nngroup.com/articles/how-to-rate-the-severity-of-usability-problems/ (the brief cited this as 1995; the NN/g page is dated 1994).
61. Sauro, J. (2013, 30 Jul). Rating the severity of usability problems. MeasuringU. https://measuringu.com/rating-severity/
62. Kohavi, R., Henne, R. M., & Sommerfield, D. (2007). Practical guide to controlled experiments on the web: Listen to your customers not to the HiPPO. *Proc. KDD 2007*, 959–967. https://doi.org/10.1145/1281192.1281295 (sample-size formula read from the authors' copy).
63. Kohavi, R., Longbotham, R., Sommerfield, D., & Henne, R. M. (2009). Controlled experiments on the web: Survey and practical guide. *Data Mining and Knowledge Discovery, 18*(1), 140–181. https://doi.org/10.1007/s10618-008-0114-1
64. Johari, R., Koomen, P., Pekelis, L., & Walsh, D. (2017). Peeking at A/B tests: Why it matters, and what to do about it. *Proc. KDD 2017*, 1517–1525. https://doi.org/10.1145/3097983.3097992
