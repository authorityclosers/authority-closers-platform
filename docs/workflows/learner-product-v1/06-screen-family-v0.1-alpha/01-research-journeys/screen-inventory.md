# Screen-family inventory

The inventory is the implementation-facing scope. “Canonical read” means the
screen may display server-owned facts; “local-only” means the state is safe to
keep on the current browser and never changes product authority. `candidate`
routes or subviews require IA/API confirmation before implementation.

| ID | User job | Primary structure | Canonical read / local state | Entry / exit | Required boundary |
| --- | --- | --- | --- | --- | --- |
| `AUTH-01` | sign in safely | email/provider actions, error region, help | identity/session; input preserved where safe | public → shell or recovery | no account enumeration; host-only cookie |
| `AUTH-02` | create account | bounded fields, exact consent, acknowledgement | identity/consent; draft input | public → verify/session | consent version explicit; no marketing inference |
| `AUTH-03` | verify account | token status, resend, return action | challenge/session | email link → shell or recovery | invalid/expired is terminal but existence-neutral |
| `AUTH-04` | request recovery | email field, neutral acknowledgement | recovery intent | public → wait for email | same response for eligible/ineligible address |
| `AUTH-05` | set password | new-password fields, requirements, status | password/session revocation | recovery link → shell/login | recent token and safe error handling |
| `AUTH-06` | recover OAuth return | provider-independent result card, next action | signed transaction outcome | callback → register/login/retry | never display provider payload/token |
| `AUTH-07` | recover after expiry | reason, safe-draft reassurance, reauth | session state; local draft | protected route → intended route | preserve supported work; no silent mutation |
| `ONB-01` | set learning context | stepper, bounded fields, save status | profile revision | verified shell → home | no inferred access, score, role, or recommendation |
| `HOME-01` | know what to do next | one dominant continue/start action, plan rail, enrolled programs, compact insight | `/v1/me`, learning projection, optional plan projection | shell → learning/activity/plans | missing ≠ zero; explicit free start only |
| `PLAN-01` | focus today | horizon header, authored/eligible items, status legend | plan projection; no invented deadlines | home subview → selected item | no schedule/notification commitment inference |
| `PLAN-02` | see week orientation | week grouping, empty/unavailable explanation | plan projection only | home subview → selected item | do not invent cadence, due date, or coach event |
| `PLAN-03` | see month orientation | month grouping, high-level progress | plan projection only | home subview → selected item | no future commercial/live scope claim |
| `LEARN-01` | find/resume owned learning | in-progress, saved, completed, filters, cards | enrollment/progress projection | shell → course/activity | access never inferred from card presence |
| `DISC-01` | explore catalog | search, categories, honest cards, empty/loading | published catalog | public/signed-in → preview | no enrollment or paid access mutation |
| `COURSE-01` | judge program fit | title, overview, modules preview, explicit sign-in/start CTA | published public preview | catalog → auth or home | read-only; does not enroll |
| `COURSE-02` | orient in owned program | course header, progress, module list, locks, support | pinned version + learning projection | enrolled → module/progress | route possession never grants access |
| `MOD-01` | choose next module activity | intent, ordered activity list, lock reasons, resume | canonical module/activity projection | course → activity/progress | program-specific prerequisites only |
| `ACT-01` | watch instructional media | player shell, captions/transcript status, evidence indicator, next action | media/evidence projection | module → reflect | 90% is provisional participation default, not mastery; provider gate |
| `ACT-02` | record reflection | prompt, long-text input, save status, previous answer | draft/evidence revision | watch → next activity | preserve draft; no score/coach fabrication |
| `ACT-03` | submit bounded implementation evidence | low-typing choice/checklist/evidence fields, submit status | evidence/submission | reflect → review | evidence is learner-reported; no real-world certainty |
| `ACT-04` | review observation | structured self-review, draft/save status | review evidence | implement → improve | no official score or AI verdict |
| `ACT-05` | choose one improvement | one-change prompt, action field, save/complete | improvement evidence | review → module/progress | completion follows configured policy only |
| `MEDIA-01` | control media accessibly | play/pause, seek, caption, transcript, resume, error | provider-neutral session/evidence | activity-owned | signed access/provider policy; no raw provider detail |
| `PROG-01` | understand completion | course/module/activity summaries, locks, range control | canonical progress projection | shell → module/activity/certificate | analytics never becomes progress authority |
| `INSIGHT-01` | interpret descriptive signal | text/chart summary with missing/stale labels | analytics/read projection | progress → route | no mastery/rank/score claims without controlled semantics |
| `NOTIF-01` | read and continue | unread/read rows, safe deep links, settings link | notification/read state | shell → owned route | preference/consent separation |
| `PROF-01` | review identity/context | avatar, name/email facts, context attributes, profile edit link | self-scoped profile | avatar → settings/onboarding | no role/tenant inference from labels |
| `AVATAR-01` | choose a private avatar | file chooser, crop/preview, validation, processing status | local preview + server object revision | profile → profile or retry | provider/upload gate; supersede safely |
| `SET-01` | inspect account | verified facts, edit route, data boundary | `/v1/me` | settings → profile/onboarding | no hidden account mutation |
| `SET-02` | choose presentation | Light/Dark/System theme mode, named presets, accent, density, motion, and preview | browser-local presentation preferences | settings → retained shell | never sync or alter account, tenant, or authority state |
| `SET-03` | revise learning setup | onboarding editor link, saved status | onboarding profile | settings → onboarding | bounded fields only |
| `SET-04` | find privacy/security help | recovery, terms/privacy, deletion-request entry only if contract exists | policy links/session facts | settings → recovery/help | no unapproved deletion/consent workflow invention |
| `SET-05` | manage current session | current device/session facts, sign-out, expiry link | session API | settings → login/shell | revocation is canonical; cache purge required |
| `CERT-01` | view completion artifact | artifact metadata, download/view, status explanation | immutable self-scoped certificate | completion → artifact/progress | not a competency certification |
| `SYS-01` | understand loading | route-shaped skeleton retaining shell | none | any request → ready/error | never show false empty/zero |
| `SYS-02` | recover transient failure | domain-specific error, retry, support/help | request trace/status | any request → retry/terminal | preserve input; no internal detail leak |
| `SYS-03` | understand offline boundary | connection state, safe cached links, retry | local shell only | network loss → reconnect | no protected mutation or authority claim |
| `SYS-04` | understand lock/unavailability | safe reason, next permitted action | authorization/progression projection | denied/locked → prerequisite/auth/support | never expose protected payload |
