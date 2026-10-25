# 07 — Usability test kit for Play testers

*Programme chapter 7. 25 Oct 2026. For moderated sessions with Sales X-Ray's Play testers,
in person or over WhatsApp video, on the **v0.89** app (Leads with Now, All leads and More,
the Leads settings gear, Tasks with Overdue / Today / Upcoming, Notes, and Remind on the lead
sheet). Five tasks in English, Hindi and Marathi, the think-aloud prompts, the forms and a
score sheet. Method and evidence: chapter 3.*

**All Hindi and Marathi text is a draft, to be checked by a native speaker before the first
session** (chapter 3 §4.6). Product words stay as sellers say them: लीड, कॉल, WhatsApp, टास्क.

| File | Use it for |
|---|---|
| `07-usability-test-kit.md` (this file) | Setup, the session script, the five tasks, what to watch, scoring and reporting |
| `07a-questionnaires.md` | SEQ card, UMUX-Lite and the all-positive SUS in English, Hindi and Marathi, with scoring |
| `07b-whatsapp-video-guide.md` | One page for the moderator (Dipak): running a session on WhatsApp video |
| `07c-score-sheet.csv` | One row per task per participant; open in Sheets or Excel |

---

## 1. Who, how many, how often

- **Five to eight testers a round**, at least three who mostly work in Hindi or Marathi, and a
  mix of phone makers (chapter 3 §1.3: five to eight find most problems in a round; rounds
  repeat).
- **Moderator:** an Indian team member who speaks the tester's language and did not design the
  screens (Dipak). Testers praise the person who made the thing; a neutral moderator gets the
  truth (chapter 3 §2.3).
- **One session = 30–35 minutes.** Monthly, or after a release that changes these journeys.
- **No managers or employers present, and results never reported by name.**

## 2. Setup before the round

1. **Test lead details** (fictional): name **Priya Sample**, company **Sunrise Rooftops**,
   phone number: **AC's own test SIM**. Never a real customer's number.
2. **Workspace:** testers use their own app on the latest Play version.
   - Personal workspace (most testers): Task 1 uses variant A (they add the lead you send).
   - A team workspace with lead assignment: Task 1 uses variant B (they switch on taking new
     leads). AC creates a fictional test organisation for this only through an approved data
     change; ask the orchestrator.
3. **Test SIM phone** with you, to answer as "Priya" in person (remote sessions don't place
   the call; see Task 2).
4. **The score sheet** (`07c-score-sheet.csv`) and the forms (`07a`) ready.
5. **Consent** sent the day before (the message is in `07b`).
6. **Pre-test onboarding: the tester videos** (66 videos in English, Hindi and Marathi, on
   AC's Drive: https://drive.google.com/drive/folders/1x51YeyTnpMkbTuKlUQbMYuPIOvldevBi).
   Before the session send only the getting-started ones: joining the testers, installing
   from Play, signing in in the app, and "if something hangs". **Don't send the videos that
   show the tasks** (calling and logging a result, notes, tasks and reminders) until after
   the session: a tester who has just watched how to do a task tests the video, not the app.
7. **Check the app version** is the v0.89 build from Play (Profile or the Play listing) and
   that the tester is signed in to the workspace you planned for Task 1.

## 3. Session script (about 30 minutes)

| Minute | Step | Say (EN / HI / MR) |
|---|---|---|
| 0–3 | **Consent** to record the screen and voice | EN: "May we record your screen and voice for this session? You can say no or stop at any time." · HI: "क्या आप इस सेशन की स्क्रीन और आवाज़ रिकॉर्ड करने की अनुमति देते हैं? आप कभी भी मना कर सकते हैं या रोक सकते हैं।" · MR: "या सेशनची स्क्रीन आणि आवाज रेकॉर्ड करायला तुमची परवानगी आहे का? तुम्ही कधीही नकार देऊ शकता किंवा थांबवू शकता." |
| 3–6 | **Not testing you; think aloud**; practice on the phone's calculator (add 128 and 64) | EN: "Today we are testing the app, not you. No answer is wrong. While you work, keep saying what you are thinking, in Hindi, Marathi or English. If something is confusing, say so; that helps us most. I didn't design this app, so don't worry about my feelings." · HI: "आज हम ऐप को टेस्ट कर रहे हैं, आपको नहीं। कोई जवाब गलत नहीं है। काम करते समय जो सोच रहे हैं, बोलते रहिए — हिंदी, मराठी या इंग्लिश में। कुछ समझ न आए तो वही बताइए; वही हमारे लिए सबसे काम का है। यह ऐप मैंने नहीं बनाया, इसलिए खुलकर बताइए।" · MR: "आज आम्ही ॲप तपासतोय, तुम्हाला नाही. कोणतंही उत्तर चूक नाही. काम करताना मनात जे येईल ते बोलत राहा — मराठी, हिंदी किंवा इंग्रजीत. काही समजलं नाही तर तेच सांगा; तेच आमच्यासाठी सर्वात उपयोगी आहे. हे ॲप मी बनवलेलं नाही, त्यामुळे मोकळेपणाने सांगा." |
| 6–24 | **Tasks 1–5** (§4); after each, the ease question (SEQ, `07a`) | — |
| 24–30 | **UMUX-Lite, then the SUS** (`07a`), then one open question | EN: "What would you change first?" · HI: "आप सबसे पहले क्या बदलना चाहेंगे?" · MR: "तुम्ही सगळ्यात आधी काय बदलाल?" |
| 30 | **Thanks** | — |

**While they work** (say nothing else):
- When quiet for about 5 seconds: EN "What are you thinking now?" · HI "आप अभी क्या सोच रहे
  हैं?" · MR "आत्ता तुम्ही काय विचार करताय?"
- To keep them going: EN "Keep talking." · HI "बोलते रहिए।" · MR "बोलत राहा."
- Acknowledge only with "hmm" (HI "हम्म", MR "हं"). Never say "good", "right", "सही", "बरोबर".
- **Only after a task ends**, if they made a mistake: EN "When you tapped that, what did you
  expect to happen?" · HI "जब आपने उस पर टैप किया, तब आपको क्या होने की उम्मीद थी?" · MR
  "तुम्ही त्यावर टॅप केलं तेव्हा काय होईल असं तुम्हाला वाटलं होतं?"
- Don't help. If they give up or reach the time cap, the task fails; then help only enough to
  set up the next task.

## 4. The five tasks

Read each task aloud and also send it as a message. Start the timer when they say they are
ready; stop it when they say they are done or reach the cap. Time caps: 3 minutes a task.

### Task 1 — Take a lead (≈ 20 s for a practised seller)

- **Variant A, personal workspace.** First send the lead details by WhatsApp: "Priya Sample,
  Sunrise Rooftops, <test SIM number>".
  - EN: "Your colleague just sent you a new enquiry on WhatsApp. Put this lead into Sales
    X-Ray so you can work on it."
  - HI: "आपके साथी ने अभी WhatsApp पर एक नई पूछताछ भेजी है। इस लीड को Sales X-Ray में डालिए
    ताकि आप उस पर काम कर सकें।"
  - MR: "तुमच्या सहकाऱ्याने आत्ताच WhatsApp वर एक नवीन चौकशी पाठवली आहे. या लीडवर काम करता
    यावं म्हणून ती Sales X-Ray मध्ये टाका."
  - **Done when:** a lead named Priya Sample with the right number is saved and open.
- **Variant B, team workspace** (taking new leads is switched off; two fictional leads wait).
  - EN: "Your manager says new enquiries are coming in. Make sure the app gives you new leads,
    then open the newest lead you received."
  - HI: "आपके मैनेजर ने बताया है कि नई पूछताछ आ रही है। ऐसा कीजिए कि ऐप आपको नई लीड्स देने लगे,
    फिर सबसे नई आई लीड खोलिए।"
  - MR: "तुमच्या मॅनेजरने सांगितलं आहे की नवीन चौकशी येत आहे. ॲप तुम्हाला नवीन लीड्स देईल असं
    करा, आणि मग सर्वात नवीन आलेली लीड उघडा."
  - **Done when:** taking new leads is on and the newest lead is open.
- **Watch:** where they look first (Home, Leads, "+"); in Leads, whether they start on Now or
  go to All leads, and whether they open More; Add lead or the quick-add line; for variant B,
  whether they find the "Taking leads" switch in the Leads header or look in the gear (Leads
  settings), and whether they understand what "taking new leads" means; typing the number;
  the "already a lead" warning.

### Task 2 — Call the lead from the app (≈ 15 s)

- EN: "Call Priya Sample from the app. The number is ours; I'll answer as the customer."
- HI: "ऐप से प्रिया सैंपल को कॉल कीजिए। नंबर हमारा है; ग्राहक बनकर मैं फ़ोन उठाऊँगा/उठाऊँगी।"
- MR: "ॲपमधून प्रिया सॅम्पल यांना कॉल करा. नंबर आमचा आहे; ग्राहक म्हणून मी फोन उचलेन."
- **On WhatsApp video** a phone call takes over the tester's phone, so add:
  - EN: "Tap Call; when the dialler shows the number, end the call and come back to this video
    call."
  - HI: "Call पर टैप कीजिए; जब डायलर में नंबर दिखे, तो कॉल काट दीजिए और इस वीडियो कॉल पर वापस
    आइए।"
  - MR: "Call वर टॅप करा; डायलरमध्ये नंबर दिसला की कॉल कट करा आणि या व्हिडिओ कॉलवर परत या."
- **In person:** answer on the test SIM as Priya for 60–90 s: interested in a 3 kW rooftop
  system, her roof is shared with a neighbour, call back tomorrow.
- **Done when:** the dialler opens from inside the app with Priya's number (and, in person,
  the call connects).
- **Watch:** the route to the lead (Now and Start calling, All leads, search, or the lead
  sheet); Call on the lead sheet vs a one-tap Call on a card vs tapping the number; the "Call
  from Sales X-Ray" hint; the SIM chooser; any permission prompt (write down the exact
  answer: allowed, denied, closed); whether the app comes back after the call.

### Task 3 — Log the call's result (≈ 16 s)

- EN: "The call is over. Record how it went: you spoke to Priya, she is interested and wants a
  call back tomorrow, and her roof is shared with a neighbour."
- HI: "कॉल खत्म हो गई। ऐप में दर्ज कीजिए कि कॉल कैसी रही: आपकी प्रिया से बात हुई, वे इच्छुक हैं,
  कल दोबारा कॉल चाहती हैं, और उनकी छत पड़ोसी के साथ साझा है।"
- MR: "कॉल संपला. ॲपमध्ये कॉल कसा झाला ते नोंदवा: तुमचं प्रियाशी बोलणं झालं, त्या इच्छुक आहेत,
  त्यांना उद्या पुन्हा कॉल हवा आहे, आणि त्यांचं छत शेजाऱ्यांसोबत शेअर्ड आहे."
- **Done when:** the result is saved as "we talked" with interest and a call tomorrow, and the
  roof remark is saved on the lead (in the result's note or as a note). Any language or script.
- **Watch:** does "How did it go?" appear by itself; Save refused for something missing (count
  how often); typing vs tapping; keyboard covering Save; "not sent yet".

### Task 4 — Add a task (≈ 25 s, custom time)

- EN: "Make sure you are reminded to send Priya a quotation on Monday at 11 a.m."
- HI: "ऐसा कीजिए कि सोमवार सुबह 11 बजे आपको प्रिया को कोटेशन भेजने की याद दिलाई जाए।"
- MR: "सोमवारी सकाळी 11 वाजता प्रियाला कोटेशन पाठवायची आठवण तुम्हाला मिळेल असं करा."
- **Done when:** a task or reminder on Priya's lead is set for Monday at 11:00 (±15 min).
  Check it together afterwards in Leads → More → Tasks, under Upcoming.
- **Watch:** whether they use Remind on the lead sheet or go to Tasks first; whether a preset
  fits or they need a custom day and time; AM/PM and day mistakes; whether they expect a phone
  notification and whether notifications are on.

### Task 5 — Find a note (≈ 30 s, assumed)

First say "Go to Home" (HI "होम पर जाइए", MR "होमवर जा") and wait until they are there.
- EN: "A colleague asks: what did Priya say about her roof? Find the answer in the app."
- HI: "आपका साथी पूछता है: प्रिया ने अपनी छत के बारे में क्या बताया था? ऐप में जवाब ढूँढिए।"
- MR: "तुमचा सहकारी विचारतो: प्रियाने तिच्या छताबद्दल काय सांगितलं होतं? ॲपमध्ये उत्तर शोधा."
- **Done when:** they read out the roof remark from the app.
- **Watch:** the route they take: search, Leads → More → Notes, or opening the lead and
  reading its notes or History; whether they scroll past it; whether a note saved inside the
  call result is where they expect notes to be.

## 5. Scoring

For every task fill one row of `07c-score-sheet.csv` (copy the six P01 rows per tester; the
`end_questionnaires` row holds UMUX-Lite and SUS answers and their scores, `07a`; delete the
two P00 example rows):

| Column | How |
|---|---|
| `result` | `pass`, `pass_with_help` (a hint was needed; counts as a fail in the numbers) or `fail` |
| `seconds` | from "ready" to done, or the cap (180) |
| `wrong_taps` | taps that went somewhere they didn't mean to |
| `save_refused` | times Save or Continue refused them |
| `seq` | the ease answer, 1–7 |
| `permission` | any Android prompt and its answer (`allowed`, `denied`, `closed`, `none`) |
| `quote` | one short thing they said, in their words (no names or numbers) |
| `problem` | the problem you saw, in one line |
| `severity` | 1 cosmetic · 2 slows them · 3 they fail without help · 4 data lost or wrong |

**Per round, report:**
- completion per task with its range (chapter 3 §6.1: with 5–8 people, read it as a range,
  not a percentage);
- median time of the successful attempts;
- median SEQ;
- UMUX-Lite and SUS per language (`07a`; never compare Hindi or Marathi scores with English
  norms);
- the top three problems with severity, each with the friction-report measure that should move
  when it is fixed (chapter 4 and chapter 6).

**Targets for these tasks** (chapter 3 §7, assumed until measured): completion ≥ 85–92%; SEQ
≥ 5.8; median times about 20 s (Task 1), 15 s (Task 2), 16 s (Task 3), 25 s (Task 4), 30 s
(Task 5) for novices.

## 6. Privacy and data

- Use participant codes (P01, P02…) everywhere. Names and numbers stay in the tester list, not
  in notes, sheets or this repository.
- Recordings: only with a "yes" to the consent question; kept in AC's restricted research
  folder for 90 days, then deleted (log the deletion). Never shared with an employer.
- No real customer data in any task: the lead is fictional and the number is AC's test SIM.
- Findings go to the research folder and the friction log as codes and quotes only.
