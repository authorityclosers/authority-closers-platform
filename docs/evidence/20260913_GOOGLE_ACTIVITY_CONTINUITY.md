# Google sign-in activity continuation

Date: 2026-09-13 (Asia/Kolkata). Source parent: `8546810`.

## Result

Google sign-in and explicit Google registration now carry a validated activity
UUID through the existing server-signed OAuth return path. Activity continuation
first opens onboarding, whose canonical profile read and existing completion
control lead back to the activity. The activity API still resolves current access.
Course-only and ordinary Google destinations retain their existing behavior.

Login, registration, the registration GET form's hidden return path, the fixed
staging handoff, and server-result recovery pages all preserve this context.
Registration consent controls remain disabled until the actual consent check.
Server recovery extracts context only from the signed transaction and exact
generated onboarding path shapes. External paths, duplicate or extra parameters,
encoded near-misses, other courses and callback-query injection cannot supply
recovery context. UI parsers reject array and malformed activity values.

No cookie, OAuth state/nonce, identity, consent, membership, enrollment, database,
scoring, progress, payment or provider activation contract changed. Navigation is
not authority. Email verification/reset delivery continuity is a separate item;
this change does not claim live Google provider acceptance or deployment.

## Validation

Receipts are under
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.

- `google-activity-continuity-red`: before implementation, 11 of 14 new mounted
  UI cases and two of eight new API cases failed. The malformed-input controls
  passed. These original failure logs remain retained.
- `google-activity-continuity-targeted`: 153 UI cases across seven files passed,
  followed by all 89 authentication route/transaction cases. API cases exercise
  signed callback success and provider rejection with controlled provider test
  doubles; they do not contact Google. One existing Starlette/httpx warning.
- `google-activity-continuity-validation`: all 1,694 learner tests across 92 files
  passed with one worker under Node 24.19.0. TypeScript, scoped zero-warning
  ESLint, Python Ruff and formatting passed. `result.json` binds all ten source
  and test paths to SHA-256 digests. Owned local UI/API processes were stopped
  through their canonical managers before this run; the database was preserved.

The mounted tests use the actual login, registration and callback surfaces,
including registration consent interaction, GET form fields, staging links,
recovery states and rejected destination inputs. Existing onboarding and password
continuation regressions are included in the full suite.

Independent Luna xhigh review found no actionable P0-P3 findings in this bounded candidate. Live provider/runtime acceptance remains separately required.
