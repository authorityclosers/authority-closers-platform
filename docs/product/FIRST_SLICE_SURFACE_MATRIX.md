# Free Course surface and state matrix

Every route implements the applicable universal states in this order: `DEFAULT`, `LOADING`, `EMPTY`, `ERROR_RETRYABLE`, `ERROR_TERMINAL`, `OFFLINE`, `PERMISSION_DENIED`, `LOCKED`, `PARTIAL`, `SUCCESS_FEEDBACK`.

| Surface | Canonical route | Controlled IDs | Initial component focus |
|---|---|---|---|
| Public home | `/` | `UXS-0001`–`UXS-0010` | `UI-C006`, `UI-C009`, `UI-C017`, `UI-C025`, `UI-C027` |
| Program detail | `/programs/{slug}` | `UXS-0011`–`UXS-0020` | `UI-C009`, `UI-C014`, `UI-C017`, `UI-C021` |
| Login and callback | `/login`, `/auth/callback` | Controlled auth states; numbered UXS IDs pending | `AuthShell` pending UI ID; `UI-C017`, `UI-C025`, `UI-C029`, `UI-C065` |
| Onboarding | `/onboarding` | `UXS-0031`–`UXS-0040` | `UI-C001`, `UI-C006`, `UI-C012`, `UI-C017` |
| Learner home | `/home` | `UXS-0041`–`UXS-0050` | `UI-C001`–`UI-C004`, `UI-C009`–`UI-C012` |
| Program learning | `/learn/{programSlug}` | `UXS-0051`–`UXS-0060` | `UI-C005`, `UI-C006`, `UI-C009`, `UI-C010`, `UI-C014` |
| Module | `/learn/{programSlug}/module/{moduleId}` | `UXS-0061`–`UXS-0070` | `UI-C010`–`UI-C012`, `UI-C014`, `UI-C017` |
| Activity | `/activity/{activityId}` | Video `UXS-0071`–`UXS-0080`; other IDs pending | `UI-C012`, `UI-C017`, `UI-C047`, `UI-C048`; activity shells pending IDs |
| Completion | `/learn/{programSlug}/complete` | IDs pending controlled-source fix | `CompletionChecklist` pending UI ID |
| Certificate | `/certificates/{certificateId}` | IDs pending controlled-source fix | `CertificateView` pending UI ID |
| Admin people | `/people` | `UXS-0231`–`UXS-0240` | `UI-C004`, `UI-C041`–`UI-C043`, `UI-C062`–`UI-C064` |
| Admin catalog | `/catalog` | `UXS-0241`–`UXS-0250` | Same dense admin system |
| Admin learning ops | `/learning-operations` | `UXS-0271`–`UXS-0280` | Same dense admin system |

Checkout handoff `UXS-0021`–`UXS-0030` remains capability-gated and is not exposed in the Free Course build.
