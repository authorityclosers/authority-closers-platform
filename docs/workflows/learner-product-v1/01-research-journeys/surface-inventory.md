# Surface inventory

This inventory is the page/tab/section backlog. Status values are
`existing-narrow`, `missing`, `contract-first`, or `future-gated`.

| Surface                 | Route intent                             | Major sections                                                                                | Status          |
| ----------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------- | --------------- |
| Dashboard               | `/home`                                  | continue learning; today's plan; quick practice; enrolled courses; upcoming; compact insights | existing-narrow |
| My Learning             | `/learning`                              | in progress; saved; completed; course filters; course cards                                   | existing-narrow |
| Discover                | `/discover`                              | catalog; categories; search; free/coming-soon states; program detail                          | existing-narrow |
| Progress                | `/progress`                              | cross-course completion; module/activity evidence; time range; unavailable states             | existing-narrow |
| Notifications           | `/notifications`                         | unread/read; learning reminders; release notices; preferences link                            | contract-first  |
| Profile                 | `/profile`                               | photo/avatar; identity; role/context; learning setup; account completeness                    | existing-narrow |
| Settings                | `/settings`                              | account; appearance; accessibility; notifications; privacy/security; sessions; data controls  | existing-narrow |
| Course overview         | `/learn/{programSlug}`                   | course header; progress; modules; resources; instructor/support                               | existing-narrow |
| Module overview         | `/learn/{programSlug}/module/{moduleId}` | module intent; activity sequence; lock reasons; resume                                        | existing-narrow |
| Activity                | `/activity/{activityId}`                 | media/practice workspace; progress context; save/evidence/recovery                            | existing-narrow |
| Media player            | activity-owned                           | HLS/source; poster; captions; transcript; playback errors; resume                             | contract-first  |
| Onboarding              | `/onboarding`                            | context; goal; situation; weekly rhythm; review                                               | existing-narrow |
| Account menu / More     | shell-owned                              | profile; notifications; settings; help; sign out                                              | existing-narrow |
| Authentication/recovery | existing auth routes                     | sign in; register; verify; recover; reset; session expired                                    | existing-narrow |
| Commercial discovery    | Discover-owned                           | free access; coming soon; paid teaser; entitlement-safe CTA                                   | future-gated    |

## Navigation contract

Wide sidebar: Dashboard, My Learning, Discover, Progress, Notifications; lower
Profile, Settings, Help. Header: page context, command search where supported,
notification status, and clickable learner avatar/account menu.

Compact bottom bar: Home, Learning, Discover, Progress, More. The avatar and
More sheet expose Profile, Notifications, Settings, Help, and Sign out. Compact
navigation does not simply duplicate every desktop sidebar item.
