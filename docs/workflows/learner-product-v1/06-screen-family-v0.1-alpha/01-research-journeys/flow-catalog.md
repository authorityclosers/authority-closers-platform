# Flow and screen ID catalog

IDs are stable within `AC-WF-LEARNER-SF-V0.1A`. A screen ID refers to the
same route intent and behavior in the inventory, behavioral specification,
state matrix, diagram, AI context, and QA checklist. A shared route can host
multiple IDs only when the user job or canonical state differs.

| Flow ID | Actor | Entry | Exit / handoff | Primary outcome | Authority boundary |
| --- | --- | --- | --- | --- | --- |
| `FLOW-AUTH-ONB-01` | anonymous or verified learner | public sign-in, register, callback, or recovery link | authenticated shell or safe recovery state | establish/recover a learner session and bounded profile | Identity API; host-only session; no account enumeration |
| `FLOW-SHELL-PLAN-01` | authenticated learner | app shell, `/home`, or plan subview | owned learning route, plan horizon, or account surface | orient to the next safe action | `/v1/me` and canonical learning/plan projection; no invented plan commitments |
| `FLOW-DISCOVER-01` | visitor or authenticated learner | `/discover` or public program preview | sign-in return path or enrolled learning path | understand program fit and choose an explicit next action | published catalog and server-authorized free enrollment; no checkout/access inference |
| `FLOW-LEARNING-01` | enrolled learner | `/learning`, `/learn/{programSlug}`, or module deep link | activity, next module, or return to library | resume an eligible program and understand locks | pinned published version and learning projection; route possession never grants access |
| `FLOW-ACTIVITY-01` | enrolled learner | activity deep link or resume action | next configured activity or module/progress view | perform Watch → Reflect → Implement → Review → Improve with safe evidence | activity policy/evidence API; no client-only completion, mastery, or official scoring |
| `FLOW-PROGRESS-01` | enrolled learner | `/progress` or completion link | activity/module/certificate route | understand canonical completion and descriptive insight | canonical progress projection; analytics remains secondary |
| `FLOW-NOTIFY-01` | authenticated learner | header bell or compact More surface | owned deep link or settings | read an informational notification and continue safely | notification/read-state service; delivery preferences separate from learning facts |
| `FLOW-PROFILE-01` | authenticated learner | avatar/account menu or `/profile` | profile saved state or settings | review identity/context and prepare a private avatar change | self-scoped profile service; avatar processing/provider gate is explicit |
| `FLOW-SETTINGS-01` | authenticated learner | `/settings` or More | local confirmation, onboarding, recovery, or sign-out | change bounded presentation/session preferences safely | `/v1/me`/onboarding/session APIs; theme is device-local only |
| `FLOW-RESILIENCE-01` | learner with degraded connectivity/session | any supported route | retry, stale read, local draft, reauth, or `/offline` | preserve safe work and communicate limits | browser-local cache/draft is never canonical authority |
| `FLOW-CERT-01` | learner | completion/progress link | issued certificate artifact or truthful unavailable/incomplete state | distinguish course completion artifact from competency credential | self-scoped certificate API and completion predicate |

## Screen ID index

| Screen ID | Name | Flow | Route / surface |
| --- | --- | --- | --- |
| `AUTH-01` | Sign in | `FLOW-AUTH-ONB-01` | `/login` |
| `AUTH-02` | Register | `FLOW-AUTH-ONB-01` | `/register` |
| `AUTH-03` | Verify email | `FLOW-AUTH-ONB-01` | `/verify-email` |
| `AUTH-04` | Forgot password | `FLOW-AUTH-ONB-01` | `/forgot-password` |
| `AUTH-05` | Reset password | `FLOW-AUTH-ONB-01` | `/reset-password` |
| `AUTH-06` | OAuth callback recovery | `FLOW-AUTH-ONB-01` | `/auth/callback` |
| `AUTH-07` | Session expired | `FLOW-AUTH-ONB-01` / `FLOW-RESILIENCE-01` | `/session-expired` |
| `ONB-01` | Progressive onboarding | `FLOW-AUTH-ONB-01` | `/onboarding` |
| `HOME-01` | Learner dashboard/home | `FLOW-SHELL-PLAN-01` | `/home` |
| `PLAN-01` | Today plan horizon | `FLOW-SHELL-PLAN-01` | `/home` subview `today` |
| `PLAN-02` | Week plan horizon | `FLOW-SHELL-PLAN-01` | `/home` subview `week` |
| `PLAN-03` | Month plan horizon | `FLOW-SHELL-PLAN-01` | `/home` subview `month` |
| `LEARN-01` | My Learning library | `FLOW-LEARNING-01` | `/learning` |
| `DISC-01` | Discover/catalog | `FLOW-DISCOVER-01` | `/discover` |
| `COURSE-01` | Public program preview | `FLOW-DISCOVER-01` | `/programs/{slug}` |
| `COURSE-02` | Enrolled program detail | `FLOW-LEARNING-01` | `/learn/{programSlug}` |
| `MOD-01` | Module/path map | `FLOW-LEARNING-01` | `/learn/{programSlug}/module/{moduleId}` |
| `ACT-01` | Watch activity | `FLOW-ACTIVITY-01` | `/activity/{activityId}` |
| `ACT-02` | Reflect activity | `FLOW-ACTIVITY-01` | `/activity/{activityId}` |
| `ACT-03` | Implement activity | `FLOW-ACTIVITY-01` | `/activity/{activityId}` |
| `ACT-04` | Review activity | `FLOW-ACTIVITY-01` | `/activity/{activityId}` |
| `ACT-05` | Improve activity | `FLOW-ACTIVITY-01` | `/activity/{activityId}` |
| `MEDIA-01` | Activity-owned media player region | `FLOW-ACTIVITY-01` | `/activity/{activityId}` region |
| `PROG-01` | Progress overview | `FLOW-PROGRESS-01` | `/progress` |
| `INSIGHT-01` | Descriptive insights panel | `FLOW-PROGRESS-01` | `/progress` subview |
| `NOTIF-01` | Notification center | `FLOW-NOTIFY-01` | `/notifications` |
| `PROF-01` | Profile overview | `FLOW-PROFILE-01` | `/profile` |
| `AVATAR-01` | Avatar select/crop overlay | `FLOW-PROFILE-01` | `/profile` overlay |
| `SET-01` | Account and profile facts | `FLOW-SETTINGS-01` | `/settings` section `account` |
| `SET-02` | Appearance and theme | `FLOW-SETTINGS-01` | `/settings` section `appearance` |
| `SET-03` | Learning setup | `FLOW-SETTINGS-01` | `/settings` section `learning` |
| `SET-04` | Security, privacy, and help links | `FLOW-SETTINGS-01` | `/settings` section `privacy` |
| `SET-05` | Sessions and sign-out | `FLOW-SETTINGS-01` | `/settings` section `sessions` |
| `CERT-01` | Course-completion certificate | `FLOW-CERT-01` | `/certificates/{certificateId}` |
| `SYS-01` | Route-shaped loading | `FLOW-RESILIENCE-01` | retained shell on any route |
| `SYS-02` | Retryable failure | `FLOW-RESILIENCE-01` | inline on any route |
| `SYS-03` | Offline shell | `FLOW-RESILIENCE-01` | `/offline` |
| `SYS-04` | Locked or unavailable resource | `FLOW-RESILIENCE-01` | inline on protected routes |
