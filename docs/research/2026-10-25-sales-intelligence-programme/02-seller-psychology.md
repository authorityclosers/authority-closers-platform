# 02 — The psychology of sellers: habits, motivation, targets, nudges, gamification and cognitive load

*Sales Intelligence Research Programme, chapter 2 of the series. Written 25 October 2026.*

**Scope.** This chapter covers what the research says about how inside-sales sellers form work habits, what motivates them, how targets and quotas change behaviour, when nudges and notifications help or hurt, which kinds of gamification work, how much a phone screen can ask of a busy mind, and how Indian multilingual users read and type. It ends with a behaviour model for Sales X-Ray, design principles, anti-patterns and 15 ranked recommendations. Those cover daily targets, drift nudges and their sound and frequency caps, leaderboards, streaks, how coaching reports are framed, and notification tiers.

**Evidence legend.** Key claims carry a strength tag:
**MA** = meta-analysis or systematic review · **RCT** = randomised experiment (lab or field) · **FE** = field or quasi-experiment in a real workplace or market · **OBS** = observational or field study · **LAB** = lab study, not randomised to real work · **TH** = theory or narrative review · **PR** = practitioner, industry or platform documentation · **BK** = book.
Citations are numbered [n]. The full list, with DOIs or URLs, is at the end. "AC proposal" marks a design number or rule that is our own inference from the evidence, not a research finding. Each one needs testing.

**Verification note.** Every reference was checked online on 25 Oct 2026, against DOI metadata (Crossref), the publisher's page or the primary document. Partway through, the shared web-search budget for this session ran out. Sources that could not then be checked are left out or flagged in "Sources not verified" at the end. Reddit is blocked for these research tools, so this chapter contains no first-hand community evidence (for example, sellers' own posts about tracking apps, leaderboards or CRM nagging). Section 8.6 says where that evidence would have mattered.

---

## Key findings at a glance

1. **Habits come from stable cues, not from push reminders.** Habits are context→response links built by repetition [4][5]. In a randomised study, app reminders increased repetition but slowed automaticity, while event-based cues sped it up [11]. Building habit takes weeks to months, about 66 days on average in one field study [3][7]. For Sales X-Ray, the end of each call is the cue to design around.
2. **Tangible, controlling rewards erode intrinsic motivation. Informational feedback strengthens it.** Expected tangible rewards undermined free-choice motivation (d ≈ −0.28 to −0.40), while positive feedback raised it (d ≈ +0.33) [21] (MA). Incentives drive quantity, and intrinsic motivation drives quality [22] (MA).
3. **Feedback is not automatically good.** It helps on average (d = 0.41), but more than a third of feedback interventions made performance worse, mostly when the feedback pulled attention towards the self and away from the task [23] (MA). Frequent coaching from unskilled coaches hurt sales goal attainment [26] (OBS, 1,246 reps).
4. **Targets work, and they also cause gaming.** Specific, hard goals raise effort [34]. Daily income targets make people stop once the target is hit [44] (OBS). Nonlinear sales targets shift deals and cut prices, costing one vendor 6–8% of revenue [48] (OBS). Unmet goals increase cheating, most of all near the line [50] (LAB).
5. **Notifications have real costs, and caps matter.** A notification alone disrupts attention about as much as a call or text [63] (LAB). Batching to three times a day improved well-being and attention [65] (RCT). In a clinical alert system, each extra reminder in the same visit cut acceptance by about 30% [73] (OBS).
6. **Monitoring does not raise performance, and it does raise stress, unless it is transparent, developmental and light.** A meta-analysis of 94 samples found no evidence that electronic monitoring improves performance, and found it associated with more stress [81] (MA). In call centres, monitoring with a developmental purpose and clear criteria went with better well-being, while monitoring *intensity* went with worse [83] (OBS).
7. **Leaderboards are double-edged.** Removing rank feedback raised furniture sales by about 11% [100] (RCT, working paper). Social comparison cut performance among low performers [99] (FE). Recognising the top few lifted everyone, including the people not recognised [103] (FE). Games imposed without consent backfired [93] (FE, working paper).
8. **People remember little of a call minutes later.** About 10% of a conversation's idea units were recalled after five minutes [118][119] (LAB). The other person's words are remembered worst [120]. Logging must happen within seconds and must not depend on typing.

---

## 1. Habit formation

### 1.1 What a habit is

Psychologists define a habit as an automatic response triggered by a context: a place, a time, a preceding action. The response has been repeated in that context until it no longer needs a conscious decision [4][5] (TH). Goals start the repetition. Once the habit forms, the context triggers the action directly, and the action becomes fairly insensitive to changes in the reward that originally drove it [5]. Wood's book gives an accessible summary of this research [16] (BK). In diary studies, about 43% of the everyday behaviours people reported were done almost daily in the same setting, often while thinking about something else [6] (OBS).

This matters for Sales X-Ray. A seller who has made the habit "call ends → log the result → tap the next lead" will keep doing it on a bad day. A seller who logs only when reminded will stop when reminders stop or get annoying.

### 1.2 The Fogg Behavior Model (B = MAP)

Fogg proposed that a behaviour happens when **m**otivation, **a**bility and a **p**rompt ("trigger" in the 2009 paper) come together at the same moment [1] (TH). If ability is low, a task feels hard, and only high motivation gets it done. If ability is high, a task feels easy, and even low motivation is enough. In his book *Tiny Habits*, Fogg turns this into a method. Anchor a tiny behaviour to an existing routine ("after I…, I will…"), then celebrate straight away [2] (BK). The model is a useful design vocabulary. It is a framework, not a tested causal theory. We found no meta-analysis that tests B = MAP as a whole.

**Design reading:** at 100+ calls a day, motivation dips. The reliable lever is **ability**: make the next step take one tap. The best **prompt** is the context the seller is already in, which is the end of a call.

### 1.3 How long habits take

In the best-known real-world study, 96 people repeated a chosen daily health behaviour for 84 days, and 82 provided usable data. Automaticity rose along a curve that flattened over time. Reaching the plateau took about 66 days on average. Individual estimates ran from 18 days to a forecast 254 days [3] (OBS). The abstract also reports that missing a single opportunity did not materially harm habit formation [3]. That point comes from the abstract; the full text was not re-read this session. A 2023 machine-learning study of more than 30,000 gym-goers over four years and more than 3,000 hospital workers found that handwashing habits formed in weeks and gym habits in months. The best predictors were context variables such as time and day [7] (OBS). The popular "21 days" figure has no scientific basis [3][7]. The practical advice drawn from this work is to repeat one simple action in the same context, every time that context comes up [13] (TH).

**Design reading:** onboarding should expect a 2–3 month habit curve, not a one-week activation. One missed day should not be treated as failure (see streaks, §5.4).

### 1.4 Cue–routine–reward, Hooked, and the critiques

Duhigg popularised the cue → routine → reward loop [8] (BK). Eyal's *Hooked* model adds two things to the loop. Rewards should be **variable**, and users should make an **investment**, such as data or content, that loads the next trigger [9] (BK). Variable rewards come from operant conditioning. The deliberate use of unpredictable rewards to sustain engagement is exactly what Schüll documented in her ethnography of machine-gambling design [14] (BK). The HCI literature lists repeated prompting after refusal ("nagging") among dark patterns [15] (TH).

The key empirical critique comes from habit-app research. A 4-week study, together with a review of 115 habit apps, found that reminders helped people repeat a behaviour but **hindered** the development of automaticity. Event-based cues increased automaticity, and positive reinforcement had no measurable effect [11] (RCT). A follow-up qualitative study of a popular habit app found that reminders and streaks made users dependent on the app. When people stopped using it, the behaviour often stopped too [12] (OBS). We searched for a peer-reviewed empirical test of the Hooked model and found none. Its claims should be treated as practitioner heuristics.

### 1.5 What makes a daily work app a habit rather than a chore

Smartphone "checking habits" are brief, repeated looks, usually under 30 seconds, at quickly accessible information. They are triggered by particular contexts and kept going by informational rewards [10] (OBS). Users described them more as a nuisance than an addiction [10]. A work app becomes a habit when its core action:

- **is tied to a stable cue the seller already has** (a call ending, the shift starting, a lead arriving), not to a push [4][5][11];
- **is short and cheap** (high ability) [1];
- **returns useful information at once**: the lead moved, the follow-up was set, progress ticked up [10];
- **builds a record the seller values**, the "investment" [9], without loss-framed pressure to keep it up [15].

It becomes a chore when the seller does the work twice (call, then retype), when the app interrupts the work, or when the main beneficiary of logging is someone else, namely surveillance (§4.6).

### 1.6 A replication caution

Many popular "willpower" claims rest on ego depletion, the idea that self-control is a resource that runs down. A 23-lab preregistered replication (N = 2,141) found an effect of d = 0.04, with a 95% CI from −0.07 to 0.15 [17] (RCT). Do not build features on the assumption that sellers "run out of willpower by 4 pm". Late-day slumps may be real, but the explanation should come from our own data, not from this theory.

---

## 2. Motivation

### 2.1 Self-Determination Theory (SDT)

SDT holds that people do better, with more persistence, quality and well-being, when three psychological needs are met: **autonomy** (acting by choice), **competence** (feeling effective) and **relatedness** (feeling connected) [18] (TH). Motivation runs along a continuum from external control to internalised and intrinsic forms [18][19]. A meta-analytic review of 99 workplace studies (119 samples) found that satisfying each need independently predicted well-being and growth at work [20] (MA). Video-game enjoyment is likewise explained by need satisfaction, not by points [106] (OBS/LAB).

### 2.2 Intrinsic versus extrinsic motivation, and crowding-out

A meta-analysis of 128 experiments found that **expected tangible rewards** reduced later free-choice intrinsic motivation. The effect was d = −0.40 for engagement-contingent rewards, −0.36 for completion-contingent and −0.28 for performance-contingent. **Positive verbal feedback** increased it, d = +0.33 for free choice and +0.31 for self-reported interest [21] (MA). A 40-year meta-analysis (183 studies, N = 212,468) gives a more nuanced picture. Intrinsic motivation predicted performance (ρ = .21–.45), more for **quality**, while incentives better predicted **quantity**. The two were not necessarily in conflict, but intrinsic motivation mattered less when incentives were tied directly to performance [22] (MA).

**Design reading:** sellers already have pay and incentives, which the app does not control. The app should not add another layer of controlling rewards on top. Instead it should supply **informational** feedback ("you set 9 follow-ups today and 6 picked up") that supports competence and quality.

### 2.3 Feedback intervention theory

Kluger and DeNisi pooled 607 effect sizes (23,663 observations). On average, feedback interventions improved performance (d = 0.41), **but more than one-third made it worse**. The moderator was where the feedback drew attention: towards the task (helpful) or towards the self, such as ego, ranking or praise of the person (less helpful or harmful) [23] (MA). Hattie and Timperley's review makes the same point. Feedback about the task, the process and self-regulation works. Feedback about the self ("you're a star") does little [24] (TH/MA synthesis). Expertise also changes what people want. Novices sought and responded to positive feedback, which kept them committed. Experts sought negative feedback, which told them where progress was still insufficient [25] (LAB/OBS).

### 2.4 Coaching evidence in sales

In a pharmaceutical sales force (1,246 reps in 136 teams, followed for a year), managers' **coaching skill**, measured in an assessment exercise, predicted their reps' sales goal attainment. Clearer roles partly explained the link. **Coaching frequency hurt goal attainment when the coach was unskilled** [26] (OBS, predictive design). A meta-analysis of workplace coaching by professional coaches (k = 17) found an overall effect on organisational outcomes of δ = 0.36. Effects did not differ between face-to-face, blended and e-coaching [27] (MA, small k).

**Design reading:** AI coaching in Sales X-Ray is a coach whose "skill" depends on how accurate and relevant its advice is. Frequent but generic or wrong advice may do harm [26]. Quality and focus matter more than volume.

### 2.5 Mindset and "positivity" claims: cautions

Dweck's growth-mindset idea is that people do better if they see ability as improvable [28] (BK); its authors updated the framework in 2019 [29] (TH). The evidence for mindset *interventions* is weak and disputed. Sisk et al. found an average intervention effect of d = 0.08 [30] (MA). In 2023, two meta-analyses in the same journal reached opposite conclusions. One found that apparent effects fade in higher-quality, unconflicted studies [31] (MA). The other found that effects vary by subgroup and context [32] (MA). Separately, the popular "3:1 positivity ratio" for praise versus criticism was mathematically discredited [33]. **Use growth-oriented language because it is respectful and accurate ("not yet", "next call, try…"), not because it will lift performance on its own.**

---

## 3. Goals, targets and quotas

### 3.1 Goal-setting theory

Thirty-five years of research summarised by Locke and Latham show that **specific, difficult goals** lead to higher performance than vague "do your best" goals. Commitment, feedback, ability and task complexity moderate the effect, and for complex or new tasks, learning goals can beat outcome goals [34] (TH/MA synthesis). The 2019 retrospective restates the core findings and their limits [35] (TH). Goals act as **reference points**. Falling short of a goal feels like a loss, so effort rises as people near it [41] (LAB).

### 3.2 The goal gradient and how progress is perceived

Hull's rats ran faster as they neared the food [36]. In a café loyalty programme, customers bought coffee more often as they approached a free drink. Customers given a 12-stamp card with 2 stamps already filled completed faster than customers with a blank 10-stamp card [37] (FE). Artificially "endowed" progress raises completion in the same way [38] (FE). How progress is shown also matters. Early in a goal, pointing to **progress done** motivates more. Near the end, pointing to **what is left** motivates more. In both cases, the smaller number feels more motivating ("small-area hypothesis") [39] (FE/LAB). Motivation can also **dip in the middle**, when both start and finish feel far away [40] (LAB).

### 3.3 Sales-force quota and bonus evidence

- **Bonuses and sub-goals.** A structural analysis of an office-supply sales force found that bonuses raise productivity, and quarterly bonuses worked better than annual ones. The quarterly bonus acted as a sub-goal that kept especially the low performers on track. Overachievement commissions stopped people slowing down after reaching quota, and raising future quotas after a good year ("ratcheting") discouraged top performers from overshooting [42] (OBS, structural model).
- **Different groups, different levers.** Steenburgh and Ahearne argue that laggards, core performers and stars respond to different incentives. In one experiment, multi-tier targets gave core performers stepping stones to a higher level [43] (PR/FE, HBR).
- **Daily targets can cap effort.** New York cab drivers behaved as if they had a loose daily income target and stopped once it was reached. For less experienced drivers, the wage elasticity of hours was about −1 [44] (OBS). A daily target with no reward beyond the line invites stopping at the line.
- **Proximal goals build competence.** Short-range sub-goals produced faster progress, higher self-efficacy and more intrinsic interest than a distant goal alone [45] (RCT, children's maths).
- **Monitoring progress works, especially when recorded.** A meta-analysis of 138 randomised studies (N = 19,951) found that prompting people to monitor progress improved goal attainment (d = 0.40). The effect was larger when progress was **physically recorded** or **reported publicly** [46] (MA).

### 3.4 Daily versus weekly targets

The evidence supports a **weekly (or monthly) target as the real goal, with daily pacing as sub-goals** [42][45]. Daily numbers give the near-term focus and feedback that proximal goals need [45][46]. On their own, they risk the cab-driver effect of stopping at the line [44] and the frustration of a bad-luck day, since connect rates swing. Weekly targets make use of the "fresh start" a new week brings: people are more likely to start aspirational behaviour just after temporal landmarks such as a new week or month [53] (OBS, three field datasets).

### 3.5 End-of-period gaming, stretch goals and unethical behaviour

- **Timing games.** Under nonlinear pay, firms' revenues peak at fiscal year-end and dip at the start. Salespeople pull deals forward and cut prices to hit thresholds [47] (OBS). At one enterprise software vendor, salespeople accepted significantly lower prices in quarters when closing paid more. The mispricing cost 6–8% of revenue [48] (OBS, about 8,000 deals).
- **Rewarding A while hoping for B.** Organisations get the behaviour they measure, not the behaviour they say they want [49] (TH). A target on *dials* gets dials, including very short, pointless calls.
- **Cheating near the line.** In a lab experiment, people with unmet specific goals overstated their performance more than "do your best" participants, with or without money at stake, and most when they had **narrowly missed** [50] (LAB).
- **The debate.** Ordóñez and colleagues argued that goal setting is over-prescribed and lists side effects: narrowed focus, risk-taking, cheating, eroded intrinsic motivation [51] (TH). Locke and Latham replied that these harms come from badly designed goals, not from goals as such [52] (TH). Both sides agree that **what is measured, how hard it is and whether progress can be gamed** decide whether a goal helps.

---

## 4. Nudges and notifications

### 4.1 How strong are nudges, really?

Thaler and Sunstein define a nudge as a change in choice architecture that steers behaviour without forbidding options or materially changing incentives [54] (BK). A 2022 meta-analysis of more than 200 publications estimated a medium average effect (d ≈ 0.43), with defaults strongest [57] (MA). A reanalysis that corrected for publication bias found **no remaining evidence** of an average nudge effect, though effects vary widely [58] (MA reanalysis). Comparing 126 RCTs run by two government nudge units with published academic trials, the average effect was **1.4 percentage points in practice versus 8.7 in journals**. About 70% of the gap came from selective publication [59] (MA of RCTs). In a megastudy of 54 gym-attendance programmes (N = 61,293), about 45% of programmes increased visits by 9–27% during the four weeks they ran. **Only 8% left a significant effect after they ended.** The best performer was small rewards for **returning after a missed workout**. Experts could not predict which programmes would work [60] (RCT).

**Design reading:** expect small effects from any single nudge, test every one, and design for the **return after a lapse**, not for never lapsing.

### 4.2 Implementation intentions

"If situation X, then I will do Y" plans had a medium-to-large effect on goal attainment (d = 0.65 across 94 independent tests) [55][56] (MA). The plan hands control to a situational cue [55], which is the same mechanism as habit cues (§1). **Design reading:** after a call, "Next: call Priya at 4:30 — tap to set" is an implementation intention. "Remember to follow up!" is not.

### 4.3 The cost of a notification

- People in one 15-person, one-week study handled **63.5 notifications a day** on average and usually looked at them within minutes, even when the phone was silenced [61] (OBS).
- Across 10,372 notifications from 20 users, how disruptive a notification felt depended on the task the person was doing (its type, complexity and stage), on the sender and on how it was presented. **Useful content could still be disruptive** [62] (OBS).
- **Simply receiving a notification**, without touching the phone, harmed performance on an attention-demanding task by an amount comparable to taking a call or reading a text [63] (LAB).
- In a two-week within-person experiment with 221 students, having alerts on raised self-reported inattention and hyperactivity. Higher inattention predicted lower productivity and well-being [64] (RCT, students).
- Interrupted office workers finished tasks faster with no loss of quality, **at the cost of more stress, frustration, time pressure and effort** [68] (LAB). In the field, 57% of work segments were interrupted, and interrupted work was usually resumed only after more than two other activities [67] (OBS).

### 4.4 Timing, batching and breakpoints

Interruptions at **task boundaries** cost less than interruptions mid-task [69] (LAB). Deferring notifications to detected breakpoints reduced frustration and resumption cost [70] (LAB), and on smartphones it reduced users' perceived cognitive load compared with random-time delivery [71] (LAB/OBS). In a randomised field experiment (N = 237), **batching notifications three times a day** improved attention, productivity and well-being. Hourly batching did little, and turning notifications off completely increased anxiety and fear of missing out [65] (RCT). When 30 volunteers spent a day on Do Not Disturb, they felt more productive but also anxious about responsiveness [66] (OBS). Silence is not the goal. **Predictable, well-timed delivery** is.

**Sales X-Ray's natural breakpoint** is the moment just after the after-call sheet is saved. The worst moments are during a call and while the seller is logging.

### 4.5 Alarm fatigue, habituation, sound and haptics

Hospital alarm research is the clearest warning. Reviews link staff desensitisation to high false-alarm rates and to the sheer number of alarming devices [72] (MA/integrative review). In a primary-care decision-support system (112 clinicians), **each extra reminder in the same visit cut acceptance by about 30%**, and each 5-point rise in the share of repeated reminders cut it by about 10%. Repeated exposure over months did not, by itself, cause desensitisation [73] (OBS). Volume within a moment matters more than exposure over time. Brain-imaging and field studies show that people habituate to repeated warnings, and that **varying a warning's appearance ("polymorphic" warnings) slows habituation**. There is a trade-off with recognisability [74] (LAB/FE).

For sound, perceived urgency rises predictably with speed, pitch, repetition and irregular (inharmonic) content, and falls with slower, lower and simpler sounds [75][76] (LAB). For touch, vibration patterns ("tactons") can carry distinct meanings through rhythm, duration and intensity [77] (LAB). On Android, notification **channels** fix importance at creation: Urgent (sound and heads-up), High (sound), Medium (silent), Low (silent and not in the status bar). Users can change any channel later, and the app cannot raise its importance afterwards [78] (PR). If we spend user trust on loud channels, users will mute them and we cannot take that back.

### 4.6 Supportive or surveillant? Electronic performance monitoring

- A meta-analysis of 94 samples (N = 23,461) found **no evidence that electronic performance monitoring (EPM) improves performance**, and found it associated with **more stress** regardless of how monitoring was done. More transparent and less invasive monitoring went with better attitudes [81] (MA). The framework review behind it treats EPM as multidimensional: purpose, invasiveness, transparency and so on [80] (TH).
- A second meta-analysis (70 samples) found small negative effects on job satisfaction (r = −.10), more stress (r = .11), no link to performance (r = −.01) and a small rise in counter-productive behaviour (r = .09). **Performance targets and feedback attached to monitoring made these effects worse** [82] (MA).
- In UK call centres, monitoring with **clear criteria and quick feedback**, and monitoring seen as having a **developmental purpose**, went with better well-being. Perceived monitoring **intensity** had the strongest negative link [83] (OBS).
- Monitoring that is relevant to the job, and that workers had a say in, felt less invasive and fairer [84] (LAB). Earlier reviews reached the same conclusion [85] (TH).
- In a Chinese phone factory, giving production lines a modest amount of privacy from managers **improved** performance. Fully observed workers hid their best improvisations [86] (FE).
- Controlling, forceful language ("You must…") provoked resistance in health messaging [87] (LAB).
- Indian voice call centres were found to reproduce the tight monitoring of Western call centres in exaggerated form [88] (OBS, qualitative). Sellers in our market may already be sensitive to surveillance.

**What makes a "come back to work" nudge feel supportive?** Pulling these findings together, a supportive nudge:

- **goes to the seller first and privately**, not to the manager [81][83][86];
- **gives a useful next action** (who to call, why now), not a reprimand [23][83];
- **is light in intensity**: rare, quiet and capped [73][83];
- **respects the seller's own account** ("on a break", "in a meeting") [84][18];
- **uses autonomy-supportive words** [87][18];
- **is visible**, meaning the seller knows what is tracked and why [81][84].

Community evidence on how Indian sellers feel about specific CRM nudges would have come from Reddit and similar forums. Those were blocked for this research, so this needs AC's own interviews.

### 4.7 Quiet hours and recovery

"Workplace telepressure", the urge to respond to work messages at once, gets in the way of recovery after work and is linked to poorer outcomes [79] (OBS). Quiet hours are not a nice-to-have. They protect the recovery that next-day performance depends on.

---

## 5. Gamification that works and gamification that backfires

### 5.1 What reviews say

An early review found mostly positive effects of gamification, but effects depended heavily on context and on the users [89] (MA/review). A later review of 819 studies leaned positive but reported a "remarkable" share of mixed results and weak theory [90] (MA/review). In education, a meta-analysis found small effects: g = 0.49 on cognitive outcomes (k = 19), 0.36 on motivational (k = 16) and 0.25 on behavioural (k = 9). Only the cognitive effect held up in the most rigorous studies [92] (MA). An experiment that varied single game elements found that badges, leaderboards and performance graphs raised the sense of **competence** and **meaningfulness**, while avatars, stories and teammates raised **relatedness** [91] (RCT). Gamification is not one thing. Each element works through a specific need.

### 5.2 Consent and legitimacy: "mandatory fun"

In a field experiment with several hundred salespeople selling coupon deals to businesses, a basketball-style sales game **raised positive feelings among those who consented to it** and **lowered positive feelings and performance among those who did not**. A follow-up lab study found that legitimacy and a sense of agency produced consent [93] (FE, SSRN working paper, not peer-reviewed). Work-gamification theory frames these systems as a new delivery channel for performance feedback, so they carry all of feedback's risks [94] (TH).

### 5.3 Leaderboards and social comparison

People evaluate themselves by comparing with others, usually with similar others [95] (TH). The field evidence pulls in both directions:

| Finding | Evidence |
|---|---|
| Revealing relative standing at a piece-rate firm gave a large, lasting productivity rise | [101] (FE, quasi-experiment) |
| A leaderboard pushed people to perform as if given difficult or impossible goals | [96] (RCT) |
| **Removing** private rank feedback raised furniture sales by about 11%. People below their expected rank shifted effort elsewhere | [100] (RCT, 1,754 salespeople, working paper) |
| Social comparison **cut** performance, especially among low-ability trainees, while recognition and visibility raised it | [99] (FE) |
| Effort was U-shaped by rank: highest for first and last, lowest in the middle ranks | [102] (LAB) |
| Unannounced recognition of the top performers raised later performance, mainly through people who were **not** recognised. Recognising the top three worked best | [103] (FE) |
| Points, levels and leaderboards raised the *quantity* of work but not intrinsic motivation | [97] (RCT) |
| A gamified course (leaderboard and badges) had *lower* motivation, satisfaction and exam scores than an identical non-gamified course | [98] (FE, students) |

**Reading:** a public league table of everyone, ranked on volume, is the riskiest design. Recognising a few, comparing people with their own past, opt-in competition and team-versus-target framing carry less risk [99][100][103][93].

### 5.4 Streaks and loss aversion

Losses loom larger than equal gains [104] (TH/LAB). Streak counters exploit this. Across seven studies, an intact streak shown in a log made people more likely to repeat the behaviour, while a **broken** streak made them less likely to continue. The drop was smaller when the streak could be **repaired** [105] (RCT/LAB). Habit-app streaks also build dependence on the app [12]. One missed day did not derail real habit formation [3]. A strict daily streak therefore punishes the seller for something the science says does not matter. The best re-engagement tactic in the gym megastudy was rewarding the return after a miss [60].

### 5.5 Points versus mastery

Points work as extrinsic incentives for quantity [97]. Competence comes from performance graphs and meaningful feedback [91], and from need satisfaction more broadly [106][18]. For sellers, "mastery" means visible skill growth: objection handling, discovery questions, follow-up discipline.

### 5.6 Call-centre and sales gamification field evidence

Rigorous peer-reviewed field experiments on gamification in call centres or inside sales are **scarce**. Our search turned up mostly vendor case studies whose headline percentages come without methods, and we do not cite them. The closest strong evidence is the salesperson consent experiment [93], the furniture rank RCT [100], the sales-force bonus model [42] and the recognition experiments [99][103]. This is a real evidence gap. AC should treat any gamified feature as an experiment.

---

## 6. Cognitive load on phones

### 6.1 Working memory and Cognitive Load Theory

New information passes through a working memory with limited capacity and duration before it is stored long-term [107][108] (TH, extensive RCT base). Working memory holds about **four chunks** [109] (TH/MA synthesis). A seller just off a call is holding the lead's needs, the promised next step, the next lead's name and maybe a WhatsApp to send. That is already at capacity.

### 6.2 Choices, reach and touch

- **Hick–Hyman law:** decision time rises with the information in the choice set, roughly logarithmically with the number of equally likely options [110][111] (LAB). Fewer, clearly different outcome buttons are faster.
- **Fitts' law:** the time to hit a target rises with distance and falls with target size [112] (LAB).
- **Grip:** in 1,333 street observations (780 people touching the screen), 49% held the phone one-handed, 36% cradled it and 15% used two hands. Of the one-handed users, 67% used the right thumb [113] (PR/OBS).
- **Thumb reach** depends on screen size, hand size and grip, and can be modelled. Large phones leave the top corners out of comfortable reach [114] (LAB).
- **Target size:** for one-handed thumb use, 9.2 mm targets for discrete taps and 9.6 mm for serial taps did not hurt performance [115] (LAB). Android guidance recommends at least 48×48 dp (about 9 mm) with 8 dp spacing [116] (PR).

### 6.3 During and after the call

- **During:** a phone conversation doubled missed signals in a driving simulator, whether the phone was handheld or hands-free. Listening to the radio did not [117] (LAB). The conversation itself takes up attention. **Do not ask sellers to read or type while they talk.**
- **After:** five minutes after a 7-minute conversation, people recalled about **10%** of its idea units; the best of 128 participants recalled 40% [118][119] (LAB). After 3–4 days, people recalled 6% of their own statements and 3% of their partner's [120] (LAB). Across studies, detailed recall after minutes to weeks ranged from 0% to 20% [119] (review). Forgetting is steepest at the start [121] (LAB, replication). The next call adds interference.

**Design reading:** the result sheet must appear the moment the call ends and must take seconds. It should rely on taps and an optional voice note, not on typing. The customer's own words, which are recalled worst [120], are exactly what an AI transcript and summary can preserve.

### 6.4 Budget phones and perceived waiting

At 0.1 s a response feels instant. Up to 1 s it keeps the flow of thought but needs a sign of activity. Past 10 s attention is lost, and a progress indicator and a way to cancel are needed [122][123] (PR/LAB). The Model Human Processor work gives the cognitive basis for these thresholds [124] (BK/TH). Maister's principles of waiting say occupied, explained and finite waits feel shorter than empty, unexplained and uncertain ones [125] (TH/PR). On budget Android phones with slow storage, the after-call sheet should save locally and at once (optimistic UI), with sync in the background.

---

## 7. Indian multilingual usage

### 7.1 Indian-language internet

By the end of 2016, India had 234 million Indian-language internet users against 175 million English users. The Indian-language base was projected to reach 536 million by 2021, about 75% of all users. Marathi and Bengali users, alongside Hindi, were expected to drive that growth. In the same survey, 68% of users said they found local-language content more reliable than English, 70% of Indian-language users reported difficulty with English keyboards, 88% said they were more likely to respond to an ad in their own language, and chat apps were used by more than 90% [128] (PR, industry survey). IAMAI–Kantar's annual *Internet in India* reports are the standard source for current figures. We could not verify a current edition this session (see the end).

### 7.2 Code-mixing and Hinglish

In an annotated sample of Facebook posts, 17.2% of posts, holding nearly a quarter of all words, mixed English and Hindi. Hindi sentences contained English words far more often (23.7%) than the reverse (7.2%). Words ran along a continuum from clear borrowing ("call", "lead") to true mixing, and romanised spelling was non-standard [126] (OBS). Population-dynamics modelling describes Hinglish as a growing variety [127] (TH/model). **Design reading:** labels such as "Follow-up", "Call back" or "Lead" may be better understood as code-mixed loanwords than as formal Hindi or Marathi translations. Test both with sellers.

### 7.3 Romanised versus Devanagari input and reading

Romanised Hindi (and Marathi) typing is common on social media, with inconsistent spellings [126], and English keyboards are a stated barrier [128]. We found and verified **no** peer-reviewed study comparing reading speed or accuracy for romanised versus Devanagari text among working adults. This is an evidence gap. **AC proposal:** accept both scripts everywhere, make search transliteration-aware (typing "sharma" finds "शर्मा"), and let each seller choose the script they read in.

### 7.4 Voice-first behaviour, literacy and numeracy

For first-time low-literacy users, text interfaces were unusable and error-prone. Graphical interfaces gave the highest task completion in mobile banking, users familiar with speech finished faster with spoken dialogue, and a live operator was most accurate for health data [131] (RCT/OBS, India and three other countries). Text-free designs using icons, voice and video helped illiterate and semi-literate users [130] (LAB/FE). Basic skills vary widely in India. Among 34,745 rural 14–18-year-olds surveyed in 2023, about 25% could not fluently read a Std II text in their regional language, only 43.3% could do a 3-digit by 1-digit division, and 57.3% could read English sentences. Close to 90% had a smartphone at home and could use one [129] (OBS, large household survey). Inside-sales staff are usually older and more educated than this rural youth sample, so these figures mark the *floor* of variation, not the typical seller. **Design reading:** show counts ("4 to go") rather than percentages or ratios, and offer voice notes in any language.

### 7.5 Icons and labels across languages

In a lab study, text labels, alone or with icons, supported learning an application better than icons alone [132] (LAB). For novice and low-literacy users, the evidence favours **icon plus label**, with spoken help where possible [130][131]. Icon meanings are learned and culture-bound, so they need testing with real sellers.

### 7.6 Honorifics, politeness and Marathi

Politeness theory treats requests as threats to "face" that respectful wording softens [133] (BK/TH). Hindi grades the second person (आप / तुम / तू), and Marathi does too (आपण or तुम्ही for respect, तू for intimacy). In UI copy addressed to adult workers, the respectful forms (आप in Hindi, तुम्ही in Marathi) are the safe default. Imperatives should read as invitations ("अगला कॉल करें?") rather than orders, which also reduces reactance [87]. Marathi is a distinct language with its own vocabulary and idiom, even though it shares the Devanagari script with Hindi. Copy should be written or reviewed by native Marathi speakers, not adapted from Hindi. (This paragraph is descriptive linguistics and AC practice. We verified no UI study specific to Hindi or Marathi honorifics.)

### 7.7 Evidence gaps for India

Missing evidence: field studies of CRM or notification behaviour among Indian inside-sales staff; studies comparing reading in romanised and Devanagari script; recent verified IAMAI–Kantar figures on voice and Indic use; and community evidence (Reddit blocked). AC's own telemetry and interviews should fill these gaps.

---

## 8. Synthesis for Sales X-Ray

### 8.1 Seller behaviour model for Sales X-Ray

The model below adapts trigger → action → reward → investment [9] in two ways. **Triggers are mainly contexts, not pushes** [4][11]. **Rewards are informational and competence-building, not variable or slot-machine** [21][14].

| Loop (frequency) | Trigger (cue) | Action (one tap) | Reward (immediate) | Investment (loads next trigger) | Screens |
|---|---|---|---|---|---|
| **Shift start** (1/day) | Usual start time and place. One gentle morning card only if the app is not opened [2][53] | "Start calling" → first lead's call button | Today's plan in one glance; "1 done" | Seller confirms or adjusts today's pace (co-set) [34][84] | Home / Today |
| **Core call loop** (50–150/day) | **Call ends** → after-call sheet appears in under 1 s [1][122] | Tap outcome (≤5 big buttons), optional voice note, "Call next" | Progress tick; lead moves stage; follow-up auto-proposed [39][46] | Note and next-step time create the future reminder (implementation intention) [55] | Call, After-call sheet, Lead page |
| **Follow-up loop** (10–40/day) | Reminder due (Tier 2) or callback time [55] | Call or send a WhatsApp template | Lead warmed; reply received | Next stage or next date set | Leads, Lead page, Notifications |
| **Recovery (drift) loop** (0–3/day) | Idle during working hours with leads queued: private card, then capped sound [73][83] | "Call [name] now" or "On a break" | Acknowledgement on return; progress resumes [60] | Honest status ("break", "meeting") [84] | Drift card, Home |
| **Learning loop** (weekly) | Weekly coaching digest (batched, Tier 3) [65] | Open one report; read 1 strength and 1 focus | Concrete "next call, try…" tip [23][25] | Pick this week's focus skill → shown before calls | Call report, Coaching |
| **Manager loop** (daily) | Daily team summary (not real-time idle alerts) [81][83] | Coach one seller on one skill | Team trend | Adjust targets *with* the seller [42][43] | Manager dashboard |

### 8.2 Design principles

1. **Context is the cue.** Anchor habits to the end of a call and the start of a shift. Pushes are a fallback, not the engine [4][5][11].
2. **One thumb, one tap, one second.** Primary actions sit in the lower thumb zone, at least 48 dp, with 5 or fewer choices, and respond within 0.1–1 s [110][112][113][115][116][122].
3. **Capture before memory fades.** The outcome is logged within seconds of the call. Voice beats typing [118][119][120][121].
4. **Progress you can see, in units you control.** Count meaningful conversations and completed follow-ups, not raw dials [46][49].
5. **Private first, manager second, team last.** The seller sees their data first, managers see aggregates, and comparison with the team is opt-in [81][83][99][100].
6. **Informational, not controlling.** Feedback is about the task and its next step, in respectful language [21][23][87][133].
7. **Reward the return, never punish the lapse** [3][60][105].
8. **Fewer, better interruptions.** Use tiers, hard caps, batching, breakpoints, nothing during calls and quiet hours [65][69][70][73][79].
9. **Consent for every game element.** Opt in, explain why it exists, and let sellers leave [93][84].
10. **Mastery over points.** Celebrate skills and craft, not volume alone [22][91][97].
11. **Measure what you want, or it will be gamed.** Verify progress from canonical call records [48][49][50].
12. **Speak the seller's language.** Code-mixed vocabulary, either script, icon plus label, respectful forms [126][128][131][132][133].
13. **Test every nudge.** Expect small effects, pre-register success metrics and keep a kill switch [57][58][59][60].

### 8.3 Anti-patterns to avoid

- **A daily streak that breaks on one miss, with loss-framed warnings** ("You'll lose your 12-day streak!") [3][15][105].
- **Real-time "seller is idle" alerts to managers**, which is high-intensity surveillance [81][82][83].
- **A public all-team leaderboard ranked on dials or call minutes** [49][99][100][98].
- **A hard daily target with nothing beyond it**, which creates a stop line [44][42].
- **A red "failed" state at the end of the day**, which invites over-reporting near the line [50].
- **Sounding every reminder**, or repeating an alert the seller has already dismissed [73][15].
- **Any notification or modal during a live call** [117][63].
- **AI skill scores on leaderboards, targets or pay.** They would turn a coaching estimate into a high-stakes number and crowd out the quality motive [22][21]. They also conflict with AC's rule against official autonomous AI scoring before the AC-SVAL gates.
- **Long forms after calls, or required typed notes** [109][118].
- **English-only labels, or icon-only buttons** [128][131][132].
- **Variable "mystery" rewards or confetti slot-machine mechanics** [14][9].
- **Percentages, ratios and dense charts on seller screens** [129].
- **"Positivity ratio" formulas, or mindset slogans in place of concrete skill tips** [30][31][33].

### 8.4 Specific guidance

#### Daily targets UI
- **The weekly target is the goal, and the day is a pacing ring.** Default: weekly target ÷ working days, adjusted for leave and half days [42][45][53].
- **Unit:** "conversations" (connected calls above a minimum length, for example 30 s; AC proposal) and "follow-ups done". Dials can appear as a secondary count but are not the target [49][48].
- **Small-area display:** before the halfway point, show what is done ("7 done"). After it, show what is left ("5 to go"). Add a gentle mid-day marker to counter the middle dip [39][40].
- **Two tiers, base and stretch**, with visible recognition beyond the stretch tier ("+3 beyond stretch"), so there is no stop line [43][44][42].
- **Co-set targets:** the manager sets a range and the seller picks a number in it each week [34][84][18].
- **The end of the day is neutral.** "Carried to tomorrow: 3" replaces red failure. Progress is counted only from canonical call and activity records, never from client analytics events, so it cannot be inflated by hand [50][48].
- **Weekly fresh start:** each Monday, a short "new week" card with last week's personal best [53].

#### Drift nudges: rules, sound and frequency caps (all thresholds are AC proposals to A/B test)
- **Eligibility:** only during the seller's declared working hours; only when leads or tasks are queued; never on leave days or holidays; never during a call; never within 5 minutes after a call ends (the seller may be writing notes); never while the seller is on "break" or in a "meeting"; always respect the phone's Do Not Disturb [69][70][79].
- **Step 1 (after 20 minutes idle, configurable from 10 to 60):** a silent card on a Medium channel. It names one specific next lead and its reason ("Rahul asked for a call after lunch") and offers two buttons: **Call now** and **On a break (15/30/60 min)** [55][84].
- **Step 2 (15 minutes later, if still idle):** the custom drift sound on a High (not Urgent) channel, without a heads-up banner.
- **Caps:** at most **1 sounded drift nudge per 60 minutes** and **3 per day**. After **2 dismissals in a row**, pause drift nudges for 2 hours. Never repeat a nudge inside the same idle episode [73].
- **The sound:** shorter than 1.5 s, two or three notes, mid-to-low pitch, slow tempo, harmonic and not harsh. It must be clearly calmer than the Urgent tone [75][76]. Ship 2–3 small melodic variants of one timbre to slow habituation while staying recognisable [74]. Use the notification audio stream, never the alarm stream.
- **Haptic:** one long, soft pulse, distinct from Urgent's three short, strong pulses [77].
- **The return:** when the seller makes the next call, show a small, warm acknowledgement such as "Back on track — 1 more to today's pace". No mention of the gap [60][105].
- **Visibility:** drift events are private to the seller. Managers see only daily and weekly aggregates (for example, "active calling hours") that the seller can also see, explained on a "What we track and why" page [81][83][84][86].
- **Kill switch:** if more than 10% of active sellers disable the drift channel, or the median dismiss rate goes above 60% in a week, freeze the rollout and review (AC proposal) [57][59].

#### Leaderboards (or not)
- **Default: off.** No all-team rank table [99][100][98].
- **If a team turns one on:** it is opt-in per seller [93]. Show **top-3 recognition** for behaviours under the seller's control (follow-ups completed, same-day logging), refreshed weekly [103]. Each seller's main view compares them with their own personal best [91]. Team-versus-target framing is preferred over person-versus-person [99]. **Never rank on AI coaching scores or raw dials** [22][49].
- Re-test the effect on the bottom half of performers specifically, since that is where harm appears [99][100][102].

#### Streaks
- Replace daily streaks with **weekly consistency**: "Logged every call within 1 minute on 4 of 5 days", counting working days only [3][105].
- Build in **repair**: one grace day a week, plus "make it up tomorrow" [105].
- **No loss-framed pushes about streaks** [15][104]. Show streaks only in-app, as a quiet record of craft [12].

#### Coaching-report framing
- **Order:** for new sellers (for example, the first 60 days, AC proposal), start with one specific, observable strength and then **one** focus point. For experienced sellers, offer the focus point first, with the option to switch [25][21].
- **Task level, not self level:** "When the customer said 'too costly', you moved straight to discount. Next call, ask what they're comparing with." Not "You're weak at objections" [23][24].
- **Every report ends with an if–then plan** for the next call [55][56].
- **Language:** growth-oriented and respectful ("not yet", "try next"). Do not claim that mindset itself raises sales [29][30][31][32]. Use no positivity ratios [33].
- **Scores:** label them as coaching estimates, not official ratings, until AC-SVAL clears them. Keep them private to the seller and manager by default, and keep them out of targets, pay and leaderboards [21][22].
- **Cadence:** one weekly "focus skill" digest. Individual reports are available on demand, not pushed for every call [26][65].

#### Notification tiers (mapped to Android channels [78])

| Tier | Android importance | Sound / haptic | Use for | Caps (AC proposal) |
|---|---|---|---|---|
| **1 Urgent** | Urgent (heads-up + sound) | Distinct urgent tone; 3 short strong pulses | New hot lead to call within minutes; callback due *now* that the seller scheduled | Held during calls and delivered at the call's end [117][69]; at most 6 a day |
| **2 High** | High (sound, no heads-up) | Soft tone; 2 medium pulses | Reminders due within 15 minutes; drift step 2 | 1 sounded drift nudge an hour; no repeats once dismissed [73] |
| **3 Medium** | Medium (silent) | None | Drift step 1 card; coaching tip; report ready; target milestones | Batched into 2–3 digests a day [65] |
| **4 Low** | Low (silent, not in the status bar) | None | Weekly summaries; product news | Weekly |

Create all channels at install, with honest names, because importance cannot be raised later [78]. Quiet hours (default 20:00–09:00, seller-adjustable within org policy) silence Tiers 1–3 apart from callbacks the seller explicitly scheduled for that time [79].

### 8.5 Implications for Sales X-Ray: 15 recommendations

| # | Recommendation | Impact | Effort | Evidence |
|---|---|---|---|---|
| 1 | **After-call sheet in seconds:** appears within 1 s of call end; 5 or fewer outcome buttons at least 48 dp in the thumb zone; smart default from call length; optional voice note in any language; one-tap save that works offline. Target: median completion under 8 s. | **H** | M | [117]–[121], [109]–[116], [122], [125] (LAB, PR) |
| 2 | **Notification tier system** with fixed Android channels, hard caps, digest batching for Tiers 3–4, nothing during calls, and delivery at call-end breakpoints. | **H** | M | [61]–[71], [73], [78] (RCT, LAB, OBS, PR) |
| 3 | **Drift nudge v1** exactly as specified in §8.4: private, two steps, capped, with a calm sound, a "break" option and acknowledgement on return. | **H** | M | [55], [60], [73]–[77], [83], [84] (RCT, OBS, LAB) |
| 4 | **Drift visibility rules:** no real-time idle alerts to managers; aggregates only; a "What we track and why" page the seller can see. | **H** | S | [80]–[86] (MA, OBS, FE) |
| 5 | **Weekly target, daily pacing ring** with the small-area display, a mid-day marker, base and stretch tiers, and no stop line. | **H** | M | [39], [40], [42]–[46], [53] (FE, OBS, MA) |
| 6 | **Target metric = conversations + follow-ups done**, computed from canonical call records; dials secondary; quality floor such as minimum call length. | **H** | M | [47]–[50] (OBS, LAB, TH) |
| 7 | **Co-set targets:** the manager sets a range, the seller chooses within it, and the seller can explain a low day. | M | S | [18], [34], [84] (TH, LAB) |
| 8 | **Leaderboards off by default.** If enabled: opt-in, top-3 recognition on controllable behaviours, personal bests, never AI scores or dials. | M | S | [93], [96]–[103] (RCT, FE) |
| 9 | **Weekly consistency instead of streaks**, with grace days, repair, and no loss-framed pushes. | M | S | [3], [12], [60], [105] (OBS, RCT) |
| 10 | **Coaching reports:** strength first for novices, gap first for experts; one focus; task-level wording; an if–then plan for the next call; scores labelled as coaching estimates. | **H** | M | [21], [23]–[26], [55] (MA, OBS) |
| 11 | **Coaching cadence:** one weekly focus skill shown before calls; reports on demand, not pushed for every call. | M | S | [26], [27], [65] (OBS, MA, RCT) |
| 12 | **Language and script:** Hindi, Marathi and English UI plus code-mixed loanwords; romanised and Devanagari input; transliteration-aware search; native Marathi copy review; respectful second-person forms. | **H** | M | [126]–[128], [133], [87] (OBS, PR, TH) |
| 13 | **Low-numeracy, low-literacy displays:** counts, not percentages; large numerals; icon plus label everywhere; voice help on key screens. | M | S | [129]–[132] (OBS, RCT, LAB) |
| 14 | **Budget-phone performance budget:** tap feedback within 100 ms; screen changes under 1 s; saves done locally and optimistically; explained progress for anything over 1 s. | **H** | M | [122]–[125] (PR, TH) |
| 15 | **Nudge experimentation discipline:** A/B test every nudge and game element; pre-register metrics (time back to the next call after drift, drift-channel disable rate, dismiss rate, follow-up completion, seller-reported annoyance); kill switch; report effects honestly. | M | S | [57]–[60] (MA, RCT) |

### 8.6 What AC should measure, and where evidence is thin

- **Habit:** share of calls logged within 60 s of ending, tracked weekly over the first 90 days (expect a slow curve [3][7]).
- **Nudges:** median time back to the next call after a drift nudge, drift-channel disable rate, dismiss rate, and outcomes of a holdout group [59][60].
- **Targets:** distribution of daily totals around the target line. A spike exactly at the target suggests stopping at the line [44], and very short "calls" near the line suggest gaming [50].
- **Coaching:** whether the focus skill improves on later calls, judged against the AC-SVAL-gated method once available.
- **Sentiment:** short in-app pulse questions ("Did this reminder help?") and seller interviews. Community forum evidence (Reddit) was blocked for this research and should be gathered by other means.

---

## Sources not verified this session

- **IAMAI–Kantar, *Internet in India* (2023, 2024 or 2025 editions):** not verified, because the shared web-search budget ran out. No figures from it are used. Check the latest edition before quoting.
- **Sendelbach & Funk (2013), "Alarm fatigue: a patient safety concern," *AACN Advanced Critical Care* 24(4), 378–386:** the citation exists, but the widely quoted "72–99% false alarms" figure could not be traced reliably to it, so it is **not used**.
- **Lally et al. (2010), the claim that "missing one opportunity did not materially affect" habit formation:** taken from the abstract as summarised by secondary sources. The full text was not re-read (the publisher blocked access).
- **Badrinarayanan, Dixon, West & Zank (2015), sales-coaching review in *European Journal of Marketing*:** bibliographic details could not be confirmed, so it is **not used**.
- **Mark et al.'s "23 minutes to resume" figure:** not found in the primary source checked, so it is **not used**.
- **Wiedenbeck (1999):** bibliographic details verified, but the precise findings are summarised from prior knowledge of the paper. Treat [132] as indicative.

---

## References

All accessed 25 Oct 2026.

[1] Fogg, B. J. (2009). A behavior model for persuasive design. *Proceedings of the 4th International Conference on Persuasive Technology (Persuasive '09)*, 1–7. ACM. https://doi.org/10.1145/1541948.1541999
[2] Fogg, B. J. (2019). *Tiny Habits: The Small Changes That Change Everything*. Houghton Mifflin Harcourt. (BK; ISBN 9780358003328)
[3] Lally, P., van Jaarsveld, C. H. M., Potts, H. W. W., & Wardle, J. (2010). How are habits formed: Modelling habit formation in the real world. *European Journal of Social Psychology*, 40(6), 998–1009. https://doi.org/10.1002/ejsp.674
[4] Wood, W., & Neal, D. T. (2007). A new look at habits and the habit–goal interface. *Psychological Review*, 114(4), 843–863. https://doi.org/10.1037/0033-295X.114.4.843
[5] Wood, W., & Rünger, D. (2016). Psychology of habit. *Annual Review of Psychology*, 67, 289–314. https://doi.org/10.1146/annurev-psych-122414-033417
[6] Wood, W., Quinn, J. M., & Kashy, D. A. (2002). Habits in everyday life: Thought, emotion, and action. *Journal of Personality and Social Psychology*, 83(6), 1281–1297. https://doi.org/10.1037/0022-3514.83.6.1281
[7] Buyalskaya, A., Ho, H., Milkman, K. L., Li, X., Duckworth, A. L., & Camerer, C. (2023). What can machine learning teach us about habit formation? Evidence from exercise and hygiene. *PNAS*, 120(17), e2216115120. https://doi.org/10.1073/pnas.2216115120
[8] Duhigg, C. (2012). *The Power of Habit: Why We Do What We Do in Life and Business*. Random House. (BK; ISBN 9781400069286)
[9] Eyal, N. (with Hoover, R.) (2014). *Hooked: How to Build Habit-Forming Products*. Portfolio/Penguin. (BK; ISBN 9781591847786)
[10] Oulasvirta, A., Rattenbury, T., Ma, L., & Raita, E. (2012). Habits make smartphone use more pervasive. *Personal and Ubiquitous Computing*, 16(1), 105–114. https://doi.org/10.1007/s00779-011-0412-2
[11] Stawarz, K., Cox, A. L., & Blandford, A. (2015). Beyond self-tracking and reminders: Designing smartphone apps that support habit formation. *Proceedings of CHI 2015*, 2653–2662. https://doi.org/10.1145/2702123.2702230
[12] Renfree, I., Harrison, D., Marshall, P., Stawarz, K., & Cox, A. (2016). Don't kick the habit: The role of dependency in habit formation apps. *CHI 2016 Extended Abstracts*, 2932–2939. https://doi.org/10.1145/2851581.2892495
[13] Gardner, B., Lally, P., & Wardle, J. (2012). Making health habitual: The psychology of 'habit-formation' and general practice. *British Journal of General Practice*, 62(605), 664–666. https://doi.org/10.3399/bjgp12X659466
[14] Schüll, N. D. (2012). *Addiction by Design: Machine Gambling in Las Vegas*. Princeton University Press. (BK; ISBN 9780691127552)
[15] Gray, C. M., Kou, Y., Battles, B., Hoggatt, J., & Toombs, A. L. (2018). The dark (patterns) side of UX design. *Proceedings of CHI 2018*, 1–14. https://doi.org/10.1145/3173574.3174108
[16] Wood, W. (2019). *Good Habits, Bad Habits: The Science of Making Positive Changes That Stick*. Farrar, Straus and Giroux. (BK; ISBN 9781250159076; background reading)
[17] Hagger, M. S., Chatzisarantis, N. L. D., et al. (2016). A multilab preregistered replication of the ego-depletion effect. *Perspectives on Psychological Science*, 11(4), 546–573. https://doi.org/10.1177/1745691616652873
[18] Ryan, R. M., & Deci, E. L. (2000). Self-determination theory and the facilitation of intrinsic motivation, social development, and well-being. *American Psychologist*, 55(1), 68–78. https://doi.org/10.1037/0003-066X.55.1.68
[19] Deci, E. L., Olafsen, A. H., & Ryan, R. M. (2017). Self-determination theory in work organizations: The state of a science. *Annual Review of Organizational Psychology and Organizational Behavior*, 4, 19–43. https://doi.org/10.1146/annurev-orgpsych-032516-113108
[20] Van den Broeck, A., Ferris, D. L., Chang, C.-H., & Rosen, C. C. (2016). A review of self-determination theory's basic psychological needs at work. *Journal of Management*, 42(5), 1195–1229. https://doi.org/10.1177/0149206316632058
[21] Deci, E. L., Koestner, R., & Ryan, R. M. (1999). A meta-analytic review of experiments examining the effects of extrinsic rewards on intrinsic motivation. *Psychological Bulletin*, 125(6), 627–668. https://doi.org/10.1037/0033-2909.125.6.627
[22] Cerasoli, C. P., Nicklin, J. M., & Ford, M. T. (2014). Intrinsic motivation and extrinsic incentives jointly predict performance: A 40-year meta-analysis. *Psychological Bulletin*, 140(4), 980–1008. https://doi.org/10.1037/a0035661
[23] Kluger, A. N., & DeNisi, A. (1996). The effects of feedback interventions on performance: A historical review, a meta-analysis, and a preliminary feedback intervention theory. *Psychological Bulletin*, 119(2), 254–284. https://doi.org/10.1037/0033-2909.119.2.254
[24] Hattie, J., & Timperley, H. (2007). The power of feedback. *Review of Educational Research*, 77(1), 81–112. https://doi.org/10.3102/003465430298487
[25] Finkelstein, S. R., & Fishbach, A. (2012). Tell me what I did wrong: Experts seek and respond to negative feedback. *Journal of Consumer Research*, 39(1), 22–38. https://doi.org/10.1086/661934
[26] Dahling, J. J., Taylor, S. R., Chau, S. L., & Dwight, S. A. (2016). Does coaching matter? A multilevel model linking managerial coaching skill and frequency to sales goal attainment. *Personnel Psychology*, 69(4), 863–894. https://doi.org/10.1111/peps.12123
[27] Jones, R. J., Woods, S. A., & Guillaume, Y. R. F. (2016). The effectiveness of workplace coaching: A meta-analysis of learning and performance outcomes from coaching. *Journal of Occupational and Organizational Psychology*, 89(2), 249–277. https://doi.org/10.1111/joop.12119
[28] Dweck, C. S. (2006). *Mindset: The New Psychology of Success*. Random House. (BK; ISBN 9781400062751)
[29] Dweck, C. S., & Yeager, D. S. (2019). Mindsets: A view from two eras. *Perspectives on Psychological Science*, 14(3), 481–496. https://doi.org/10.1177/1745691618804166
[30] Sisk, V. F., Burgoyne, A. P., Sun, J., Butler, J. L., & Macnamara, B. N. (2018). To what extent and under which circumstances are growth mind-sets important to academic achievement? Two meta-analyses. *Psychological Science*, 29(4), 549–571. https://doi.org/10.1177/0956797617739704
[31] Macnamara, B. N., & Burgoyne, A. P. (2023). Do growth mindset interventions impact students' academic achievement? A systematic review and meta-analysis with recommendations for best practices. *Psychological Bulletin*, 149(3–4), 133–173. https://doi.org/10.1037/bul0000352
[32] Burnette, J. L., Billingsley, J., Banks, G. C., Knouse, L. E., Hoyt, C. L., Pollack, J. M., & Simon, S. (2023). A systematic review and meta-analysis of growth mindset interventions: For whom, how, and why might such interventions work? *Psychological Bulletin*, 149(3–4), 174–205. https://doi.org/10.1037/bul0000368
[33] Brown, N. J. L., Sokal, A. D., & Friedman, H. L. (2013). The complex dynamics of wishful thinking: The critical positivity ratio. *American Psychologist*, 68(9), 801–813. https://doi.org/10.1037/a0032850
[34] Locke, E. A., & Latham, G. P. (2002). Building a practically useful theory of goal setting and task motivation: A 35-year odyssey. *American Psychologist*, 57(9), 705–717. https://doi.org/10.1037/0003-066X.57.9.705
[35] Locke, E. A., & Latham, G. P. (2019). The development of goal setting theory: A half century retrospective. *Motivation Science*, 5(2), 93–105. https://doi.org/10.1037/mot0000127
[36] Hull, C. L. (1932). The goal-gradient hypothesis and maze learning. *Psychological Review*, 39(1), 25–43. https://doi.org/10.1037/h0072640
[37] Kivetz, R., Urminsky, O., & Zheng, Y. (2006). The goal-gradient hypothesis resurrected: Purchase acceleration, illusionary goal progress, and customer retention. *Journal of Marketing Research*, 43(1), 39–58. https://doi.org/10.1509/jmkr.43.1.39
[38] Nunes, J. C., & Drèze, X. (2006). The endowed progress effect: How artificial advancement increases effort. *Journal of Consumer Research*, 32(4), 504–512. https://doi.org/10.1086/500480
[39] Koo, M., & Fishbach, A. (2012). The small-area hypothesis: Effects of progress monitoring on goal adherence. *Journal of Consumer Research*, 39(3), 493–509. https://doi.org/10.1086/663827
[40] Bonezzi, A., Brendl, C. M., & De Angelis, M. (2011). Stuck in the middle: The psychophysics of goal pursuit. *Psychological Science*, 22(5), 607–612. https://doi.org/10.1177/0956797611404899
[41] Heath, C., Larrick, R. P., & Wu, G. (1999). Goals as reference points. *Cognitive Psychology*, 38(1), 79–109. https://doi.org/10.1006/cogp.1998.0708
[42] Chung, D. J., Steenburgh, T., & Sudhir, K. (2014). Do bonuses enhance sales productivity? A dynamic structural analysis of bonus-based compensation plans. *Marketing Science*, 33(2), 165–187. https://doi.org/10.1287/mksc.2013.0815
[43] Steenburgh, T., & Ahearne, M. (2012). Motivating salespeople: What really works. *Harvard Business Review*, 90(7–8), July–August 2012. https://hbr.org/2012/07/motivating-salespeople-what-really-works (PR; title, authors and issue checked on HBR's page; the multi-tier target finding is checked via secondary summaries because the article body is paywalled)
[44] Camerer, C., Babcock, L., Loewenstein, G., & Thaler, R. (1997). Labor supply of New York City cabdrivers: One day at a time. *Quarterly Journal of Economics*, 112(2), 407–441. https://doi.org/10.1162/003355397555244
[45] Bandura, A., & Schunk, D. H. (1981). Cultivating competence, self-efficacy, and intrinsic interest through proximal self-motivation. *Journal of Personality and Social Psychology*, 41(3), 586–598. https://doi.org/10.1037/0022-3514.41.3.586
[46] Harkin, B., Webb, T. L., Chang, B. P. I., Prestwich, A., Conner, M., Kellar, I., Benn, Y., & Sheeran, P. (2016). Does monitoring goal progress promote goal attainment? A meta-analysis of the experimental evidence. *Psychological Bulletin*, 142(2), 198–229. https://doi.org/10.1037/bul0000025
[47] Oyer, P. (1998). Fiscal year ends and nonlinear incentive contracts: The effect on business seasonality. *Quarterly Journal of Economics*, 113(1), 149–185. https://doi.org/10.1162/003355398555559
[48] Larkin, I. (2014). The cost of high-powered incentives: Employee gaming in enterprise software sales. *Journal of Labor Economics*, 32(2), 199–227. https://doi.org/10.1086/673371
[49] Kerr, S. (1975). On the folly of rewarding A, while hoping for B. *Academy of Management Journal*, 18(4), 769–783. (Bibliographic details verified via reference lists; DOI not confirmed.)
[50] Schweitzer, M. E., Ordóñez, L., & Douma, B. (2004). Goal setting as a motivator of unethical behavior. *Academy of Management Journal*, 47(3), 422–432. https://doi.org/10.5465/20159591
[51] Ordóñez, L. D., Schweitzer, M. E., Galinsky, A. D., & Bazerman, M. H. (2009). Goals gone wild: The systematic side effects of overprescribing goal setting. *Academy of Management Perspectives*, 23(1), 6–16. https://doi.org/10.5465/amp.2009.37007999
[52] Locke, E. A., & Latham, G. P. (2009). Has goal setting gone wild, or have its attackers abandoned good scholarship? *Academy of Management Perspectives*, 23(1), 17–23. https://doi.org/10.5465/amp.2009.37008000
[53] Dai, H., Milkman, K. L., & Riis, J. (2014). The fresh start effect: Temporal landmarks motivate aspirational behavior. *Management Science*, 60(10), 2563–2582. https://doi.org/10.1287/mnsc.2014.1901
[54] Thaler, R. H., & Sunstein, C. R. (2008). *Nudge: Improving Decisions about Health, Wealth, and Happiness*. Yale University Press. Revised "final edition" 2021. (BK)
[55] Gollwitzer, P. M. (1999). Implementation intentions: Strong effects of simple plans. *American Psychologist*, 54(7), 493–503. https://doi.org/10.1037/0003-066X.54.7.493
[56] Gollwitzer, P. M., & Sheeran, P. (2006). Implementation intentions and goal achievement: A meta-analysis of effects and processes. *Advances in Experimental Social Psychology*, 38, 69–119. https://doi.org/10.1016/S0065-2601(06)38002-1
[57] Mertens, S., Herberz, M., Hahnel, U. J. J., & Brosch, T. (2022). The effectiveness of nudging: A meta-analysis of choice architecture interventions across behavioral domains. *PNAS*, 119(1), e2107346118. https://doi.org/10.1073/pnas.2107346118
[58] Maier, M., Bartoš, F., Stanley, T. D., Shanks, D. R., Harris, A. J. L., & Wagenmakers, E.-J. (2022). No evidence for nudging after adjusting for publication bias. *PNAS*, 119(31), e2200300119. https://doi.org/10.1073/pnas.2200300119
[59] DellaVigna, S., & Linos, E. (2022). RCTs to scale: Comprehensive evidence from two nudge units. *Econometrica*, 90(1), 81–116. https://doi.org/10.3982/ECTA18709
[60] Milkman, K. L., Gromet, D., Ho, H., et al. (2021). Megastudies improve the impact of applied behavioural science. *Nature*, 600(7889), 478–483. https://doi.org/10.1038/s41586-021-04128-4
[61] Pielot, M., Church, K., & de Oliveira, R. (2014). An in-situ study of mobile phone notifications. *Proceedings of MobileHCI '14*, 233–242. https://doi.org/10.1145/2628363.2628364
[62] Mehrotra, A., Pejovic, V., Vermeulen, J., Hendley, R., & Musolesi, M. (2016). My phone and me: Understanding people's receptivity to mobile notifications. *Proceedings of CHI 2016*, 1021–1032. https://doi.org/10.1145/2858036.2858566
[63] Stothart, C., Mitchum, A., & Yehnert, C. (2015). The attentional cost of receiving a cell phone notification. *Journal of Experimental Psychology: Human Perception and Performance*, 41(4), 893–897. https://doi.org/10.1037/xhp0000100
[64] Kushlev, K., Proulx, J., & Dunn, E. W. (2016). "Silence your phones": Smartphone notifications increase inattention and hyperactivity symptoms. *Proceedings of CHI 2016*, 1011–1020. https://doi.org/10.1145/2858036.2858359
[65] Fitz, N., Kushlev, K., Jagannathan, R., Lewis, T., Paliwal, D., & Ariely, D. (2019). Batching smartphone notifications can improve well-being. *Computers in Human Behavior*, 101, 84–94. https://doi.org/10.1016/j.chb.2019.07.016
[66] Pielot, M., & Rello, L. (2017). Productive, anxious, lonely: 24 hours without push notifications. *Proceedings of MobileHCI '17*. https://doi.org/10.1145/3098279.3098526
[67] Mark, G., Gonzalez, V. M., & Harris, J. (2005). No task left behind? Examining the nature of fragmented work. *Proceedings of CHI 2005*, 321–330. https://doi.org/10.1145/1054972.1055017
[68] Mark, G., Gudith, D., & Klocke, U. (2008). The cost of interrupted work: More speed and stress. *Proceedings of CHI 2008*, 107–110. https://doi.org/10.1145/1357054.1357072
[69] Adamczyk, P. D., & Bailey, B. P. (2004). If not now, when? The effects of interruption at different moments within task execution. *Proceedings of CHI 2004*, 271–278. https://doi.org/10.1145/985692.985727
[70] Iqbal, S. T., & Bailey, B. P. (2008). Effects of intelligent notification management on users and their tasks. *Proceedings of CHI 2008*, 93–102. https://doi.org/10.1145/1357054.1357070
[71] Okoshi, T., Ramos, J., Nozaki, H., Nakazawa, J., Dey, A. K., & Tokuda, H. (2015). Attelia: Reducing user's cognitive load due to interruptive notifications on smart phones. *IEEE PerCom 2015*, 96–104. https://doi.org/10.1109/PERCOM.2015.7146515
[72] Cvach, M. (2012). Monitor alarm fatigue: An integrative review. *Biomedical Instrumentation & Technology*, 46(4), 268–277. https://doi.org/10.2345/0899-8205-46.4.268
[73] Ancker, J. S., Edwards, A., Nosal, S., Hauser, D., Mauer, E., & Kaushal, R. (2017). Effects of workload, work complexity, and repeated alerts on alert fatigue in a clinical decision support system. *BMC Medical Informatics and Decision Making*, 17, 36. https://doi.org/10.1186/s12911-017-0430-8
[74] Anderson, B. B., Vance, A., Kirwan, C. B., Jenkins, J. L., & Eargle, D. (2016). From warning to wallpaper: Why the brain habituates to security warnings and what can be done about it. *Journal of Management Information Systems*, 33(3), 713–743. https://doi.org/10.1080/07421222.2016.1243947
[75] Edworthy, J., Loxley, S., & Dennis, I. (1991). Improving auditory warning design: Relationship between warning sound parameters and perceived urgency. *Human Factors*, 33(2), 205–231. https://doi.org/10.1177/001872089103300206
[76] Hellier, E. J., Edworthy, J., & Dennis, I. (1993). Improving auditory warning design: Quantifying and predicting the effects of different warning parameters on perceived urgency. *Human Factors*, 35(4), 693–706. https://doi.org/10.1177/001872089303500408
[77] Brewster, S., & Brown, L. M. (2004). Tactons: Structured tactile messages for non-visual information display. *Proceedings of the Fifth Australasian User Interface Conference (AUIC 2004)*, CRPIT 28, 15–23. https://eprints.gla.ac.uk/3443/
[78] Android Developers. Create and manage notification channels. https://developer.android.com/develop/ui/views/notifications/channels (PR)
[79] Barber, L. K., & Santuzzi, A. M. (2015). Please respond ASAP: Workplace telepressure and employee recovery. *Journal of Occupational Health Psychology*, 20(2), 172–189. https://doi.org/10.1037/a0038278
[80] Ravid, D. M., Tomczak, D. L., White, J. C., & Behrend, T. S. (2020). EPM 20/20: A review, framework, and research agenda for electronic performance monitoring. *Journal of Management*, 46(1), 100–126. https://doi.org/10.1177/0149206319869435
[81] Ravid, D. M., White, J. C., Tomczak, D. L., Miles, A. F., & Behrend, T. S. (2023). A meta-analysis of the effects of electronic performance monitoring on work outcomes. *Personnel Psychology*, 76(1), 5–40. https://doi.org/10.1111/peps.12514
[82] Siegel, R., König, C. J., & Lazar, V. (2022). The impact of electronic monitoring on employees' job satisfaction, stress, performance, and counterproductive work behavior: A meta-analysis. *Computers in Human Behavior Reports*, 8, 100227. https://doi.org/10.1016/j.chbr.2022.100227
[83] Holman, D., Chissick, C., & Totterdell, P. (2002). The effects of performance monitoring on emotional labor and well-being in call centers. *Motivation and Emotion*, 26(1), 57–81. https://doi.org/10.1023/A:1015194108376
[84] Alge, B. J. (2001). Effects of computer surveillance on perceptions of privacy and procedural justice. *Journal of Applied Psychology*, 86(4), 797–804. https://doi.org/10.1037/0021-9010.86.4.797
[85] Stanton, J. M. (2000). Reactions to employee performance monitoring: Framework, review, and research directions. *Human Performance*, 13(1), 85–113. https://doi.org/10.1207/S15327043HUP1301_4
[86] Bernstein, E. S. (2012). The transparency paradox: A role for privacy in organizational learning and operational control. *Administrative Science Quarterly*, 57(2), 181–216. https://doi.org/10.1177/0001839212453028
[87] Miller, C. H., Lane, L. T., Deatrick, L. M., Young, A. M., & Potts, K. A. (2007). Psychological reactance and promotional health messages: The effects of controlling language, lexical concreteness, and the restoration of freedom. *Human Communication Research*, 33(2), 219–240. https://doi.org/10.1111/j.1468-2958.2007.00297.x
[88] Taylor, P., & Bain, P. (2005). 'India calling to the far away towns': The call centre labour process and globalization. *Work, Employment and Society*, 19(2), 261–282. https://doi.org/10.1177/0950017005053170
[89] Hamari, J., Koivisto, J., & Sarsa, H. (2014). Does gamification work? A literature review of empirical studies on gamification. *Proceedings of the 47th Hawaii International Conference on System Sciences*, 3025–3034. https://doi.org/10.1109/HICSS.2014.377
[90] Koivisto, J., & Hamari, J. (2019). The rise of motivational information systems: A review of gamification research. *International Journal of Information Management*, 45, 191–210. https://doi.org/10.1016/j.ijinfomgt.2018.10.013
[91] Sailer, M., Hense, J. U., Mayr, S. K., & Mandl, H. (2017). How gamification motivates: An experimental study of the effects of specific game design elements on psychological need satisfaction. *Computers in Human Behavior*, 69, 371–380. https://doi.org/10.1016/j.chb.2016.12.033
[92] Sailer, M., & Homner, L. (2020). The gamification of learning: A meta-analysis. *Educational Psychology Review*, 32(1), 77–112. https://doi.org/10.1007/s10648-019-09498-w
[93] Mollick, E., & Rothbard, N. (2014). Mandatory fun: Consent, gamification and the impact of games at work. SSRN Working Paper (Wharton), revised 30 Sep 2014. https://doi.org/10.2139/ssrn.2277103 (not peer-reviewed)
[94] Cardador, M. T., Northcraft, G. B., & Whicker, J. (2017). A theory of work gamification: Something old, something new, something borrowed, something cool? *Human Resource Management Review*, 27(2), 353–365. https://doi.org/10.1016/j.hrmr.2016.09.014
[95] Festinger, L. (1954). A theory of social comparison processes. *Human Relations*, 7(2), 117–140. https://doi.org/10.1177/001872675400700202
[96] Landers, R. N., Bauer, K. N., & Callan, R. C. (2017). Gamification of task performance with leaderboards: A goal setting experiment. *Computers in Human Behavior*, 71, 508–515. https://doi.org/10.1016/j.chb.2015.08.008
[97] Mekler, E. D., Brühlmann, F., Tuch, A. N., & Opwis, K. (2017). Towards understanding the effects of individual gamification elements on intrinsic motivation and performance. *Computers in Human Behavior*, 71, 525–534. https://doi.org/10.1016/j.chb.2015.08.048
[98] Hanus, M. D., & Fox, J. (2015). Assessing the effects of gamification in the classroom: A longitudinal study on intrinsic motivation, social comparison, satisfaction, effort, and academic performance. *Computers & Education*, 80, 152–161. https://doi.org/10.1016/j.compedu.2014.08.019
[99] Ashraf, N., Bandiera, O., & Lee, S. S. (2014). Awards unbundled: Evidence from a natural field experiment. *Journal of Economic Behavior & Organization*, 100, 44–63. https://doi.org/10.1016/j.jebo.2014.01.001
[100] Barankay, I. (2012). Rank incentives: Evidence from a randomized workplace experiment. Working paper, The Wharton School, University of Pennsylvania. https://repository.upenn.edu/mgmt_papers/264 (not peer-reviewed)
[101] Blanes i Vidal, J., & Nossol, M. (2011). Tournaments without prizes: Evidence from personnel records. *Management Science*, 57(10), 1721–1736. https://doi.org/10.1287/mnsc.1110.1383
[102] Gill, D., Kissová, Z., Lee, J., & Prowse, V. (2019). First-place loving and last-place loathing: How rank in the distribution of performance affects effort provision. *Management Science*, 65(2), 494–507. https://doi.org/10.1287/mnsc.2017.2907
[103] Bradler, C., Dur, R., Neckermann, S., & Non, A. (2016). Employee recognition and performance: A field experiment. *Management Science*, 62(11), 3085–3099. https://doi.org/10.1287/mnsc.2015.2291
[104] Kahneman, D., & Tversky, A. (1979). Prospect theory: An analysis of decision under risk. *Econometrica*, 47(2), 263–291. https://doi.org/10.2307/1914185
[105] Silverman, J., & Barasch, A. (2023). On or off track: How (broken) streaks affect consumer decisions. *Journal of Consumer Research*, 49(6), 1095–1117. https://doi.org/10.1093/jcr/ucac029
[106] Ryan, R. M., Rigby, C. S., & Przybylski, A. (2006). The motivational pull of video games: A self-determination theory approach. *Motivation and Emotion*, 30(4), 344–360. https://doi.org/10.1007/s11031-006-9051-8
[107] Sweller, J. (1988). Cognitive load during problem solving: Effects on learning. *Cognitive Science*, 12(2), 257–285. https://doi.org/10.1207/s15516709cog1202_4
[108] Sweller, J., van Merriënboer, J. J. G., & Paas, F. (2019). Cognitive architecture and instructional design: 20 years later. *Educational Psychology Review*, 31, 261–292. https://doi.org/10.1007/s10648-019-09465-5
[109] Cowan, N. (2001). The magical number 4 in short-term memory: A reconsideration of mental storage capacity. *Behavioral and Brain Sciences*, 24(1), 87–114. https://doi.org/10.1017/S0140525X01003922
[110] Hick, W. E. (1952). On the rate of gain of information. *Quarterly Journal of Experimental Psychology*, 4(1), 11–26. https://doi.org/10.1080/17470215208416600
[111] Hyman, R. (1953). Stimulus information as a determinant of reaction time. *Journal of Experimental Psychology*, 45(3), 188–196. https://doi.org/10.1037/h0056940
[112] Fitts, P. M. (1954). The information capacity of the human motor system in controlling the amplitude of movement. *Journal of Experimental Psychology*, 47(6), 381–391. https://doi.org/10.1037/h0055392
[113] Hoober, S. (2013, 18 Feb). How do users really hold mobile devices? *UXmatters*. https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php (PR/OBS)
[114] Bergstrom-Lehtovirta, J., & Oulasvirta, A. (2014). Modeling the functional area of the thumb on mobile touchscreen surfaces. *Proceedings of CHI 2014*, 1991–2000. https://doi.org/10.1145/2556288.2557354
[115] Parhi, P., Karlson, A. K., & Bederson, B. B. (2006). Target size study for one-handed thumb use on small touchscreen devices. *Proceedings of MobileHCI '06*, 203–210. https://doi.org/10.1145/1152215.1152260
[116] Google. Touch target size (Android Accessibility Help). https://support.google.com/accessibility/android/answer/7101858 (PR)
[117] Strayer, D. L., & Johnston, W. A. (2001). Driven to distraction: Dual-task studies of simulated driving and conversing on a cellular telephone. *Psychological Science*, 12(6), 462–466. https://doi.org/10.1111/1467-9280.00386
[118] Stafford, L., & Daly, J. A. (1984). Conversational memory: The effects of recall mode and memory expectancies on remembrances of natural conversations. *Human Communication Research*, 10(3), 379–402. https://doi.org/10.1111/j.1468-2958.1984.tb00024.x (figures as reported in [119])
[119] Brown-Schmidt, S., & Benjamin, A. S. (2018). How we remember conversation: Implications in legal settings. *Policy Insights from the Behavioral and Brain Sciences*, 5(2), 187–194. https://doi.org/10.1177/2372732218786975
[120] Ross, M., & Sicoly, F. (1979). Egocentric biases in availability and attribution. *Journal of Personality and Social Psychology*, 37(3), 322–336. https://doi.org/10.1037/0022-3514.37.3.322 (figures as reported in [119])
[121] Murre, J. M. J., & Dros, J. (2015). Replication and analysis of Ebbinghaus' forgetting curve. *PLOS ONE*, 10(7), e0120644. https://doi.org/10.1371/journal.pone.0120644
[122] Nielsen, J. (1993). *Usability Engineering*. Academic Press (BK; ISBN 9780125184052); excerpted as "Response times: The 3 important limits," Nielsen Norman Group (updated 2014). https://www.nngroup.com/articles/response-times-3-important-limits/
[123] Miller, R. B. (1968). Response time in man-computer conversational transactions. *Proceedings of the AFIPS Fall Joint Computer Conference*, 267–277. https://doi.org/10.1145/1476589.1476628
[124] Card, S. K., Moran, T. P., & Newell, A. (1983). *The Psychology of Human-Computer Interaction*. Lawrence Erlbaum Associates. (BK)
[125] Maister, D. H. (1985). The psychology of waiting lines. In J. A. Czepiel, M. R. Solomon, & C. F. Surprenant (Eds.), *The Service Encounter* (pp. 113–123). Lexington Books. https://davidmaister.com/articles/1/52/ (page range not re-verified)
[126] Bali, K., Sharma, J., Choudhury, M., & Vyas, Y. (2014). "I am borrowing ya mixing?" An analysis of English-Hindi code mixing in Facebook. *Proceedings of the First Workshop on Computational Approaches to Code Switching*, 116–126. ACL. https://doi.org/10.3115/v1/W14-3914
[127] Parshad, R. D., Bhowmick, S., Chand, V., Kumari, N., & Sinha, N. (2016). What is India speaking? Exploring the "Hinglish" invasion. *Physica A: Statistical Mechanics and its Applications*, 449, 375–389. https://doi.org/10.1016/j.physa.2016.01.015
[128] KPMG in India & Google (2017, April). *Indian Languages — Defining India's Internet*. https://assets.kpmg.com/content/dam/kpmg/in/pdf/2017/04/Indian-languages-Defining-Indias-Internet.pdf (PR; industry survey with Nielsen primary research)
[129] ASER Centre (2024). *Annual Status of Education Report (Rural) 2023: Beyond Basics* — Main findings. Pratham. https://asercentre.org/wp-content/uploads/2022/12/ASER-2023_Main-findings-1.pdf
[130] Medhi, I., Sagar, A., & Toyama, K. (2007). Text-free user interfaces for illiterate and semiliterate users. *Information Technologies and International Development*, 4(1), 37–50. https://doi.org/10.1162/itid.2007.4.1.37
[131] Medhi, I., Patnaik, S., Brunskill, E., Gautama, S. N. N., Thies, W., & Toyama, K. (2011). Designing mobile interfaces for novice and low-literacy users. *ACM Transactions on Computer-Human Interaction*, 18(1), 1–28. https://doi.org/10.1145/1959022.1959024
[132] Wiedenbeck, S. (1999). The use of icons and labels in an end user application program: An empirical study of learning and retention. *Behaviour & Information Technology*, 18(2), 68–82. https://doi.org/10.1080/014492999119129
[133] Brown, P., & Levinson, S. C. (1987). *Politeness: Some Universals in Language Usage*. Cambridge University Press. https://doi.org/10.1017/CBO9780511813085
