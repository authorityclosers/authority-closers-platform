# NeoDove: public evidence for a Sales Xray "Lead Desk"

Compiled 16 Oct 2026, from public material only. I did not sign up, log in, submit any form or download anything.

**How to read this file**
- Every bullet ends with its source in brackets.
- "(inferred)" marks something I concluded but no source states directly.
- Text in "quotes" is a short on-screen label copied verbatim from the source. Everything else is paraphrased.
- Most detail comes from the official help centre at docs.neodove.com. Each page there also has a raw `.md` twin (append `.md`), and the full index is at [https://docs.neodove.com/llms.txt].
- Freshness:
  - The help-centre product updates run from Aug 2023 to Nov 2024.
  - The iOS release notes run to Oct 2026.
  - The marketing site is current.
  - Where these sources conflict, it is noted.

Product shape in one line: NeoDove has three surfaces:
- an Admin Portal (web, connect.neodove.com) for managers and admins;
- an Agent web app, also called the "Web Dialer" or "Agent Portal";
- an Agent mobile app (Android `com.cellphone.neodove`, iOS id1663716707). [https://neodove.com] [https://docs.neodove.com/llms.txt] [https://apps.apple.com/app/id1663716707] [https://play.google.com/store/apps/details?id=com.cellphone.neodove&hl=en_US — package id from search result; page body not readable]

---

## 1. Salesperson (telecaller / "Executive") mobile app

### 1.1 App identity and sign-in
- Android app name: "NeoDove Telecalling CRM", package `com.cellphone.neodove`, developer NeoDove Technologies Pvt Ltd. [https://play.google.com/store/apps/details?id=com.cellphone.neodove&hl=en_IN — via search snippet]
- The Play listing tagline describes the app as a dialer and telecalling CRM with Caller ID. [Play listing via search snippet, same URL]
- AppBrain reportedly shows about 150K downloads. [https://www.appbrain.com/app/neodove-telecalling-crm/com.cellphone.neodove — via search snippet; page itself failed to load]
- iOS app "NeoDove", subtitle "India's Best Telecalling CRM", version 1.6.14 as of Oct 2026. [https://apps.apple.com/app/id1663716707]
- Sign-in uses the registered mobile number and a password. [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]
- Admins and managers can switch between Admin and Agent views from an icon at the top right. [https://docs.neodove.com/product-updates/february-2024]
- Admins and managers can set Agent View or Admin View as their default. [https://docs.neodove.com/product-updates/january-2024]
- Some advanced functions are web-only. The core lead and call tasks work on mobile. [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]

### 1.2 Home / Dashboard
The doc says there are 10 sections but describes only 9. [https://docs.neodove.com/neodove-mobile-application/homepage]
1. **"Start"** button, under the user's name at the top. It begins calling leads in priority and follow-up order. [same]
2. **"My Campaigns"**: campaigns the user belongs to. Starts campaign-wise calling. [same]
3. **"My Leads"**: overview of **Open**, **Follow-up** and **Not Connected** leads. It has a "View" option (browse manually) and "Start Calling" (run the call loop). [same]
4. **"My Tasks"**: tasks assigned to you, or reported by you. [same]
5. **"My Reports"**: Call and Login reports, with a calendar to pick the date. [same]
6. **"Call Logs"** (bottom left): full call history. [same]
7. **"Walk-In Leads"** (next to Call Logs): add a single lead by hand. [same]
8. **Filter option** (top): search and filter, then call the filtered set. [same]
9. **Notification bell** (top right). [same]

The Agent web app home has the same items. Its 10th item is a "Message Us" button that escalates to the "NeoDove Delight Team" on WhatsApp. On the web, Walk-In is a "+" above Call Logs. [https://docs.neodove.com/neodove-web-application/homepage]

Other menu items in the app: Change Language, Contact Support, Refer And Earn. [https://docs.neodove.com/llms.txt]

### 1.3 Lead lists, tabs and filters
- There are four ways to start calling. [https://docs.neodove.com/neodove-mobile-application/calling-leads]
  - **Priority-wise**: across campaigns.
  - **Campaign-wise**: ignores priority.
  - **Through "My Leads"**.
  - **Through filters**.
- My Leads categories, as written: "New/Unattempted leads", "Follow-up Leads", "Not Connected Leads". You pick a category, then tap "Start Calling". [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-through-my-leads]
- My Campaigns: open a campaign to see its lead list, then tap "Start Calling" to get leads one by one. [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-campaign-wise]
- Filters (agent web app):
  - "Search by contact number" plus a filter dropdown.
  - A checkbox, "Include converted and lost leads in your search?". Closed leads are hidden by default.
  - Then "Start Calling". [https://docs.neodove.com/neodove-web-application/calling-leads/filter-wise]
- Agents can filter by lead assignment date, in the Agent App, the Agent Portal and the Admin Portal. [https://docs.neodove.com/product-updates/july-2024]
- Agents can filter Status → Not Connected, then tick specific not-connected reasons. [https://docs.neodove.com/product-updates/april-2024]
- "My Followups" has a quick date filter at the top, pre-set to "Today". [https://docs.neodove.com/product-updates/july-2024]
- iOS added an "All Leads" view with quick filters (v1.5.7) and a "Merge & Reopen" filter (v1.6.13). [https://apps.apple.com/app/id1663716707]
- Search covers alternate numbers as well as the primary number. [https://docs.neodove.com/product-updates/october-2024]
- Search works on the first 6 digits, for when the last 4 are masked. [https://docs.neodove.com/product-updates/august-2024]
- Saved filters exist in the Agent Portal. Admins can save up to 10. [https://docs.neodove.com/product-updates/july-2024]

### 1.4 Lead card / lead detail
- The lead card shows name, number, campaign name "and more". [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-priority-wise]
- A pencil icon edits the lead's details. [same]
- The permission "Allow user to edit lead information" controls edits to name, primary number, alternate numbers and email. [https://docs.neodove.com/product-updates/july-2024]
- Number masking can hide the lead's number. The setting "Display contact number on the lead" was later moved into Roles and Permissions. [https://docs.neodove.com/admin-portal/settings]
- The lead info page shows the lead's current assignee. [https://docs.neodove.com/product-updates/august-2024]
- Unassigned leads show **"Assign to Myself"**. The agent must claim the lead before calling, editing or disposing it. [https://docs.neodove.com/product-updates/october-2024]
- Expanded lead view:
  - An "About Lead" section holds contact details and engagement-form answers.
  - A single **Timeline** merges stage changes and calls. It replaced the separate "Call Logs" and "Dispose History" tabs. [https://docs.neodove.com/product-updates/february-2024]
- Dispose remarks show in the dispose history. [https://docs.neodove.com/llms.txt — "Remarks in Dispose History", Oct 2023]
- The disposition pop-up shows full lead details, the complete interaction timeline and call history (iOS v1.1.151). [https://apps.apple.com/app/id1663716707]
- Contact-history call recordings can be played in the Agent Application, not only the Agent Portal. [https://docs.neodove.com/product-updates/january-2024]
  - Conflict: the Settings doc says the "Allow to Listen Contact History Call Recording" toggle works only in the Web App. [https://docs.neodove.com/admin-portal/settings]
- "Display additional lead properties" shows every property of leads merged into a campaign. [https://docs.neodove.com/admin-portal/settings]

### 1.5 The call button flow
1. Tap **Start** (or **Start Calling**). One lead is pushed to the screen. [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-priority-wise]
2. Review the lead's info and contact history. [https://docs.neodove.com/neodove-mobile-application/dispose-lead]
3. **Place the call.** The default is to tap the number. If the admin turned on **"Enable automatic call dialing"**, the app dials by itself after a set interval. Example: with a 5-second interval, the call starts within 5 s of the lead appearing. [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-priority-wise] [https://docs.neodove.com/admin-portal/settings]
4. On a dual-SIM phone, choose the SIM. The app places the call through the phone's dialer, so there is no manual dialling. [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-priority-wise]
5. After the call, open the "Lead Details Form" / "Customer Details Form" and dispose the lead (§1.6). [same]
6. **The current lead must be disposed before the next call.** [https://docs.neodove.com/neodove-mobile-application/dispose-lead]
   - The FAQ says disposition is mandatory because it captures the call recording, talk time and the details entered. [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]

Calling from the agent web app:
- Clicking the number gives "a notification on your phone". The call is then made from the phone's dialer and SIM, so web click-to-call is bridged to the agent's phone (inferred). [https://docs.neodove.com/neodove-web-application/calling-leads/priority-wise] [https://docs.neodove.com/neodove-web-application/calling-leads/filter-wise]
- The web dialer can also call over VoIP from the browser. [https://docs.neodove.com/neodove-web-application/faqs-web-application]

Telephony modes:
- **GSM / personal SIM**: the default. [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]
- **PSTN**: a SIM-based IVR call, bought as an add-on through Marketplace. [https://docs.neodove.com/admin-portal/marketplace-ivr/ivr-services/basic-differences]
- **VoIP / SoftPhone**: internet calling, also a Marketplace add-on. [same]

PSTN versus VoIP: [https://docs.neodove.com/admin-portal/marketplace-ivr/ivr-services/basic-differences]
- PSTN is domestic only, with no multiple outbound DIDs.
- VoIP is domestic plus international, with multiple DIDs.
- Both support call barging. Only VoIP supports transfer and conference.

Other call features:
- A **"Dialpad"** lets an agent call a number without first creating a lead, over personal SIM, PSTN or VoIP, then optionally save it as a lead. [https://docs.neodove.com/product-updates/november-2024]
- **Caller ID** shows lead details on incoming calls. [Play listing via search snippet]
- **Missed calls** (cloud telephony only): the relevant user is notified and can call back. Missed calls appear in agent and admin call logs. [https://docs.neodove.com/product-updates/october-2024]
- An incoming-call pop-up for VoIP gives a browser notification, and the number can be copied. [https://docs.neodove.com/llms.txt — Aug 2023 updates]

### 1.6 Post-call disposition ("Dispose Lead")
The first question is **"Was the Call Connected?"**, with two buttons: **"Yes, Connected"** and **"Not Connected"**. [https://docs.neodove.com/neodove-mobile-application/dispose-lead]

**Path A, "Yes, Connected"** [https://docs.neodove.com/neodove-mobile-application/dispose-lead/yes-connected] [https://docs.neodove.com/neodove-mobile-application/dispose-lead]
1. The campaign's **Engagement Form** (Customer Details / Lead form, a questionnaire or script) opens. Answers are saved to the lead and appear in report downloads.
2. A small **send-message tab** with WhatsApp, SMS and Email icons sits beside the questionnaire.
   - Tapping an icon loads the pre-drafted template into "Message Preview".
   - Pick the number or email ID, then tap "Send". The native WhatsApp, SMS or email app opens with the text, and the agent can edit it there.
3. Tap **"Next"**.
4. Select **Stage** and **Tags**. These come from the campaign's pipeline, set in the Admin Portal.
5. **"Select next action"**:
   - Stages **Converted** and **Lost** close the lead.
   - Any other stage or tag needs a follow-up date and time, which is the default below this section.
   - The follow-up becomes optional if the admin enables "Allow Dispose Lead Without FollowUp".
6. **Quick follow-up chips**: "One Hour", "Tomorrow" (+24 h), "Next Week" (+7 d). Otherwise pick from a calendar, with a year dropdown. [https://docs.neodove.com/product-updates/august-2023/lead-dispose-quick-follow-up-options]
7. Optional: **"Re-assign this lead to other User"** and **"Copy lead to other campaign"**. Each is gated by a permission (§2.3).
8. **"Dispose Remark"**: free-text notes. iOS has speech-to-text for remarks (inferred from the v1.6.9 fix "speech-to-text permission … for remarks"). [https://apps.apple.com/app/id1663716707]
9. **"Submit"**.

More on Path A:
- A deal amount can be recorded during disposition. The admin chooses its currency. [https://docs.neodove.com/admin-portal/settings]
- Disposing another user's lead no longer moves it to you, unless you reassign it to yourself in the dispose step. [https://docs.neodove.com/product-updates/august-2024]
- Disposing from a list view records the call start time. [https://docs.neodove.com/product-updates/october-2024]

**Path B, "Not Connected"** [https://docs.neodove.com/neodove-mobile-application/dispose-lead] [https://docs.neodove.com/neodove-web-application/dispose-lead/not-connected]
1. Pick one reason (verbatim list in §9.1).
2. Optionally set a follow-up date and time. The admin can make it mandatory with "Follow-ups to be mandatory for Not Connected Leads".
3. Reassign and copy-to-campaign are available here too.
4. Messaging (WhatsApp, SMS, Email) is available too.
5. "Submit".

More on Path B:
- Admins can rename not-connected reasons, for example showing both "Did Not Pick" and "Call Not Connected" as "DNP". [https://docs.neodove.com/product-updates/july-2024]
- iOS v1.5.3 made the not-connected reason optional (admin-controlled), added in-line follow-up warnings, and added auto-scheduled follow-ups for retries. [https://apps.apple.com/app/id1663716707]

### 1.7 Follow-ups, notes, tasks
- Follow-ups are set in the dispose flow (§1.6), and the "My Followups" list defaults to Today (§1.3).
- Tasks: "My Tasks" has two tabs, **"Assigned to me"** and **"Reported by me"**. [https://docs.neodove.com/neodove-mobile-application/my-tasks/assigned-to-me]
  - Open a task to view its lead details.
  - Press "Call" to ring the lead.
  - Add a comment, choose an updated status, then "Submit".
- A 9 AM notification lists tasks due today. [https://docs.neodove.com/product-updates/january-2024]
- Notes are the "Dispose Remark" (§1.6) plus engagement-form answers. No separate notes screen is documented (inferred).

### 1.8 WhatsApp / SMS / Email templates
- Templates are built inside the campaign's Engagement Form as a "Send message" question type. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/customer-details-form]
  - They cover SMS, Email and WhatsApp, with unlimited templates.
  - A "Send Email" type sends from one central email ID.
  - An "Attach File" type is also available.
- Template variables:
  - A variables dropdown sits in "Send Message". [https://docs.neodove.com/product-updates/august-2024]
  - Variables include contact number and user number. [https://docs.neodove.com/product-updates/april-2024]
  - iOS v1.2.0 added lead, agent and organisation placeholders, usable inside the Dialer. [https://apps.apple.com/app/id1663716707]
- File uploads in Send Message are email attachments only, not WhatsApp. [https://docs.neodove.com/product-updates/august-2024]
- Messages are sent without saving the contact to the phone. [https://neodove.com/features/customer-engagement/]
- Ordinary sends open the native WhatsApp app. Automated WhatsApp from Workflows needs NeoDove's paid WhatsApp API. [https://docs.neodove.com/admin-portal/workflows]
- Agent web has a "Neo WhatsApp" page. [https://docs.neodove.com/llms.txt]

### 1.9 "Power dialer" / auto-dial queue
- The queue is the Start → call → dispose → next-lead loop. Leads come "one by one" from Start, Start Calling (campaign), My Leads category, or a filter result. [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-campaign-wise] [https://docs.neodove.com/neodove-web-application/homepage]
- Auto-dial is a timed auto-call after the lead appears, controlled by the admin setting "Enable automatic call dialing" plus an interval. [https://docs.neodove.com/admin-portal/settings]
- The admin can hide the campaign Start Calling button with "Display Start Calling button". [https://docs.neodove.com/admin-portal/settings]
- Marketing language:
  - "status-wise calling, click-to-dial, campaign-based calling" and "Progressive Auto Dialing". [https://neodove.com/features/dialer/] [https://apps.apple.com/app/id1663716707]
  - The FAQ separates progressive (shows details before dialling) from predictive (bulk dialling) dialers. [https://neodove.com/?p=46532 (Integrations page FAQ)]
  - Reviewers mention a "predictive dialer". [https://www.softwareadvice.com/voip/neodove-profile/reviews/ — via search snippet]
- In product terms it is a one-at-a-time progressive dialer on the agent's own phone. No public doc describes true parallel predictive dialling (inferred).

### 1.10 Call recording (Android)
- Older marketing FAQ: SIM-based recording is not possible because of Google's rules. Recording comes via IVR (cloud telephony). [https://neodove.com/?p=46532]
- Current approach: a GSM recording setup reads the phone's own call-recording files. The steps follow. [https://docs.neodove.com/neodove-mobile-application/gsm-call-recording-setup-guide]
  1. Turn on auto-record in the phone's native dialer. Make a test call to find the folder, e.g. Internal Storage > Recordings > Call.
  2. In NeoDove app Settings, enable the call-recording toggle. Under "Call Recording Path", choose either:
     - **"Use Built-in Call Recorder"**, or
     - **"Use NeoDove Call Dialer"**.
  3. Enter the recordings folder path by hand. The folder must have **no subfolders**.
  4. If the phone saves into sub-folders (Itel and Infinix are named), install the third-party recorder **Cube ACR**. Enable its "Cube ACR App Connector" accessibility service and allow restricted settings and background running.
  5. Grant all permissions, especially storage.
  6. After a call and disposition, the recording and duration show under **Call Logs**. Sync can take **up to 15 minutes**.
- **NeoDialer** (Feb 2024) is NeoDove's own call-recording dialer app, giving accurate call duration and recordings. [https://docs.neodove.com/product-updates/february-2024] (setup page mobile-docs.neodove.com/neodialer returned 403)
- The FAQ links disposition to capturing the recording and talk time. Upload is probably triggered or matched at dispose time (inferred). [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]
- How a file is matched to a call is not documented. Matching by call time and number from the call log is likely (inferred).
- Third-party APK mirrors list these permissions: record audio, read call log, storage read/write. Not verified against the official listing. [https://apkpure.com/neodove-telecalling-crm/com.cellphone.neodove — via search snippet]
- Workflows/webhook can send call duration and the recording to third-party tools for each disposition. [https://docs.neodove.com/product-updates/october-2024]
- iOS: the GSM guide covers Android only. iOS GSM recording is presumably unsupported (inferred). [https://docs.neodove.com/neodove-mobile-application/gsm-call-recording-setup-guide]
- One review complaint (Oct 2023) says call recordings and reports were hard to get. [https://www.softwareadvice.com/voip/neodove-profile/reviews/ — via search snippet]

### 1.11 Call logs, my reports, walk-ins, notifications
- **Call logs**: [https://docs.neodove.com/neodove-mobile-application/call-logs]
  - All incoming and outgoing calls for the agent.
  - IVR produces incoming and outgoing logs. GSM produces outgoing only.
  - IVR incoming logs are created automatically when answered, with lead info and time.
- **My Reports**: [https://docs.neodove.com/neodove-mobile-application/my-reports]
  - "Call Reports" (total talk time, total calls made, etc.) and "Login Reports" (the day's activity).
  - Date calendar on the left.
  - A custom date range was added later. [https://docs.neodove.com/product-updates/october-2024]
  - "Agent Report" was redesigned for the web portal and the app. [same]
- **Walk-In Leads**:
  - A bottom button opens it. Enter the details and Submit. The lead is created and assigned to the agent who added it, and a notification opens it. [https://docs.neodove.com/neodove-mobile-application/walk-in-leads]
  - Required fields: name, phone, campaign, agents to assign. [https://docs.neodove.com/admin-portal/contacts/faqs-contacts-or-data-upload]
  - A duplicate warning offers create new, merge or ignore. [https://docs.neodove.com/product-updates/october-2024]
  - Phone contacts can be imported as walk-in leads. [https://docs.neodove.com/product-updates/april-2024]
  - Section names show on custom lead forms. [https://docs.neodove.com/product-updates/october-2024]
- **Contacts module on mobile**: add, edit and manage contacts. [https://docs.neodove.com/product-updates/october-2024]
- **Notifications**: [https://docs.neodove.com/neodove-mobile-application/notifications]
  - Bell at top right. Items stay **24 hours**. Pending items are highlighted.
  - Tapping an item opens the lead to call and dispose. The exception is "bulk leads assigned", which is not clickable.
  - Follow-up notifications for Not Connected leads were opt-in, then default for manual follow-ups. [https://docs.neodove.com/product-updates/january-2024] [https://docs.neodove.com/product-updates/february-2024]

### 1.12 Breaks, offline
- Agents have a break state: the admin setting "Time to Notify Manager If Executive is on Break" alerts the manager when a break runs over. A break/resume control in the app is probable (inferred). [https://docs.neodove.com/admin-portal/settings] [https://apps.apple.com/app/id1663716707 — "break notifications"]
- Offline behaviour: not documented anywhere I found. The product is described as cloud-based. [https://neodove.com/telecalling-software/]

---

## 2. Manager / admin web screens (Admin Portal, connect.neodove.com)

### 2.1 Navigation
- Areas named in docs: [https://docs.neodove.com/admin-portal] [https://docs.neodove.com/admin-portal/campaigns/create-campaign] [https://docs.neodove.com/admin-portal/trends]
  - Dashboard
  - Pipeline (campaigns)
  - Contacts
  - Integrations
  - Reports
  - Trends
  - Marketplace (IVR, WhatsApp API, SMS)
  - Workflows
  - Settings / Manage Users
  - Billing and Subscription
  - Profile
- The left menu can be collapsed, in both the admin and the dialer web portals. [https://docs.neodove.com/product-updates/september-2024]

### 2.2 Dashboard
- Views: "Classic View" and "New View". [https://docs.neodove.com/admin-portal]
- Sections: [https://docs.neodove.com/admin-portal]
  - **Pinned Campaigns**: maximum 4. [https://docs.neodove.com/product-updates/september-2023/admin-dashboard-redesign]
  - **Lead Source Summary**: leads by channel for the period.
  - **Lead Analysis**: leads in buckets.
  - **Call Analysis**: total call attempts, calls connected, and % for each.
  - Shortcuts for upload leads, create campaign, user reports and manage users.
- Live agent tracking and campaign stage data were added to the dashboard. [https://docs.neodove.com/product-updates/october-2024]
- Dashboard filters: custom date range (last 30 days). Filter choices persist after logout. [https://docs.neodove.com/product-updates/september-2024]
- Marketing claims about the manager dashboard: [https://neodove.com/features/team-management/]
  - Real-time view of live calls, agent status and availability, pending follow-ups and lead status.
  - Metrics named: "calls made", "calls connected", "talk time", "follow-ups completed", "lead conversions", "response time", "productivity", "attendance", "team performance".

### 2.3 Team / agent management ("Manage Users")
- User actions listed in the docs: [https://docs.neodove.com/llms.txt]
  - Add user
  - Add users in bulk
  - Edit
  - Deactivate
  - Reset password
  - View a user's assigned campaigns
  - Re-assign all of a user's leads across every campaign
  - Disable Lead Assignment
  - Delete
  - Roles & Permissions
- **Disable Lead Assignment**: from the three-dot menu on the user. The user stops receiving new leads in all campaigns, from uploads and integrations. Reversed with "Enable Lead Assignment". [https://docs.neodove.com/admin-portal/users/how-to-disable-lead-assignment] [https://docs.neodove.com/product-updates/january-2024]
- Default roles: **Organization Admin**, **Managers**, **Assistant Managers**, **Executives**. [https://docs.neodove.com/admin-portal/users/roles-and-permissions]
  - Roles can be renamed, and new ones added with "Add New Role". "Reset to Default" restores them. [same] [https://docs.neodove.com/admin-portal/settings]
- Permissions named in docs:
  - "Allow user view contact history", "Allow user to reassign lead to other user", "Allow user to copy lead to other campaign". [https://docs.neodove.com/product-updates/september-2023/app-permissions]
  - "Allow user to edit lead information". [https://docs.neodove.com/product-updates/july-2024]
  - View lead's history across campaigns. [https://docs.neodove.com/product-updates/november-2024]
  - Reopen closed leads. [https://docs.neodove.com/product-updates/january-2024]
  - Number masking. [https://docs.neodove.com/admin-portal/settings]
- Working hours can be set per user. [https://docs.neodove.com/product-updates/february-2024]
- The "Manage Users" layout was revamped, and the old table view kept. [https://docs.neodove.com/product-updates/october-2024]

### 2.4 Lead management (campaign "View Leads" = Lead Summary)
- Path: Pipeline → pipeline type → campaign → "View Leads". [https://docs.neodove.com/admin-portal/campaigns/lead-summary]
- The lead list shows detail plus a timeline of when added, stage changes, rep interactions and messages. [same]
- Columns are configurable under Settings → Manage Columns (default properties and custom properties), and the choice also applies to downloads. [https://docs.neodove.com/admin-portal/settings]
  - Optional columns include "Last Call Date" and Call Attempt Count. [https://docs.neodove.com/product-updates/april-2024]
- Shift-click selects a range of leads. [https://docs.neodove.com/product-updates/february-2024]
- **Advance Filters**, 10 criteria: Lead details, Users, Status, Stages, Tags, Creation date, Assignment date, Contact source, Follow up, Call attempts. Plus "Save Filter". [https://docs.neodove.com/admin-portal/campaigns/lead-summary/advance-filters-lead-summary]
  - Paused and active campaigns are separated in the filter. [https://docs.neodove.com/product-updates/october-2024]
- **Bulk Actions** [https://docs.neodove.com/admin-portal/campaigns/lead-summary/bulk-actions]
  - **Update**: change stages, tags and follow-up dates, plus **Reassign Leads** (user to user, or unassigned to user).
  - **Delete**: type "Delete", then "Yes, I'm Sure". This is a hard delete.
  - **Move to Other Campaign**: moves the leads with their history.
  - **Close Leads**: upload a file to mark leads converted or lost. Closed leads drop out of call flows.
  - **Copy** to another campaign. [https://docs.neodove.com/product-updates/april-2024]
- Campaign actions menu: Upload Leads, Edit Campaign (including pause or stop), Copy a Campaign, Delete a Campaign, View Tasks, View Call Logs. [https://docs.neodove.com/llms.txt] [https://docs.neodove.com/admin-portal/campaigns/faqs-pipelines-and-campaigns]
- Deleting an uploaded file deletes every lead it created. [https://docs.neodove.com/product-updates/august-2024]
- The "Move Lead Journey" feature (move leads between campaigns, set user, stage and tags) is available in the Admin Portal, the Agent App and Workflows. [https://docs.neodove.com/product-updates/november-2024]

### 2.5 Reports
- Report names, verbatim: see §9.3. [https://docs.neodove.com/admin-portal/reports]
- The Reports home has: [same]
  - "All Reports", "Recently Viewed", "Favourites" (star a report)
  - "Download Logs" (with a "Download Now" link)
  - Search, and "New View"
- Shared features across reports: [https://docs.neodove.com/admin-portal/reports/user-call-report] [https://docs.neodove.com/product-updates/september-2024] [https://docs.neodove.com/product-updates/july-2024] [https://docs.neodove.com/product-updates/october-2024]
  - Choose columns ("… View" option), add or hide columns, drag to reorder, resize.
  - Export to Excel, PDF, JPG or CSV.
  - "Focused Downloads" for chosen columns.
  - Share reports by WhatsApp or email.
  - Downloads include the total record count.
- What each report shows (column names are only in screenshots):
  - **User Report**: an all-in-one view of each user's calling, disposition and activity. Filters: Date, Reporting Manager, Users. [https://docs.neodove.com/admin-portal/reports/user-report] [https://docs.neodove.com/product-updates/october-2024]
  - **User Activity Report**: productivity time, number of breaks, active working hours. Filters: Date, Users. [https://docs.neodove.com/admin-portal/reports/user-activity-report]
  - **Lead Disposition Report** (also "User Lead Disposition Report"): disposition columns, split out of the user call report. Filters: Date, Users. [https://docs.neodove.com/admin-portal/reports/lead-disposition-report] [https://docs.neodove.com/product-updates/september-2024]
  - **Message Activity Report**: counts of WhatsApp, email and SMS sent per user. [https://docs.neodove.com/product-updates/september-2024]
  - **User Call Report**: calls made, call types, durations. Filters: Date, Users. [https://docs.neodove.com/admin-portal/reports/user-call-report]
    - Choosing a date range gives one aggregate row per user. [https://docs.neodove.com/product-updates/august-2023/user-call-report-aggregate-stats-for-date-range]
    - Example columns: "Total Calls Attempted", "Average Call Duration". [https://docs.neodove.com/product-updates/july-2024]
  - **Follow-Up Report**: due and missed follow-ups (MVP: due today, missed yesterday). Filters: Users, Managers. [https://docs.neodove.com/admin-portal/reports/follow-up-report] [https://docs.neodove.com/product-updates/january-2024]
  - **Login Report**: user login activity. [https://docs.neodove.com/admin-portal/reports]
  - **Campaign Report**: calls per campaign, call types, durations. Filters: Date, Pipeline, Campaign, "Campaign Status Wise". [https://docs.neodove.com/admin-portal/reports/campaign-report]
  - **Campaign Lead Report**: listed, not described. [https://docs.neodove.com/admin-portal/reports]
  - **Campaign Stage Report**: stage-wise lead counts per campaign, with no date filter. Filters: Pipeline, Campaign. [https://docs.neodove.com/admin-portal/reports/campaign-stage-report] [https://docs.neodove.com/product-updates/october-2024]
- **Automatic Report**: productivity and lead-progress reports sent to the Org Admin's email and phone, daily, weekly or monthly. [https://docs.neodove.com/admin-portal/settings]
- Hourly report download exists. [https://docs.neodove.com/llms.txt — Aug 2023]
- **Trends** has two tabs. [https://docs.neodove.com/admin-portal/trends]
  - **Business Trends**: "Call Attempted V/s Call Connected", "Total Call Duration", "Total leads closed vs Total leads converted", "Leads Added", "Lead Sources", "Lost Leads".
  - **User Trends**: "Call Attempted V/s Call Connected", "Total leads closed vs Total leads converted", "Total Call Duration", "Average Break Time per Day", "Average Number of Breaks per Day", "Lost Leads".
  - At most 4 charts and 4 widgets show at once. A "Graph & Widget" picker swaps them, and "Request Graph" sends a request to the team.
  - A toggle switches between trends and data tables. [https://docs.neodove.com/product-updates/april-2024]
- Admin reports and trends are also in the mobile app, with user, date and campaign filters. [https://docs.neodove.com/product-updates/november-2024]

### 2.6 Live monitoring, call recording review, leaderboard
- Live monitoring:
  - Dashboard "live agent tracking". [https://docs.neodove.com/product-updates/october-2024]
  - Marketing describes real-time call activity and agent status. [https://neodove.com/features/team-management/]
  - Call barging is available on PSTN and VoIP IVR. [https://docs.neodove.com/admin-portal/marketplace-ivr/ivr-services/basic-differences]
- Call recording review:
  - Campaign → "View Call Logs", filtered by date range, users and call status, and later lead stage. Downloadable. [https://docs.neodove.com/admin-portal/campaigns/call-logs] [https://docs.neodove.com/product-updates/october-2024]
  - Recordings appear in Call Logs. [https://docs.neodove.com/neodove-mobile-application/gsm-call-recording-setup-guide]
  - Recordings can also be played from the lead's contact history. [https://docs.neodove.com/admin-portal/settings]
- Unattempted-but-disposed detection is a manual Excel exercise:
  1. Export the call logs.
  2. Pivot Call Duration by User Assigned.
  3. Count "Null" durations: these are leads disposed without a call. [https://docs.neodove.com/product-updates/september-2023/find-out-if-your-leads-are-even-being-attempted-or-not]
- Leaderboard: none found. Marketing mentions only "team comparison" and top performers. [https://neodove.com/features/team-management/]

---

## 3. Lead states, stages, pipeline, fields, sources

- **Pipeline**: [https://docs.neodove.com/admin-portal/campaigns]
  - A set of stages, plus tags per stage, plus transitions.
  - A default pipeline ships with default stages, tags and transitions. Their names are not public.
  - Everything is editable: "Create Pipeline", "+" → "Add Stage", "Save".
  - Tags are typed per stage (examples: hot, cold, warm).
  - Every campaign belongs to exactly one pipeline.
- "Categories" were renamed "Pipelines", with up to 10 allowed. [https://docs.neodove.com/product-updates/january-2024]
- Plan limits are 2 pipelines (Lite) and 4 (Plus). [https://neodove.com/pricing/]
- A new stage is auto-enabled as a transition from all other stages. A pipeline can be deleted only once it has no campaigns. [https://docs.neodove.com/product-updates/february-2024]
- **Closing stages**: **Converted** and **Lost** close a lead. All other stages need a follow-up. [https://docs.neodove.com/neodove-mobile-application/dispose-lead/yes-connected]
- **Status**, which is a separate filter from Stage: [https://docs.neodove.com/admin-portal/campaigns/lead-summary/advance-filters-lead-summary]
  - Status values seen in docs: Open, Follow-up, Not Connected [https://docs.neodove.com/neodove-mobile-application/homepage].
  - "New/Unattempted" [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-through-my-leads].
  - Unassigned [https://docs.neodove.com/product-updates/october-2024].
  - Closed (converted or lost) [https://docs.neodove.com/admin-portal/campaigns/lead-summary/bulk-actions].
  - Reopened (Merge & Reopen) [https://apps.apple.com/app/id1663716707].
  - The exact enum is not public (inferred list). iOS v1.4.11 notes "New and enhanced lead statuses" without naming them. [https://apps.apple.com/app/id1663716707]
- Lead categories in a campaign show two views, "leads status" and "lead tags". Tags are clickable to filter. [https://docs.neodove.com/product-updates/august-2023/interactive-lead-tags-simplifying-campaign-category-navigation]
- **Lead fields**:
  - API standard keys are `name`, `mobile` (mandatory) and `email`, plus any custom keys. [https://docs.neodove.com/admin-portal/integrations/custom-integration]
  - Google Sheets mapping requires "Contact Name" and "Contact Number". [https://docs.neodove.com/admin-portal/integrations/google-sheets-integration/integration-steps]
  - Other fields: alternate numbers [https://docs.neodove.com/product-updates/july-2024], contact source, creation date, assignment date, follow-up, call attempts [https://docs.neodove.com/admin-portal/campaigns/lead-summary/advance-filters-lead-summary], last call date [https://docs.neodove.com/product-updates/april-2024].
- **Custom fields: "Custom Contact Properties" (CCP)** [https://docs.neodove.com/admin-portal/contacts/what-are-custom-contact-properties]
  - Types: text, date (with a date format) and number.
  - Rename only. Deleting a CCP deletes its data. A toggle turns mapping on or off.
  - Used for search and filters.
  - Can be created during file upload. [https://docs.neodove.com/product-updates/april-2024]
  - Engagement-form questions can be mapped to CCPs. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/customer-details-form]
- **Engagement Form question types**: see the verbatim list in §9.4. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/customer-details-form]
  - Options include a compulsory toggle per question, "Allow Other as a option", and section branching by answer.
  - Scripts can be in any language. There is a Preview, and "Duplicate Section". [https://docs.neodove.com/product-updates/august-2024]
- **Lead sources**:
  - The "Contact source" filter. [https://docs.neodove.com/admin-portal/campaigns/lead-summary/advance-filters-lead-summary]
  - Facebook leads get source "Facebook" and Instagram leads get "Instagram". [https://docs.neodove.com/product-updates/april-2024]
  - IndiaMART leads carry `QUERY_TYPE` (for example "W" = direct enquiry). [https://docs.neodove.com/admin-portal/integrations/indiamart-integration]
  - The dashboard has a Lead Source Summary. [https://docs.neodove.com/admin-portal]

---

## 4. Lead allocation / distribution rules

- Distribution is set **per campaign** in "Lead Distribution Settings". It should be set before uploading. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/lead-distribution-settings]
  1. **"AI Assignment"**, renamed **"On-Demand Assignment"** in Nov 2024. [https://docs.neodove.com/product-updates/november-2024]
     - Leads sit in an unassigned or open bucket.
     - Agents who are actively calling pull them first-come, first-served. It is pull-based: idle agents get nothing.
  2. **"Equal Assignment"**: splits leads evenly among all campaign users. The docs never call it "round robin" (inferred to be round-robin-like).
  3. **"Conditional Assignment"**: rule rows. The verbatim labels are:
     - "Column Name" / "Field Name"
     - "Option 1" (the value)
     - the assignee: one user, or a group of users split equally
     - "Otherwise assign lead to" (fallback)
     - "Update" (save)
     - Multiple conditions are allowed.
     - The doc's example routes by language: Hindi leads to two reps, English leads to everyone. [https://docs.neodove.com/product-updates/may-2024]
- Campaign creation fields: "Campaign Name", "Pipeline Type", "Who will be managing this campaign", "Select Agents", "Lead Distribution Settings", "Campaign Priority", "Lead Duplicacy Settings". [https://docs.neodove.com/admin-portal/campaigns/create-campaign]
- **Campaign Priority**: agents calling priority-wise get high-priority campaigns first. [https://docs.neodove.com/admin-portal/campaigns/create-campaign]
- **"Lead Priority"** settings: drag and drop to reorder the lead priorities that drive distribution. The buckets are not named. [https://docs.neodove.com/admin-portal/settings]
- **Auto-reassign on no-action**: "Assign Scheduled Lead of a User to another User" moves a scheduled (follow-up) lead to another user after a set time if the owner is unavailable. [https://docs.neodove.com/admin-portal/settings]
- **Retry Settings** for not-connected leads: [https://docs.neodove.com/admin-portal/settings]
  - Each reason has its own on/off toggle and retry timing. The first seven reasons are on by default, the last three (invalid number, incoming not available, number not in use) off.
  - "Logic setup" sets variable retry gaps, e.g. first retry after 1 hour, next after 1 day. [https://docs.neodove.com/product-updates/july-2024]
  - Retries auto-schedule follow-ups (iOS v1.5.3). [https://apps.apple.com/app/id1663716707]
- Manual controls:
  - Bulk "Reassign Leads" [https://docs.neodove.com/admin-portal/campaigns/lead-summary/bulk-actions]
  - Re-assign all of a user's leads [https://docs.neodove.com/llms.txt]
  - Disable Lead Assignment per user [https://docs.neodove.com/admin-portal/users/how-to-disable-lead-assignment]
  - Agent-side "Re-assign this lead to other User" at dispose [https://docs.neodove.com/neodove-mobile-application/dispose-lead/yes-connected]
  - "Assign to Myself" for unassigned leads [https://docs.neodove.com/product-updates/october-2024]
- Routing by source:
  - Facebook leads can be split into campaigns by conditions on the incoming fields or by Form ID. [https://docs.neodove.com/admin-portal/integrations/facebook-integration/segregate-leads-to-different-campaign]
  - Each integration targets one campaign. [https://docs.neodove.com/admin-portal/integrations/indiamart-integration]
- Marketing wording: "rule-based auto-assignment" by location, language, product interest or agent availability. [https://neodove.com/?p=93789 (blog "How to Manage Leads Efficiently by Using NeoDove CRM")]
- Not found: load-based or capacity-based assignment, or caps per user.

---

## 5. Integrations / lead capture

- All integrations sit under Admin → Integrations. They are on by default for all orgs. Failed lead creations are logged. [https://docs.neodove.com/product-updates/january-2024]
- **Facebook / Instagram Lead Ads** [https://docs.neodove.com/admin-portal/integrations/facebook-integration/integration-steps] [https://docs.neodove.com/product-updates/october-2024]
  - Steps: pick the NeoDove campaign → "Continue with Facebook" → choose the Page → choose the form(s).
  - An "All Forms" option includes future forms.
  - Leads arrive in real time.
  - Live integrations are listed under "Active Integrations Page".
  - Each form can have its own field mapping.
- **Google Sheets** [https://docs.neodove.com/admin-portal/integrations/google-sheets-integration/integration-steps] [https://docs.neodove.com/product-updates/october-2024]
  - Paste the sheet URL → "Upload Google Sheet" → link the Google account → choose a new or existing campaign.
  - Map fields. "Contact Name" and "Contact Number" are required.
  - Manual "Sync" from the Action menu.
  - A Google Sheets add-on can push rows automatically.
- **Google Forms**: Workspace add-on that creates a lead on submit. [https://docs.neodove.com/product-updates/june-2024] [https://workspace.google.com/marketplace/app/neodove_crm/512404941494]
- **Google Ads** lead forms: real time. [https://docs.neodove.com/product-updates/april-2024]
- **IndiaMART** [https://docs.neodove.com/admin-portal/integrations/indiamart-integration] [https://docs.neodove.com/product-updates/october-2024]
  - PULL with a CRM key: every 10 min per the integration doc, every 5 min per the Oct 2024 notes.
  - PUSH: real time, depending on the IndiaMART plan.
- Property and listing portals: JustDial, Sulekha, TradeIndia, 99acres, Housing.com, Magicbricks, Homeonline. [https://docs.neodove.com/llms.txt]
- CRM, commerce and payment tools: HubSpot, Zoho, Wix, WooCommerce (lead per order), Shopify, Razorpay (lead per captured payment), Pabbly, Sarv. [https://docs.neodove.com/llms.txt] [https://docs.neodove.com/product-updates/may-2024]
- WhatsApp providers: WhatsApp API, Aisensy, Interakt, Wati, DoubleTick. These create a lead when a new person messages. [https://docs.neodove.com/product-updates/october-2024] [https://docs.neodove.com/product-updates/november-2024]
- Zapier, IFTTT and Integromat appear on marketing pages. [https://neodove.com]
- **Custom Integration (inbound API)** [https://docs.neodove.com/admin-portal/integrations/custom-integration]
  - A per-campaign "Endpoint" URL (there is also "Endpoint(Update only)").
  - POST with a raw JSON body containing `name`, `mobile` (required), `email` and custom keys.
  - Responds "OK".
  - No auth scheme is documented.
- **Outbound Webhook**: triggers "Lead Create", "Lead Dispose", "Lead Delete". Configured with "Webhook URL" and "Turn it On", with an "Event Status" log. [https://docs.neodove.com/admin-portal/integrations/webhook]
- **Workflows**: [https://docs.neodove.com/admin-portal/workflows]
  - Triggers: lead created, call connected, call not connected.
  - Conditions: campaign, stage, tag.
  - Actions: Copy lead, Move lead, Send WhatsApp template, Send webhook, Send text SMS.
  - Workflows can also create a lead in a new campaign. [https://docs.neodove.com/product-updates/january-2024]
  - Ready-made workflows exist. [https://docs.neodove.com/product-updates/february-2024]
- **File import**: [https://docs.neodove.com/admin-portal/contacts/upload-contacts] [https://docs.neodove.com/admin-portal/contacts/faqs-contacts-or-data-upload]
  - CSV or XLS/XLSX via Contacts → "Upload Contacts", or Campaign → Action → "Upload Leads".
  - Flow: choose a new or existing campaign → map columns → choose duplicate handling → map CCPs → Submit → push notification.
  - The first row and first column must not be blank.
- **Dedupe**:
  - Upload options, verbatim:
    - "Ignore Duplicate"
    - "Merge Duplicate"
    - "Create Duplicate Leads"
    - "Merge Duplicate and Reopen Closed Leads": a new enquiry matching a closed lead reopens it as a new lead. [https://docs.neodove.com/admin-portal/contacts/upload-contacts]
  - Scope: "Global Lead Duplicacy Setting" (org-wide, admin only) or "Campaign Wise Lead Duplicacy Setting". Campaign scope can check within the campaign, within the pipeline, or across all campaigns. [https://docs.neodove.com/admin-portal/settings] [https://docs.neodove.com/product-updates/july-2024]
  - The match key is not documented. It is probably the phone number (inferred).
  - Reviewers complain that duplicates confuse users. [https://www.capterra.co.uk/software/204000/neodove — via search snippet]

---

## 6. Follow-ups, reminders, notifications

- Follow-ups:
  - A follow-up is mandatory on a connected dispose unless the stage is Converted or Lost. Admin can relax this with "Allow dispose lead without Follow-up". [https://docs.neodove.com/admin-portal/settings]
  - Optional on Not Connected unless the admin sets "Followups to be mandatory for not connected calls". [same]
  - Quick picks: "One Hour", "Tomorrow", "Next Week", or a calendar. [https://docs.neodove.com/product-updates/august-2023/lead-dispose-quick-follow-up-options]
- Due follow-ups come first in the Start / priority queue. [https://docs.neodove.com/neodove-web-application/homepage]
  - "My Followups" defaults to Today. [https://docs.neodove.com/product-updates/july-2024]
  - In-line follow-up warnings were added (iOS v1.5.3). [https://apps.apple.com/app/id1663716707]
- An unattended scheduled lead can auto-move to another user. [https://docs.neodove.com/admin-portal/settings]
- Notifications:
  - In-app bell with 24 h retention. [https://docs.neodove.com/neodove-mobile-application/notifications]
  - Follow-up notifications for both connected and not-connected leads. [https://docs.neodove.com/product-updates/february-2024]
  - Tasks-due notification at 9 AM. [https://docs.neodove.com/product-updates/january-2024]
  - "Notifications" settings tab where admins choose PUSH or In-App per event. [https://docs.neodove.com/product-updates/october-2024]
  - Manager alert when an agent's break runs over. [https://docs.neodove.com/admin-portal/settings]
  - Missed-call alert (cloud telephony). [https://docs.neodove.com/product-updates/october-2024]
- The Follow-Up Report shows due and missed follow-ups. [https://docs.neodove.com/admin-portal/reports/follow-up-report]

---

## 7. Pricing (India, annual, excluding GST)

All rows below are from [https://neodove.com/pricing/]:

| Plan | Price per year | Users | Contacts | Pipelines | Workflows | AI agents / minutes |
|---|---|---|---|---|---|---|
| **NeoLite** (Telecalling) | ₹17,999 (list ₹19,999) | up to 10 | 50,000 | 2 | 5 | none |
| **NeoPlus** | ₹24,999 (list ₹29,999) | up to 20 | 200,000 | 4 | 10 | none |
| **NeoLite AI** | ₹22,999 | up to 10 | 50,000 | 2 | 5 | 2 AI agents, 250 min |
| **NeoPlus AI** | ₹29,999 | up to 20 | 200,000 | 4 | 10 | 4 AI agents, 500 min |
| **NeoOne** | custom | | | | | |

- Add-ons: AI Voice Agents, WhatsApp API, IVR/VoIP, extra AI credits. [same]
- An older listing put Enterprise from ₹500 per user per month. [https://www.techjockey.com/detail/neo-dove — via search snippet]
- In-product billing: buy or upgrade plans, invoices by financial year, renewal alerts for add-on (VAS) services. [https://docs.neodove.com/product-updates/november-2024] [https://docs.neodove.com/product-updates/september-2024]
- Company: Dealroom reports that Vyapar acquired NeoDove in May 2022. [https://app.dealroom.co/companies/neodove — via search snippet]

---

## 8. Notable UX patterns worth copying

- **A single "Start" button drives the day.** The agent does not pick leads. The system serves the next lead by follow-up due time and priority. [https://docs.neodove.com/neodove-mobile-application/homepage]
- **A hard call → dispose → next loop.** The next lead waits until the current one is disposed, which yields clean outcome data and talk time on every attempt. [https://docs.neodove.com/neodove-mobile-application/dispose-lead] [https://docs.neodove.com/neodove-mobile-application/faqs-mobile-application]
- **A two-button first question, "Was the Call Connected?".**
  - Not-connected becomes a single tap from a fixed list of reasons, which then drives automatic retry timing.
  - Connected opens the campaign script, then stage and tag, then the follow-up. [https://docs.neodove.com/neodove-mobile-application/dispose-lead] [https://docs.neodove.com/admin-portal/settings]
- **Mandatory next action**: every open lead leaves the dispose screen with a follow-up time, using quick chips (One Hour / Tomorrow / Next Week). [https://docs.neodove.com/product-updates/august-2023/lead-dispose-quick-follow-up-options]
- **Optional timed auto-dial**, e.g. 5 s after the lead card appears: a progressive dialler on the agent's own SIM. [https://docs.neodove.com/admin-portal/settings]
- **Messaging inside the dispose step**: tap WhatsApp, SMS or Email, the template is pre-filled, and the native app opens. [https://docs.neodove.com/neodove-mobile-application/dispose-lead/yes-connected]
- **Script as a form**: the per-campaign Engagement Form is both the call script and the data capture. It supports branching, multiple languages, and mapping into custom fields. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/customer-details-form]
- **Claim-before-act** on unassigned leads ("Assign to Myself"). [https://docs.neodove.com/product-updates/october-2024]
- **Number masking** with a 6-digit prefix search. [https://docs.neodove.com/product-updates/august-2024]
- **A unified Timeline** of calls and stage changes, plus "About Lead". [https://docs.neodove.com/product-updates/february-2024]
- **Exception-light admin**: per-reason retry rules, auto-reassign of stale scheduled leads, and Disable Lead Assignment for leavers. [https://docs.neodove.com/admin-portal/settings] [https://docs.neodove.com/admin-portal/users/how-to-disable-lead-assignment]

---

## 9. Verbatim label lists

### 9.1 Dispositions
- Top level: **"Yes, Connected"** / **"Not Connected"**, under the prompt "Was the Call Connected?" [https://docs.neodove.com/neodove-mobile-application/dispose-lead]
- Not Connected reasons, in order:
  1. Did not pick
  2. Busy in another call
  3. User disconnected the call
  4. Switch off
  5. Out of Coverage Area / Network issue
  6. Call not connected / call not be completed (Settings spells it "can not be completed")
  7. Other reason
  8. Incorrect / Invalid Number
  9. Incoming calls not available
  10. Number not in use / does not exists / out of service

  [https://docs.neodove.com/neodove-mobile-application/dispose-lead] [https://docs.neodove.com/neodove-web-application/dispose-lead/not-connected] [https://docs.neodove.com/admin-portal/settings]
- Connected outcome: the pipeline **Stage** plus **Tags**, which are customer-defined. The fixed closing stages are **Converted** and **Lost**. [https://docs.neodove.com/neodove-mobile-application/dispose-lead/yes-connected]
- Dispose-screen controls: "Select next action", "Re-assign this lead to other User", "Copy lead to other campaign", "Dispose Remark", "Next", "Submit". Quick follow-ups: "One Hour", "Tomorrow", "Next Week". [same] [https://docs.neodove.com/product-updates/august-2023/lead-dispose-quick-follow-up-options]

### 9.2 Lead statuses and categories
- Home "My Leads": **Open**, **Follow-up**, **Not Connected**. [https://docs.neodove.com/neodove-mobile-application/homepage]
- My Leads list: "New/Unattempted leads", "Follow-up Leads", "Not Connected Leads". [https://docs.neodove.com/neodove-mobile-application/calling-leads/calling-leads-through-my-leads]
- Also seen: **Unassigned** [https://docs.neodove.com/product-updates/october-2024], closed (**converted** / **lost**) [https://docs.neodove.com/admin-portal/campaigns/lead-summary/bulk-actions], reopened ("Merge & Reopen") [https://apps.apple.com/app/id1663716707].
- Default stage names other than Converted and Lost: not public.

### 9.3 Report names (Admin → Reports)
1. User Report
2. User Activity Report
3. Lead Disposition Report
4. Message Activity Report
5. User Call Report
6. Follow-Up Report (also written "Followup Report")
7. Login Report
8. Campaign Report
9. Campaign Lead Report
10. Campaign Stage Report

[https://docs.neodove.com/admin-portal/reports]

Also: "Trends" (Business Trends, User Trends) [https://docs.neodove.com/admin-portal/trends]; agent side "My Reports" → "Call Reports", "Login Reports" [https://docs.neodove.com/neodove-mobile-application/my-reports]; "Automatic Report" [https://docs.neodove.com/admin-portal/settings].

### 9.4 Engagement Form question types
Text, Short Answer, Number, Long Answer, Date, Time, Multiple Choice, Checkbox, Dropdown, Send message, Attach File, Send Email. [https://docs.neodove.com/admin-portal/campaigns/create-campaign/customer-details-form]

### 9.5 App Settings toggles (Admin → Settings → Preference)
- "Time to Notify Manager If Executive is on Break"
- "Enable automatic call dialing"
- "Followups to be mandatory for not connected calls"
- "Assign Scheduled Lead of a User to another User"
- "Display contact number on the lead"
- "Display Start Calling button"
- "Display additional lead properties"
- "Allow dispose lead without Follow-up"
- "Allow to Listen Contact History Call Recording"
- "Hide Contact History for Open Leads"
- Choose Currency
- Choose email provider to html email setup

The Settings tabs are: Users, Preference, Accessibility, Pipelines, Profile, Roles and Permissions, Automatic Report, Manage Columns, Retry Settings, Lead Priority. [https://docs.neodove.com/admin-portal/settings]

---

## 10. Not found publicly

- The exact default pipeline stage names, apart from Converted and Lost, and the full lead-status list. The iOS 1.4.11 "new lead statuses" are not named.
- What the "Lead Priority" buckets are and their default order, and the exact algorithm for choosing the next lead on "Start".
- Column names for every report and for the admin dashboard tiles. They appear only in screenshots I could not read.
- Any per-agent leaderboard or ranking screen.
- A live call-listening or whisper UI. Only "call barging" is listed, for IVR.
- Load or capacity-based assignment, per-user lead caps, and assignment by working hours. Working hours exist but are described as groundwork for future features.
- How a recording file is matched to a call record and uploaded (timing, matching key). The playback UI (scrubbing, speed).
- iOS call-recording behaviour.
- Offline mode, queued dispositions or local caching.
- The dedupe match key (phone, email, or both).
- An auth scheme for the inbound Custom Integration endpoint, and the field list for the outbound webhook payload.
- The full text of the Google Play listing (the page did not render), its screenshot captions and the Android permission list. Only search snippets and third-party mirrors were available.
- YouTube help videos: the playlist page did not render and search returned nothing, so no titles or chapters.
- G2 / Capterra / GetApp / Software Advice review bodies (403). Only search-snippet summaries were available.
- The NeoDialer setup page (mobile-docs.neodove.com/neodialer, 403).
- Task fields and status values, and the walk-in form fields beyond name, phone, campaign and assignee.
