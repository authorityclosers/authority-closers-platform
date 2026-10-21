# Digest B — Accuracy Brain 4.0, Dimensions 11–18

Source file: `Accuracy Brain 4.0.txt` (UTF-8). The file has 25,466 lines. The last line has no trailing newline, so `wc -l` reports 25,465.

Read in full, line by line, with the Read tool: lines 1–27 (table of contents) and lines 12600–25466 (my range starts at 12626; I started at 12600 to see where Dimension 10 ends). There is **no content after Dimension 18**: the file ends at L25466 with D18's "This is the version I would lock …" sentence.

Conventions: "Lnnnn" is a line number. "(inference)" marks my own interpretation, not text from the file. "—" is the rubric's display value for "not scored". Quotes are kept short.

---

## 0. Table of contents (L1–27) and document shape

- L1 is the title, "Accuracy Brain 4.0". L2–22 list three categories and 18 dimensions:
  - Category 1, How You Talk: 1 Starting the Call, 2 Setting the Plan, 3 Tone, Pace & Pauses, 4 Listening Well, 5 Asking the Right Questions, 6 Building Connection, 7 Being Professional.
  - Category 2, How Well You Understand the Buyer: 8 Finding the Decision-Makers, 9 Understanding Problems & Goals, 10 Understanding What They're Doing Now, 11 Understanding the Real Impact, 12 Understanding How They Will Decide.
  - Category 3, How Well You Move the Sale Forward: 13 Matching the Right Solution, 14 Explaining the Solution Clearly, 15 Talking About Price & Budget, 16 Handling Objections, 17 Asking for the Decision, 18 Setting Clear Next Steps.
- L23–26 are blank. L27 is the banner "BRAIN 4.0 — ACCURACY ENGINE", which opens every dimension.
- Each TOC name matches the "Simple Report Name" in the dimension header, and each header's Category matches the TOC.
- The TOC has **no entry** for an overall score, category roll-up or report layout. The body has none either (see section 9).

### 0.1 Template repeated in every dimension in my range
Section numbers vary, but every dimension follows the same skeleton:
1. Header: banner, `DIMENSION nn — NAME`, Simple Report Name, Internal Meaning (missing in D12), Category.
2. Purpose (the question the dimension answers).
3. Boundary sections against neighbouring dimensions.
4. Principles, then "core evidence signals".
5. Score bands 5/5 → 1/5. Each band has a Definition, a one-line **"Simple Brain 4.0 Meaning"** (the learner-facing sentence) and worked examples with "Why n/5?".
6. "— NOT ENOUGH EVIDENCE" scenarios, plus "IMPORTANT" anti-rules (absence ≠ low score, presence ≠ high score).
7. "1/5 VS — MUST NEVER BE CONFUSED", with a canonical rule.
8. Score calibration table.
9. "Confidence is separate from score" (High / Medium / Low), with a canonical rule.
10. "Transcript is usually strong evidence" (what text shows and what audio adds).
11. Many "SPECIAL ACCURACY RULE" sections.
12. Brain 3.0 coaching rule (no vague coaching; a list of specific weaknesses) and an example of specific coaching.
13. Longitudinal accuracy rule (one call ≠ a person's identity).
14. "Do not score commercial outcome".
15. "FINAL BRAIN 4.0 SCORING RULE": one paragraph in the form "Never score … based on … Score whether …".
16. Internal output format (a field list with enumerations).
17. Example final analyzer output (**always a 5/5 example**).
18. "LOCKED SCORING TABLE", followed by "This is the version I would lock for Dimension nn …".

Fields shared by every output format in my range: Dimension, Internal Skill (missing in D12), Category, Applicability (Applicable / Not Applicable / Not Enough Evidence), Rating (1–5 / —), Confidence (High / Medium / Low), Evidence Spans (Timestamp(s)), Observed Behavior, Positive Evidence, Negative Evidence, Severity, Reason for Rating, and Inference ("None / clearly labelled inference").

Cross-dimension ethics flag: several 1/5 examples add "Potential: Being Professional: Ethics FAIL" (L14907, L19268, L21094, L22949, L24692; conditional at L19235) or "Being Professional: Ethics concern" (L16308, L17814). Being Professional is D07, outside my range.

---

## 1. Dimension 11 — Understanding the Real Impact

### 1.1 Identity
- Simple Report Name: Understanding the Real Impact. Internal Meaning: "Impact Quantification / Value Creation Foundation" (L12630).
- Category: How Well You Understand the Buyer.
- Lines: banner L12625, header L12626, lock sentence L14067; the dimension ends at L14069.

### 1.2 Purpose
L12638: did the salesperson help make clear the real significance of the buyer's problem, in money, time, effort, emotion and opportunity, "without exaggerating or manufacturing pain"? The core question (L12732): what the problem costs today, what continues or worsens if nothing changes, and what upside becomes possible if it is solved. The goal is "real significance", not "maximum pain" (L12735–12737).

### 1.3 Boundaries
- D09 owns WHAT is wrong and what they want. D11 owns HOW MUCH it matters (L12663–12682). Brain 3.0 is cited: problem depth and quantification are different skills.
- One-line Category 2 cross-reference (L12686–12708): D08 WHO, D09 WHAT, D10 HOW they deal with it now and what they tried, D11 HOW MUCH, D12 HOW / WHEN / by what criteria.
- Later "value" dimensions (L12712–12726): D11 owns the buyer-side value context. D13 (match), D14 (explain) and D15 (price) use it. "Dimension 11 creates the value foundation. Later dimensions use it."
- In the gap map (Current State → Consequences → Desired State → Gap → Capability Needed), D11 owns Consequences and the value significance of the transition (L13123–13128).
- Value creation (D11) ≠ value presentation (later dimensions) (L13881–13890). Do not use product value to invent problem value retroactively (L13894–13899).

### 1.4 Part of the call and context rules
- Discovery, before the relevant presentation. Impact should be understood before presenting; presenting while impact is "materially unclear" can reduce D11 (L13860–13863).
- Impact depth follows relevance. Not all five buckets are needed; do not ask emotional or family questions in a B2B productivity sale just because the bucket exists (L12940–12956, L13763–13772).
- "Personal depth must remain context-sensitive. Do not force emotional disclosure" (L12802–12803).
- Identify the primary impact by the buyer's own priorities (L12980–12987). The same result can mean different value to different buyers (L13108–13119).
- Buyer may understate impact: clarify calmly and let the buyer explain (L13776–13785). Buyer may overstate: ground it, and do not amplify the drama (L13789–13796).

### 1.5 Core evidence signals
Five impact buckets (lettered A–E, L12741–12817), each with a numbered signal section (L12991–13065):
- **A. Financial**: current, previous and target revenue, conversion gap, missed deals, wasted spend, lost profit. "But never manufacture economics."
- **B. Time**: hours per day or week of founder, manager or team time, delays, repeated manual work. A derived calculation (12 h/week ≈ 50 h/month) is fine if it comes from buyer data.
- **C. Effort**: complexity, coordination, cognitive load, supervision burden, chasing people.
- **D. Emotional / Mental**: buyer-supported frustration, uncertainty, fatigue, stress. "Do not diagnose clinical mental-health states"; write "the buyer said …", not "the buyer is anxious" (L13043–13048).
- **E. Opportunity**: what is not happening because of the problem (partnerships, scaling, hiring, ad spend held back).

Other signals:
- Cost of inaction, "where real" (L13069–13092). It must be discovered, not fabricated, and needs a plausible chain; the more dramatic the consequence, the stronger the evidence required (L13800–13805).
- Desired upside or opportunity value (L12821–12835).
- Buyer-generated value, e.g. "what would that be worth to you?" (L13096–13104). Value stated by the buyer outweighs value imposed by the seller (L13823–13830).
- "Why does this matter to you?" can be enough (L13923–13928).

### 1.6 Score bands
- **5/5** (L13132–13152): a clear, grounded, multidimensional understanding using the most relevant mix of financial, time, effort, emotional and opportunity cost, cost of inaction and desired upside. Quantifies where reality permits. Separates known, estimated and aspirational. No manufactured pain, fake numbers or exaggerated ROI, and does not treat emotional intensity as proof. Simple meaning: "You made the real size and importance of the problem clear without exaggerating it."
  - Ex1 Financial + Time: 9% vs 17–18% conversion, about 100 opportunities, deal value, plus 12 h/week of reviews. Quantifies from buyer data, does not claim every lost deal is recoverable, two distinct categories.
  - Ex2 Buyer cannot give an exact money figure: the seller pivots to operational cost (2 h/day). No fake precision.
  - Ex3 Opportunity cost: time spent fixing sales delays a two-city expansion.
  - Ex4 Emotional impact without forcing: "It's exhausting"; the seller acknowledges it and does not pitch. Emerges naturally from buyer evidence.
  - Ex5 Cost of inaction: "won't increase ad spend". Discovered, not manufactured.
  - Ex6 Buyer-generated value: 10 h/week becomes hiring and partnerships. The buyer defines the strategic value.
- **4/5** (L13255–13264): major impact understood; minor depth missing (one relevant bucket missed, time not fully quantified, cost of inaction light, upside could be sharper). Still enough to support value and pricing later. Simple meaning: "…main cost and importance … well, with only a few missing details."
  - Ex1 Strong time impact, no check for revenue leakage: one useful dimension missing.
  - Ex2 Strong financial impact, stress mentioned briefly and not explored: "4/5, perhaps even 5 depending on context"; emotional depth is not mandatory.
  - Ex3 Cost of inaction not asked, but already clear from the buyer's statements: minor completeness gap.
  - 5 vs 4 (L13309–13319): "Do not require every call to contain all five impact buckets for 5/5."
- **3/5** (L13323–13331): the problem matters but impact is broad, qualitative or incomplete. Simple meaning: "…not clearly enough how much it is costing or affecting the buyer."
  - Ex1 "A lot of time" with no follow-up: vague.
  - Ex2 "Losing money" accepted with no how or how much: known conceptually, not quantified.
  - Ex3 Only frustration explored; obvious time and business consequences ignored.
  - Ex4 "Probably … a few lakhs?" "Maybe": weak evidence. "If salesperson pushes this estimate as fact later, score can fall further" (L13389).
- **2/5** (L13393–13402): materially fails despite clear opportunities. Unquantified, buyer-stated impact ignored, jumps to the solution, unsupported impact claims, emotional focus while missing obvious economics, or forcing numbers the buyer cannot know. Simple meaning: "…missed most of what it was actually costing or affecting."
  - Ex1 "Conversion dropped by half" followed straight by the pitch: major impact ignored.
  - Ex2 "I personally listen to calls every night", answered with "Okay": clear signal missed.
  - Ex3 Forced fake precision, then "Let's say ₹5 lakh": creates a number. "If later used as factual ROI, severity can become 1" (L13453).
  - Ex4 Emotional pain mining on "It's annoying": pain amplification.
- **1/5** (L13467–13476): materially manufactures, exaggerates or misrepresents impact or value in a way that distorts the decision (invented loss, aspiration turned into guaranteed ROI, fabricated cost of inaction, forced catastrophe, manipulative emotional pain, knowingly unsupported numbers used to justify price). Simple meaning: "You materially distorted the value or cost of the problem …"
  - Ex1 "At least ₹10 lakh a year" with no basis, later used to justify price.
  - Ex2 Buyer goal of ₹6 lakh/month turned into "10X return".
  - Ex3 "Your company could fail", continued after the buyer denies it.
  - Ex4 "Imagine how much worse your family life will be": manufactured emotional impact.

### 1.7 Not enough evidence, overrides and caps
- Scenarios (L13533–13577):
  1. Recording starts after impact discovery: — unless later evidence validates it.
  2. Very early discovery call: "potentially —" rather than an automatic 2/5.
  3. Operational follow-up ("resend the invoice"): —.
  4. Buyer refuses to quantify and the seller respects it: score if enough qualitative evidence exists, otherwise —.
- No exact number ≠ low score; concrete time and opportunity impact can be 5/5 (L13581–13591).
- Exact numbers ≠ high score; they must be relevant, grounded and correctly interpreted (L13595–13603).
- 1/5 = clear evidence of distortion or manufacture; — = not enough evidence. "Missing quantification is not automatically fabricated quantification — and fabricated quantification is far worse than missing evidence" (L13619).
- Confidence is per impact claim. Example: "₹2–3 lakh, buyer estimate, Medium", not "observed loss ₹3 lakh" (L13641–13657).
- Number provenance must be tagged: Buyer-Stated / Calculated From Buyer Inputs / Seller Estimate (labelled) / Unknown-Unsupported (L13675–13684).
- Calculated ≠ guaranteed: keep the current gap separate from the solution effect. Current loss ≠ solution upside (L13688–13711).
- Value before price, but no manipulation before price (L13715–13722). Price must not drive impact discovery ("product costs ₹60,000, so I need to find ₹2 lakh of pain" is wrong, L13726–13731).
- Opportunity cost can outweigh direct loss; do not force a loss number (L13735–13745). Translate time carefully; no hourly rupee value without support (L13749–13759).
- One impact category can be enough for 5/5 (L13834–13844). Five buckets with shallow data is not 5/5 (L13848–13856).
- Range-based quantification is fine if the ranges have a basis (L13903–13910). Qualitative impact can still be material; "Do not under-score simply because there is no rupee amount" (L13914–13919).
- Weak D11 can cause later price resistance, but "do not automatically duplicate the penalty in price handling" (L13867–13877).
- Do not score commercial outcome (L13971–13977). Final rule L13982.

### 1.8 Inputs needed
- Transcript text: **essential**. It carries numbers, hours, costs and buyer-described stress (L13661–13670).
- Timestamps: **essential** for evidence spans (L13994) and for judging whether impact was established *before* the presentation (L13860).
- Audio (tone, pauses): **helpful only**. "Audio can improve understanding of emotional significance but is not mandatory" (L13671).
- Earlier-call or CRM context: **helpful**. It matters when the recording starts mid-call or for follow-ups (Scenario 1).
- Product and price knowledge: **helpful**. Needed to catch "current loss = what product will recover" conflation and price-justification misuse (L13704–13731). (inference)

### 1.9 Inconsistencies and unclear points
- L13293: a worked example gives an undecided score ("4/5, perhaps even 5"). It should not be used as a gold label without adjudication (inference).
- 2/5 includes "makes unsupported impact claims" (L13400), while 1/5 is manufacturing that "distorts the buyer's decision" (L13469). The boundary rests on materiality and later use (L13389, L13453); a pipeline needs an explicit escalation rule (inference).
- L13860 lets D11 drop when the seller presents before impact is clear. D13 (premature recommendation, L15946) and D17 (premature ask) can penalise the same moment. D11 has an anti-duplication rule only for price handling (L13874–13877).
- Calibration table (L13623–13637) vs locked table (L14052–14066): the locked table adds "realistic downside/upside", "cost-of-inaction clarity" and "poorly connected or unsupported". The wording drifts but the meaning is compatible.
- The output example (L14026–14048) uses only a subset of the 35 fields listed at L13986–14022.
- L12686–12708 is a **cross-reference table** of one-line questions for D08–D12, not duplicated content.
- About 180 lines in my range end with a citation token "Brain 2.0", "Brain 2.1" or "Brain 3.0" (e.g. L12657, L12659, L12682). These look like source-citation residue from a chat export; the cited documents are not in this file (inference).

### 1.10 Size
Approx. 1,445 lines (L12625–14069), ~6,200 words.

---

## 2. Dimension 12 — Understanding How They Will Decide

### 2.1 Identity
- Simple Report Name: Understanding How They Will Decide.
- **No "Internal Meaning" line** in the header (L14071–14075), and no "Internal Skill" in the output format (L15442–15443).
- Category: How Well You Understand the Buyer.
- Lines: banner L14070, header L14071, lock sentence L15526; the dimension ends at L15528.

### 2.2 Purpose
L14081: did the salesperson clearly understand how the buyer will actually decide, including what needs to happen, what matters in the choice, what remains unresolved, and when a real decision can happen? A list (L14086–14095) includes "whether the decision itself is pending or only the process/payment is pending". Brain 2.0 is cited: PROCESS, i.e. what must happen for a legitimate decision, and a credible future-date decision needs date or trigger, reason, next action, known objections and an understood process (L14097–14098).

### 2.3 Boundaries
- Category 2 cross-reference, L14102–14132 (D08 WHO, D09 WHAT, D10 HOW now / WHAT tried, D11 HOW MUCH, D12 HOW / WHEN / based on WHAT). This is a **cross-reference table, not duplicated content**. It is the same one-liners as D11's L12686–12708, with slight wording drift.
- Decision process ≠ decision-maker: "My co-founder also needs to approve" belongs to D08 (WHO). "Comparing three options Thursday, then finance releases payment Friday" belongs to D12 (L14247–14256).
- Decision process ≠ next step: D12 owns the logic behind the decision; D18 owns whether a clear next step was agreed (L14260–14271).
- Decision process ≠ objection: "I need two days" is not automatically an objection. Ask how exactly the decision will be made (L14275–14293).
- D12 is not about controlling every decision. If the buyer honestly needs space after enough pushing, stop (L14297–14307).

### 2.4 Part of the call and context rules
- Late discovery, post-presentation and closing stages, wherever decision logic surfaces.
- Four core parts (L14135–14146): **A. Decision Process**, **B. Decision Criteria**, **C. Remaining Uncertainty**, **D. Decision Timing / Trigger**. "All four may not be relevant in every sale. The correct score depends on what was reasonably required."
- "Yes, but process" (decided, procurement pending) is not an open sale; move to execution support (L14472–14484).
- Future dates must be credible: date or trigger, reason, real next action, known major objections, understood process (L14488–14501).
- Event-based follow-up beats calendar-based follow-up (L14505–14518).
- Context types: early discovery (not applicable), extremely simple purchase, operational call, B2B multi-step, competitor evaluation, family crisis.

### 2.5 Core evidence signals ("evidence lenses, not a checklist", L14312)
- Process (L14316–14358): A remaining decision clear; B required steps; C process ownership; D sequence; E structured vs vague delay.
- Criteria (L14362–14399): A what matters most; B comparison criteria; C must-haves; D trade-offs; E disqualifiers.
- Remaining uncertainty (L14403–14434): A missing information; B risk; C comparison gap; D internal uncertainty; E decision anxiety vs real uncertainty ("Big decision है, थोड़ा nervous हूँ" vs "I still don't understand implementation").
- Timing (L14438–14468): A specific timing; B specific trigger; C legitimate reason; D real next event; E decision date vs payment date ("decision made, process pending" vs "decision not made").

### 2.6 Score bands
- **5/5** (L14522–14535): clear, evidence-grounded understanding of what is undecided, criteria, missing information, remaining steps, the required event, whether only operational process is pending, and when. Delay is categorised correctly, and no vague "follow up later" remains where more clarity was obtainable. Simple meaning: "You clearly understood how this buyer will make the decision, what matters in that decision and what has to happen next."
  - Ex1 Structured B2B: CTO integration check, then co-founder comparison; criteria integration, support and total cost; Thursday.
  - Ex2 Genuine 24 hours: "what exactly do you want to think through" isolates implementation confidence; vague delay becomes a specific variable.
  - Ex3 Decision separated from payment timing (money arrives on the 10th).
  - Ex4 Competitor evaluation: criteria plus priority (implementation), "not merely competitor names".
  - Ex5 Procurement week: "decision is made … what do they need from us?" Process friction, not sales resistance.
  - Ex6 Vendor contract ends 30 November; review in the last week of November: real trigger.
- **4/5** (L14654–14662): main process understood, one or two minor gaps (criteria not prioritised, one step vague, stakeholder meeting time not fixed, one risk lightly explored). Simple meaning: "…with only a few small gaps."
  - Ex1 Process clear, criteria slightly vague.
  - Ex2 Criteria clear, timing "probably next week".
  - Ex3 Operations-head input needed, meeting not scheduled: "minor execution gap".
- **3/5** (L14726–14734): some elements known, meaningful uncertainty remains. Simple meaning: "You understood part of how the buyer will decide, but the process was still too vague."
  - Ex1 "I need to think" answered with "Let's speak tomorrow": timing only.
  - Ex2 Three vendors, criteria never asked.
  - Ex3 "Finance has to approve", but whether the buyer already said yes is unclear.
  - Ex4 "Maybe next month" answered with a follow-up next month.
- **2/5** (L14797–14807): materially fails despite clear opportunities. Accepts "I'll think" without diagnosis, accepts vague timing, misses criteria, confuses process delay with objection or procurement with decision, follows up repeatedly without knowing what changed, assumes the timeline. Simple meaning: "You did not clearly understand what the buyer still needed to decide or how that decision would happen."
  - Ex1 "A few days" answered with "I'll call in three days": arbitrary timing, no event.
  - Ex2 Procurement treated as an objection and the pitch restarted.
  - Ex3 Competitor comparison reduced to "what price did they quote?"
  - Ex4 "Legal and finance need to review" answered with "So you're still unsure?": decision state misclassified.
- **1/5** (L14868–14877): materially distorts or overrides a legitimate process, harming decision quality, trust or autonomy. Simple meaning: "You materially mishandled or overrode the buyer's real decision process."
  - Ex1 Board approval above ₹5 lakh answered with "just pay the token now".
  - Ex2 Legal review answered with a fake "decide today or lose the price"; possible Being Professional Ethics FAIL.
  - Ex3 Family emergency answered with "Decide now".
  - Ex4 Keeps asking controlling questions after "I genuinely need some space" and substantial prior pressure.

### 2.7 Not enough evidence, overrides and caps
- Scenarios (L14930–14972):
  1. Early discovery call: "— / Not Applicable".
  2. Recording ends before decision discussion: —.
  3. Extremely simple purchase: **scoreable and can be positive** if the seller reasonably establishes that no other process exists. "Do not require artificial criteria questioning."
  4. Operational call (resend payment details): —.
- An immediate yes can still provide evidence (L14976–14985). A long cycle ≠ a strong process (L14989–14997). A short cycle ≠ a weak process (L15001–15007).
- "Missing decision-process evidence is not the same as poor decision-process understanding" (L15023).
- Confidence example: "next week after my meeting" gives Timing Next week, Trigger Meeting, Process Clarity Partial, Confidence Medium. "Do not invent the rest" (L15045–15065).
- Special rules:
  - "I need to think" is a category, not a process (L15082–15094).
  - Criteria can change during the call; update them (L15110–15117). Stated criteria vs behaviour: clarify, don't accuse (L15121–15128).
  - Prioritise criteria where relevant, but do not force a ranking (L15132–15141). Must-have vs nice-to-have (L15145–15152). Risk is part of the process (L15156–15164).
  - Pending states: information, stakeholder, commercial, timing deferred, genuine processing (L15168–15225).
  - A polite exit can look like process; look for specificity, a real next event, reciprocity, reason and criteria (L15229–15240).
  - A future date needs a reason (L15244–15251). The next action should be real (L15255–15262). Major objections must be known before a future date counts as credible (L15266–15271).
  - Process friction ≠ sales resistance: a "major Brain 4.0 guardrail" (L15275–15283).
  - Do not reopen a made decision (L15287–15294), and do not pretend the process is done when the decision isn't (L15298–15308).
  - The process can be nonlinear (Decision Ready → Evaluating), citing Brain 3.0 stages (L15312–15319). Buying signals change the process (L15323–15333).
  - A competitor objection should surface real criteria (L15337–15348).
  - Do not over-interrogate (L15352–15362). One vague detail should not destroy a strong process (L15366–15370). One specific date does not make a process strong (L15374–15382).
- Do not score commercial outcome (L15425–15431). Final rule L15436.

### 2.8 Inputs needed
- Transcript: **essential** (L15069–15077).
- Timestamps: **essential** for evidence spans.
- Audio: **helpful**, adding "processing/hesitation context but is not mandatory" (L15078).
- Earlier-call or CRM context: **helpful to important** for follow-up calls and operational calls (Scenario 4), and for knowing whether a decision was already made elsewhere (inference).
- Product knowledge: **low need**.

### 2.9 Inconsistencies and unclear points
- No Internal Meaning or Internal Skill line, unlike D11 and D13–D18.
- Severity enum lacks "Critical" (L15477), unlike D11 and D13–D18.
- **Contradiction:** the 2/5 typical patterns include "accepts 'I'll think' without diagnosis" and "accepts vague timing" (L14801–14802). Yet 3/5 Ex1 ("I need to think" → "Let's speak tomorrow", L14743–14755) is rated 3/5, and the near-identical 2/5 Ex1 ("I need a few days" → "I'll call in three days", L14816–14825) is rated 2/5. The rubric gives no stated difference between them. These two need owner adjudication before entering an eval set (inference).
- Not-enough-evidence Scenario 3 (L14957–14963) is filed under "—" but says the call can be scored positively.
- The decision-state enum (L15448: Exploring / Evaluating / Decision Process / Decision Ready / Commercially Committed / Process Pending / Deferred / Lost / Unknown) differs from D17's (L23462) and D18's (L25332).
- The 1/5 band overlaps D16, D17 and D18 for the same behaviours (stakeholder bypass, fake urgency, overriding processing). See section 10(d).
- Calibration (L15027–15041) vs locked table (L15511–15525): the locked table adds "risks", "misclassified" and "timing need or buyer autonomy".

### 2.10 Size
Approx. 1,459 lines (L14070–15528), ~5,800 words.

---

## 3. Dimension 13 — Matching the Right Solution

### 3.1 Identity
- Simple Report Name: Matching the Right Solution.
- Internal Meaning: "Solution Fit / Recommendation Quality / Problem-to-Solution Relevance" (L15534). The output format uses "…Problem-to-Solution Mapping" (L16801).
- Category: How Well You Move the Sale Forward.
- Lines: banner L15529, header L15530, lock sentence L16883; the dimension ends at L16885.

### 3.2 Purpose
L15542: did the salesperson recommend and prioritise the solution, product, plan, feature set or next action that fits this buyer's diagnosed problems, goals, constraints and ability to implement? The test is "Which part of what we sell makes sense for this specific buyer — and why?" (L15546). It must use problems, goals, impact, current approach, previous attempts, budget, implementation capacity, decision criteria and risks. Brain 2.1's mapping chain is cited: Current Problem → Consequence → Needed Capability → Relevant Feature → Mechanism → Expected Outcome → Evidence (L15560).

### 3.3 Boundaries
- D13 is "what should we recommend?"; D14 is "how well did we explain it?" (L15566–15587). The text gives paired examples: perfect recommendation explained badly is D13 5/5 and D14 2/5; a beautifully explained wrong fit is D13 1–2/5 and D14 5/5. L15568–15586 is this **contrast block, not duplication**.
- Category 2 builds the buyer model and Category 3 uses it (L15591–15608). D09–D12 are listed as one-line questions, followed by "Diagnosis → Prescription", not "Product first → find reasons afterward". This is a **cross-reference table**.
- Feature-to-outcome emphasis: D13 asks whether the correct capability was chosen; D14 asks how clearly the chain was explained (L15887–15892).
- Feature dumping: D13 scores a poorly prioritised recommendation; D14 scores a good recommendation explained verbosely (L16605–16614).
- Commercial fit: D15 goes deeper, but D13 "should not completely ignore viability" (L16711–16720). Fit comes from need first; price handles feasibility afterwards (L16700–16707).
- Do not double-penalise one upstream miss: D09 and D13 can both be low, but their explanations must be distinct (L16631–16641).

### 3.4 Part of the call and context rules
- Presentation and recommendation, after discovery. "Discovery earns the recommendation" (L15612–15625). The internal test is "Can I explain exactly why this prospect needs each thing I am about to recommend?"
- Early product request ("पहले product बताओ"): a short product glimpse and a return to discovery is fine; a full recommendation before understanding is premature (L15937–15942). Premature recommendation is negative evidence (L15946–15954).
- Fit varies by product; qualification is partly product-specific (L15656–15672). The right answer may be a different plan (L15676–15692, Brain 2.1 sequence: ask why B → understand → explain why A → compare consequences → re-evaluate), "no sale" (L15696–15708), "keep what you already have" (L15712–15722), or a partial solution (L15726–15735).
- Follow the primary gap, not the features the seller likes (L15739–15750).
- One-product companies still have a fit decision: yes / no / not yet / conditional (L16395–16404).

### 3.5 Core evidence signals
Five lettered things (L15629–15640): **A Fit**, **B Relevance**, **C Prioritization**, **D Feasibility**, **E Recommendation Integrity** ("would the salesperson still recommend this option if a different option — or no sale — were better?").

Numbered signals (L15754–15884):
- problem → needed capability → recommendation;
- goal-to-solution fit;
- impact-to-solution fit (uses D11);
- previous-attempt fit (uses D10);
- implementation fit;
- buyer readiness (team, data, bandwidth, ownership, realistic expectations);
- prioritisation ("For you, three things matter most…");
- capability gap;
- expected outcome (realistic, not "guarantees conversion doubles");
- evidence for fit (proof only matters if it supports why this solution fits this buyer).

Locked rules:
- Matching ≠ selling the most expensive plan (L15896–15903), even if the buyer purchases.
- Matching ≠ selling the cheapest plan (L15907–15912).
- Recommendations should be confident but updateable (L15916–15924). Do not defend the first recommendation out of ego (L15928–15933).

### 3.6 Score bands
- **5/5** (L15958–15973): clearly fits the diagnosed situation. It addresses the primary problem, supports the outcome, reflects impact, accounts for previous attempts, preserves what works, fits readiness, prioritises only relevant capabilities, separates must-have from nice-to-have, stays updateable and does not sacrifice fit for revenue. "A correct no-sale or smaller-plan recommendation can receive 5/5." Simple meaning: "You recommended what actually fit this buyer — not simply what you wanted to sell."
  - Ex1 Personalised capability match (not lead generation, not another training library; call analysis + manager coaching + accountability), grounded in problem, current approach, previous failure and desired state.
  - Ex2 Recommends the lower plan (Premium unnecessary): fit over revenue.
  - Ex3 Recommends the higher-support plan because three programs failed on implementation: addresses the failure mechanism.
  - Ex4 "Keep [the CRM]": no unnecessary replacement.
  - Ex5 Revises the recommendation after the buyer reveals in-house operations: evidence beats attachment.
  - Ex6 Buyer needs done-for-you lead generation; company offers coaching only, so "not the right answer": correct no sale.
- **4/5** (L16063–16071): clearly appropriate, minor gaps (a secondary capability overemphasised, a useful feature missed, implementation needs not fully explored, prioritisation could be tighter, some unnecessary features). Simple meaning: "…right solution overall, with only a few small relevance gaps."
  - Ex1 Right plan, five capabilities explained, only three relevant.
  - Ex2 Correct recommendation, manager weekly participation not confirmed.
  - Ex3 A minor adoption issue is not reflected.
  - 5 vs 4 (L16112–16126): 5 is specific, prioritised, buyer-grounded, implementation-aware and commercially honest; the seller "could clearly defend why this is the best fit and why other parts are not needed".
- **3/5** (L16130–16138): broadly relevant, shallow personalisation (generic recommendation, relevant features mixed with irrelevant ones, weak tie to discovery, unclear implementation fit, default plan). Simple meaning: "The solution probably fits, but the recommendation was still too generic or only partly personalized."
  - Ex1 Sales coaching "because you want more sales".
  - Ex2 Feature list where only call analysis and visibility fit.
  - Ex3 "I can spend ₹50K" → "Then Standard is right": fit reasoning based on budget only.
  - Ex4 Right program, but emphasis on content and templates instead of accountability.
- **2/5** (L16207–16217): materially generic, premature or mismatched (recommended before discovery, misses the primary problem, ignores failed attempts, replaces what works, ignores capacity, upsell-driven, unrelated features). Simple meaning: "Your recommendation did not fit the buyer's real situation closely enough."
  - Ex1 "Sales are low" → "Premium Closer Program is exactly what you need".
  - Ex2 Lead generation sold for a conversion problem.
  - Ex3 "50 more modules" after the buyer said information is not the issue.
  - Ex4 Replaces a working CRM.
  - Ex5 Four-hour/week program for a buyer with under one hour/week.
- **1/5** (L16279–16288): knowingly or clearly recommends a materially wrong, unsuitable or harmful solution despite evidence (cannot solve the need, revenue-driven, refuses to update, conceals a limitation, pushes despite inability to implement, foreseeable harm). Simple meaning: "You recommended something that clearly did not fit the buyer."
  - Ex1 Claims coaching will deliver done-for-you appointment setting: material mismatch; potential "Being Professional: Ethics concern".
  - Ex2 "Premium is the only plan that will work" because of commission.
  - Ex3 Pushes a program after the buyer repeatedly says the participation is impossible.
  - Ex4 "No, Plan A is what I recommend" without addressing the buyer's evidence.

### 3.7 Not enough evidence, overrides and caps
- Score only when a meaningful recommendation opportunity exists (L16347–16351). Scenarios (L16355–16391):
  1. Discovery-only: —.
  2. Recording ends before presentation: —. "Do not infer what salesperson would have recommended."
  3. Fixed single product: score normally if a fit decision occurred, otherwise — may be appropriate.
  4. Follow-up after an earlier recommendation: "— / lower-confidence score depending on how much rationale appears."
- The buyer asking for a plan does not make it right; understand why, then evaluate (L16408–16414). A different plan is not automatically upselling: "Judge fit. Not price direction" (L16418–16425).
- "Missing recommendation evidence is not poor recommendation quality" (L16441).
- Confidence: missing implementation-capacity data can give 4/5 with Medium confidence. "Do not automatically reduce the score because one contextual area is missing" (L16463–16476).
- Special rules:
  - Trace each recommended capability back to buyer evidence (L16494–16505).
  - Not every problem needs a product feature (L16509–16516).
  - The primary problem controls priority (L16520–16527). A previous failure must change the recommendation (L16531–16536). Preserve current strengths (L16540–16547).
  - Classify capabilities as Required / Useful / Irrelevant (L16551–16559). Implementation requirements are part of fit (L16563–16570).
  - Expectation quality: don't call fit strong until a false expectation is corrected (L16574–16581).
  - The seller may challenge the buyer's preferred option (evidence-based, explained, autonomy preserved) or accept the buyer's better reasoning (L16584–16601).
  - Buyer agreement supports fit but does not prove it (L16645–16654). The recommendation must fit D12 decision criteria too (L16658–16666).
  - Problem fit vs buyer fit (L16670–16681). Category fit vs delivery-model fit (L16685–16696).
  - No sale can be excellent execution: 5/5 with ₹0 revenue (L16724–16736).
- Do not score commercial outcome (L16781–16789). Final rule L16794.

### 3.8 Inputs needed
- Transcript: **essential** (L16480–16490).
- Timestamps: **essential**.
- **Product, plan and offer catalogue: essential** (inference, strongly implied). The model cannot judge "product cannot solve stated need", Basic vs Premium contents, required participation, integrations or "keep vs replace" without knowing what is sold and what each plan includes (L15676–15692, L16297–16305, L16563–16570).
- Earlier-call or CRM context: **important** for follow-up calls (Scenario 4) and for D09–D12 findings from earlier calls.
- Audio: "can add context but is not mandatory" (L16490).

### 3.9 Inconsistencies and unclear points
- Internal-meaning wording differs between the header (L15534) and the output format (L16801).
- 4/5 Ex2 says "One meaningful readiness detail remains" (L16099), while the 4/5 definition says "minor" gaps.
- Section 39 heading typo "UPSelling" (L16418).
- 1/5 Ex2 depends on seller motive ("because of commission", L16317), which is usually not observable in a transcript (inference).
- Scenario 4 offers "— / lower-confidence score" without a rule for choosing between them (L16389–16391).
- Ethics flag label is "Ethics concern" here (L16308) but "Ethics FAIL" elsewhere.
- Calibration (L16445–16459) vs locked table (L16868–16882): the locked table adds "may correctly recommend a smaller plan, complement or no sale" (5/5), "poorly prioritized" (2/5) and "or knowingly prioritizes revenue over fit" (1/5).

### 3.10 Size
Approx. 1,357 lines (L15529–16885), ~6,000 words.

---

## 4. Dimension 14 — Explaining the Solution Clearly

### 4.1 Identity
- Simple Report Name: Explaining the Solution Clearly. Internal Meaning: "Solution Clarity / Mechanism Explanation / Buyer Comprehension" (L16891).
- Category: How Well You Move the Sale Forward.
- Lines: banner L16886, header L16887, lock sentence L18380; the dimension ends at L18382.

### 4.2 Purpose
L16899: did the salesperson explain the recommended solution so the buyer could easily understand what it does, how it works, why it matters, what implementation looks like and what can realistically be expected? Brain 2.0's standard is cited: Diagnosis → Relevant Component → Benefit → Outcome → Visualize → Check Certainty (L16913).

### 4.3 Boundaries
- D13 is the right thing; D14 is making that thing easy to understand. Both directions have examples (L16918–16952).
- D15 owns price positioning, affordability, terms, discounts and payment. Not understanding *what they are paying for* is partly a D14 failure (L16956–16967).
- D16: "I don't understand how implementation works" is a clarity question for D14 and a diagnosis and resolution question for D16 (L16971–16979).
- D03 Tone/Pace owns vocal delivery. Talking too fast is a D03 problem, while the explanation itself can still be strong (L16983–16992).
- Product knowledge ≠ explanation skill (L17151–17157).
- Certainty types (Brain 2.0, L18060–18073): seller/company trust, solution certainty, self/execution certainty, outcome certainty. "Will my team use it?" may be an execution or self-certainty issue, not a clarity failure.

### 4.4 Part of the call and context rules
- Presentation and demo segments, plus answers to product questions.
- Core question (L16996–17005): could the buyer answer what it is, how it works, why it is useful to them, what happens when they start, what they will need to do, and what to realistically expect?
- "Can they repeat it back?" is a conceptual test; do not literally require "repeat it back to me" (L17009–17021).
- Clarity is relative to buyer knowledge (technical vs business buyer, L17372–17382) and buyer priority (L17386–17392). Jargon must serve understanding, not status (L17122–17134). Simplicity is not dumbing down (L17138–17147).
- Presentations should be interactive: explain → check → adapt → next (L17310–17315). Buyer questions should change the explanation; no "I'll cover that on slide 17" (L17319–17326). Know when to stop: buying signals, implementation questions, or repeated explanation adding nothing (L17350–17357).

### 4.5 Core evidence signals
There is no lettered list. The explanation structure (L17039–17064) is Relevant Capability → Function → Mechanism → Impact → Outcome → Implementation → Evidence/Proof → Check Understanding. Feature → Function → Impact → Value (L17096–17107).

Signals (L17161–17306):
- what it does;
- how it works (mechanism, "not magic", L17025–17035);
- why it helps (the "So what?" chain);
- connection to the buyer's problem;
- implementation (setup, onboarding, time, integrations, roles, timeline, support);
- scope;
- limitations;
- expected outcome (what is controlled vs what depends on implementation vs what is merely expected);
- proof (supports logic, does not replace it);
- visualisation;
- checking understanding ("Does that make sense?" is not enough by itself; better checks reveal comprehension, L17298–17306).

Also: buyer-specific language (L17111–17118); do not overload (L17329–17333); more information ≠ more clarity (L17337–17346); repeating in different words is not clarity (L17361–17368); explain differentiation through mechanism (L17396–17402); hype must not replace mechanism, "truth wins" (L17406–17415); clear explanation of risk areas such as refund, support and data security creates value (L17419–17431).

### 4.6 Score bands
- **5/5** (L17435–17455): very easy to understand without oversimplifying or exaggerating. Clear mental model of what, how, why, connection, implementation, buyer role, realistic change, limitations and next. Uses buyer language, mechanism and translated jargon; prioritises; checks understanding; adapts; stops when clear. Simple meaning: "The buyer could clearly understand what the solution does, how it works and why it matters to them."
  - Ex1 Call analysis: input, process, output, practical effect.
  - Ex2 "Three courses already", so emphasise the implementation loop: why it differs, plus mechanism.
  - Ex3 Onboarding steps in sequence: concrete, sequential, easy to visualise.
  - Ex4 "AI will train my team automatically?" "Not entirely…": capability, limitation, responsibility.
  - Ex5 Skips analytics depth to show the manager workflow the buyer asked about.
  - Ex6 Buyer correctly summarises the workflow: repeat-back satisfied.
- **4/5** (L17546–17556): effective, minor gaps (something overexplained, some jargon, implementation brief, one limitation missing, one feature weakly connected, minor overload). Simple meaning: "You explained the solution well, with only a few small clarity gaps."
  - Ex1 "Semantic analysis layer" explained well when asked: minor miss, good recovery.
  - Ex2 Strong mechanism, onboarding described only broadly.
  - Ex3 Two minutes on an unneeded feature.
  - Ex4 One clarification needed (how alerts arrive).
- **3/5** (L17628–17638): general idea gets across, but parts are vague, generic, too technical or disconnected (features without mechanism, vague implementation, too much information, repeated basic clarification questions). Simple meaning: "The buyer got the basic idea, but important parts were still unclear or unnecessarily complicated."
  - Ex1 Component list; buyer asks what call analysis shows.
  - Ex2 Circular "more accountable".
  - Ex3 Heavy jargon, simplified only after the buyer asks ("Explanation works eventually").
  - Ex4 Implementation never explained until the buyer asks.
  - Ex5 15-minute feature tour; buyer later asks something already covered.
- **2/5** (L17706–17718): noticeable confusion or major gaps (feature dumping, unclear mechanism or implementation, unexplained jargon, generic promises, buyer repeatedly asks what it does, adds information while the buyer is confused). Simple meaning: "Your explanation left the buyer unclear about important parts of the solution."
  - Ex1 Feature dump.
  - Ex2 "That's what the AI does".
  - Ex3 Buyer says "I don't understand" repeatedly; seller adds more terms, features and proof.
  - Ex4 Material implementation burden omitted (manual uploads, 4 h/week). "Depending on whether omission was deliberate, Being Professional may also be affected" (L17771).
  - Ex5 "Transform your business" / "Everything becomes more efficient".
- **1/5** (L17787–17796): materially misleads, creates a fundamentally false understanding, or hides operational reality (false capability, "fully automatic" when major human work is needed, deliberately hidden requirements, unsupported outcomes as guaranteed, contradicting known limits, buyer deciding on a false model). Simple meaning: "The buyer was given a materially inaccurate or misleading understanding of the solution."
  - Ex1 "Automatically coach and manage your entire sales team" (Ethics concern).
  - Ex2 "Plug-and-play?" "Yes, pretty much", despite a four-week setup.
  - Ex3 "Conversion will definitely double".
  - Ex4 Confirms the buyer's false belief that "your team will … make all our sales calls".

### 4.7 Not enough evidence, overrides and caps
- Scenarios (L17853–17895):
  1. Discovery-only: —.
  2. Recording starts after the presentation ("Okay, sounds clear"): —. "Do not infer quality from one reaction."
  3. A one-line product mention, then the call ends: —.
  4. Follow-up call without the original explanation: — may be correct.
- A simple product with a short explanation can be 5/5; "Do not reward length" (L17899–17905). A complex product doesn't need a lecture; completeness ≠ exhaustive detail (L17909–17918).
- Buyer questions do not automatically mean a bad explanation and can be buying signals. Score avoidable confusion vs healthy evaluation (L17922–17932). No questions does not mean clear; "haan… okay…" is not proof (L17936–17941).
- "Missing explanation evidence is not poor explanation quality" (L17957).
- Confidence example: transcript clear but buyer audio partly missing gives 4/5 with Medium confidence. Canonical: "Confidence = certainty that available evidence supports the comprehension judgment" (L17979–17997).
- Special rules:
  - Judge clarity from the buyer's perspective (L18020–18026).
  - "Why should this specific prospect care?" before every detail (L18030–18037). Top relevant capabilities first, in buyer-relevance order (L18041–18046).
  - Mechanism before big outcome (L18050–18056). Explain who does what (L18077–18086). Explain the sequence (L18090–18094).
  - Analogies must stay accurate (L18098–18103, including the "X-ray for the sales conversation" analogy). Stories should explain, not distract (L18107–18113). Proof must match the point (L18117–18124). Say limitations before they become surprises (L18128–18133).
  - Clarity should survive challenge (L18137–18143). Re-explain differently, not louder (L18147–18156). Recovery counts: "score the overall relevant pattern including recovery" (L18160–18165).
  - One minor unclear detail should not destroy the score (L18169–18173), but one material misunderstanding (e.g. done-for-you vs do-it-yourself) "matters a lot" (L18177–18183).
  - Buying signals may mean stop explaining (L18187–18194). Don't fix confusion by adding features (L18198–18205). Clarity ≠ persuasion intensity (L18221–18227).
- Do not score commercial outcome (L18272–18279). Final rule L18285.

### 4.8 Inputs needed
- Transcript: **essential** (L18001–18011).
- Timestamps and turn timing: **important**. Several judgments are about duration and sequencing ("25-minute uninterrupted explanation" L17312, "15-minute feature tour" L17696, "two minutes on a secondary feature" L17592, stopping after buying signals L18348).
- Audio: **helpful** ("pace, emphasis, confusion tone"; "not mandatory for most Dimension 14 findings", L18012–18016).
- **Product knowledge: essential for 1/5 and for limitations.** You cannot detect a "materially false" capability claim or a hidden setup burden without ground truth about the product (L17805–17829) (inference).
- Earlier-call context: **helpful** for follow-ups (Scenario 4) and for the diagnosed problem the explanation should connect to.

### 4.9 Inconsistencies and unclear points
- 4/5 Ex1 (jargon, clarified when asked) and 3/5 Ex3 (heavy jargon, simplified after a request) differ only by degree. The line between "slight" and "heavy" jargon is not defined.
- Rule 68 (recovery counts) vs 3/5 Ex3, where recovery still leaves 3/5: partial credit for recovery, with the amount unspecified.
- 2/5 Ex4 (omission) vs 1/5 Ex2 (asked directly and denied): the boundary is intent and whether the buyer asked. L17771 defers ethics to "whether omission was deliberate", which is often unobservable (inference).
- Calibration (L17961–17975) vs locked table (L18365–18379): the locked table adds "accurate" (5/5), "overly technical" (3/5) and "around mechanism, relevance, scope or implementation" (2/5).
- Boundary sections L16918–16992 are cross-reference blocks, not duplication.

### 4.10 Size
Approx. 1,497 lines (L16886–18382), ~6,300 words.

---

## 5. Dimension 15 — Talking About Price & Budget

### 5.1 Identity
- Simple Report Name: Talking About Price & Budget. Internal Meaning: "Budget Qualification / Price Communication / Commercial Fit" (L18388).
- Category: How Well You Move the Sale Forward.
- Lines: banner L18383, header L18384, lock sentence L19878; the dimension ends at L19880.

### 5.2 Purpose
L18396: did the salesperson discuss money "clearly, calmly and realistically", understanding the buyer's financial context, presenting price appropriately, and distinguishing affordability, value, expectation and payment timing rather than treating every money concern the same? The capability list (L18398–18409):
- discuss budget without awkwardness;
- separate capacity from willingness;
- understand the expected range;
- state price clearly;
- don't hide it artificially and don't apologise for it;
- let the buyer react;
- no panic discounting;
- transparent legitimate options;
- separate logistics from resistance;
- don't force commercially inappropriate purchases.

Brain 2.0 (clear price, pause, diagnosis before discount, composure) and Brain 3.0 (budget diagnosis) are cited (L18410–18412).

### 5.3 Boundaries
- D16 owns diagnosis and resolution once the buyer resists. Example: "The investment is ₹60,000. Is that within the range…?" is D15. "Compared to what?" after "too expensive" belongs "primarily under Handling Objections" (L18416–18447).
- D11 owns what the problem costs; D15 owns how price was discussed against that reality. "Do not score the same economic discovery twice" (L18451–18461).
- D13 owns which plan fits; D15 owns whether it is affordable and was discussed properly. Don't downgrade to a cheaper plan that can't solve the need, or push a pricier one because the buyer can afford it (L18465–18473).
- D17: stating price is not asking for the sale (L18477–18485).
- Different plan ≠ discount. D13 decides fit; D15 handles the commercial discussion (L19512–19517).
- Price delivery and objection diagnosis are separate. A D15 5/5 with a D16 2/5 is possible (L19659–19667).

### 5.4 Part of the call and context rules
- Any budget qualification (often in discovery), the price reveal, payment options, logistics, and post-yes payment friction.
- "Budget issue" is too broad (L18489–18504). Five states:
  1. Cannot Afford.
  2. Can Afford, Did Not Allocate.
  3. Can Afford, Expected Lower Price.
  4. Can Afford, Does Not See Enough Value.
  5. Can Afford, Cash-Flow Timing Problem.
- Budget ≠ willingness to pay (L18508–18519). Price expectation ≠ affordability (L18523–18534). Cash flow ≠ affordability (L18538–18545). Payment logistics ("EMI है?", card, GST invoice, UPI, split) ≠ price resistance and may signal intent (L18549–18557).
- Price timing is contextual. Late ≠ good and early ≠ weak; reveal "when the buyer can meaningfully interpret it" (L18561–18589). No price-shock engineering (hiding price to build sunk cost) (L18593–18599).
- Delivery: "State clearly → Pause → Ask the relevant question" (L18603–18612). Do not apologise for a justified price (L18616–18624). Confidence ≠ aggression or shaming (L18628–18636). Silence after the price is not automatically bad; don't rescue the buyer from silence (L18640–18653).
- Early budget statements are low-confidence data; requalify when context changes, and never weaponise earlier statements (L18764–18786).
- Value context should exist before price is judged, but this does not justify hiding price (L18790–18803). No fake ROI to defend price; D11's aspirational-upside rule carries over (L18807–18814).
- Payment friction after a yes is not decision failure (L18857–18866). Friction types: Technical, Cash Flow, Timing, Authority, Emotional Hesitation (L18870–18882).
- A token must have a legitimate purpose (L18886–18893). Commercial mechanisms should solve friction, not manufacture commitment (L18897–18902).

### 5.5 Core evidence signals
Numbered sections L18657–18760:
- budget context (range, allocation, affordability, expected price, cash flow, constraints, willingness; no explicit "What's your budget?" is required);
- price expectation and anchor (competitor, previous purchase, available budget, doing nothing; "Compared to what does ₹60,000 feel high?");
- affordability from evidence, never from company size, clothes, title or perceived wealth;
- allocation;
- willingness to pay;
- cash flow (genuine timing vs affordability vs polite exit: "Do not guess");
- commercial options (full, EMI, phased, different plan; no fake options);
- discount discipline (approved, justified, tied to real terms; not panic);
- transparency (price, inclusions, structure, conditions, taxes and terms).

### 5.6 Score bands
- **5/5** (L18905–18920): strong clarity and judgment. Understands budget context, separates affordability from willingness, knows the expectation where needed, reveals price at the right time, states it calmly, lets the buyer react, no apology or panic, no premature discount, separates cash flow and logistics from objections, explains options transparently, preserves autonomy. Simple meaning: "You made the money conversation clear, calm and realistic — without awkwardness, guessing or pressure."
  - Ex1 Price stated with a range check; buyer expected ₹40K; seller identifies an anchor mismatch, not an affordability problem.
  - Ex2 Genuine inability to pay, respected without shame. A no sale is still 5/5 (Brain 3.0 cited).
  - Ex3 "₹60K okay, today difficult, funds on the 10th": classified as timing.
  - Ex4 Card and GST invoice questions answered without re-pitching.
  - Ex5 Seller waits through silence; no discount.
  - Ex6 Approved two-part payment explained transparently.
- **4/5** (L19019–19029): strong, with a minor miss (budget context slightly late, mildly awkward delivery, an option less clear, speaks slightly too quickly after the price, one small premature concession, expectation could be explored deeper). Simple meaning: "…well, with only a few small commercial misses."
  - Ex1 Price revealed late (₹30K expected vs ₹60K) but handled well.
  - Ex2 "So… the investment is ₹60,000" with slight hesitation.
  - Ex3 Correct cash-flow diagnosis, options overexplained.
- **3/5** (L19089–19099): workable but inconsistent (awkward price statement, generic budget question, expectation not understood, slight discount reflex, price left late without major harm, affordability and value partly mixed, options without diagnosis). Simple meaning: "The money conversation worked, but parts of it were vague, awkward or weakly diagnosed."
  - Ex1 "Budget कितना है?" "Depends", accepted.
  - Ex2 Price followed immediately by inclusions, defending before any reaction.
  - Ex3 "₹60K?" answered with an unprompted "₹55K": negotiating against oneself.
  - Ex4 "Can afford, not sure it's worth it" answered with EMI talk ("some conversation remains productive").
- **2/5** (L19155–19167): repeated confusion, pressure or poor judgment (budget never explored despite relevance, artificial late surprise, apologetic delivery, panic discounting, assumed affordability, willingness confused with capacity, payment plan pushed without understanding, every money response treated as "budget", concessions without logic). Simple meaning: "Your price and budget discussion created avoidable confusion or weakened the commercial conversation."
  - Ex1 Price-shock engineering: 50 minutes, repeated asks, then ₹2 lakh.
  - Ex2 ₹50K then ₹45K into silence.
  - Ex3 EMI offered to a value doubt.
  - Ex4 "If you're serious … you'll find the money" (professionalism may be affected).
  - Ex5 Fake "only today" option. "If deliberately false and material: this may become 1/5 + Ethics FAIL" (L19235).
- **1/5** (L19239–19249): materially misrepresents price, terms or financial reality, or uses commercial mechanisms manipulatively (fake price increase or discount, false terms, hidden charges, misrepresented affordability, trap tokens, pressure despite genuine inability that crosses ethical lines). Simple meaning: "The price or budget conversation materially misled or commercially pressured the buyer."
  - Ex1 Fake ₹1 lakh "normal" price (Ethics FAIL).
  - Ex2 "Tomorrow price becomes ₹80K", known false.
  - Ex3 Non-refundable ₹5,000 token described as "means nothing".
  - Ex4 Hides a mandatory ₹25K implementation fee when asked "full amount?".

### 5.7 Not enough evidence, overrides and caps
- Scenarios (L19304–19340):
  1. Discovery-only: —.
  2. Recording ends before price: —.
  3. Follow-up after an earlier price discussion: evaluate current behaviour if sufficient, otherwise "— / lower-confidence score".
  4. Free product: "— / Not Applicable".
- No budget question ≠ low score if commercial context was already understood (L19343–19353). Asking "What's your budget?" ≠ high score; the number's meaning (maximum, allocated, expected, preference, anchor) matters (L19357–19368).
- "Missing price evidence is not poor price handling" (L19384).
- Confidence example: "I can probably manage it" gives Financial Capacity Possible, Confidence Low/Medium (L19406–19419). This section has no "Score = … / Confidence = …" canonical line, unlike the other dimensions.
- Special rules:
  - Record price exactly: amount, currency, tax context. "Commercial numbers are high-risk facts" (L19442–19453).
  - Price, value, affordability and willingness are different problems; this is "one of the locked Brain 4.0 rules" (L19457–19460).
  - "Too expensive" is not a diagnosis. D15 captures commercial state; D16 scores the deeper diagnosis (L19464–19475). Negotiation ≠ affordability (L19479–19486).
  - No discount before knowing why price is resisted (L19489–19497). Concessions need commercial logic (L19501–19508). A cheaper plan must follow fit; "recommendation comes first, choice second", no "Silver or Gold?" before fit (L19521–19526).
  - Price can be a qualification tool (L19530–19537). Don't punish a genuine budget constraint (L19541–19551).
  - Awkwardness may be a confidence gap, not a knowledge gap; coaching should diagnose knowledge, confidence, judgment or wording (L19555–19565).
  - No inference from status signals (L19569–19577). Company money ≠ personal money (L19581–19589). Approximate ranges are fine (L19593–19599). Budget may change after value is clear (L19603–19610). Price may change with scope (L19614–19622).
  - Installments are not a price reduction ("Only ₹20K") (L19626–19634). EMI doesn't solve a value gap (L19638–19645). A discount doesn't solve every objection (L19649–19655).
  - Don't penalise delivery because the buyer reacts negatively (L19671–19675). Buyer acceptance ≠ 5/5 (L19679–19686).
  - Payment questions may be buying signals (L19690–19698). Payment failure ≠ deal failure (L19702–19707). Preserve dignity (L19711–19718).
- Do not score commercial outcome (L19762–19769). Final rule L19774.

### 5.8 Inputs needed
- Transcript: **essential** (price, range, terms, discounts, EMI, statements; L19423–19432).
- **Turn timing and audio: important.** Pause after price, panic fill and the "slightly nervous" delivery (4/5 Ex2) need timing and voice. "For exact price-delivery tonality, audio increases confidence" (L19433–19438). The output field "Price Confidence … / Audio Unavailable" (L19801) and "Pause After Price: … Panic Fill / Unknown" (L19800) assume this.
- **Price book and commercial policy: essential for 1/5 and discount basis** (inference, strongly implied): real list price, approved discounts and campaigns, EMI and split availability, real deadlines, mandatory fees, token refundability (L19258–19300, L19812).
- Earlier-call or CRM context: **helpful** for follow-ups (Scenario 3) and for earlier budget statements.

### 5.9 Inconsistencies and unclear points
- **Overlap with D16:**
  - D15 says "Compared to what?" belongs primarily to D16 (L18443–18447).
  - But D15's own signal section recommends asking "Compared to what does ₹60,000 feel high?" (L18684), and D15 5/5 Ex1 (L18929–18945) is almost the same scenario as D16 5/5 Ex1 (L20711–20734).
  - The same exchange can be credited or penalised twice. The pipeline needs an ownership rule; one candidate is: D15 = classifying the commercial state, D16 = diagnosis and resolution steps (inference).
- Late-price gradient: 4/5 "budget context comes slightly late", 3/5 "price is left too late without major harm", 2/5 "artificial late price surprise". These are graded by harm, with no explicit test.
- Discount gradient: one unprompted reduction is 3/5 (Ex3); repeated reductions into silence are 2/5 (Ex2).
- 2/5 Ex5 (fake "only today" option) can escalate to 1/5 depending on "deliberately false", which needs policy knowledge.
- "Not Applicable" and "Not Enough Evidence" both display "—" (Scenario 4).
- Calibration (L19388–19402) vs locked table (L19863–19877): the locked table adds "allocation … logistics" to 5/5 and expands the 2/5 list.

### 5.10 Size
Approx. 1,498 lines (L18383–19880), ~6,300 words.

---

## 6. Dimension 16 — Handling Objections

### 6.1 Identity
- Simple Report Name: Handling Objections. Internal Meaning: "Objection Diagnosis / Root-Blocker Resolution / Decision Uncertainty Management" (L19886).
- Category: How Well You Move the Sale Forward.
- Lines: banner L19881, header L19882, lock sentence L21765; the dimension ends at L21767.

### 6.2 Purpose
L19894: when the buyer expressed resistance, hesitation, doubt or a reason not to proceed, did the salesperson understand what was actually unresolved and help examine or resolve it "without arguing, guessing or pressuring"? "The first statement is evidence. It is not necessarily the final diagnosis" (L19905–19906). Brain 2.0 is cited: "Objection = information … hypothesis", with the loop Hear → Pause → Acknowledge → Clarify → Isolate → Diagnose → Resolve → Confirm → Decide. Brain 2.1 is cited: Objection → Possible meanings → Isolation → Diagnosis → Evidence → Root blocker → Resolution → Re-check → Decision (L19907–19914). Core principle (L19918–19923): not "how cleverly did they overcome" but whether they understood what the objection represented, resolved what could truthfully be resolved, and knew whether to continue, clarify, involve someone, pause or stop.

### 6.3 Boundaries
- **D15** owns budget qualification, price timing and delivery, affordability, options, discount discipline and logistics. **D16** owns what happened once resistance appeared: pause, clarify, isolate, "compared to what", diagnose, respond, re-check (L19927–19958).
- **D12**: "I need to speak to my co-founder" is a process question for D12; D16 asks whether, as resistance, it was diagnosed correctly (genuine requirement vs uncertainty vs something else) (L19962–19970).
- **D17**: the later re-ask belongs to D17; D16 asks whether the blocker was resolved enough to justify returning to a decision (L19974–19980).
- **D18**: a blocker that can't be resolved now; D16 identifies it, D18 converts it into a next step (L19984–19991).
- **D06 Building Connection** owns the relationship; D16 owns the reasoning around resistance (L19995–20002).
- **D03 Tone/Pace**: calmness belongs "partly under Tone/Pace". D16 asks whether calmness supported better reasoning (L21447–21454).

### 6.4 Part of the call and context rules
- Any moment of resistance, mostly after price or the close attempt, but also earlier.
- An objection is not always a rejection (L20006–20019). A "no" is not always an objection: "clarify once if useful, then respect it"; "Every no hides a yes" is over-pushing (L20023–20032).
- Context matters: genuine crisis, emotional processing, explicit need for space, prior pressure. Know when to give space (L20659–20672). Brain 2.1 conflict rules: processing integrity > closing urgency, fit > seller conviction, shared decision rules > one-call close, autonomy > momentum, truth > confidence, curiosity > rebuttal. Know when to stop (L20676–20682).

### 6.5 Core evidence signals
Master loop, 10 steps (L20036–20057): 1 Hear, 2 Pause, 3 Acknowledge, 4 Clarify, 5 Isolate, 6 Diagnose, 7 Use Evidence, 8 Resolve, 9 Re-check, 10 Return to Decision ("only if state has changed").

Step detail (L20062–20219):
- Hear the exact words; don't translate them into a favourite category; keep "what was said" separate from "what it might mean".
- Pause; don't sound like a memorised answer was waiting.
- Acknowledge ≠ agree.
- Clarify ("outside what you can spend, or higher than expected?").
- Isolate ("Apart from price, is there anything else…?").
- Diagnose before resolving ("Apart from that?", "Compared to what?", "What exactly are you going to evaluate…?").
- Use existing call evidence rather than restarting.
- Resolve the actual blocker. Mapping: affordability → commercial reality; value → relevance and economics; trust → evidence and clarity; implementation → process, support and capacity; stakeholder → bring them in; fear → the feared outcome; competitor → compare criteria; timing → will the future actually differ.
- Re-check; "Okay" is not proof. Look for the concern withdrawn, forward questions, an accurate summary, or a changed decision state.
- Re-close only after the decision state changes.

Objection taxonomy, 11 types (Brain 2.1, L20223–20390): Financial, Value, Risk, Trust (including self-trust), Timing, Authority, Fit, Implementation, Emotional, Comparative, Avoidance / polite exit.

Depth, 5 levels (L20394–20407): Surface, Tactical, Structural, Emotional, Identity-Level. "The deeper the objection: the less useful a canned rebuttal becomes."

Specific patterns:
- self-trust (L20411–20423);
- previous failure (L20427–20439);
- spouse or partner: "Never automatically classify as fake objection" (L20443–20455);
- competitor: ask what is compared; don't insult (L20459–20472);
- timing: never assume time is always an excuse (L20476–20486);
- "I need to think" and "too expensive" are not diagnoses (L20490–20520).

Behaviour rules:
- Empathy before reframe: Acknowledge → Understand → Diagnose → Reframe → Ask, not Rebut → Push → Close (L20524–20528).
- Empathy ≠ surrender (L20532–20539). Challenge can be appropriate if respectful, evidence-based and proportionate (L20543–20553). Challenge ≠ arguing (L20557–20565).
- Stay on the prospect's side (L20569–20575). Objection fighting is a failure mode; frame it as "seller + buyer vs unresolved decision" (L20579–20592).
- Anti-patterns:
  - Reminder Trap (using the buyer's earlier words as a weapon, L20596–20604);
  - feature-dumping into an objection (L20609–20619);
  - fake scarcity (L20623–20630);
  - exploiting emotional pain (L20634–20645);
  - bypassing a real stakeholder (L20649–20655).

### 6.6 Score bands
- **5/5** (L20686–20702): strong diagnostic judgment. Listens, stays calm, no instant rebuttal, acknowledges, clarifies, isolates, separates the stated objection from the root, uses call evidence, gives a specific response, re-checks, returns to the decision only when appropriate, respects a true no, knows when not to push. Simple meaning: "You understood what was really stopping the buyer and dealt with that — not just the words they said first."
  - Ex1 "Compared to what?" reveals a ₹30–35K expectation; seller revisits scope and value, then re-checks.
  - Ex2 "A lot of money" turns out to be "I'm afraid I'll … not implement"; seller follows the evidence to self-trust.
  - Ex3 "Ask my wife": formal joint decision above ₹20K, so involve her.
  - Ex4 "Team won't use this": previous tools died, so explain the workflow and accountability, then re-check.
  - Ex5 Competitor cheaper: criteria (implementation first), truthful comparison.
  - Ex6 True no: clarify fit vs timing once, then "I won't push this".
- **4/5** (L20834–20843): strong, minor misses (one response slightly quick, incomplete isolation with correct diagnosis, a secondary concern unexplored, weak re-check, a challenge that could be framed better). Simple meaning: "…well, with only a few small diagnostic or follow-through misses."
  - Ex1 Correct diagnosis, no re-check.
  - Ex2 "It definitely does—", then recovers into diagnosis.
  - Ex3 Genuine co-founder approval, but what the co-founder will evaluate is not clarified.
- **3/5** (L20902–20913): useful but inconsistent (partial diagnosis, one clarification then assumption, partly generic answer, surface resolved but deeper blocker missed, no isolation, weak re-check, canned language, occasional defensiveness). Simple meaning: "You responded to the objection, but did not fully understand or resolve what was underneath it."
  - Ex1 "Not exactly [beyond budget]" not explored.
  - Ex2 "What do you need to think about?" "Just overall", then "talk tomorrow".
  - Ex3 "We have better support" without knowing the buyer's criteria.
  - Ex4 Onboarding explained, possible deeper personal-consistency fear never checked.
- **2/5** (L20981–20995): repeatedly reacts instead of diagnosing (instant rebuttal, scripts, arguing, defensive explanation, feature dumping, ignoring the concern, assuming the type, fake logic, poor isolation, unresolved treated as solved, repeated re-closing without new information). Simple meaning: "You reacted to the objection more than you understood it."
  - Ex1 "No, … it's actually cheap".
  - Ex2 Feature dump.
  - Ex3 Reminder trap.
  - Ex4 "That's usually just hesitation … decide yourself" (spouse assumed fake). "If seller encourages secret payment despite genuine shared authority: this can become 1/5" (L21045–21046).
  - Ex5 Endless re-close.
- **1/5** (L21063–21075): materially damages decision quality, trust or autonomy (manipulates resistance, invents urgency, shames, argues aggressively, exploits vulnerability, bypasses a stakeholder, pushes after a true no, false guarantees, overrides a request for space). Simple meaning: "Your objection handling materially pressured, distorted or damaged the buyer's decision."
  - Ex1 False "price disappears tonight" (Ethics FAIL).
  - Ex2 "Stop being afraid and pay today".
  - Ex3 Buyer says no three times; seller keeps re-closing.
  - Ex4 "Pay the token now. Tell her later."
  - Ex5 "I guarantee you'll double revenue."

### 6.7 Not enough evidence, overrides and caps
- Score only when a meaningful objection opportunity occurs (L21145–21149). Scenarios (L21153–21187):
  1. No objection occurs: —. "Do not give 5/5 simply because nothing went wrong."
  2. Call ends before objections: —.
  3. Clarification question, not an objection: don't create an objection opportunity.
  4. Payment logistics only: usually — (D15 may evaluate).
- Buyer question ≠ objection; "do not inflate objection count" (L21191–21199). Disagreement ≠ objection; an objection must affect movement toward a decision (L21203–21209). Silence ≠ objection (L21213–21222).
- One objection can change category (Financial → Self-Trust / Implementation) (L21226–21234). Multiple objections can coexist: record a primary and secondary blockers (L21238–21248). Resolving one can reveal another, which is not seller failure (L21252–21260).
- "Absence of objections is not evidence of excellent objection handling" (L21276).
- Confidence example: "I'll think" with the transcript ending gives Stated: need to think, Root blocker: Unknown; "Do not invent: 'Buyer was avoiding the decision'" (L21298–21315).
- Special rules:
  - **Store Stated Objection → Possible Meanings → Root Blocker** (root only "after enough evidence"). "This structure should reduce hallucinated diagnosis" (L21339–21352). The root blocker may remain unknown, and strong handling can still exist (L21356–21361).
  - Resolution must match the blocker type (L21365–21380). Logic does not always solve emotion; emotion does not invalidate economics; address both (L21384–21398).
  - A competitor objection may reveal criteria (L21402–21408). A price objection may be an upstream failure; score what happened here and let coaching choose the upstream focus (L21412–21422).
  - Handling depends on listening and discovery (L21426–21443). Calmness helps but is not the score (L21447–21454). Confidence helps, overconfidence hurts: "confidence + curiosity" (L21457–21467).
  - Canned scripts are not automatically bad (L21471–21480). "Apart from that?" must not become a trick (L21484–21495). Reframe follows understanding (L21499–21508). Proof must match the objection (L21512–21522).
  - Valid resolutions include "You're right" (no fit), "Not now" (real crisis), "Bring the stakeholder", "More information needed" (L21526–21562).
  - A true no can be 5/5 (L21566–21574). Changing the buyer's mind is not the only success (L21578–21585). A yes does not prove good handling (L21589–21594).
- Do not score commercial outcome (L21647–21658). Final rule L21663.

### 6.8 Inputs needed
- Transcript: **essential** (L21319–21328). This includes earlier-in-call content, since diagnosis must use existing evidence (L20150–20159).
- Turn timing: **important** for "Pause Before Response: Appropriate / Immediate Rebuttal" (L21683) (inference).
- Audio: **helpful, significantly for emotional objections** (defensiveness, emotional load, pauses, intensity, sarcasm; "audio can improve confidence significantly", L21329–21335).
- Product knowledge: **important** for judging truthful comparisons, false guarantees and legitimate fit objections ("You're right … integrate", L21526–21535) (inference).
- Earlier-call or CRM context: **helpful** (previous failures, stakeholder rules).

### 6.9 Inconsistencies and unclear points
- 2/5 lists "arguing" (L20987); 1/5 lists "aggressively argues" (L21070). The threshold is undefined.
- Spouse bypass appears at 2/5 (assumed fake, L21038–21046) and at 1/5 (secret payment, L21123–21129). This is consistent, but the same act also appears in D12 1/5, D17 1/5 and D18 1/5. See 10(d).
- Repeated re-close is penalised in D16 2/5 Ex5 (L21050–21059) and in D17 2/5 Ex5 (L22897–22905). There is no cross-dimension anti-duplication rule here.
- Overlap with D15 on "Compared to what?" (see 5.9).
- Calibration (L21280–21294) vs locked table (L21750–21764): the locked table adds "true no, stakeholder integrity or genuine processing" to 1/5.
- Boundary sections L19927–20002 are cross-reference blocks.

### 6.10 Size
Approx. 1,887 lines (L19881–21767), ~7,200 words.

---

## 7. Dimension 17 — Asking for the Decision

### 7.1 Identity
- Simple Report Name: Asking for the Decision. Internal Meaning: "Decision Readiness / Direct Close / Remaining-Uncertainty Check / Commitment Quality" (L21773).
- Category: How Well You Move the Sale Forward.
- Lines: banner L21768, header L21769, lock sentence L23569; the dimension ends at L23571.

### 7.2 Purpose
L21781: when the buyer had enough clarity, did the salesperson recognise the moment and directly help the buyer decide, without avoiding the ask, asking too early, using tricks, or pressuring past legitimate uncertainty? It is not merely "Did the salesperson ask for payment?" Valid outcomes include Yes, No, Later for a legitimate reason, bring another decision-maker, get specific information, no sale / wrong fit, or another stage-appropriate commitment (L21786–21791). Brain 2.0 is cited: closing is helping a qualified prospect make a clear decision after enough understanding, fit, relevance and certainty. Brain 2.1 is cited: Buying readiness → Remaining uncertainty check → Direct decision question → Operational next step → Payment/onboarding → Confirmation, not "Pressure → Trick → Payment" (L21792–21797).

**Merger note (L21802–21819):** the old standalone pointer "Checking What Is Still Unclear" was merged into D17. D17 therefore covers **A. Decision Readiness** (is enough clarity present?) and **B. Decision Ask** (does the seller actually ask?). It guards against two mistakes: asking while major uncertainty remains, and not asking when everything is clear.

### 7.3 Boundaries
- D16 resolves the blocker; D17 brings the conversation back to a clear decision (L21823–21840).
- D17 is the buyer's decision; D18 is what happens because of it (L21844–21858).
- D12 is how they decide; D17 is whether the seller recognised readiness and asked. "You can fully understand the decision process and still fail to ask" (L21862–21867).
- D15: stating price is not closing (L21871–21880).
- D03 evaluates pause skill across the call; D17 evaluates decision silence after the ask, "a distinct closing function" (L22249–22253).
- "Closing does not create clarity out of nothing." A hard close may reveal an earlier-stage problem (L21883–21899).

### 7.4 Part of the call and context rules
- The decision moment or moments, usually late, but readiness is state-based, not minute-based (L23321–23327).
- Close-readiness check (L21921–21941): Problem, Goal, Fit, Authority, Commercial Reality, Major Objections, Implementation, Remaining Uncertainty, Buying Readiness.
- "All questions answered" is not required; the standard is enough clarity for an informed decision. Do not close just because time has passed (L21945–21951).
- Decision stage → ask type (L22413–22429, L23144–23157):
  - Exploring: too early.
  - Evaluating: clarification and criteria.
  - Decision Ready: ask directly.
  - Commercially Committed: move operationally.
  - Process Pending: support the process.
  - Deferred: clarify the trigger.
  - No Fit: close as no sale.
  - Authority incomplete: bring in the co-founder.
  - Technical unknown: get validation.
  - Genuine processing: respect it.
- Decision ready ≠ payment ready (L22433–22439). Operational process pending is not a new sales decision (L23371–23377).
- B2B decisions may be multi-stage (Brain 3.0 "Domain 7", L23352–23367). Readiness is buyer-specific; first-call clarity is preferred where appropriate, "not payment at all costs" (L22367–22372, L23341–23348).

### 7.5 Core evidence signals
- **Buying signals** (L21955–21975): price and payment questions, EMI, onboarding, start date, implementation, support, accountability, exact version, possessive or future-ownership language. Signal clusters are stronger than one signal (L21978–21990).
- Asking can be better than guessing: meta-questions such as "Where are you right now with this decision?" (L21994–22001, L23381–23386).
- A clear ask ("What would you like to do next?", "Would you like to move forward?", "When would you like to start?") lets the buyer say yes, no, hesitation, missing information or next step (L22005–22017). Directness over cleverness (L22021–22031). No need for the word "buy" (L22035–22042). The ask is not always for payment; "Close the real decision stage — not an imaginary later stage" (L22046–22062).
- A correct close can be "no sale" (L22066–22071). The buyer can close themselves; do not re-ask, move operationally (L22075–22088).
- **Remaining-uncertainty check** (L22137–22146): natural questions, not mandatory if clarity is already shown. Don't invent uncertainty (L22150–22159). Normal decision anxiety ≠ unresolved objection (L22163–22172).
- **Silence after asking** (L22231–22264): "Ask the close, then allow the prospect to think." When to speak: if stuck, a gentle question.
- After a new objection appears, return to diagnosis (L22268–22279). After resolution, come back to the decision (L22283–22292). Don't re-close without new information (L22296–22308).
- Stakeholder-level asks (L22312–22318). Don't manufacture consensus on joint calls (L22322–22330). Don't force a full close if authority is absent (L22334–22339).
- Fear doesn't automatically mean stop or push (L22342–22363). Momentum matters, autonomy wins (L22377–22383). Direct ≠ hard (L22388–22397). Tricks are not required (L22400–22409). Same personality at the close (L22203–22226).
- A good ask allows all legitimate answers (L22468–22478). The buyer must be free to say no; no shame questions (L22482–22491). A clear no is a successful decision (L22495–22506). Seller attachment must not drive the close (L22510–22525).
- **Closing conflict rules** (L22529–22546), "hard calibration rules": buying signal vs unresolved fit → fit wins; one-call vs processing → processing; payment today vs shared decision → shared-decision integrity; seller desire vs clear no → no; momentum vs autonomy → autonomy; more presentation vs readiness → stop presenting; revenue vs wrong recommendation → correct recommendation.

### 7.6 Score bands
- **5/5** (L22550–22566): recognises readiness accurately and facilitates a clear, appropriate decision. Waits for clarity, confirms meaningful uncertainty, recognises signals, stops over-selling, asks directly when needed, allows silence, accepts the response, re-diagnoses new blockers, re-closes only after a state change, picks the right commitment level, respects no, preserves autonomy. "The outcome does not need to be yes." Simple meaning: "You recognized when the buyer had enough clarity and directly helped them make the right decision without pressure."
  - Ex1 Uncertainty check, then "Would you like to move forward?"
  - Ex2 Start, card and onboarding questions, so "Would you like to get started?"
  - Ex3 Buyer self-closes; seller moves to payment and onboarding.
  - Ex4 Implementation concern resolved, then re-close.
  - Ex5 "Payment is not the right decision step yet", so a joint meeting with the co-founder.
  - Ex6 "I don't think you should buy this right now."
  - Ex7 True no: clarify fit vs priority once, then don't push.
- **4/5** (L22681–22690): strong, minor gaps (slightly delayed ask, generic uncertainty check, brief over-explanation after readiness, silence filled a little early, slightly indirect ask). Simple meaning: "…well, with only small timing or execution gaps."
  - Ex1 One unnecessary extra feature before the ask.
  - Ex2 "Take your time" after two seconds of silence.
  - Ex3 "So… are you feeling like…" (mildly indirect).
- **3/5** (L22753–22764): eventually asks, but execution is inconsistent (slightly early or late, vague question, missed signals, weak uncertainty check, talks after asking, follow-up used instead of a decision until late, avoidant wording). Simple meaning: "You eventually moved toward a decision, but the timing or directness was inconsistent."
  - Ex1 "So… what are you thinking?", never sharpened.
  - Ex2 Premature "shall we start?", then recovers.
  - Ex3 Ten-minute presentation after clear signals.
  - Ex4 Talks through the buyer's pause.
- **2/5** (L22823–22834): materially struggles (avoids the ask despite clear readiness, repeatedly early, vague ending, talks past signals, repeated re-closes, awkward tricks, doesn't separate uncertainty from readiness, doesn't return to the decision after resolving blockers). Simple meaning: "The buyer had difficulty reaching a clear decision because you either avoided the ask, mistimed it or kept pushing without new clarity."
  - Ex1 "How soon can we start?" answered with a brochure and a Monday follow-up (Avoiding the Ask).
  - Ex2 Repeated "should we proceed?" while fit questions remain.
  - Ex3 Talking past the yes for 15 minutes; buyer becomes uncertain again.
  - Ex4 Price objection resolved, then "Great." and the call ends.
  - Ex5 "What about now?" again and again.
- **1/5** (L22909–22920): materially pressures, manipulates or overrides autonomy at closing (shame close, fake urgency, false guarantee, closing around the real decision-maker, continuing after a true no, coercive either/or, forcing payment despite unresolved fit, exploiting fear). Simple meaning: "You pushed for commitment in a way that materially damaged decision quality or buyer autonomy."
  - Ex1 "If you were really serious…"
  - Ex2 False "offer disappears tonight" (Ethics FAIL).
  - Ex3 "Pay the token now. We'll tell him later."
  - Ex4 "You'll regret this" after a no.
  - Ex5 "I guarantee you'll make the money back."

### 7.7 Not enough evidence, overrides and caps
- Scenarios (L22986–23030):
  1. Discovery-only: —.
  2. Recording ends before the decision stage: —. "Do not assume seller would or would not ask."
  3. Early technical evaluation: — for a full decision ask, but scoreable if the seller correctly asks for the appropriate intermediate decision.
  4. Operational call after the decision was made elsewhere: —.
- No direct ask ≠ low score if the buyer already decided (L23033–23040). A direct ask ≠ high score if fit, objections or authority are unresolved (L23044–23052). One good close can be enough; repeated closing may lower quality (L23056–23061). **Do not count trial closes** (L23065–23070).
- "Not asking on a call that was never ready for decision is not weak closing" (L23086).
- Confidence example: engaged buyer but recording ends before the close gives "Applicability: Not Enough Evidence rather than weak rating" (L23108–23120).
- Special rules:
  - "What would you like to do next?" can be excellent; don't under-score it as unsophisticated (L23161–23167).
  - "When would you like to start?" requires context (L23171–23177). Assumptive language is fine after the buyer decided and manipulative before (L23180–23191).
  - The uncertainty check can be implicit: "Do not score scripts" (L23195–23205). Don't reopen solved issues (L23209–23216). Buying signals should reduce selling (L23218–23222).
  - Seller fear causes under-closing (knowledge vs recognition vs execution vs confidence gap) (L23226–23238). Seller aggression causes over-closing (L23242–23247).
  - Hesitation after the ask is useful; return to D16 behaviour (L23250–23260).
  - Brain 2.0 valid outcomes: YES, NO, LATER, INVOLVE DECISION-MAKER, NEED SPECIFIC INFORMATION, NOT FIT, FOLLOW-UP WITH CLEAR TRIGGER (L23263–23272).
  - Commitment quality: clear yes vs tentative vs deferred vs unresolved (L23276–23285). A pressured yes is not a good close (L23289–23298). A clear no can outscore a pressured yes (L23302–23308). No fake binary choices (L23312–23317).
  - Decisions can move backward (L23331–23337).
- Do not score commercial outcome (L23436–23443). Final rule L23448.

### 7.8 Inputs needed
- Transcript: **essential, and "often enough for core scoring"** (L23124–23139).
- **Timestamps and turn gaps: essential** for silence tolerance ("After two seconds…", L22714; fields "Silence After Ask: Allowed / Filled Too Quickly / Not Observable", L23481) and for "talks through silence".
- Audio: **helpful to important** for silence tolerance, aggression, desperation and the sudden personality shift (L23133–23137). Output field "Seller Confidence … / Audio Unavailable" (L23479).
- Earlier-call or CRM context: **helpful** (authority structure, previous asks).
- Offer and policy knowledge: **needed to call urgency or guarantees false** (1/5 Ex2, Ex5) (inference).

### 7.9 Inconsistencies and unclear points
- The decision-state enum (L23462: Exploring / Evaluating / Decision Ready / Commercially Committed / Deferred / No Fit / Unknown) differs from D12 (L15448, which includes Decision Process, Process Pending, Lost) and from D18 (L25332). Section 46 (L22413–22429) itself lists Process Pending, which is missing from the D17 enum.
- Repeated re-close and stakeholder bypass are scored in D16 and D17 (and D12 and D18); see 10(d).
- Pause and silence are partly shared with D03 (L22250). The rubric asserts distinctness but gives no rule for one event counting in both.
- The strong-no example output (L23538–23550) has no Evidence timestamps, unlike the other example outputs.
- L22438 hedges "Dimension 17 may be strong" for decided-but-finance-Friday without a scoring rule.
- Calibration (L23090–23104) vs locked table (L23554–23568): the locked table adds "despite relevant opportunity" (2/5) and "misleads … stakeholder integrity or a genuine no" (1/5).

### 7.10 Size
Approx. 1,804 lines (L21768–23571), ~7,300 words.

---

## 8. Dimension 18 — Setting Clear Next Steps

### 8.1 Identity
- Simple Report Name: Setting Clear Next Steps. Internal Meaning: "Action Clarity / Ownership / Timing / Trigger / Follow-Up Quality" (L23577).
- Category: How Well You Move the Sale Forward.
- Lines: banner L23572, header L23573, lock sentence L25466 (the last line of the file).

### 8.2 Purpose
L23585: did the salesperson make it completely clear what should happen after the call: what action, who does it, when, and why it makes sense given the buyer's actual decision state? Calls should not end with "we'll be in touch", "I'll follow up", "think about it", "send me something" or "we'll talk later" (L23586–23591). Brain 2.1's post-call check is cited: Decision, Reason, Product/Plan, Commercial Terms, Stakeholders, Remaining Risk, Implementation Readiness, Next Step, Timing, Owner (L23603–23614). This is the final "no ambiguity" dimension (L23618–23635).

### 8.3 Boundaries
- D17 is what decision was made; D18 converts it into clean execution (L23639–23663).
- D12 is what the decision process looks like; D18 is what exact next action was agreed (L23667–23678).
- D08 identifies who; D18 creates the action to involve them (L23682–23691).
- D16 identifies the unresolved blocker; D18 converts a non-resolvable-now blocker into a specific action (L23695–23706).

### 8.4 Part of the call and context rules
- **The end of the call.** Also follow-up behaviour across calls where it is observable.
- The next step must match the decision state (L23723–23816):
  - **Yes**: payment, invoice, contract, PO, access, WhatsApp group, onboarding, setup, start date; the buyer should never wonder "अब क्या होगा?".
  - **Deferred**: why not now → what event first → agree a meaningful step → follow up after the event.
  - **Another decision-maker**: bring them in.
  - **Information missing**: deliverable, owner, timing, purpose.
  - **Commercial process pending**: support the process, don't re-sell.
  - **No**: close the loop; "a clear no next step can be better than fake pipeline movement".
  - **Poor fit**: stop, refer, one resource.
  - **Nurture**: reason, context, cadence; no endless "checking in".
- Respect human reality. Do not force a date in a crisis (father's surgery, L24105–24116); "Human reality outranks pipeline neatness". Real crisis: no sales-centric next step (L24283–24289).
- Implementation readiness affects the next step (a January start, L25198–25204). The next step should match the stage, not seller desire (L25208–25213).

### 8.5 Core evidence signals
- **Six-part next-step model** (L23902–23917): 1 Action, 2 Owner, 3 Timing, 4 Trigger, 5 Purpose, 6 Expected Output. "Not every next step needs all six explicitly. But stronger next steps usually contain most of them."
- Next step ≠ follow-up date ("Next step: follow up Friday" tells almost nothing, L23843–23852). Every strong step answers What, Who and When, plus After what trigger and Why where relevant (L23856–23898).
- Signals (L23921–23984): action clarity, ownership, timing, trigger, purpose, reciprocal commitment (actions from both sides), confirmation ("…Correct?"), continuity (no re-discovery).
- A next step should advance something real; "activity ≠ progress" (L23988–23998).
- "Send me details" is not automatically good (L24002–24011). "I'll call you" is not enough (L24015–24024).
- Follow up against the blocker (L24027–24039). Follow-up should create decision value: new value or information, reduced uncertainty, advance, confirm timing, or close (L24043–24052).
- No "just checking in" loop (L24056–24071). Follow-up needs a reason (L24075–24081).
- Event-based follow-up is usually stronger (L24084–24091), but calendar-based follow-up with a reason can be valid ("48 hours to review … Wednesday at 4", L24094–24101).
- No false certainty: agreed / tentative / proposed / unknown (L24120–24130). Proposed ≠ agreed (L24134–24144). A deliverable must be named (L24148–24154). The buyer's action must be clear (L24157–24162).
- After a yes, move from selling to execution (L24166–24174). After payment, confirm what happens next (L24178–24188). Payment completed ≠ next step complete (L24192–24199).
- State-specific steps: payment failure (L24203–24217), procurement (L24221–24228), technical review (L24233–24239), stakeholder (L24242–24246), genuine processing (L24250–24259), competitor comparison (L24262–24268), budget timing only (L24272–24279).
- No next step may be the right next step, and no calendar event is needed in every case (L24293–24312).

### 8.6 Score bands
- **5/5** (L24315–24332): converts the real decision state into a specific, credible, useful action. Where relevant: what, who, when, trigger, why, expected result. Moves operationally after yes, ties deferrals to events, brings stakeholders in, sends exact missing information, avoids vague follow-up, doesn't chase after a genuine no, confirms responsibilities. Simple meaning: "Everyone knew exactly what was going to happen after the call, who was responsible and when it would happen."
  - Ex1 Yes, then payment link, access today, setup call tomorrow at 11 AM with the sales manager.
  - Ex2 Co-founder Thursday; summary sent today; Friday 10 AM agreed.
  - Ex3 Integration document by 5 PM; CTO reviews tomorrow; Thursday 3 PM.
  - Ex4 48 hours on implementation capacity; Wednesday at 4.
  - Ex5 Procurement: invoice, GST and vendor form today; expected completion next Wednesday.
  - Ex6 Clear no: "I'll close this from my side".
- **4/5** (L24425–24433): useful and credible, one minor detail incomplete (time not set but day or trigger clear, owner of a secondary action ambiguous, deliverable detail light, confirmation could be sharper). Simple meaning: "The next step was clear and useful, with only a small detail missing."
  - Ex1 Friday after the co-founder meeting, no time.
  - Ex2 "Technical information" with the document not named.
  - Ex3 Post-sale flow clear except who will contact the buyer.
- **3/5** (L24495–24504): a next step exists but is partly vague (date with no purpose, "send something" without saying what, vague trigger, only one side's action, doesn't advance the decision, broad timing). Simple meaning: "There was a next step, but parts of it were still vague."
  - Ex1 "Let's talk next Tuesday."
  - Ex2 "Send me the details." "Sure."
  - Ex3 Seller-side action only, no buyer commitment.
  - Ex4 "Sometime next week after you've thought about it."
- **2/5** (L24565–24578): substantial ambiguity despite an opportunity ("I'll follow up", "let me know", "think about it", no owner, timing or trigger, random follow-up, follow-up that misses the blocker, purposeless meeting, a yes with an unclear payment or onboarding path). Simple meaning: "The call moved forward only loosely because nobody had a clear, credible action plan."
  - Ex1 "I need to think" answered with "I'll follow up".
  - Ex2 Co-founder event answered with "let me know".
  - Ex3 "I want to proceed" answered with "we'll connect with you".
  - Ex4 Funds after a client pays, but "I'll call you every two days".
  - Ex5 Security review blocker answered with a motivation video and testimonials.
- **1/5** (L24651–24661): next-step behaviour materially damages trust, autonomy or opportunity quality (ignores a request for space, fake follow-up urgency, misrepresents the agreed step, continues after a clear stop or no, a token to trap an undecided buyer, bypasses a stakeholder, actions inconsistent with what was agreed). Simple meaning: "The follow-up or next-step plan materially ignored, pressured or misrepresented the buyer's real decision state."
  - Ex1 "Give me a week, no calls", then daily calls planned.
  - Ex2 "Offer expires" when it doesn't (Ethics FAIL).
  - Ex3 "Pay ₹5,000 now and decide later".
  - Ex4 Payment today instead of co-founder review.
  - Ex5 "Please don't follow up", then five future calls scheduled.

### 8.7 Not enough evidence, overrides and caps
- Score only where an end-of-call or next-step opportunity is observable (L24728–24731). Scenarios (L24735–24767):
  1. Recording ends early: —. "Do not assume seller forgot."
  2. Call fragment with no ending: —.
  3. Pure operational call: — may be appropriate.
  4. No further action, clearly established: "can be scored positively rather than dashed".
- No future meeting ≠ low score (L24771–24782). Booking a meeting ≠ high score (L24786–24791). Specificity should be proportional to reality (L24795–24801). The next step can change with new information (L24805–24812).
- "Missing end-of-call evidence is not evidence of a vague next step" (L24828).
- Confidence example: "We'll talk Friday" with buyer audio cut gives Proposed: Friday, Agreement: Unknown, Confidence Low/Medium. "Do not upgrade seller proposal into mutually agreed next step" (L24850–24867).
- Special rules:
  - **Proposed / Agreed / Completed** are separate states (L24888–24898). Seller commitment is stored separately from buyer commitment (L24902–24909).
  - Follow-up states (Brain 2.1, L24912–24925): Decision Pending, Stakeholder Pending, Commercial Pending, Information Pending, Timing Deferred, Nurture, Unresponsive, Closed Lost, Reactivated. Each has a rule (L24929–25003): reactivation requires requalification ("What changed?").
  - Medium should fit complexity; don't force everything through WhatsApp (L25009–25016). Complex objections should not become 30-message chains (L25020–25028).
  - Content must be relevant (L25032–25039). More follow-up is not better (L25043–25049). Frequency depends on state; no universal cadence (L25054–25063). No false urgency (L25067–25072).
  - Use real context; the buyer shouldn't have to re-explain (L25076–25093). Requalify after time passes (L25097–25100).
  - Real progression vs CRM activity (L25104–25112). Real reciprocity strengthens a step; no fake reciprocity ("Send details" ≠ "Highly committed") (L25116–25133).
  - A yes produces operational clarity; a deferral produces event clarity; a no produces loop closure (L25137–25162).
  - **Store "no next step" explicitly**: "Next Step: None / Reason / Follow-Up Required: No", not a blank (L25166–25172).
  - Don't over-schedule (L25176–25183) or under-specify post-sale actions (L25187–25194). A good next step reduces uncertainty or friction (L25217–25222).
  - Don't book a follow-up to avoid a clean no (L25226–25232). Follow-up can repair earlier misses (L25236–25246).
- Do not score commercial outcome (L25294–25304). The prospect's response informs quality but enthusiasm doesn't replace structure (L25308–25314). Final rule L25319.

### 8.8 Inputs needed
- Transcript including **the actual end of the call: essential**. Without it, the result is — (L24735–24748).
- Timestamps: **essential** for evidence spans.
- Speaker attribution: **essential** to separate proposed (seller) from agreed (buyer) (inference).
- Audio: **helpful** (uncertainty, genuine agreement, casual vs firm language; "transcript is usually sufficient", L24871–24884).
- **CRM, follow-up and activity history: needed** for behaviour after the call:
  - "just checking in" loops across days (L24056–24071);
  - "Completed" status (L24896–24897);
  - planned daily calls or five scheduled calls (1/5 Ex1, Ex5);
  - reactivation and requalification (L24995–25005).
  None of these is visible in a single call transcript unless spoken aloud (inference).
- Company process knowledge (onboarding sequence, what documents exist): **helpful**.

### 8.9 Inconsistencies and unclear points
- Not-enough-evidence Scenario 4 (L24761–24767) is a scored case filed under the "—" heading.
- Two of the three example outputs (L25408–25429 post-sale, L25433–25447 clear no) omit Evidence timestamps; the deferred example (L25378–25404) includes them.
- 1/5 Ex1 and Ex5 judge actions planned after the call (L24675–24676, L24721–24722), which a call-level analyzer usually cannot see (inference).
- The final decision-state enum (L25332) differs again from D12 and D17.
- Calibration (L24832–24846) vs locked table (L25451–25465): the locked table adds "clean post-sale execution or loop closure", "reciprocal commitment", "'let me know' … poor post-sale handoff or little real decision progress".

### 8.10 Size
Approx. 1,895 lines (L23572–25466), ~7,200 words.

---

## 9. Content after Dimension 18

**There is none.** The file ends at L25466 with "This is the version I would lock for Dimension 18 — Setting Clear Next Steps under the final 18-point Brain 4.0 framework." My range contains no section on:
- overall call score;
- category scores or aggregation (Category 2 / Category 3 roll-up);
- weighting between dimensions;
- how "—" dimensions affect totals;
- how Ethics FAIL affects anything beyond the D07 label;
- a final report layout;
- how many coaching points to show.

The only report-design material in my range is the per-dimension material below. (The other half, L1–12625, may contain an introduction; that is outside my range.)

### 9.1 Report-design material that does exist (per dimension)
- **Learner-facing text**: each band has a one-sentence "Simple Brain 4.0 Meaning" in second person ("You …"). These are ready-made report sentences.
- **Example final analyzer output** pattern (all 5/5):
  1. Dimension name.
  2. Score ("5/5").
  3. "What happened:" (second-person narrative, 3–6 sentences).
  4. "Evidence:" lines of the form `mm:ss–mm:ss · short description` (3–6 lines).
  5. Dimension-specific labelled facts, e.g. D11 Financial/Time/Opportunity Impact; D12 Current Decision State, Primary Criterion; D15 Actual Price, Buyer Expected Range; D16 Stated Objection → Initial Hypotheses → Evidence → Deeper Objection → Root Blocker → Resolution.
  6. "Confidence: High".
  Examples: L14026, L15483, L16844, L18338, L19832, L21718, L23508, L23538, L25378, L25408, L25433.
- **Coaching format** (from every "Example of specific coaching"): name the observed behaviour in this call, then give a concrete cue starting "On your next relevant call, …". Vague coaching such as "Quantify pain better", "Close harder" or "Explain better" is explicitly banned. Each dimension lists the allowed specific weakness labels; see the Brain 3.0 coaching rule in each dimension.
- **Longitudinal rule**: "One call creates evidence. Not identity." Patterns are left to "Brain 3.0" across calls; the call-level report stays specific.

---

## 10. Implications for an AI pipeline

### 10(a) Compact rubrics for D11–D18 (prompt-ready)

These rules apply to all eight dimensions:
- Score 1–5 or "—".
- "—" means no relevant opportunity was observable or the dimension was not required. Never use 1/5 for missing evidence.
- Confidence (High / Medium / Low) is separate from the score.
- Never score the commercial outcome (bought / didn't buy).
- Evidence must be timestamped spans.
- Label inferences.
- If a 1/5 behaviour is also deceptive, add flag `ethics: FAIL | concern` for D07 Being Professional.
- Don't copy the same criticism into two dimensions; each dimension's reason must cite its own evidence.

**D11 Understanding the Real Impact (Cat 2).** Did the seller establish how much the buyer's problem matters (financial, time, effort, emotional, opportunity, cost of inaction, desired upside) without manufacturing pain? Not D09 (what is wrong), not D10 (current approach), not D13–15.
- Tag every important number by source (buyer-stated / calculated from buyer inputs / seller estimate / unsupported) and by state (known / estimated / aspirational). Keep current loss separate from solution upside.
- 5: grounded picture of the impact types that matter to *this* buyer, quantified where reality allows, uncertainty preserved. One bucket can suffice. Five buckets with shallow answers is not 5.
- 4: main impact clear; one relevant bucket, some quantification, cost of inaction or upside missing.
- 3: significance acknowledged but vague ("a lot of time", "losing money" accepted), only one bucket while obvious others are ignored, or an ungrounded guess ("few lakhs?" "maybe").
- 2: clear impact signal ignored; jump to the solution before consequences; unsupported impact claims; emotional pain mining; a number forced on a buyer who cannot know it ("let's say ₹5 lakh").
- 1: invented loss, aspiration turned into guaranteed ROI, fabricated catastrophe, exploited personal pain, unsupported numbers used to justify price. A guessed or forced number later used as fact or ROI escalates downward (3→lower, 2→1).
- —: recording starts after discovery (unless later evidence validates), very early discovery before impact is relevant, operational call, buyer refuses to estimate and almost no qualitative impact exists.
- Never lower for lack of a rupee figure when time or opportunity impact is concrete; never raise for an exact figure not tied to the problem. No hourly rupee conversion without basis. No clinical labels; report the buyer's words. Presenting while impact is materially unclear may lower D11; do not repeat that penalty in D15.

**D12 Understanding How They Will Decide (Cat 2).** Did the seller understand (A) the process steps and owners, (B) the criteria (priority, must-haves, trade-offs, disqualifiers), (C) the remaining uncertainty (missing information, risk, comparison gap, decision anxiety vs real uncertainty), and (D) the timing or trigger with a reason? Did the seller separate decided-but-process/payment-pending from not-decided? Not D08 (who), not D18 (agreed action), not D16 (resolution).
- 5: can explain what must happen, what matters, what is unresolved and when or after what event; delay correctly classified (structured, genuine processing, polite exit).
- 4: one or two minor gaps (criteria unranked, time not fixed).
- 3: some elements known; "need to think" met with timing only, competitors known without criteria, finance approval with the decision state unclear, vague future date.
- 2: accepts "I'll think" or vague timing without diagnosis, arbitrary follow-up, treats procurement as an objection, reduces criteria to price without evidence, misclassifies "it's just process" as doubt.
- 1: overrides a legitimate process (pay before board, legal or co-founder review; fake deadline; forcing a decision in a crisis; continued control after a genuine request for space).
- —: early discovery, recording ends before decision talk, operational call. A simple immediate yes with no further process is scoreable and can be positive.
- Don't over-interrogate; one vague detail shouldn't sink a strong process; one specific date isn't enough. Update criteria as they change. Process friction ≠ sales resistance. (Owner should adjudicate the 3/5 vs 2/5 "need to think / few days" contradiction.)

**D13 Matching the Right Solution (Cat 3).** Did the seller recommend and prioritise what fits the diagnosed problem, goal, impact, previous attempts, current setup, D12 criteria, implementation capacity and realistic expectations? Fit, Relevance, Prioritisation, Feasibility, Integrity. Not D14 (clarity of explanation).
- Map each recommended capability to buyer evidence; classify capabilities as Required / Useful / Irrelevant. Needs the product and plan catalogue.
- 5: specific, prioritised, buyer-grounded, implementation-aware, commercially honest. Preserves what works, updates on new evidence. A smaller plan, complement or no sale can be 5.
- 4: right recommendation with minor prioritisation, readiness or secondary-fit gaps.
- 3: broadly right but generic ("because you want more sales"), feature list with a few relevant items, plan chosen by budget, wrong emphasis.
- 2: premature prescription, mismatched to the primary gap (lead generation for a conversion problem; more content when information isn't the issue), replaces a working tool, ignores capacity, upsell-driven.
- 1: knowingly or clearly wrong (cannot solve the need, revenue-driven against evidence, conceals a limit, pushes despite stated inability to implement, refuses to update without addressing evidence).
- —: discovery-only, recording ends before the recommendation (don't infer), single product with no fit decision. A follow-up without the original rationale gets — or a lower-confidence score.
- Judge fit, not price direction: recommending a higher plan with reason is fine; the buyer's preference doesn't define fit. A short product glimpse on request is not premature. A one-product company still has a fit decision.

**D14 Explaining the Solution Clearly (Cat 3).** Could a normal buyer leave with an accurate mental model: what it does, how it works (mechanism, not magic), why it matters to them, implementation and who does what, scope, limitations, realistic outcome, what happens next? Not D13 (right choice), not D03 (vocal pace), not D15 (price).
- 5: buyer-specific language, mechanism, jargon translated, top relevant capabilities first, honest limits, understanding checked (ideally the buyer can summarise), adapts to questions, stops when clear. A short explanation of a simple product can be 5.
- 4: minor jargon, light onboarding detail, one unneeded feature, one clarification needed.
- 3: components without mechanism, circular benefit language, initially too technical, implementation unexplained until asked, overlong tour with comprehension unmanaged.
- 2: feature dump, "that's what the AI does", adds terms when the buyer is confused, material implementation burden omitted, generic "transform your business".
- 1: materially false capability ("fully automatic"), hidden setup burden when asked, guaranteed outcomes, confirming the buyer's false belief. Needs product ground truth.
- —: no meaningful explanation observed (discovery-only, recording starts after presentation, one-line mention, follow-up).
- Buyer questions ≠ poor clarity (may be buying signals); "haan… okay…" ≠ proof of understanding. Recovery counts. One minor unclear detail is minor; one material misunderstanding (done-for-you vs do-it-yourself) weighs heavily. Don't reward length, feature count, sophistication or charisma. Execution doubt ("will my team use it?") is not a clarity failure.

**D15 Talking About Price & Budget (Cat 3).** Commercial clarity: budget context, price stated clearly and calmly, pause, then the right question. Classify the money state as cannot afford / not allocated / expected lower / doesn't see value / cash-flow timing / negotiation / payment logistics. Use legitimate options transparently; disciplined discounting. Not D16 (diagnosing and resolving resistance), not D11, not D13.
- Record price, currency and tax exactly. Needs the price book (real list price, approved discounts, EMI and split availability, real deadlines, fees, token terms).
- 5: correct timing (when interpretable, not hidden for sunk cost), no apology or panic, lets silence work, separates affordability from expectation, value, cash flow and logistics, transparent options, dignity preserved. A genuine "can't afford" respected = 5 even with no sale.
- 4: slightly late context, slight hesitation, options over-explained.
- 3: generic "budget?" accepted, defends price before any reaction, one unprompted discount, EMI aimed at a value doubt.
- 2: price-shock engineering, successive discounts into silence, EMI for "not worth it", shaming ("you'll find the money"), invented "today only" option.
- 1: fake anchor or discount, fake price deadline, misleading token, hidden mandatory fees (add ethics flag).
- —: no price discussion observable (discovery-only, recording ends early, free product); a follow-up with the prior price talk missing gets — or lower confidence.
- No budget question ≠ low if context is known; asking "budget?" ≠ high. Don't infer affordability from status; company money ≠ personal money. Don't penalise a negative buyer reaction; acceptance ≠ 5. Installments aren't a price cut. Payment questions or failure after a yes ≠ objection.

**D16 Handling Objections (Cat 3).** When the buyer resisted, did the seller treat it as information? Hear → pause → acknowledge → clarify → isolate → diagnose with existing call evidence → resolve the actual blocker truthfully → re-check → return to decision only after the state changes.
- Store Stated Objection (exact words) → Possible Meanings → Root Blocker (confirmed / likely / unknown).
- Type: Financial, Value, Risk, Trust, Timing, Authority, Fit, Implementation, Emotional, Comparative, Avoidance.
- Depth: surface → identity-level.
- 5: precise diagnosis, targeted resolution, re-check, correct next move; true no, shared authority, crisis and space respected. "You're right, not a fit" or "not now" can be 5.
- 4: correct core with a weak re-check or a brief defensive moment that recovers.
- 3: partial diagnosis ("not exactly" unexplored), "just overall" accepted, generic competitor reply, surface resolved with a deeper blocker unchecked.
- 2: instant rebuttal, feature dump, reminder trap ("you said budget wasn't an issue"), spouse assumed fake, re-closing without new information, arguing.
- 1: fake scarcity, exploiting fear, ignoring a repeated no, encouraging a secret purchase around a co-decider, false guarantees.
- —: no meaningful objection (do not give 5 because nothing went wrong), call ends first, clarification-only questions, payment logistics only.
- A question, disagreement or silence is not an objection; don't inflate the count. Objections can change category or coexist (record primary and secondary). Resolving one can reveal another, which is not failure. "Compared to what?" is good, not "canned", when used with listening. Calmness alone isn't the score.

**D17 Asking for the Decision (Cat 3; includes the former "Checking What Is Still Unclear").** Readiness: problem, goal, fit, authority, commercial clarity, major objections, implementation, remaining uncertainty, buying signals (clusters > single). Ask: the clearest stage-appropriate ask (purchase, stakeholder meeting, technical validation, start date, or no sale), then silence.
- 5: recognises readiness, checks meaningful uncertainty (implicitly is fine), stops selling, asks directly ("What would you like to do next?" is excellent), lets the buyer think, re-diagnoses a new blocker, re-closes only after change, respects the outcome. The buyer self-closing and the seller moving operationally = 5. A clear no can be 5.
- 4: slightly delayed, slightly indirect, silence filled a bit early ("Take your time" after ~2 s).
- 3: vague ask never sharpened, early ask then recovery, readiness recognised late, talking through the pause.
- 2: avoids the ask despite clear signals ("I'll send a brochure, follow up Monday"), repeated premature asks, talking past the yes, no return to decision after resolving a blocker, repeated re-close.
- 1: shame close, fake urgency, false guarantee, closing around the real decision-maker, pushing after a clear no, coercive either/or.
- —: discovery-only, recording ends before the decision stage, early technical evaluation (unless an intermediate ask is made), operational call.
- Don't count trial closes; "when would you like to start?" is legitimate only if the buyer has chosen. Hard calibration: fit > buying signal; processing > one-call close; shared decision > payment today; no > seller desire; autonomy > momentum; stop presenting when ready; correct recommendation > revenue.

**D18 Setting Clear Next Steps (Cat 3).** Convert the actual final state (yes / no / deferred / stakeholder, information, commercial or timing pending / nurture / no fit) into Action, Owner, Timing, Trigger, Purpose, Expected Output. Store Proposed / Agreed / Completed and seller vs buyer actions separately.
- 5: specific, owned, timed or event-anchored, purposeful, buyer agreed. After yes: payment → access → onboarding with buyer prerequisites. Deferral tied to a real event. Stakeholder brought in. Exact missing information with deadline. Clean loop closure after a no.
- 4: day or trigger clear but no time, deliverable not named, one secondary owner unclear.
- 3: date without purpose, "send details" undefined, only seller-side action, broad "sometime next week".
- 2: "I'll follow up", "let me know" despite a real event, yes with no payment or onboarding path, cadence ignoring the trigger, follow-up content that doesn't address the blocker.
- 1: ignores requested space, fake urgency, trap token, payment instead of the required stakeholder review, chasing after "don't follow up".
- —: recording ends early or is a fragment, pure operational call with nothing new. An explicitly closed opportunity is scoreable (store "Next Step: None" with reason).
- No meeting ≠ low; a booked meeting without purpose ≠ high. Specificity proportional to reality; don't force a date in a crisis. Never upgrade a seller proposal to an agreed step.

### 10(b) Dimensions that cannot be judged reliably from transcript text alone
Ordered by dependency (my assessment, based on what each section says audio, timing and context add):
1. **D15 Price & Budget**: 1/5 deception (fake discount, fake deadline, hidden fees, token terms) needs the **price book and commercial policy**. Price-delivery confidence and "pause after price / panic fill" need **audio and turn timing** (L19433–19438, L19800–19801).
2. **D13 Matching** and **D14 Explaining**: need a **product, plan and limitation knowledge base** to judge fit and "materially false" claims. D14 also benefits from timing (length of tours) and audio (confusion tone).
3. **D17 Asking for the Decision**: silence tolerance after the ask needs **turn-gap timestamps**. Aggression, desperation and personality shift need **audio** (L23133–23137). Core readiness and ask are transcript-judgeable.
4. **D18 Next Steps**: in-call steps are transcript-judgeable *if the ending is captured*. "Completed" status, chasing loops, planned call cadences and reactivation need **CRM and follow-up history**.
5. **D16 Objections**: transcript works for most of it. **Audio matters for emotional or identity-level objections** and for "pause before response" (L21329–21335).
6. **D11 Impact** and **D12 Decide**: mostly transcript-sufficient. Audio only adds emotional significance or hesitation (L13671, L15078). Earlier-call context matters for follow-ups.

For every dimension, **speaker diarisation accuracy is load-bearing** (buyer-stated vs seller-estimated numbers; proposed vs agreed steps; who raised an objection). Code-mixed Hindi-English (Devanagari plus Latin) appears throughout the examples, so transcription and normalisation must preserve it (inference).

### 10(c) Suggested per-dimension output schema (derived from the internal output formats)
- `dimension_id` (11–18), `report_name`, `category`.
- `applicability`: applicable | not_applicable | not_enough_evidence. Display "—" for the last two, but keep them distinct.
- `nee_reason`: enum, e.g. recording_starts_late | recording_ends_early | fragment | discovery_only | operational_call | no_opportunity | not_required | prior_context_missing.
- `rating`: 1–5 | null.
- `confidence`: high | medium | low, with `confidence_reason` (e.g. buyer audio missing, root blocker unknown).
- `severity`: minor | meaningful | material | critical. Note that D12 omits critical in the source; harmonise.
- `evidence`: list of `{segment_id, start, end, speaker, quote_or_paraphrase, supports: positive|negative}`. The source examples use `mm:ss–mm:ss · description`.
- `what_happened` (second-person narrative), `simple_meaning` (the band sentence), `reason_for_rating`.
- `positive_evidence[]`, `negative_evidence[]`.
- `inferences[]`, each explicitly labelled.
- `boundary_notes[]`: observations deliberately routed to another dimension (e.g. "price delivery scored in D15; diagnosis in D16"), to stop double-penalising.
- `upstream_cause` (optional): e.g. "generic recommendation caused by weak D09". The rubric allows coaching to pick an upstream focus while each dimension scores what it observed.
- `ethics_flag`: none | concern | fail, with the target dimension D07.
- `coaching`: `{weakness_label (from the dimension's enumerated list), observed_behavior, next_call_cue}`.
- Dimension-specific structured fields, kept from the source because they prevent hallucination:
  - D11: number provenance and known/estimated/aspirational; current loss vs solution upside.
  - D12: decision_state, decision vs payment/procurement separation, criteria with priority.
  - D13: recommended vs buyer-preferred option, capability → evidence map, required/useful/irrelevant.
  - D14: mechanism quality, repeat-back.
  - D15: actual price, expected price, capacity/allocation/willingness/cash-flow, discount basis.
  - D16: stated objection → possible meanings → root blocker (confirmed/likely/unknown), type, depth, resolution, re-check.
  - D17: decision state before ask, ask type, silence after ask, final decision, decision freely made.
  - D18: final state, next-step status (proposed/agreed/completed), seller action, buyer action, owner, timing, trigger, purpose, loop closure, "none" with reason.
- Harmonise one **decision-state vocabulary** across D12, D17 and D18. The source has three different enums: L15448, L23462, L25332.

### 10(d) Most common failure modes the rubric warns about
1. **Scoring the commercial outcome** instead of skill. Repeated in every dimension: a pressured yes is not good; a respected no or a genuine budget constraint can be 5.
2. **Confusing "—" with 1/5**, or treating absence as excellence (no objections → 5/5; no direct ask → low when the buyer already decided; recording cut → "seller forgot").
3. **Hallucinated diagnosis or certainty**: inventing a root blocker, upgrading proposed to agreed, recording "CFO meeting confirmed" from "I'll try", treating buyer estimates as observed facts, inferring affordability from status, labelling emotions clinically.
4. **Fake precision and value inflation**: conflating known, estimated and aspirational figures; treating current loss as product upside; ROI from buyer goals.
5. **Mislabelling buyer states**: process or procurement friction as resistance; payment logistics or failure as objections; "I need to think" or "too expensive" taken as a diagnosis; questions, disagreement or silence counted as objections; normal decision anxiety treated as unresolved doubt.
6. **Rewarding surface proxies**: feature count, explanation length, charisma or confidence, number of closing questions, a booked meeting, an explicit budget question, an exact number, a specific date.
7. **Script-checking**: requiring fixed phrases ("Is anything unclear?", "What's your budget?", trial closes, five impact buckets) instead of judging whether the information was actually established.
8. **Double-penalising one moment across dimensions.** High-risk overlaps in this range:
   - stakeholder bypass and fake urgency (D12 / D16 / D17 / D18, plus a D07 ethics flag);
   - repeated re-close (D16 / D17);
   - "Compared to what?" (D15 / D16);
   - premature presentation (D11 / D13 / D17);
   - pause and silence (D03 / D15 / D17).
   The rubric asks for distinct evidence and explanations (L16631–16641, L13874–13877) but gives no global ownership table. The pipeline should define one (inference).
9. **Over-pushing and over-interrogation**: chasing every "no", "Apart from that?" used as a trick, over-asking about decision processes, forcing dates during a crisis, emotional pain mining.
10. **Vague or identity-level coaching** ("close harder", "Rahul is bad at …"). The rubric requires a specific observed weakness and a next-call cue, and keeps one call as evidence, not identity.

### 10(e) Gaps to resolve before building the eval set (from this range)
- There is no aggregation, weighting or report-assembly rule anywhere in L12626–25466.
- All 11 example analyzer outputs are 5/5. There are no worked outputs for 1–4 or "—" (inference: the eval set needs owner-labelled examples for those).
- The "Score calibration" and "Locked scoring table" in every dimension differ in wording. The locked table is presumably authoritative, since the author says "this is the version I would lock" (inference).
- The relationship between Severity and Rating is undefined.
- The handling of "— / lower-confidence score" choices (L16389–16391, L19329–19332) is undefined.
- The ethics flag label is inconsistent: "Ethics FAIL" vs "Ethics concern".
- Worked examples with ambiguous or contradictory labels: L13293 (4 or 5), and D12 L14743–14755 vs L14816–14825 (3 vs 2 for near-identical behaviour).
- About 180 lines in this range end with "Brain 2.0 / 2.1 / 3.0" citation residue. The text also has assistant-voice lock sentences. Both should be stripped before the text is used as a prompt (inference).

---

## Names seen (not repeated in the body except where unavoidable)
- **"Rahul"**: generic example learner name in longitudinal rules: L13960, L15414, L16769, L18261, L19750, L21635, L23423, L25282.
- **HubSpot** (real CRM product): L14385, L15148, L16661, L20154, L23957, L24377.
- **Authority Closers** (the company): L12840, L20136.
- **WhatsApp** (real product): L17729, L19125, L20613, L23738, L25016.
- Generic or placeholder names, not real entities: "Competitor X" (L20350, L20800), plan names "Basic / Pro / Premium / Standard" and "Silver or Gold" (L19525), "Premium Closer Program" (L16230), "Plan A / Plan B".
- Internal source documents referenced but not included: Brain 2.0, Brain 2.1, Brain 3.0 (throughout).
- No other person or company names appear in L12626–25466 or L1–27.
