# Duplicate leads: find, review, merge

The owner, 25 Oct 2026: "Under the org we need a very very strong pattern recognition and perfect
engine that detects duplicate leads based on many many factors and variables… duplicated leads are
flagged and sent for verification that do we want to merge, and after that engine should have a
capacity to merge activity even if multiple people worked on it and how it should be done and who it
should be assigned, finally all decide, get this done". The orchestrator settled the design. This doc
records it with the build's decisions.

## 1. Signals, scored with no AI (`lead_desk/dupes.py`, pure)

| Signal | Normalised as | Points |
|---|---|---|
| Same phone (E.164) | `+91…`, from the lead's phone and other phones in its payload | Certain |
| Same email | lower case | Certain |
| Same source record (form or lead id) | as given | Certain |
| Same last 10 digits of a phone | digits only | +80 |
| Same email apart from a typo | gamil/gmial/gmai/gnail/… → gmail, a pasted "www.", Gmail dots and +tags | +70 |
| Same name | honorifics out; romanised spellings folded (aa→a, ee→i, oo→u, w→v, ph→f, kh/gh/th/dh/bh/sh/ch, z→j, doubled letters, a final y→i); words sorted | +35 |
| Names 92% / 85% / 75% alike | Jaro-Winkler on the folded, sorted words; a one-word name against the other's words at 0.9 | +30 / +20 / +8 |
| Same company | Pvt, Ltd, Private, Limited and similar left out | +15 |
| Same work email domain | not a free mail provider | +15 |
| Same city | the state suffix and known misspellings folded | +5 |
| Same form or campaign | as given | +5 |
| Received within 10 minutes / the same day | | +10 / +5 |
| Different phones (both have one) | | −40 |
| Different emails (both have one) | | −15 |
| Different names (both named, under 50% alike) | | −30 |

**Bands:**
- **Certain:** the same phone, email or source record. At intake this is already a repeat; found
  later, it goes to review like the rest.
- **Probable (≥ 60):** the review queue.
- **Possible (≥ 35):** a quiet hint on the lead.

Two leads with different phones *and* different emails are two people until a person says
otherwise: never above Possible.

**Comparing only what can match.** Leads are compared within blocking keys: last-10 phone, folded
email, a name key (the first word and the last word's first three letters), company, work domain and
source record. A key shared by more than 60 leads is skipped as saying little.

The thresholds are tuned on AC's own leads (section 7) before the queue is switched on.

## 2. Review queue

Owners and managers see "Possible duplicates (N)":
- each pair side by side, with the reasons in words ("same last 10 digits of the phone; names 92%
  alike") and what speaks against it ("different emails");
- **Merge** or **Not the same**.

"Not the same" is stored and the pair is never suggested again. AI apps (the AI-writes policy) can
only add to the queue, never merge.

## 3. Merge

- **Survivor:** the lead with the most human activity (calls, notes, results, messages and tasks done
  by people), then the earliest received.
- **One timeline:** events, calls, notes, tasks, reminders, meetings, messages and form answers are
  moved to the survivor, each keeping its actor and time.
- **Stage:** the furthest along (Won, then the later milestones), with one history line saying where
  it came from.
- **Open tasks:** de-duplicated by text and due date.
- **The other lead** is kept, marked "Merged into …", and redirects there. Nothing is deleted.
- **Audit:** an event for every merge and unmerge.
- **Unmerge:** possible for 30 days. Every moved row's id is recorded with the merge.

**As built (D3, `lead_desk/merging.py`):**
- The lead merged away closes as **Junk, "Merged into another lead"** (reason key `merged`), and
  `merged_into_id` points to the kept lead. Every queue, the lead rules, alerts, the SLA and the
  reports already leave Junk out, so nothing double-counts it.
- Its moves and the kept lead's stage move carry source `merge`. These are bookkeeping
  (`transitions.stages_changed`): never progress, an ad conversion or a seller's work. Partner
  webhooks never send stage moves.
- **Moved with the lead:** history, meetings, tasks, WhatsApp and social messages, AI reply drafts,
  and calls.
- **Kept where they were made:** ad conversions, partner events, SLA records and read marks.
- **Two open meetings:** the merged lead's meeting is cancelled first, with a history line, so the
  kept lead has one.
- **Repeats:** a new record that matches the merged lead (its phone) joins the kept lead (`_live`
  in the store).
- **Unmerge:** moves every recorded row back. It restores the merged lead's stage, and the kept
  lead's stage and owner if nobody changed them since. It clears the fields the merge filled where
  they are unchanged, and reopens the task and meeting it cancelled.
- **"Worked before":** a history line names the other sellers. Their view access to the kept lead
  comes with D4.

## 4. Who gets the merged lead

- **One seller active:** the seller with the most recent human activity on either lead in the last 14
  days.
- **Two sellers active:** the review sheet asks the manager, defaulting to the most recent. The other
  seller is told, keeps view access, and sees a "worked before" note.
- **Nobody active:** the earliest assignee.
- The reason is always one line ("Kept with Dipak: called them 2 days ago").

## 5. Surfaces

- The lead page banner: "Possible duplicate of …" and "Merged into …".
- A "Duplicates" filter on Leads.
- An Admin metric: open pairs, merged, not the same.
- The API and MCP read the queue, through the AI-writes policy.

## 6. Data (migration 0135)

- `lead_desk_leads.merged_into_id` and `merged_at`.
- `lead_desk_duplicate_pairs`: tenant, the pair (ordered), score, band, reasons, against, computed at.
  Rescanned nightly and on intake.
- `lead_desk_duplicate_decisions`: append-only; not the same, merged, unmerged; by whom and when.
- `lead_desk_merges`: the survivor, the merged lead, the owner chosen and why, the moved row ids by
  kind, done_at, undone_at.

## 7. Tuning and slices

- **D1:** the engine, pure, with property tests (this slice).
- **D2:** the migration and the scan (nightly and on intake).
- **D3:** merge and unmerge.
- **D4:** the API, the filter, the banner data, the metric and the MCP read.
- **D5:** tuning on AC's leads. A read-only run in production prints scores, reasons and masked fields
  only. A sample of pairs per band is judged by its evidence, and precision is reported before the
  thresholds are set.

## 8. First run on AC's leads (25 Oct 2026, read-only, masked)

**Result:** 554 leads gave 4 pairs. Intake already makes a lead with a known phone a repeat, which
is why there are so few.

| Band | Pairs | What they were |
|---|---|---|
| Certain | 3 | 1 pair of Meta testing-tool dummies (test data). 2 pairs with the same email and different phones: plausibly the same person each |
| Possible | 1 | The same name and form within 10 minutes, no contact details: plausibly one entity entered twice |

**What follows:**
- The scan leaves test data out.
- 4 pairs are too few to tune thresholds by statistics. The thresholds stay as set, and each band's
  precision is measured from reviewers' decisions (Merge against Not the same). A band whose
  reviewers mostly say "Not the same" is raised.
