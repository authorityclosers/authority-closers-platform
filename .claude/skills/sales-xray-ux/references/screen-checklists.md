# Screen-by-screen checklists

Tick every line on the screenshots before you score. "Phone" means 360 to 412 px; "computer"
means 1440 px. The rule numbers point at `SKILL.md`.

## Every screen

- [ ] One filled primary action, named for its outcome; on phones in the bottom third (rule 1).
- [ ] Nothing scrolls sideways at 360 px; the frame fits; inner panels scroll (rule 4).
- [ ] Every overlay closes on Back, one per press, and has a visible X (rule 3).
- [ ] Targets 44 px or more, 8 px apart; frequent actions in the lower half (rule 2).
- [ ] Names with capitals, grouped phone numbers, relative dates (rule 6).
- [ ] Skeleton in the final layout; no layout shift; corner cards for errors (rule 10).
- [ ] Light and dark share one layout; text 4.5:1, chart series 3:1; `--sx-*` tokens only.
- [ ] No prices, customer names, emoji, IDs or invented numbers (house rules).
- [ ] The title says where you are (large title in the page, not squeezed into the top bar), and
      the lit tab matches.

## Home (seller)

Job: tell a salesperson who to call next. Primary: "Start calling" or "Call <name>".

- [ ] The first thing under the title is a row of count chips (Late, Due today, New), then the
      Today list: Late (red mark), Call now, Later today. Rows follow the row anatomy (rule 6)
      with a one-tap Call chip and swipe. Late items are never hidden or paged away.
- [ ] Late rows show how late in words ("2 hours late"); due rows show the time. New leads carry
      a "New" chip until the first call or message.
- [ ] Calls that ended without an outcome show as one row ("Log 2 calls") that opens the
      outcome sheet.
- [ ] One strip of today's real numbers: calls made, connected, follow-ups booked. Tapping a
      number opens the matching list.
- [ ] "All caught up" state when nothing is due: says when the next call is and offers one action
      (for example "Add lead").
- [ ] First-use state: one start card (add a lead or connect lead forms), not empty tiles.
- [ ] No long greeting, no tiles the seller cannot act on, no team numbers.
- [ ] Pull to refresh works; the list also refreshes when the app comes back to the front.

## Home (owner and admin dashboard)

Job: show how sales are going. Primary: usually none needed; if one, "View team".

- [ ] A period segmented control at the top (Today, 7 days, 30 days), kept in the address.
- [ ] Four or five outcome numbers in two columns on phones: won or closed, meetings or visits
      booked, new leads, connect rate, first-response time. Each has a trend chip against the
      last period, coloured and worded ("up 12%"), never colour alone.
- [ ] Then sellers ranked by outcome as rows (name, outcome count, connect rate, late follow-ups);
      a row opens that seller's profile.
- [ ] Then the stage funnel as sorted horizontal bars with counts.
- [ ] Activity counts (calls, minutes talked) come after outcomes, never before.
- [ ] Late follow-ups across the team show as one tappable warning chip, not a banner.
- [ ] Charts follow rule 13. No sales value unless the organisation records it. Never our prices
      or costs.
- [ ] An owner who also sells can switch to "My day" (the seller Home) in one tap.

## Leads

Job: work through leads by stage. Primary: "Start calling" (or "Call next" in a stage).

- [ ] Stage tabs with real counts directly under the title; the chosen tab has two cues (fill
      and weight). On phones the strip scrolls sideways inside itself, and the chosen tab is
      scrolled into view. Stages come from the organisation's settings.
- [ ] Search is one filled field or a search icon that opens full-screen search (Back closes it).
- [ ] One Filter chip with a count of active filters; filters open in a sheet with Apply; active
      filters show as removable chips under the tabs.
- [ ] Rows: avatar or initial, name, one context line (source, last contact), status chip, due
      or time on the right. Late rows are marked, not shouted.
- [ ] Swipe right Call, swipe left Message, each with icon and label; hold opens a menu with Call,
      Message, Book the next call and Move to stage.
- [ ] Leads and Chats switch with one segmented control on phones (Chats lives inside Leads).
- [ ] Empty stage: "No leads in <stage>. Move a lead here from its page." No results: "No leads
      match. Clear filters." First use: Add lead or connect lead forms, one button.
- [ ] Long lists page or virtualise past about 50 rows; scroll position survives opening a lead.
- [ ] Team view (owners and admins): sellers as rows with open leads, due now and late; a name
      opens the seller profile.

## Lead page

Job: everything needed to call this person and record what happened. Primary: "Call <name>".

- [ ] Header: name with capitals, stage chip, source, owner. Phone number grouped and tappable.
      The stage chip opens a sheet listing every stage, with Won and Lost always in it.
- [ ] Action row of compact chips: Call, WhatsApp, SMS, Book next call, Move to. Call is the one
      filled primary, at the bottom of the screen on phones. A chip that cannot work (no number)
      is greyed out with a hint, not hidden.
- [ ] Next step first: when the next call is due, what was promised. Then the timeline (calls,
      messages, stage changes, notes), newest first, each with a relative time.
- [ ] Calls in the timeline open their report; analysed calls show a one-line summary.
- [ ] Notes: one field, saves without a separate Save page.
- [ ] After a call ends, an outcome sheet opens by itself, pre-filled from the phone's call log
      where possible. Connected calls: 4 to 6 one-tap outcomes (for example interested, call
      back, not interested, wrong number), a next-call picker with quick choices (in 1 hour,
      this evening, tomorrow, in 3 days, next week, pick a date) and an optional note that keeps
      anything typed during the call. Unanswered calls: one "No answer · try again" chip with a
      time. "Save and book next call" is the primary. Closing it unsaved leaves a "Log call" item
      on Home.
- [ ] An open lead always shows its next call date; "No next call" is a warning chip.
- [ ] Message composer: channel chips (WhatsApp, SMS), ready messages filled with the lead's
      first name, editable before sending. We log the channel and template, never the text.
- [ ] Empty timeline: "No calls yet. Call <name> to start." with the Call button.

## Calls

Job: find a call and see how it went. Primary: "Analyse a call" (upload or pick a recording).

- [ ] Search field and one row of chips (All, Analysed, Waiting, Needs a look) or a segmented
      control; nothing more on the first screen.
- [ ] Rows: who (prospect name with capitals, or "Unknown caller" with the grouped number and an
      "Add as lead" chip), when, how long, call type chip, a status mark (ready, in progress,
      needs attention).
- [ ] A row opens the call preview sheet on phones (swipe or Back closes it) with "Open full
      report" as its primary.
- [ ] In-progress analysis shows a living status mark; it never shows a price, cost or minutes.
- [ ] Empty: "No calls yet. Analyse a recording or turn on call recording pick-up." One button.
- [ ] Numbers at the top, if any, are a small strip (calls this week, analysed, average length),
      not big tiles.

## Call report

Job: show what happened on the call and what to do next. Primary: the next step ("Book
follow-up", "Send message").

- [ ] Report, Prospect and Coaching are one segmented control. Parts are icon tabs.
- [ ] The title row shows a glance strip of real facts: prospect, business, what was sold,
      money mentioned, promises and the next step. Missing facts say "Not asked · add it".
- [ ] One waveform with one lens switch (Who talked, Call stages, Prospect's interest).
- [ ] Key facts carry confidence: a check with "heard at mm:ss" when sure, "Is this right?" when
      not.
- [ ] Quotes fold to two lines; sibling cards share one structure and height.
- [ ] Plain grade 8 to 10 words; no internal coaching citations outside Raw data.
- [ ] Loading: the report's own outline, never the previous call's waveform or text.
- [ ] Withheld or failed parts say what to do in plain words, as a card in place plus a corner
      card for retries; never a technical state.

## Chats

Job: answer leads' messages fast. Primary: "Reply" in a thread; none on the inbox.

- [ ] Inbox rows: name with capitals, last message on one line, time, unread count chip, channel
      icon. Unread rows are bold, not coloured blocks.
- [ ] Chips for All, Unread and Assigned to me; nothing else on top.
- [ ] A thread takes the whole phone screen; Back returns to the inbox at the same place.
- [ ] Composer sits above the keyboard and the safe area; ready replies as chips above it.
- [ ] The lead's panel (stage, next call, Call button) opens as a sheet from the thread header.
- [ ] Empty: "No chats yet. Messages from your lead forms and WhatsApp appear here." One button
      to connect, shown only to people who can connect.

## Settings

Job: change one setting and leave. Primary: "Save" only when changes are not saved instantly.

- [ ] Phones: a list of sections, then the section full screen; Back returns to the list.
      Computers: sections in a sidebar, or the floating settings dialog (`#settings/<section>`).
- [ ] Each row: label, current value on the right, chevron. Toggles save at once with a small
      confirmation; forms show Save in the footer.
- [ ] Group by job (Profile, Team, Leads and stages, Calls and AI, Connected apps, Alerts), five
      to seven groups, plain names.
- [ ] Destructive settings sit last, set apart, and confirm in a sheet.
- [ ] Self-serve: keys, webhooks and connections are set here, not by asking support.
- [ ] No plan prices or costs; a plan shows its name and what it includes only where allowed.

## The + sheet

Job: start something new from anywhere. Opens from the centre + tab.

- [ ] A bottom sheet with a drag handle, title and X; 3 to 6 rows, each with an icon tile,
      label and one-line hint; most used first.
- [ ] Rows are things the app really does for this person's role, for example Add lead, Log a
      recent call (pick from the phone's call log), Analyse a call, Book a follow-up.
- [ ] Add lead opens a short form as a step in the same sheet: name (required, capitals on
      input), phone (tel keyboard, +91 ready), stage (the first stage by default), source,
      owner; "More fields" stays folded. Save is the sheet's primary.
- [ ] The phone number is checked for duplicates as it is typed; a match offers "Open existing
      lead" instead of saving a second one.
- [ ] Back, swipe down, X and scrim all close it; a form with typed input asks before closing.
- [ ] The sheet never covers the tab bar's safe area in a way that hides its own Save button.
