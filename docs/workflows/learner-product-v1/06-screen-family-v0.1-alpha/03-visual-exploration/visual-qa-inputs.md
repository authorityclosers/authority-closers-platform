# Visual QA inputs (pending generation)

These are the behavioral fixtures a future visual set must represent. They are
not image prompts and are not a substitute for visual review.

| Family | Minimum frames/states to show | Must remain truthful |
| --- | --- | --- |
| Shell/home/plans | desktop and mobile ready, loading, empty, partial, offline | one dominant next action; no fake plans or progress |
| Catalog/program | results, no-results, preview, signed-out/return | preview is read-only; access is server-owned |
| Learning/module | course path, current activity, locked prerequisite | lock reason does not expose protected payload |
| Activity/player | ready, processing, provider failure, offline, completed | participation evidence is not mastery; captions/transcript status visible |
| Progress/insight | canonical ready, no evidence, stale/partial | missing is distinct from zero; analytics is descriptive |
| Auth/onboarding | form ready, validation, retry, expiry, draft recovery | no account enumeration; exact consent and safe preservation |
| Profile/settings | avatar crop, processing, failure, theme variants | avatar provider gate and device-local theme explicit |
| Notifications/certificate | empty/partial/read; issued/processing/incomplete | read state and certificate are canonical only when returned by contract |

Visual generation remains blocked until source/asset availability and the
selected three-direction decision are recorded.
