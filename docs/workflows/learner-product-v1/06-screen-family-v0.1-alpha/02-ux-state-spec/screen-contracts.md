# Screen contracts

Each contract below pairs the screen ID with its primary data boundary and
release-sensitive states. The full row-level behavior is in
[`state-transition-matrix.csv`](state-transition-matrix.csv).

| ID | Primary read/write boundary | Ready behavior | Required edge states | Handoff |
| --- | --- | --- | --- | --- |
| `AUTH-01` | Identity API | sign in via approved email/provider path | validation, provider retry, terminal denial, expired session | shell or recovery |
| `AUTH-02` | Identity + exact consent | register with bounded fields | missing consent, validation, neutral acknowledgement, retry | verify |
| `AUTH-03` | Email challenge/session | consume challenge or resend | processing, invalid/expired, resend retry, success | shell/recovery |
| `AUTH-04` | Recovery intent | submit email for neutral acknowledgement | validation, retry, terminal safe error | await email |
| `AUTH-05` | Password reset/session | set password and revoke sessions as defined | mismatch, expired link, processing, success | login/shell |
| `AUTH-06` | Signed OAuth transaction | render bounded callback result | hostile shape, missing consent, provider reject/outage, retry | register/login |
| `AUTH-07` | Host-only session + local draft | reauthenticate and restore intent | draft preserved, offline, reauth failure, success | original route |
| `ONB-01` | Profile API + revision | edit bounded context fields | loading, conflict, save retry, offline, skip/complete | home |
| `HOME-01` | `/v1/me` + learning projection | one dominant next action | no enrollment, partial, retry, stale, expired | learning/activity/plans |
| `PLAN-01..03` | canonical plan projection or safe authored intent | show horizon items if present | empty, unavailable, stale, retry | owned learning route |
| `LEARN-01` | enrollment/learning projection | grouped course cards | no enrollments, partial, stale, locked card | program detail |
| `DISC-01` | published catalog | search/filter/browse | no results, retry, partial, signed-out | preview |
| `COURSE-01` | public published program | preview + sign-in/return CTA | no content, retry, unavailable, signed-out | auth/home |
| `COURSE-02` | enrolled pinned version | program path + progress | locked, partial, retry, expiry | module/progress |
| `MOD-01` | module/activity projection | ordered activities + lock reasons | prerequisite lock, no activities, partial, stale | activity |
| `ACT-01..05` | activity/draft/evidence service | configured renderer + next action | processing, save error, offline, expiry, lock, success | next activity/module |
| `MEDIA-01` | provider-neutral media/evidence port | accessible player if approved | captions/transcript partial, provider retry, policy denial, resume | watch evidence |
| `PROG-01` | canonical progress projection | completion counts and states | no evidence, partial, stale, retry, expiry | module/activity/cert |
| `INSIGHT-01` | descriptive analytics/read model | text-equivalent insight | unavailable, stale, no data, retry | progress |
| `NOTIF-01` | notification/read-state service | safe rows and owned links | empty, partial, retry, expired target, read success | target/settings |
| `PROF-01` | self-scoped profile | identity/context + avatar | incomplete, retry, stale, expiry | avatar/settings |
| `AVATAR-01` | local preview + profile object service | crop/preview then explicit submit | invalid file, processing, retry, cancel, success | profile |
| `SET-01..05` | `/v1/me`, onboarding, session, and browser-local appearance | section-specific controls | loading, retry, expiry, local storage fallback, sign-out success | profile/login/onboarding |
| `CERT-01` | self-scoped certificate/completion | issued artifact only when authorized | incomplete, processing, not found, denied, retry | progress |
| `SYS-01..04` | presentation layer + named domain state | shape-preserving feedback | loading/retry/offline/lock/permission | original route/recovery |
