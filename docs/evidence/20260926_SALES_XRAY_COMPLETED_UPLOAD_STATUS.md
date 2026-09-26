# Clear a completed upload notice using verified Calls data

The fresh fictional staging canary completed and reopened successfully, but Calls retained the root banner saying that analysis had started and the report would appear later. The root upload store remembered acceptance indefinitely.

Calls now settles that notice when its authenticated server response lists the same submission with `hasReport`. The store checks both the current account/session/tenant and the identity that started the upload. It uses the existing settlement guard, so a pending analysis-start request remains owned until it finishes. Different calls, unknown owners, an account change, an interrupted upload, and a newer upload in flight are preserved.

Implementation was delegated through AC Orchestra to Claude Opus 5.5, high effort, with Read/Grep/Glob/Edit/Write only and explicit file ownership. Included subscription was verified at 11% session usage before dispatch, Fast disabled, paid-credit ceiling $0. The bounded implementation reached its configured 14-turn ceiling; Codex reviewed its produced changes and completed validation. No deployment, shell execution, external provider, or additional delegation was granted to Opus.

Validation at the fb4 source baseline plus this patch:

- 135 tests passed across upload-session, Calls and acquisition-studio suites. These include matching completion, pending start, unrelated call, unknown owner, account change and a newer in-flight upload.
- Typecheck initially found one untyped pending Promise in the new regression test. Codex supplied its explicit result type; typecheck then passed.
- Focused ESLint passed with zero warnings; diff whitespace checks passed.
- Local runtime was Node 22.17 (engine warning); the exact-source CI uses the repository's required Node 24 and remains the release gate.

No backend state, report content, provider routing, allowance, or consent behavior changes. This evidence records local validation; deployment and browser verification require separate release receipts.
